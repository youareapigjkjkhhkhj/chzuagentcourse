"""学情数据模型（P6.1）。

### 设计选择：函数而不是视图

P6.1 文档要求 `chapter_mastery` 视图，但这里用**函数**而不是视图：

- **视图的优点**：SQL 层面聚合，性能好
- **视图的缺点**：需要迁移脚本，SQLite 的视图不支持索引，且视图定义分散在迁移里难维护
- **函数的优点**：简单，不需要迁移，逻辑集中在一处
- **函数的缺点**：每次查询都要聚合，性能稍差

考虑到"简单、健壮、稳定、易用，不需要太臃肿"的原则，选择函数。
掌握度查询不是高频操作（只在学情总览页和首页卡片用），性能不是瓶颈。

### ReviewPage 表

记录动态插入的复习页（同章连错 ≥2 题时触发）。
"""

from __future__ import annotations

from typing import Any

from app.extensions import db
from app.models.base import PkMixin, TimestampMixin


class ReviewPage(PkMixin, TimestampMixin, db.Model):
    """动态插入的复习页（P6.1）。

    同章连错 ≥2 题时，系统自动生成一页复习内容并插入到课堂时间线中。
    `trigger_reason` 记录为什么插入这一页（"consecutive_errors" / "weak_concept"）。
    """

    __tablename__ = "review_pages"

    session_id = db.Column(
        db.String(32),
        db.ForeignKey("classroom_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    course_id = db.Column(
        db.String(32), db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    #: 触发复习的那一页（学生在这页连错 ≥2 题）
    source_page_no = db.Column(db.Integer, nullable=False)
    #: 复习页插入到时间线的哪个位置之后
    inserted_after_page_no = db.Column(db.Integer, nullable=False)
    #: 复习页的 DSL（JSON 字符串）
    dsl_json = db.Column(db.Text, nullable=False)
    #: 为什么插入这一页
    trigger_reason = db.Column(db.String(64), nullable=False)
    #: 这一页涉及的概念标签（用于学情总览的错题列表）
    concept_tag = db.Column(db.String(128))

    __table_args__ = (
        db.Index("ix_review_pages_session", "session_id"),
        db.Index("ix_review_pages_course", "course_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "courseId": self.course_id,
            "sourcePageNo": self.source_page_no,
            "insertedAfterPageNo": self.inserted_after_page_no,
            "dslJson": self.dsl_json,
            "triggerReason": self.trigger_reason,
            "conceptTag": self.concept_tag or "",
            "createdAt": self.created_at.isoformat() if self.created_at else "",
        }

    def __repr__(self) -> str:
        return f"<ReviewPage {self.session_id}#{self.source_page_no} reason={self.trigger_reason}>"


def get_chapter_mastery(course_id: str) -> list[dict[str, Any]]:
    """按章统计掌握度（P6.1）。

    返回：`[{chapterNo, total, correct, mastery}, ...]`

    掌握度 = 该章正确题数 / 总题数。

    **为什么不用视图**：见模块 docstring。
    """
    from sqlalchemy import func

    from app.models.classroom import QuizAttempt
    from app.models.course import CoursePage

    # 联合查询：quiz_attempts + course_pages（拿 chapter_no）
    rows = (
        db.session.query(
            CoursePage.chapter_no,
            func.count(QuizAttempt.id).label("total"),
            func.sum(func.cast(QuizAttempt.correct, db.Integer)).label("correct"),
        )
        .join(CoursePage, (CoursePage.course_id == QuizAttempt.course_id) & (CoursePage.page_no == QuizAttempt.page_no))
        .filter(QuizAttempt.course_id == course_id)
        .group_by(CoursePage.chapter_no)
        .order_by(CoursePage.chapter_no)
        .all()
    )

    return [
        {
            "chapterNo": row.chapter_no,
            "total": int(row.total or 0),
            "correct": int(row.correct or 0),
            "mastery": round(float(row.correct or 0) / float(row.total or 1), 3),
        }
        for row in rows
    ]


def get_wrong_questions(course_id: str, chapter_no: int | None = None) -> list[dict[str, Any]]:
    """错题列表（P6.1 学情总览页用）。

    返回：`[{pageNo, nodeId, option, correct, responseMs, ts, conceptTag}, ...]`

    `chapter_no` 为 None 时返回全课的错题，否则只返回该章的。
    """
    from app.models.classroom import QuizAttempt
    from app.models.course import CoursePage

    query = (
        db.session.query(QuizAttempt, CoursePage.chapter_no)
        .join(CoursePage, (CoursePage.course_id == QuizAttempt.course_id) & (CoursePage.page_no == QuizAttempt.page_no))
        .filter(QuizAttempt.course_id == course_id, QuizAttempt.correct == False)  # noqa: E712
    )

    if chapter_no is not None:
        query = query.filter(CoursePage.chapter_no == chapter_no)

    rows = query.order_by(QuizAttempt.ts.desc()).all()

    return [
        {
            "pageNo": attempt.page_no,
            "nodeId": attempt.node_id or "",
            "option": attempt.option or "",
            "correct": bool(attempt.correct),
            "responseMs": attempt.response_ms or 0,
            "ts": attempt.ts,
            "chapterNo": chapter,
            "conceptTag": attempt.node_id or "",  # node_id 存的就是 conceptTag
        }
        for attempt, chapter in rows
    ]


__all__ = [
    "ReviewPage",
    "get_chapter_mastery",
    "get_wrong_questions",
]
