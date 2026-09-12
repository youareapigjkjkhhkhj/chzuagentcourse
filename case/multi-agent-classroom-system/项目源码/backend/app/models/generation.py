"""生成任务、步骤与事件（P1 §5）。

三张表是一条时间线的三个粒度：

    gen_jobs    一次生成（一门课）—— 状态、总进度、总 token
    gen_steps   这次生成里的一步 —— 解析/大纲/写作/测验/语音/装配
    gen_events  这一步推给前端的每一帧 —— SSE 的原始留档

**为什么事件要落库**：SSE 连接断掉之后前端要能补上错过的进度，
补发的依据只能是「服务端记过的 seq」，不能是「前端猜它到哪了」
（AGENTS §4.3 服务端是唯一状态源）。`gen_events(job_id, seq)` 的唯一约束
就是这条补发链路的地基 —— 重号会让 Last-Event-ID 回到错的位置。
"""

from __future__ import annotations

from app.extensions import db
from app.models.base import JSONField, PkMixin, TimestampMixin

#: 任务状态。paused 是「大纲已出、等用户确认」那一档（P1 §3.1）。
JOB_STATUSES = ("queued", "running", "paused", "done", "failed", "canceled")

#: 步骤类型。tts 在 P1 只占位（P2 才接语音），但位置先留好，前端六步卡是照它画的。
STEP_TYPES = ("parse", "outline", "write", "quiz", "tts", "assemble")

#: 步骤状态。skipped 与 failed 是两回事：前者是「用户删了这章」这类正常跳过，
#: 后者要能重试（P1-F1 的失败不阻塞整课就落在这个区分上）。
STEP_STATUSES = ("wait", "running", "done", "failed", "skipped")


class GenJob(PkMixin, TimestampMixin, db.Model):
    __tablename__ = "gen_jobs"

    course_id = db.Column(
        db.String(32), db.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    owner_id = db.Column(
        db.String(32), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status = db.Column(db.String(16), nullable=False, default="queued")
    progress = db.Column(db.Integer, nullable=False, default=0)
    total_ms = db.Column(db.Integer, nullable=False, default=0)
    total_tokens = db.Column(db.Integer, nullable=False, default=0)
    options_json = db.Column(db.Text)
    error = db.Column(db.Text)

    options = JSONField("options_json")

    steps = db.relationship(
        "GenStep",
        back_populates="job",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="GenStep.seq",
    )
    events = db.relationship(
        "GenEvent",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="GenEvent.seq",
    )

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('queued', 'running', 'paused', 'done', 'failed', 'canceled')",
            name="gen_job_status_valid",
        ),
        db.CheckConstraint(
            "progress >= 0 AND progress <= 100", name="gen_job_progress_in_range"
        ),
        db.Index("ix_gen_jobs_course", "course_id"),
        db.Index("ix_gen_jobs_owner_status", "owner_id", "status"),
    )

    def to_dict(self, *, with_steps: bool = False) -> dict:
        payload = {
            "id": self.id,
            "courseId": self.course_id,
            "status": self.status,
            "progress": self.progress,
            "totalMs": self.total_ms,
            "totalTokens": self.total_tokens,
            "options": self.options or {},
            "error": self.error or "",
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
        if with_steps:
            # 下面那行的类型忽略是必要的：Flask-SQLAlchemy 3.x 的 stub 把 relationship
            # 标成 RelationshipProperty，于是「按关系取子对象」在 mypy 眼里不可迭代。
            # 这是 stub 的缺口（与 pyproject 里那条 name-defined 覆盖同源），不是代码缺陷。
            payload["steps"] = [step.to_dict() for step in self.steps]  # type: ignore[attr-defined]
        return payload

    def __repr__(self) -> str:
        return f"<GenJob {self.id} {self.status} {self.progress}%>"


class GenStep(PkMixin, TimestampMixin, db.Model):
    __tablename__ = "gen_steps"

    job_id = db.Column(
        db.String(32), db.ForeignKey("gen_jobs.id", ondelete="CASCADE"), nullable=False
    )
    seq = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(16), nullable=False)
    title = db.Column(db.String(255), nullable=False, default="")
    status = db.Column(db.String(16), nullable=False, default="wait")
    detail_json = db.Column(db.Text)
    duration_ms = db.Column(db.Integer, nullable=False, default=0)
    tokens = db.Column(db.Integer, nullable=False, default=0)
    error = db.Column(db.Text)
    started_at = db.Column(db.String(32))
    finished_at = db.Column(db.String(32))

    detail = JSONField("detail_json")

    job = db.relationship("GenJob", back_populates="steps")

    __table_args__ = (
        db.UniqueConstraint("job_id", "seq", name="uq_gen_steps_job_seq"),
        db.CheckConstraint(
            "type IN ('parse', 'outline', 'write', 'quiz', 'tts', 'assemble')",
            name="gen_step_type_valid",
        ),
        db.CheckConstraint(
            "status IN ('wait', 'running', 'done', 'failed', 'skipped')",
            name="gen_step_status_valid",
        ),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "jobId": self.job_id,
            "seq": self.seq,
            "type": self.type,
            "title": self.title,
            "status": self.status,
            "detail": self.detail or {},
            "durationMs": self.duration_ms,
            "tokens": self.tokens,
            "error": self.error or "",
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
        }

    def __repr__(self) -> str:
        return f"<GenStep {self.job_id}#{self.seq} {self.type} {self.status}>"


class GenEvent(PkMixin, TimestampMixin, db.Model):
    __tablename__ = "gen_events"

    job_id = db.Column(
        db.String(32), db.ForeignKey("gen_jobs.id", ondelete="CASCADE"), nullable=False
    )
    seq = db.Column(db.Integer, nullable=False)
    event = db.Column(db.String(32), nullable=False)
    payload_json = db.Column(db.Text)

    payload = JSONField("payload_json")

    __table_args__ = (
        db.UniqueConstraint("job_id", "seq", name="uq_gen_events_job_seq"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "jobId": self.job_id,
            "seq": self.seq,
            "event": self.event,
            "payload": self.payload or {},
            "createdAt": self.created_at,
        }

    def __repr__(self) -> str:
        return f"<GenEvent {self.job_id}#{self.seq} {self.event}>"


__all__ = ["JOB_STATUSES", "STEP_STATUSES", "STEP_TYPES", "GenEvent", "GenJob", "GenStep"]
