"""课程页的版本链（P1 §5 / P1-C4）。

每次生成、重写、人工编辑都追加一条，**不覆盖**。当前内容仍以
`course_pages.dsl_json` 为准（读页面不必 join 版本表），版本表是
「改坏了能退回去」的那条退路，也是 P1-A7「其余页未受影响」的比对依据。

`meta_json` 里放 `promptVersion`：prompt 调过一次，同一门课的前后页
就是两个版本生成的 —— 质量回溯时得能说清某页出自哪一版（技术方案 §209）。
"""

from __future__ import annotations

from app.extensions import db
from app.models.base import JSONField, PkMixin, TimestampMixin

#: 版本来源。manual 是用户在编辑区手改（P1-A11 要求能查到这个标记）。
#:
#: `seed` 是 P1-7 的示例课才有的：那几页是手写素材，既不是模型生成
#: （generate）也不是人工编辑（manual）—— 记成哪一个都是在数据里说谎，
#: 而版本表存在的意义正是「这一页是怎么变成现在这样的」。手写素材进了
#: 版本表，用户第一次重写它时也才有一个能退回去的「上一版」。
#:
#: 改这个元组必须同步迁移：SQLite 改不动 CHECK 约束，只能重建表
#: （migrations/versions/*_p1_seed_page_versions.py）。
PAGE_VERSION_REASONS = ("generate", "rewrite", "manual", "seed")


class CoursePageVersion(PkMixin, TimestampMixin, db.Model):
    __tablename__ = "course_page_versions"

    page_id = db.Column(
        db.String(32), db.ForeignKey("course_pages.id", ondelete="CASCADE"), nullable=False
    )
    rev = db.Column(db.Integer, nullable=False)
    dsl_json = db.Column(db.Text)
    reason = db.Column(db.String(16), nullable=False, default="generate")
    instruction = db.Column(db.Text)
    model = db.Column(db.String(64))
    tokens = db.Column(db.Integer, nullable=False, default=0)
    meta_json = db.Column(db.Text)

    dsl = JSONField("dsl_json")
    meta = JSONField("meta_json")

    page = db.relationship("CoursePage")

    __table_args__ = (
        db.UniqueConstraint("page_id", "rev", name="uq_course_page_versions_page_rev"),
        db.CheckConstraint(
            "reason IN ('generate', 'rewrite', 'manual', 'seed')",
            name="course_page_version_reason_valid",
        ),
        db.CheckConstraint("rev > 0", name="course_page_version_rev_positive"),
    )

    def to_dict(self, *, include_dsl: bool = False) -> dict:
        payload = {
            "id": self.id,
            "pageId": self.page_id,
            "rev": self.rev,
            "reason": self.reason,
            "instruction": self.instruction or "",
            "model": self.model or "",
            "tokens": self.tokens,
            "createdAt": self.created_at,
        }
        if include_dsl:
            payload["dsl"] = self.dsl or {}
        return payload

    def __repr__(self) -> str:
        return f"<CoursePageVersion {self.page_id} rev={self.rev} {self.reason}>"


__all__ = ["PAGE_VERSION_REASONS", "CoursePageVersion"]
