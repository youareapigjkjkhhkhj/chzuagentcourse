"""课程与课程页。

`dsl_json` 是课程的中间表示（Intermediate Representation）：
P1 生成它，P3 课堂运行时消费它，P5 导出 PPTX/HTML/PDF 时再消费一次。
三种消费方共用一个 DSL，避免「生成一套、导出另一套」的漂移。
"""

from __future__ import annotations

from app.extensions import db
from app.models.base import JSONField, PkMixin, TimestampMixin

COURSE_STATUSES = ("draft", "generating", "ready", "failed")

#: P1 §3.2 的九种页型。P0 曾是 (cover, content, quiz, summary) 四个占位值 ——
#: content 被 concept 取代（「概念讲解」才是主力页型的真实语义），
#: outline/figure/example/code/debate 是 P1 随生成管线一起定下来的。
#: 改这里必须同步迁移：SQLite 的 CHECK 约束改不动，只能重建表。
PAGE_KINDS = (
    "cover",
    "outline",
    "concept",
    "figure",
    "example",
    "code",
    "quiz",
    "summary",
    "debate",
)
PAGE_STATUSES = ("pending", "ready", "failed")


class Course(PkMixin, TimestampMixin, db.Model):
    __tablename__ = "courses"

    title = db.Column(db.String(255), nullable=False)
    topic = db.Column(db.String(255))
    cover_json = db.Column(db.Text)
    status = db.Column(db.String(16), nullable=False, default="draft")
    page_count = db.Column(db.Integer, nullable=False, default=0)
    duration_min = db.Column(db.Integer, nullable=False, default=0)
    owner_id = db.Column(
        db.String(32), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # 软删标记（P1 §4 的 DELETE /api/courses/{id}）。非空即已删：
    # 列表与详情都看不见它，但页面、版本、事件都还在库里 —— 用户点了删除
    # 又想要回来，或者要去查「那次生成到底怎么回事」时，还在。
    deleted_at = db.Column(db.String(32))
    dsl_json = db.Column(db.Text)

    cover = JSONField("cover_json")
    dsl = JSONField("dsl_json")

    pages = db.relationship(
        "CoursePage",
        back_populates="course",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="CoursePage.page_no",
    )

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('draft', 'generating', 'ready', 'failed')",
            name="course_status_valid",
        ),
        db.CheckConstraint("page_count >= 0", name="course_page_count_non_negative"),
        db.Index("ix_courses_owner_status", "owner_id", "status"),
        # 列表几乎总是「某人的、没删的、按更新时间倒序」，这个索引正对它。
        db.Index("ix_courses_owner_updated", "owner_id", "deleted_at", "updated_at"),
    )

    def to_dict(self, *, include_dsl: bool = False) -> dict:
        payload = {
            "id": self.id,
            "title": self.title,
            "topic": self.topic or "",
            "status": self.status,
            "pageCount": self.page_count,
            "durationMin": self.duration_min,
            "ownerId": self.owner_id,
            "cover": self.cover or {},
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
        if include_dsl:
            payload["dsl"] = self.dsl or {}
        return payload

    def __repr__(self) -> str:
        return f"<Course {self.id} {self.title!r} status={self.status}>"


class CoursePage(PkMixin, TimestampMixin, db.Model):
    __tablename__ = "course_pages"

    course_id = db.Column(
        db.String(32), db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    chapter_no = db.Column(db.Integer, nullable=False, default=1)
    page_no = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(16), nullable=False, default="concept")
    title = db.Column(db.String(255))
    status = db.Column(db.String(16), nullable=False, default="pending")
    dsl_json = db.Column(db.Text)
    # 乐观锁版本号：P1 里同一个课程可能被并行重生成单页
    rev = db.Column(db.Integer, nullable=False, default=1)

    dsl = JSONField("dsl_json")

    course = db.relationship("Course", back_populates="pages")

    __table_args__ = (
        db.UniqueConstraint("course_id", "page_no", name="uq_course_pages_course_page"),
        db.CheckConstraint("page_no > 0", name="course_page_no_positive"),
        db.CheckConstraint(
            "kind IN ('cover', 'outline', 'concept', 'figure', 'example',"
            " 'code', 'quiz', 'summary', 'debate')",
            name="course_page_kind_valid",
        ),
        db.CheckConstraint(
            "status IN ('pending', 'ready', 'failed')", name="course_page_status_valid"
        ),
    )

    def to_dict(self, *, include_dsl: bool = False) -> dict:
        payload = {
            "id": self.id,
            "courseId": self.course_id,
            "chapterNo": self.chapter_no,
            "pageNo": self.page_no,
            "kind": self.kind,
            "title": self.title or "",
            "status": self.status,
            "rev": self.rev,
            "updatedAt": self.updated_at,
        }
        if include_dsl:
            payload["dsl"] = self.dsl or {}
        return payload

    def __repr__(self) -> str:
        return f"<CoursePage {self.course_id}#{self.page_no} {self.kind}>"
