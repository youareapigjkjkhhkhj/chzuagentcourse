"""板书：`boardPlan` → 真实笔画（§2.4 / P3-A8 / P3-C3）。

P1 只给出**计划**（`{tool, desc, atBeat}`：「画一条时间轴，标出三个点」）。
白板要的是能一笔一笔画出来的坐标，所以这里用一次 LLM 调用把 `desc` 翻成
`polyline | curve | text | arrow` + 归一化坐标，落 `board_strokes`。

三条口径：

1. **一门课的一页只生成一次。** 老师重开一堂课，同一页的板书不该长得不一样 ——
   第二次进来时有现成的行就**照抄一份**给新会话，不再问模型。这既省一次调用，
   也保证了 P3-A8「再次进入同一页看到相同板书」。
2. **生成失败就是空板书，不是异常。** 模型超时/返回看不懂的东西时返回空列表：
   没有板书课照上，画错一笔学生就记住了错的（§2.4 MVP 只要回放，不要花活）。
3. **坐标一律归一化**（0~1）。老师在投影上看、学生在手机上看，存像素等于把
   板书绑死在某个屏幕上。越界的点直接夹回边界 —— 拒绝整笔比夹一下更糟：
   一笔画坏了，整块板书就残了。

`board_sync`（学生端教具条）复用同一套清洗与落库，笔画标 `author=me`。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.common.dbw import db_write
from app.common.errors import AppError
from app.common.logging import get_logger
from app.extensions import db
from app.models import BoardStroke, ClassroomSession
from app.services.classroom import prompts
from app.services.generation.llm import call_json
from app.services.provider_registry import get_registry

logger = get_logger("app.classroom.board")

#: 认得的笔画工具。与 `board_strokes.tool` 的 CHECK 一致 —— 这里多一个值，
#: 落库时就会 500。
TOOLS = ("polyline", "curve", "text", "arrow", "rect", "ellipse")

#: 一笔画多久（毫秒）。§2.4 写的默认值。
DEFAULT_DUR_MS = 800

#: 单笔时长的上下限。太快像闪一下，太慢会挡住下一笔。
MIN_DUR_MS, MAX_DUR_MS = 100, 5000

#: 一块板书最多几笔。§2.4 让模型给 2~5 笔，这里是硬上限：
#: 学生盯着的是讲解，不是一幅画。
MAX_STROKES = 24

#: 一段板书文字最多几个字。板书是提要，不是讲稿。
MAX_TEXT = 80

#: 最后一行少于这个字数就别留了。留一两个字（「关键词：稀」）比不留更难看，
#: 也更容易被当成渲染坏了。
MIN_TAIL = 6


def clip_text(text: str) -> str:
    """文字超长就截到 `MAX_TEXT`。**按行截，不从中间劈开。**

    `text[:80]` 是按字符数的，会把最后一行劈成半句 —— 库里就留着
    「关键词：稀」这样的行，在白板上看就是一句话没写完整。这里整行整行地
    放：放得下就全留，放不下就只留放得下的那部分（够 `MIN_TAIL` 才留）。
    只有最后一行可能是半句 —— 前面每一行都是完整的。
    """
    if len(text) <= MAX_TEXT:
        return text
    kept: list[str] = []
    used = 0
    for line in text.split("\n"):
        # 第一行的额度就是全额；之后每留一行，都要多花一个换行符的额度
        room = MAX_TEXT - used if kept else MAX_TEXT
        if len(line) <= room:
            kept.append(line)
            used += len(line) + 1
            continue
        if room >= MIN_TAIL:
            kept.append(line[:room])
        break
    return "\n".join(kept)


def strokes_of(session_or_id: ClassroomSession | str, page_no: int) -> list[dict]:
    """这一页现有的笔画（本会话的），按 `stroke_no` 升序。"""
    session_id = _id_of(session_or_id)
    rows = (
        BoardStroke.query.filter_by(session_id=session_id, page_no=int(page_no))
        .order_by(BoardStroke.stroke_no.asc())
        .all()
    )
    return [row.to_dict() for row in rows]


def pages_with_strokes(session_or_id: ClassroomSession | str) -> list[int]:
    """这堂课留有板书的页号，升序（记录页按页取快照，P3-C3）。

    **问「哪几页有」而不是「每一页有什么」**：一堂课几十页，绝大多数页没有
    板书（`boardPlan` 只挂在一部分页上），逐页问一遍就是几十次查询，
    而结果里绝大部分是空数组。
    """
    rows = (
        db.session.query(BoardStroke.page_no)
        .filter(BoardStroke.session_id == _id_of(session_or_id))
        .distinct()
        .order_by(BoardStroke.page_no.asc())
        .all()
    )
    return [int(row[0]) for row in rows]


def ensure(
    session: ClassroomSession,
    page_row: Mapping[str, Any],
    *,
    force: bool = False,
) -> list[dict]:
    """保证这一页有板书可放。返回笔画列表（可能是空的）。

    顺序是「本会话已有 → 照抄别的会话 → 问模型」。第二条是关键：
    **同一门课的同一页只生成一次**（P3-A8），重开一堂课不会得到另一块白板。
    """
    page_no = int(page_row.get("pageNo") or 0)
    if not page_no:
        return []

    existing = strokes_of(session, page_no)
    if existing and not force:
        return existing

    plan = [item for item in (page_row.get("boardPlan") or []) if item]
    if not plan:
        # 没有板书计划的页就是没有板书。不要为了「有点东西」让模型自由发挥，
        # 那不是这门课的板书。
        return existing

    template = _template(session.course_id, page_no) if not force else []
    if template:
        return _clone(session, template)

    return _generate(session, page_row, plan)


def append_client_strokes(
    session: ClassroomSession, page_no: int, strokes: Sequence[Mapping[str, Any]]
) -> list[dict]:
    """收下客户端（`board_sync`）发来的笔画，接在现有笔画后面。

    §2.4 的 MVP 口径是「工具条对学生本地生效」—— 这里做的是把**本页的笔画**
    存下来并回播，所以标 `author=me`：记录页要分得清哪几笔是老师预生成的、
    哪几笔是课上有人画的。
    """
    cleaned = clean(strokes)
    if not cleaned:
        return strokes_of(session, page_no)

    base = len(strokes_of(session, page_no))

    def _write() -> list[dict]:
        rows = [
            BoardStroke(
                session_id=session.id,
                course_id=session.course_id,
                page_no=int(page_no),
                stroke_no=base + index,
                tool=item["tool"],
                points=item["points"],
                text=item.get("text") or None,
                at_beat_id=item.get("atBeatId") or None,
                dur_ms=item["durMs"],
                author="me",
            )
            for index, item in enumerate(cleaned, start=1)
        ]
        db.session.add_all(rows)
        db.session.flush()
        return [row.to_dict() for row in rows]

    added = db_write(_write)
    logger.info("课堂板书追加 %s 笔（session=%s page=%s）", len(added), session.id, page_no)
    return strokes_of(session, page_no)


def clean(strokes: Sequence[Mapping[str, Any]]) -> list[dict]:
    """清洗笔画：认工具、夹坐标、补时长、丢掉看不懂的。

    模型和浏览器都往这里送东西，所以它对**两边**都当不可信输入处理。
    """
    result: list[dict] = []
    for raw in strokes:
        if len(result) >= MAX_STROKES:
            logger.debug("板书画笔超过上限 %s，余下丢弃", MAX_STROKES)
            break
        if not isinstance(raw, Mapping):
            continue

        tool = str(raw.get("tool") or "polyline")
        if tool not in TOOLS:
            continue

        points = _points(raw.get("points"))
        text = str(raw.get("text") or "").strip()
        if tool == "text":
            if not text:
                continue
            points = points or [[0.12, 0.18]]
        elif len(points) < 2:
            # 一个点的线画不出来；箭头至少要两点才有方向
            continue

        item: dict[str, Any] = {
            "tool": tool,
            "points": points,
            "durMs": _dur_ms(raw.get("durMs")),
        }
        if text:
            item["text"] = clip_text(text)
        at_beat = str(raw.get("atBeatId") or raw.get("atBeat") or "")
        if at_beat:
            item["atBeatId"] = at_beat
        result.append(item)
    return result


def submit_pregeneration(session_id: str, page_no: int) -> bool:
    """把这一页的板书生成丢到后台（老师翻到前一页时就可以开始想）。

    返回 False 表示同一页已经有一个在跑了 —— 这正是后台任务器
    `submit(key, fn)` 的语义，也是「同一门课同一页只生成一次」的另一半。
    """
    from app.common.tasks import get_runner

    key = f"board:{session_id}:{int(page_no)}"

    def _run() -> None:
        session = db.session.get(ClassroomSession, session_id)
        if session is None:
            return
        from app.models import CoursePage

        page = CoursePage.query.filter_by(
            course_id=session.course_id, page_no=int(page_no)
        ).first()
        if page is None:
            return
        ensure(session, {"pageNo": page.page_no, **(page.dsl or {})})

    return get_runner().submit(key, _run)


# --- 内部 ---


def _generate(
    session: ClassroomSession, page_row: Mapping[str, Any], plan: Sequence[Mapping[str, Any]]
) -> list[dict]:
    """问模型要笔画。失败返回空列表（不抛：课堂不能因为板书停住）。"""
    try:
        result = call_json(
            get_registry().current_llm(),
            prompts.board_messages(page_row, plan),
            schema=prompts.SCHEMA_BOARD,
        )
    except AppError as exc:
        logger.info("板书生成跳过（page=%s）：%s", page_row.get("pageNo"), exc.message)
        return []

    cleaned = clean(result.data.get("strokes") or [])
    if not cleaned:
        logger.info("板书生成没有得到可用笔画（page=%s）", page_row.get("pageNo"))
        return []

    page_no = int(page_row.get("pageNo") or 0)

    def _write() -> list[dict]:
        rows = [
            BoardStroke(
                session_id=session.id,
                course_id=session.course_id,
                page_no=page_no,
                stroke_no=index,
                tool=item["tool"],
                points=item["points"],
                text=item.get("text") or None,
                at_beat_id=item.get("atBeatId") or _beat_for(plan, index),
                dur_ms=item["durMs"],
                author="teacher",
            )
            for index, item in enumerate(cleaned, start=1)
        ]
        db.session.add_all(rows)
        db.session.flush()
        return [row.to_dict() for row in rows]

    rows = db_write(_write)
    logger.info("板书生成完成：page=%s %s 笔", page_no, len(rows))
    return rows


def _template(course_id: str, page_no: int) -> list[dict]:
    """别的会话（哪怕是上周那堂）里同一门课同一页的笔画。"""
    rows = (
        BoardStroke.query.filter_by(course_id=course_id, page_no=int(page_no))
        .filter(BoardStroke.author == "teacher")
        .order_by(BoardStroke.created_at.asc(), BoardStroke.stroke_no.asc())
        .all()
    )
    if not rows:
        return []
    first = rows[0].session_id
    return [row.to_dict() for row in rows if row.session_id == first]


def _clone(session: ClassroomSession, template: Sequence[Mapping[str, Any]]) -> list[dict]:
    """照抄一份给这个会话（新的 id、新的 session_id，笔画本身一模一样）。"""
    def _write() -> list[dict]:
        rows = [
            BoardStroke(
                session_id=session.id,
                course_id=session.course_id,
                page_no=int(item["pageNo"]),
                stroke_no=int(item["strokeNo"]),
                tool=str(item["tool"]),
                color=str(item.get("color") or "#1f2937"),
                width=float(item.get("width") or 2.0),
                points=list(item.get("points") or []),
                text=item.get("text") or None,
                at_beat_id=item.get("atBeatId") or None,
                dur_ms=int(item.get("durMs") or DEFAULT_DUR_MS),
                author="teacher",
            )
            for item in template
        ]
        db.session.add_all(rows)
        db.session.flush()
        return [row.to_dict() for row in rows]

    return db_write(_write)


def _beat_for(plan: Sequence[Mapping[str, Any]], index: int) -> str:
    """第 index 笔（从 1 起）该在哪出现：`boardPlan[index-1].atBeat`。

    模型可能少给或多给笔画，所以按下标对齐到计划上 —— 板书「什么时候出现」
    由计划决定，不由模型决定。
    """
    if 1 <= index <= len(plan):
        return str(plan[index - 1].get("atBeat") or "")
    return ""


def _points(raw: Any) -> list[list[float]]:
    points: list[list[float]] = []
    for item in raw or []:
        if isinstance(item, Mapping):
            values = (item.get("x"), item.get("y"))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            values = (item[0], item[1])
        else:
            continue
        x, y = _number(values[0]), _number(values[1])
        if x is None or y is None:
            continue
        points.append([_clamp(x), _clamp(y)])
    return points


def _number(raw: Any) -> float | None:
    """能当坐标用的数才算数：`null`、`"左"`、缺字段一律返回 None 由调用方跳过。"""
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _clamp(value: float) -> float:
    return round(max(0.0, min(value, 1.0)), 4)


def _dur_ms(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_DUR_MS
    return max(MIN_DUR_MS, min(value, MAX_DUR_MS))


def _id_of(session_or_id: ClassroomSession | str) -> str:
    return (
        session_or_id.id
        if isinstance(session_or_id, ClassroomSession)
        else str(session_or_id)
    )


__all__ = [
    "DEFAULT_DUR_MS",
    "MAX_STROKES",
    "TOOLS",
    "append_client_strokes",
    "clean",
    "clip_text",
    "ensure",
    "pages_with_strokes",
    "strokes_of",
    "submit_pregeneration",
]
