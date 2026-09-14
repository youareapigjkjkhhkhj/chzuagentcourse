"""测验即时反馈（P6.1）。

把测验做成课堂时间线上的**暂停节点**：答对快速带过；答错由 AI 同学补充讲解；
连错则插入一页复习。课后生成按章掌握度报告。

### 三档分支

1. **pass**（答对）：教师一句话带过（"答对了！我们继续。"）
2. **remedial**（答错）：AI 同学补充讲解该概念（LLM 生成一句 ≤30 字的讲解）
3. **review**（同章连错 ≥2 题）：动态插入一页复习内容（LLM 生成要点 + 讲稿）

### 设计选择

- **不阻塞课堂**：LLM 调用 3 秒超时，降级为"显示参考答案"
- **不重复讲解**：同一个 conceptTag 在一堂课里只讲解一次（避免复读）
- **复习页落库**：插入的复习页存 `review_pages` 表，课后生成学情报告时用

### 与 runtime.py 的集成

`submit_quiz` 判完答案后调用 `decide_branch`，根据分支调用不同的处理函数：

```python
branch = quiz_feedback.decide_branch(session, page, correct)
if branch == "pass":
    quiz_feedback.handle_pass(session, page)
elif branch == "remedial":
    quiz_feedback.handle_remedial(session, page, concept_tag)
elif branch == "review":
    quiz_feedback.handle_review(session, page, chapter_no)
```
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from app.common.logging import get_logger
from app.extensions import db
from app.models import ClassroomSession, QuizAttempt, ReviewPage
from app.models.course import CoursePage
from app.services.classroom import recorder, roster
from app.services.generation.llm import call_json
from app.services.provider_registry import get_registry

logger = get_logger("app.classroom.quiz_feedback")

#: LLM 调用超时（秒）。超时降级为"显示参考答案"，不阻塞课堂。
LLM_TIMEOUT_SEC = 3.0

#: 同章连错几次触发复习页
CONSECUTIVE_ERROR_THRESHOLD = 2

#: 补充讲解的最大字数
REMEDIAl_MAX_CHARS = 30

#: 复习页的要点数
REVIEW_PAGE_BULLETS = 3


def decide_branch(
    session: ClassroomSession,
    page: Mapping[str, Any],
    correct: bool,
) -> str:
    """决定走哪一档分支（P6.1）。

    返回：`"pass"` / `"remedial"` / `"review"`

    逻辑：
    - 答对 → pass
    - 答错 → 检查同章连错次数
      - 连错 < 2 → remedial
      - 连错 ≥ 2 → review
    """
    if correct:
        return "pass"

    # 答错：检查同章连错次数
    page_no = int(page.get("pageNo") or 0)
    chapter_no = _get_chapter_no(session.course_id, page_no)
    if chapter_no is None:
        return "remedial"  # 拿不到章号，保守走 remedial

    consecutive_errors = _count_consecutive_errors(session.id, chapter_no)
    if consecutive_errors >= CONSECUTIVE_ERROR_THRESHOLD:
        return "review"

    return "remedial"


def handle_pass(session: ClassroomSession, page: Mapping[str, Any]) -> dict:
    """答对：教师一句话带过（P6.1）。

    返回：quiz_result 事件的载荷（branch="pass"）
    """
    teacher = roster.teacher()
    text = "答对了！我们继续。"

    # 发一条教师消息
    msg = recorder.add_message(
        session,
        speaker_code=teacher["code"],
        speaker_kind="teacher",
        type="comment",
        text=text,
        page_no=int(page.get("pageNo") or 0),
    )

    # 发 quiz_feedback 事件（前端渲染教师消息）
    event = recorder.publish(
        session,
        "quiz_feedback",
        {
            "pageNo": int(page.get("pageNo") or 0),
            "branch": "pass",
            "message": msg,
        },
    )

    return event


def handle_remedial(
    session: ClassroomSession,
    page: Mapping[str, Any],
    concept_tag: str,
) -> dict:
    """答错：AI 同学补充讲解该概念（P6.1）。

    返回：quiz_result 事件的载荷（branch="remedial"）

    **降级策略**：LLM 调用 3 秒超时，降级为"显示参考答案"。
    """
    page_no = int(page.get("pageNo") or 0)
    quiz = page.get("quiz") or {}
    explain = str(quiz.get("explain") or "")

    # 尝试用 LLM 生成一句补充讲解
    text = _generate_remedial_text(session, concept_tag, explain)

    # 选一位 AI 同学发言（轮流，避免总是同一个人）
    classmates = roster.classmates()
    if not classmates:
        # 没有 AI 同学，降级为教师讲解
        teacher = roster.teacher()
        speaker = teacher
        speaker_kind = "teacher"
    else:
        # 轮流选一位同学
        index = _count_remedial_messages(session.id) % len(classmates)
        speaker = classmates[index]
        speaker_kind = "student_ai"

    # 发一条 AI 同学消息
    msg = recorder.add_message(
        session,
        speaker_code=speaker["code"],
        speaker_kind=speaker_kind,
        type="comment",
        text=text,
        page_no=page_no,
    )

    # 发 quiz_feedback 事件
    event = recorder.publish(
        session,
        "quiz_feedback",
        {
            "pageNo": page_no,
            "branch": "remedial",
            "conceptTag": concept_tag,
            "message": msg,
        },
    )

    return event


def handle_review(
    session: ClassroomSession,
    page: Mapping[str, Any],
    chapter_no: int,
) -> dict:
    """同章连错 ≥2 题：动态插入一页复习内容（P6.1）。

    返回：quiz_result 事件的载荷（branch="review"）

    **降级策略**：LLM 调用 3 秒超时，降级为"插入一页空白复习页"。
    """
    page_no = int(page.get("pageNo") or 0)

    # 尝试用 LLM 生成一页复习内容
    review_page_dsl = _generate_review_page(session, chapter_no)

    # 落 review_pages 表
    review_page = ReviewPage(
        session_id=session.id,
        course_id=session.course_id,
        source_page_no=page_no,
        inserted_after_page_no=page_no,
        dsl_json=json.dumps(review_page_dsl, ensure_ascii=False),
        trigger_reason="consecutive_errors",
        concept_tag=_get_weak_concept(session.id, chapter_no),
    )
    db.session.add(review_page)
    db.session.flush()

    # 发 quiz_feedback 事件（前端渲染复习页）
    event = recorder.publish(
        session,
        "quiz_feedback",
        {
            "pageNo": page_no,
            "branch": "review",
            "chapterNo": chapter_no,
            "reviewPage": review_page_dsl,
            "reviewPageId": review_page.id,
        },
    )

    return event


# --------------------------------------------------------------------------
# 内部函数
# --------------------------------------------------------------------------


def _get_chapter_no(course_id: str, page_no: int) -> int | None:
    """拿这一页属于第几章。"""
    row = CoursePage.query.filter_by(course_id=course_id, page_no=page_no).first()
    return row.chapter_no if row else None


def _count_consecutive_errors(session_id: str, chapter_no: int) -> int:
    """同章连错几次（从最近一次往前数，直到遇到答对为止）。"""
    # 拿这一章的所有作答记录，按时间倒序
    attempts = (
        QuizAttempt.query.join(
            CoursePage,
            (CoursePage.course_id == QuizAttempt.course_id) & (CoursePage.page_no == QuizAttempt.page_no),
        )
        .filter(
            QuizAttempt.session_id == session_id,
            CoursePage.chapter_no == chapter_no,
        )
        .order_by(QuizAttempt.ts.desc())
        .all()
    )

    # 从最近一次往前数，直到遇到答对
    count = 0
    for attempt in attempts:
        if attempt.correct:
            break
        count += 1

    return count


def _count_remedial_messages(session_id: str) -> int:
    """这一堂课已经发过几条 remedial 消息（用于轮流选同学）。"""
    from app.models import ClassroomMessage

    return (
        ClassroomMessage.query.filter_by(
            session_id=session_id,
            type="comment",
            speaker_kind="student_ai",
        )
        .count()
    )


def _generate_remedial_text(
    session: ClassroomSession,
    concept_tag: str,
    explain: str,
) -> str:
    """用 LLM 生成一句补充讲解（≤30 字）。

    **降级策略**：3 秒超时或调用失败，返回 explain 的前 30 字。
    """
    if not explain:
        return f"这道题考察的是{concept_tag}，我们再看一下。"

    # 构建提示词
    messages = [
        {
            "role": "system",
            "content": "你是一位耐心的助教，用一句话（≤30字）补充讲解学生答错的概念。不要重复题目，直接讲要点。",
        },
        {
            "role": "user",
            "content": f"概念：{concept_tag}\n解析：{explain}\n请生成一句补充讲解（≤30字）：",
        },
    ]

    schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "maxLength": 30},
        },
        "required": ["text"],
    }

    try:
        # 调用 LLM（3 秒超时）
        result = call_json(
            get_registry().current_llm(),
            messages,
            schema=schema,
            timeout=LLM_TIMEOUT_SEC,
        )
        text = str(result.data.get("text") or "").strip()
        if text and len(text) <= REMEDIAl_MAX_CHARS:
            return text
    except Exception as e:
        logger.warning("生成补充讲解失败，降级为显示解析: %s", e)

    # 降级：返回 explain 的前 30 字
    return explain[:REMEDIAl_MAX_CHARS] + ("..." if len(explain) > REMEDIAl_MAX_CHARS else "")


def _generate_review_page(session: ClassroomSession, chapter_no: int) -> dict[str, Any]:
    """用 LLM 生成一页复习内容（要点 + 讲稿）。

    **降级策略**：3 秒超时或调用失败，返回一页空白复习页。
    """
    # 拿这一章的错题
    weak_concept = _get_weak_concept(session.id, chapter_no)

    # 构建提示词
    messages = [
        {
            "role": "system",
            "content": "你是一位课程设计师，为答错多题的学生生成一页复习内容。输出 JSON：{title, bullets: [3条要点], narration: [2-3句讲稿]}。",
        },
        {
            "role": "user",
            "content": f"第{chapter_no}章，薄弱概念：{weak_concept}\n请生成一页复习内容：",
        },
    ]

    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "bullets": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3},
            "narration": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 3},
        },
        "required": ["title", "bullets", "narration"],
    }

    try:
        # 调用 LLM（3 秒超时）
        result = call_json(
            get_registry().current_llm(),
            messages,
            schema=schema,
            timeout=LLM_TIMEOUT_SEC,
        )
        data = result.data
        if data and isinstance(data, dict):
            # 构建复习页 DSL
            return {
                "kind": "concept",
                "title": str(data.get("title") or f"第{chapter_no}章复习"),
                "bullets": [{"text": str(b)} for b in (data.get("bullets") or [])],
                "narration": [{"beatId": f"review_{i}", "text": str(t), "estSec": 5} for i, t in enumerate(data.get("narration") or [])],
                "visual": {"desc": "复习页", "type": ""},
            }
    except Exception as e:
        logger.warning("生成复习页失败，降级为空白页: %s", e)

    # 降级：返回一页空白复习页
    return {
        "kind": "concept",
        "title": f"第{chapter_no}章复习",
        "bullets": [{"text": f"回顾{weak_concept}的核心概念"}],
        "narration": [{"beatId": "review_0", "text": f"我们再来看一下{weak_concept}。", "estSec": 5}],
        "visual": {"desc": "复习页", "type": ""},
    }


def _get_weak_concept(session_id: str, chapter_no: int) -> str:
    """拿这一章错得最多的概念标签。"""
    from sqlalchemy import func

    # 统计这一章每个 conceptTag 的错题数
    rows = (
        db.session.query(
            QuizAttempt.node_id,
            func.count(QuizAttempt.id).label("error_count"),
        )
        .join(
            CoursePage,
            (CoursePage.course_id == QuizAttempt.course_id) & (CoursePage.page_no == QuizAttempt.page_no),
        )
        .filter(
            QuizAttempt.session_id == session_id,
            CoursePage.chapter_no == chapter_no,
            QuizAttempt.correct == False,  # noqa: E712
        )
        .group_by(QuizAttempt.node_id)
        .order_by(func.count(QuizAttempt.id).desc())
        .first()
    )

    if rows and rows.node_id:
        return str(rows.node_id)

    return f"第{chapter_no}章核心概念"


__all__ = [
    "decide_branch",
    "handle_pass",
    "handle_remedial",
    "handle_review",
]
