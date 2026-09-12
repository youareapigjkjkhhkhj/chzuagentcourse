"""时间工具。

约定（P0 §5）：所有时间统一存 UTC ISO8601 **字符串**，形如
    2026-09-12T08:30:00.123456Z

为什么不用 SQLAlchemy 的 DateTime：
- SQLite 没有原生时间类型，存字符串反而更可控、可跨库导出；
- 微秒精度让 updated_at 的「是否变化」可判断；
- 带 Z 后缀，前端 `new Date(...)` 直接可解析。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

UTC = timezone.utc

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_iso(moment: datetime | None = None) -> str:
    """datetime → UTC ISO8601 字符串（带 Z）。naive 时间按 UTC 处理。"""
    if moment is None:
        moment = utcnow()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime(ISO_FORMAT) + "Z"


def utcnow_iso() -> str:
    """当前 UTC 时间。用作 SQLAlchemy 的 default / onupdate。"""
    return to_iso()


def parse_iso(value: str | None) -> datetime | None:
    """ISO8601 字符串 → 带时区的 datetime。解析不了返回 None，不抛异常。"""
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def elapsed_ms(started: datetime | None) -> int:
    """从某个时刻到现在经过的毫秒数，用于探活延迟等。"""
    if started is None:
        started = utcnow()
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    delta: timedelta = utcnow() - started
    return max(0, int(delta.total_seconds() * 1000))


__all__ = ["UTC", "elapsed_ms", "parse_iso", "to_iso", "utcnow", "utcnow_iso"]
