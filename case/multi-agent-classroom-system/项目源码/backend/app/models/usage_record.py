"""语音用量记账（P2 §5 / P2-A11）。

`model_calls` 记的是「调用发生了几次」，这张表记的是「**按量计费的东西用了多少**」——
TTS 按字符、ASR 与实时语音按秒。两笔账分开，因为看板要回答的问题不同：
前者回答「系统稳不稳、哪里慢」，后者回答「这门课花了多少钱」。

三条口径：

1. **这是估算，不是账单。** `est_cost` 由本地价目表（配置项）乘出来，
   与火山控制台的结算数字**不会**逐分对上（阶梯价、赠送额度、舍入都不在这里）。
   所以列名是 `est_cost`、前端文案是「估算费用」，谁也别拿它去对账。
2. **单位必须跟着数值一起存**（`units` + `unit_name`）。只存一个数字，
   过两天就没人知道那是 1200 个字符还是 1200 秒 —— 而这两者的价差是数量级的。
3. **`ref_type`/`ref_id` 是弱引用（不建外键）**，与 `model_calls` 同理：
   课程删了，这几次合成确实花过钱，这笔账不该跟着消失（P5 成本看板会系统性少报）。
   `ref_type=session` 时 `ref_id` 是实时语音会话 id，用于回答「**本次课堂**用了多少」（P2-A11）。
"""

from __future__ import annotations

from app.extensions import db
from app.models.base import PkMixin, TimestampMixin

#: 会花钱的三条链路（llm 走 token，记在 model_calls）
USAGE_KINDS = ("tts", "realtime", "asr")

#: 计量单位。chars = 合成字符数；seconds = 语音时长（识别与对话都按秒）
UNIT_NAMES = ("chars", "seconds")

#: 这笔账挂在什么上
REF_TYPES = ("course", "session")


class UsageRecord(PkMixin, TimestampMixin, db.Model):
    __tablename__ = "usage_records"

    kind = db.Column(db.String(16), nullable=False)
    provider = db.Column(db.String(32), nullable=False, default="")
    #: Integer 而非 Float：字符数是整数，时长按秒取整。计费粒度本来就是整数量级，
    #: 用小数只会让人误以为这里存的是精确值。
    units = db.Column(db.Integer, nullable=False, default=0)
    unit_name = db.Column(db.String(16), nullable=False, default="chars")
    #: 估算金额（元）。理由见模块 docstring 第 1 条，别拿它当账
    est_cost = db.Column(db.Float, nullable=False, default=0.0)
    ref_type = db.Column(db.String(16), nullable=False, default="course")
    ref_id = db.Column(db.String(32), nullable=False, default="")

    __table_args__ = (
        db.CheckConstraint(
            "kind IN ('tts', 'realtime', 'asr')", name="usage_record_kind_valid"
        ),
        db.CheckConstraint(
            "unit_name IN ('chars', 'seconds')", name="usage_record_unit_name_valid"
        ),
        db.CheckConstraint(
            "ref_type IN ('course', 'session')", name="usage_record_ref_type_valid"
        ),
        db.CheckConstraint("units >= 0", name="usage_record_units_non_negative"),
        db.CheckConstraint("est_cost >= 0", name="usage_record_cost_non_negative"),
        # 「本次课堂花了多少」按 ref 查（P2-A11 / P2-C3）
        db.Index("ix_usage_records_ref", "ref_type", "ref_id"),
        # 成本看板按时间与链路聚合
        db.Index("ix_usage_records_kind_created", "kind", "created_at"),
        db.Index("ix_usage_records_created", "created_at"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "provider": self.provider,
            "units": self.units,
            "unitName": self.unit_name,
            "estCost": round(float(self.est_cost or 0.0), 6),
            "refType": self.ref_type,
            "refId": self.ref_id,
            "createdAt": self.created_at,
        }

    def __repr__(self) -> str:
        return f"<UsageRecord {self.kind} {self.units}{self.unit_name} ref={self.ref_id}>"


__all__ = ["REF_TYPES", "UNIT_NAMES", "USAGE_KINDS", "UsageRecord"]
