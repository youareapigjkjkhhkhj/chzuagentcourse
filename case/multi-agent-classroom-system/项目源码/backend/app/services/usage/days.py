"""日界（P5-7 / F5-8）。

**这个模块只回答一个问题：某一刻属于哪一天。**

它有必要单独存在，是因为仓库里所有时间都按 UTC 存（P0 §5），而「今天」对用户
不是 UTC 的今天。北京时间 9 月 13 日早上 7 点的课，UTC 时刻属于 9 月 12 日 ——
如果日预算按 UTC 日重置，用户会在**早上 8 点**看到预算归零。那不是一个小数点
的问题，是「日预算」这个词在用户那里根本不成立。

所以：**日 = UTC 时刻 + 偏移量之后的日历日**，偏移量由 `USAGE_DAY_OFFSET_HOURS`
给出（缺省 8，即北京时间）。部署到别的时区就改它，UTC 就设 0。

看板的横轴、`daily_usage.date`、日预算的重置时刻**共用这一个定义** ——
两处各定义一次「天」，迟早会出现「看板说今天花了 3 块，预算说今天花了 0 块」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from flask import current_app

from app.common.timeutil import UTC, parse_iso, to_iso, utcnow

__all__ = [
    "DEFAULT_OFFSET_HOURS",
    "Range",
    "bounds",
    "clean",
    "day_of",
    "days_between",
    "local_day",
    "offset_hours",
    "shift",
    "today",
    "window",
]

#: 缺省偏移（小时）。8 = 北京时间 —— 这个产品的用户在哪，看界面语言就知道。
DEFAULT_OFFSET_HOURS = 8


@dataclass(frozen=True)
class Range:
    """一段本地日区间，以及它在库里的 UTC 时刻范围。

    `start` / `end` 是**库里拿来做范围比较的**那两个字符串（左闭右开），
    `first` / `last` / `days` 是给人看的（响应里要原样回显、横轴要按它铺格子）。
    """

    start: str
    end: str
    first: str
    last: str
    days: list[str] = field(default_factory=list)


#: 真实存在的时区偏移区间（UTC-12 ~ UTC+14）。越界的一律当成配置写错了。
_OFFSET_RANGE = (-12, 14)


def offset_hours() -> int:
    """本地时区相对 UTC 的偏移（小时），夹在真实时区的范围内。

    夹一下是因为**写错的偏移不会报错**：`USAGE_DAY_OFFSET_HOURS=80` 只会让
    每一天都往后挪三天多，于是「今天」永远是空的、看板上的柱子一根根错位 ——
    而界面一切正常。宁可退回缺省，也不要按一个不存在的时区算账。
    """
    try:
        value = int(current_app.config.get("USAGE_DAY_OFFSET_HOURS", DEFAULT_OFFSET_HOURS))
    except (TypeError, ValueError):
        return DEFAULT_OFFSET_HOURS
    low, high = _OFFSET_RANGE
    return max(low, min(high, value))


def shift(moment: datetime) -> datetime:
    """UTC 时刻 → 「本地钟面上」的时刻（仍带 UTC 时区，只是小时数平移过）。

    平移而不是真换时区：下游只需要用它取日历日与做日界运算，
    而 `zoneinfo` 要处理夏令时（中国没有，别的部署可能有），
    这里要的是「运维说了算的一个固定偏移」。
    """
    return moment.astimezone(UTC) + timedelta(hours=offset_hours())


def today() -> str:
    """今天的本地日，`YYYY-MM-DD`。"""
    return local_day()


def local_day(moment: datetime | None = None) -> str:
    return shift(moment or utcnow()).strftime("%Y-%m-%d")


def day_of(value: str | None) -> str:
    """库里那个 ISO 时刻属于哪一天。解析不了给空串（调用方按「无日」处理）。"""
    parsed = parse_iso(value)
    return local_day(parsed) if parsed is not None else ""


def bounds(day: str) -> tuple[str, str]:
    """一个本地日 ⇄ 库里的 UTC 时刻窗口 `[start, end)`。

    存的是字符串，所以范围查询也是字符串比较 —— 格式固定
    （`%Y-%m-%dT%H:%M:%S.%fZ`）时它与时间先后一致，见 `common/timeutil.py`。
    """
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC) - timedelta(hours=offset_hours())
    return to_iso(start), to_iso(start + timedelta(days=1))


def window(date_from: str = "", date_to: str = "") -> Range:
    """把 `?from=&to=` 两个本地日变成一段可查的窗口。

    两头都缺省时给的是「最近 30 天（含今天）」—— 成本看板一打开总得有东西看。
    只给一头时另一头按「今天」补齐，这样 `?from=2026-09-01` 是「从那天到今天」，
    与人的直觉一致。两个日期填反了就对调：少一次 400，多一次能看的图。
    """
    last = clean(date_to) or today()
    first = clean(date_from) or _minus(last, 29)
    if first > last:
        first, last = last, first
    start, _ = bounds(first)
    _, end = bounds(last)
    return Range(start=start, end=end, first=first, last=last, days=days_between(first, last))


def _minus(day: str, days: int) -> str:
    moment = datetime.strptime(day, "%Y-%m-%d") - timedelta(days=days)
    return moment.strftime("%Y-%m-%d")


def clean(value: str) -> str:
    """`YYYY-MM-DD` → 自己；`2026-9-3` 这类不补零的也认（顺手补成 `2026-09-03`）。

    别的（空串、`昨天`、带时间的 ISO、`2026-13-40`）→ 空串。

    空串在上游被当成「没填」，于是走缺省值 —— 比抛一个 400 好：
    成本看板打开时不带参数是**常态**，而一个手输的日期格式不对，
    用户的预期是「给我默认的」，不是「给我一句报错」。

    **带时间的 ISO 会被截成日期**（先取前 10 个字符再解析）：
    `2026-09-13T00:00:00Z` → `2026-09-13`。宽松是有意的 —— 前端某些
    日期控件回的就是这种串，为此把它当非法值退回「最近 30 天」，
    用户看到的是「我筛了 9 月 13 日，它给我一整月」。
    注意截的是**日期部分**，而后端里所有日期都是本地日，
    所以 `...T23:00:00Z` 那一天按东八区算会落到次日 —— 前端要传就传纯日期。
    """
    text = str(value or "").strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def days_between(first: str, last: str) -> list[str]:
    """`[first, last]` 之间的每一个本地日。区间内的日期都是合法的，不会有空洞。"""
    start = date(*map(int, first.split("-")))
    end = date(*map(int, last.split("-")))
    return [
        (start + timedelta(days=index)).strftime("%Y-%m-%d")
        for index in range((end - start).days + 1)
    ]
