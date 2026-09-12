"""外部调用记账与审计（AGENTS §4.5 / §24，P1-F2）。

`model_calls` 是**账本**，不是业务数据的附属品：它记的是「钱已经花出去了」。
所以 job_id / owner_id 用普通字符串列而**不建外键** —— 删掉一门课不应该
让「这几次调用花过多少 token」从账上消失，否则 P5 的成本看板会系统性少报。

`audit_logs` 记的是「系统为合规做过什么」，P1 只用到敏感词拦截一条路径
（命中即整段重生成 1 次，并把命中的词与处理结果留档）。
"""

from __future__ import annotations

from app.extensions import db
from app.models.base import JSONField, PkMixin, TimestampMixin

#: 四类外部能力，与技术方案的能力划分一致
MODEL_CALL_KINDS = ("llm", "tts", "asr", "realtime")


class ModelCall(PkMixin, TimestampMixin, db.Model):
    __tablename__ = "model_calls"

    kind = db.Column(db.String(16), nullable=False)
    provider = db.Column(db.String(32), nullable=False, default="")
    model = db.Column(db.String(64), nullable=False, default="")
    tokens = db.Column(db.Integer, nullable=False, default=0)
    latency_ms = db.Column(db.Integer, nullable=False, default=0)
    ok = db.Column(db.Boolean, nullable=False, default=True)
    error_code = db.Column(db.String(32))
    #: 这些是弱引用（无外键）：账本不随业务数据级联删除，见模块 docstring
    job_id = db.Column(db.String(32))
    owner_id = db.Column(db.String(32))

    __table_args__ = (
        db.CheckConstraint(
            "kind IN ('llm', 'tts', 'asr', 'realtime')", name="model_call_kind_valid"
        ),
        db.Index("ix_model_calls_created", "created_at"),
        db.Index("ix_model_calls_job", "job_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "provider": self.provider,
            "model": self.model,
            "tokens": self.tokens,
            "latencyMs": self.latency_ms,
            "ok": bool(self.ok),
            "errorCode": self.error_code or "",
            "createdAt": self.created_at,
        }

    def __repr__(self) -> str:
        return f"<ModelCall {self.kind} {self.provider}/{self.model} ok={bool(self.ok)}>"


class AuditLog(PkMixin, TimestampMixin, db.Model):
    __tablename__ = "audit_logs"

    action = db.Column(db.String(32), nullable=False)
    #: 形如 `course:c_01H…` / `page:p_01H…`，用字符串而不是两个外键：
    #: 被审计的对象可能已经被删了，而这正是审计要能回答的问题之一。
    target = db.Column(db.String(64))
    owner_id = db.Column(db.String(32))
    detail_json = db.Column(db.Text)

    detail = JSONField("detail_json")

    __table_args__ = (db.Index("ix_audit_logs_action_created", "action", "created_at"),)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action": self.action,
            "target": self.target or "",
            "ownerId": self.owner_id or "",
            "detail": self.detail or {},
            "createdAt": self.created_at,
        }

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} {self.target or '-'}>"


__all__ = ["MODEL_CALL_KINDS", "AuditLog", "ModelCall"]
