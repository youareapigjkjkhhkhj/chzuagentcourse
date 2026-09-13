"""外部调用记账与审计（AGENTS §4.5 / §24，P1-F2；P5 扩列见 §5）。

`model_calls` 是**账本**，不是业务数据的附属品：它记的是「钱已经花出去了」。
所以 job_id / owner_id 用普通字符串列而**不建外键** —— 删掉一门课不应该
让「这几次调用花过多少 token」从账上消失，否则 P5 的成本看板会系统性少报。

`audit_logs` 记的是「系统为合规做过什么」，P1 只用到敏感词拦截一条路径
（命中即整段重生成 1 次，并把命中的词与处理结果留档）。

### P5 扩列（F5-7 / F5-10 / A14）

账本里原本只有 `tokens`（总数）与 `latency`，够回答「稳不稳、快不快」，
不够回答 P5 问的三个问题：

1. **贵在哪一半？** 补 `prompt_tokens` / `completion_tokens`。输入输出价差
   通常有好几倍，只有一个总数就没法解释「为什么这次特别贵」。
2. **这次调用是为谁花的？** 补 `ref_type`（`course` / `job` / `session` / `chat`）、
   `ref_id` 与 `step_id`。没有它们，单课明细（`GET /api/usage/courses/{id}`）
   与任务时间线（F5-10）只能靠 `job_id` 反查，而工作台改课那条链路根本没有 job。
3. **折成钱是多少？** 补 `est_cost`（本地价目表乘出来的**估算**，口径同
   `usage_records`：不是账单，前端文案写「估算费用」）。

`units` / `unit_name` 是给**非 token 链路**留的位（TTS 按字符、ASR 与实时语音
按秒）。它们与 `usage_records` 有重叠，但两边记的**粒度和时机不同**：`model_calls`
记「调用了一次」（连失败的那次也在），`usage_records` 记「按什么计价用了多少」。
P5 的成本看板把两者合起来算，口径写在 P5 文档 §10.2。

**`tokens` 继续是总数**（= 输入 + 输出），不是「历史遗留列」：P1-D4 的
`_ledger_tokens()` 按 `job_id` 对它求和来对账，改它的含义等于推翻一条已验收的口径。
"""

from __future__ import annotations

from app.extensions import db
from app.models.base import JSONField, PkMixin, TimestampMixin

#: 四类外部能力，与技术方案的能力划分一致
MODEL_CALL_KINDS = ("llm", "tts", "asr", "realtime")

#: 这笔调用是**为谁**花的。空串表示「还不知道」（老数据、或调用发生在归属确定之前）。
#: 名字带 CALL_ 前缀是因为 `usage_records` 另有一套 REF_TYPES（course/session）——
#: 两者别混：那边回答「按量计费的东西挂在谁身上」，这边还要多一个 `chat`（工作台改课）。
CALL_REF_TYPES = ("course", "job", "session", "chat")

#: `units` 的单位。`tokens` 是 LLM 的，另两个与 `usage_records` 的 UNIT_NAMES 同源
CALL_UNIT_NAMES = ("tokens", "chars", "seconds")


class ModelCall(PkMixin, TimestampMixin, db.Model):
    __tablename__ = "model_calls"

    kind = db.Column(db.String(16), nullable=False)
    provider = db.Column(db.String(32), nullable=False, default="")
    model = db.Column(db.String(64), nullable=False, default="")
    #: **总数**（输入 + 输出）。P1-D4 按它求和，别改含义，见模块 docstring
    tokens = db.Column(db.Integer, nullable=False, default=0)
    latency_ms = db.Column(db.Integer, nullable=False, default=0)
    ok = db.Column(db.Boolean, nullable=False, default=True)
    error_code = db.Column(db.String(32))
    #: 这些是弱引用（无外键）：账本不随业务数据级联删除，见模块 docstring
    job_id = db.Column(db.String(32))
    owner_id = db.Column(db.String(32))

    # --- P5 扩列 ---
    prompt_tokens = db.Column(db.Integer, nullable=False, default=0)
    completion_tokens = db.Column(db.Integer, nullable=False, default=0)
    #: 非 token 链路的用量（TTS 字符数 / ASR 与实时语音秒数）
    units = db.Column(db.Integer, nullable=False, default=0)
    unit_name = db.Column(db.String(16), nullable=False, default="")
    #: 估算金额（元）。列名带 est_ 就是提醒：这是估算，不是账单
    est_cost = db.Column(db.Float, nullable=False, default=0.0)
    ref_type = db.Column(db.String(16), nullable=False, default="")
    ref_id = db.Column(db.String(32), nullable=False, default="")
    #: 生成任务里的哪一步（`gen_steps.id`），F5-10 的「每步耗时/重试/token」按它聚合
    step_id = db.Column(db.String(32), nullable=False, default="")

    # 注：P5 加的这几列**没有** CHECK 约束，是有意的 —— SQLite 加 CHECK 要整表重建，
    # 而这是 P1 起就在写热的账本。非负性由唯一的写入点 `services/usage/ledger.py`
    # 保证（那里有单测）。这条口径写在 P5 那条迁移的 docstring 里。
    __table_args__ = (
        db.CheckConstraint(
            "kind IN ('llm', 'tts', 'asr', 'realtime')", name="model_call_kind_valid"
        ),
        db.Index("ix_model_calls_created", "created_at"),
        db.Index("ix_model_calls_job", "job_id"),
        # 单课明细（GET /api/usage/courses/{id}）与课堂用量都按这一对查
        db.Index("ix_model_calls_ref", "ref_type", "ref_id"),
        # 任务时间线按步骤聚合（F5-10）
        db.Index("ix_model_calls_step", "step_id"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "provider": self.provider,
            "model": self.model,
            "tokens": self.tokens,
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
            "units": self.units,
            "unitName": self.unit_name,
            "estCost": round(float(self.est_cost or 0.0), 6),
            "latencyMs": self.latency_ms,
            "ok": bool(self.ok),
            "errorCode": self.error_code or "",
            "jobId": self.job_id or "",
            "refType": self.ref_type,
            "refId": self.ref_id,
            "stepId": self.step_id,
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
    #: P5-A14：审计要能回答「谁、从哪儿、用什么」做的。IP 与 UA 各存一列 ——
    #: 塞进 detail_json 就成了「看运气才有的信息」，而这两列是要能直接查的。
    ip = db.Column(db.String(64), nullable=False, default="")
    ua = db.Column(db.String(255), nullable=False, default="")

    detail = JSONField("detail_json")

    __table_args__ = (
        db.Index("ix_audit_logs_action_created", "action", "created_at"),
        db.Index("ix_audit_logs_owner_created", "owner_id", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action": self.action,
            "target": self.target or "",
            "ownerId": self.owner_id or "",
            "detail": self.detail or {},
            "ip": self.ip or "",
            "ua": self.ua or "",
            "createdAt": self.created_at,
        }

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} {self.target or '-'}>"


__all__ = ["CALL_REF_TYPES", "CALL_UNIT_NAMES", "MODEL_CALL_KINDS", "AuditLog", "ModelCall"]
