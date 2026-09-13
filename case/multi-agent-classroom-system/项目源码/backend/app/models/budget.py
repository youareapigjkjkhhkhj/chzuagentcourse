"""成本日聚合与预算（P5 §5 / F5-7、F5-8）。

两张表回答的是**两个不同的问题**，别混：

- `daily_usage` 回答「这个月每天花了多少」—— 看板的时间轴（F5-7）。
  它是**派生数据**：把 `model_calls`（LLM）与 `usage_records`（语音）按天重算
  一遍就能得到，删了可以重建。存下来的唯一理由是看板不该每次扫全表。
- `budgets` 回答「还能不能接着花」—— 超限拒绝新任务（F5-8）。

### 账本有两个来源

P2 就把语音用量记在了 `usage_records`（按字符 / 按秒），P0 起 LLM 用量记在
`model_calls`（按 token）。P5 的成本看板**合并这两个来源**，而不是把语音那半
重记一遍进 `model_calls`：P2-A11 的「本次课堂用了多少」已经建在 `usage_records`
上，改动它等于推翻一条已验收的口径。这件事记在 P5 文档 §10.2。

所以 `daily_usage.kind` 跨两个账本取值，见下面的常量。

### 单位与「估算」口径

`total_tokens` 只统计 LLM（语音没有 token 这个概念）；`total_units` 统计语音，
**单位跟着 `kind` 走**（tts 是字符、asr/realtime 是秒），与 `usage_records` 同源。
两者都只对各自的链路有意义，所以**不做跨 kind 求和**：跨链路把 token 与字符
加起来是一个没有意义的数。

`est_cost` 是估算（本地价目表乘出来的），不是账单 —— 这条口径在
`models/usage_record.py` 里已经写过一遍，看板与预算都沿用，前端文案写「估算费用」。
"""

from __future__ import annotations

from app.extensions import db
from app.models.base import PkMixin, TimestampMixin
from app.models.usage_record import USAGE_KINDS

#: 日聚合里的链路：LLM 来自 `model_calls`，其余三条来自 `usage_records`
DAILY_KINDS = ("llm", *USAGE_KINDS)

#: 预算的作用域。`global` 总量 / `course` 单课 / `day` 每日
BUDGET_SCOPES = ("global", "course", "day")


class DailyUsage(PkMixin, TimestampMixin, db.Model):
    """按天 × 链路 × 主人的一行聚合。派生数据，可重算（见模块 docstring）。"""

    __tablename__ = "daily_usage"

    #: **本地日**（`YYYY-MM-DD`），不是 UTC 日 —— 口径见 `services/usage/days.py`：
    #: 按 UTC 切，北京时间早上 8 点日预算就重置了。用日期而不是时间戳：
    #: 看板的横轴是「天」，而按天聚合的行不该在一天之内被写很多次。
    date = db.Column(db.String(10), nullable=False)
    owner_id = db.Column(db.String(32), nullable=False, default="")
    kind = db.Column(db.String(16), nullable=False)
    #: LLM 的 token 总数（语音链路恒为 0，它们的量在 total_units 里）
    total_tokens = db.Column(db.Integer, nullable=False, default=0)
    #: 语音的用量：单位跟着 kind 走（tts=字符，asr/realtime=秒）
    total_units = db.Column(db.Integer, nullable=False, default=0)
    #: 估算金额（元）。别拿它去对账，见模块 docstring
    est_cost = db.Column(db.Float, nullable=False, default=0.0)
    #: 这一行聚合了几次调用 —— 看板上「12 次调用」这种数字要有来源
    calls = db.Column(db.Integer, nullable=False, default=0)

    __table_args__ = (
        db.CheckConstraint(
            "kind IN ('llm', 'tts', 'asr', 'realtime')", name="daily_usage_kind_valid"
        ),
        db.CheckConstraint("total_tokens >= 0", name="daily_usage_tokens_non_negative"),
        db.CheckConstraint("total_units >= 0", name="daily_usage_units_non_negative"),
        db.CheckConstraint("est_cost >= 0", name="daily_usage_cost_non_negative"),
        db.CheckConstraint("calls >= 0", name="daily_usage_calls_non_negative"),
        # 一天一行：聚合写库走「有则累加、无则新建」，靠这条唯一约束兜底
        db.UniqueConstraint("date", "owner_id", "kind", name="uq_daily_usage_date_owner_kind"),
        db.Index("ix_daily_usage_date", "date"),
    )

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "ownerId": self.owner_id,
            "kind": self.kind,
            "totalTokens": self.total_tokens,
            "totalUnits": self.total_units,
            "estCost": round(float(self.est_cost or 0.0), 6),
            "calls": self.calls,
        }

    def __repr__(self) -> str:
        return f"<DailyUsage {self.date} {self.kind} tokens={self.total_tokens}>"


class Budget(PkMixin, TimestampMixin, db.Model):
    """一条预算上限（F5-8）。

    **0 表示不限**，而不是「限额为零」—— 用「没有这一行」表示不限的话，
    设置页上「把日预算关掉」就得删行，而删行与「没设过」在库里长得一样，
    分不清是用户关掉的还是从没设过。

    两个上限（token 与金额）是**或**的关系：先撞上哪个就按哪个拒。
    只设一个也行，另一个留 0。
    """

    __tablename__ = "budgets"

    scope = db.Column(db.String(16), nullable=False)
    #: `course` 时是 course_id；`global` / `day` 是空串（各自唯一一条）
    ref_id = db.Column(db.String(32), nullable=False, default="")
    #: 上限（token 数）。0 = 不限
    limit_tokens = db.Column(db.Integer, nullable=False, default=0)
    #: 上限（元）。0 = 不限
    limit_cost = db.Column(db.Float, nullable=False, default=0.0)
    #: 告警阈值：用到这个比例（0~1）就算「接近上限」，界面提前提示
    alert_ratio = db.Column(db.Float, nullable=False, default=0.8)
    enabled = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (
        db.CheckConstraint(
            "scope IN ('global', 'course', 'day')", name="budget_scope_valid"
        ),
        db.CheckConstraint("limit_tokens >= 0", name="budget_limit_tokens_non_negative"),
        db.CheckConstraint("limit_cost >= 0", name="budget_limit_cost_non_negative"),
        db.CheckConstraint(
            "alert_ratio >= 0 AND alert_ratio <= 1", name="budget_alert_ratio_in_range"
        ),
        # 一个作用域一条：设置页改的是这一条，不是再插一条
        db.UniqueConstraint("scope", "ref_id", name="uq_budgets_scope_ref"),
    )

    def covers(self, *, tokens: int = 0, cost: float = 0.0) -> bool:
        """这份用量还在不在限额内（`enabled=False` 时永远在）。判定逻辑在服务层，
        这里只回答「这两个数有没有撞线」——模型不认识「今天已经花了多少」。"""
        if not self.enabled:
            return True
        if self.limit_tokens and tokens > self.limit_tokens:
            return False
        return not (self.limit_cost and cost > self.limit_cost)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "scope": self.scope,
            "refId": self.ref_id,
            "limitTokens": self.limit_tokens,
            "limitCost": round(float(self.limit_cost or 0.0), 6),
            "alertRatio": round(float(self.alert_ratio or 0.0), 4),
            "enabled": bool(self.enabled),
            "createdAt": self.created_at,
        }

    def __repr__(self) -> str:
        return f"<Budget {self.scope}:{self.ref_id or '*'} tokens={self.limit_tokens}>"


__all__ = ["BUDGET_SCOPES", "DAILY_KINDS", "Budget", "DailyUsage"]
