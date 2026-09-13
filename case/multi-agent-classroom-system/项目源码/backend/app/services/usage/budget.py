"""预算与告警（P5 §4.2 / F5-8）。

**这是整个成本链路里唯一一个会「拒绝别人干活」的模块。** 看板算错了只是难看，
预算判错了要么让用户莫名其妙地干不了活（误拒），要么让限额形同虚设（漏拒）。
所以这里的每条规则都写清楚为什么：

### 谁是「已经花了多少」

与看板同一口径、同一份代码（`aggregate`）：LLM 取 `model_calls`，
语音取 `usage_records`。**不另算一遍** —— 两处各算一遍，迟早会出现
「看板说今天花了 3 块，预算说今天花了 0 块」，而那时用户已经不知道该信哪个。

### 三个作用域，取最严的

`day` 看今天（本地日，见 `days.py`），`course` 看这门课从建课至今，`global` 看全部。
一次判断要**三个都过**：日预算拦「今天花太猛了」，单课预算拦「这一门课太贵了」，
全局拦「总共就这么多」。

### 0 = 不限，不是「限额为零」

与 `models/budget.py` 同一条口径：用「没有这一行」表示不限的话，
设置页上「把日预算关掉」就得删行，而删行与「没设过」在库里长得一样。

### 告警与拒绝是两件事

用量到 `alert_ratio`（缺省 0.8）算「接近上限」—— 接口把它带回去让界面变黄，
**但不拦任何事**。只有真的超了才拒。提前拦住一个还没超预算的请求，
用户看到的是「我明明还有额度，它却说超了」。
"""

from __future__ import annotations

from typing import Any, Mapping

from app.common.dbw import db_write
from app.common.errors import StateError, ValidationError
from app.extensions import db
from app.models import Budget, Course
from app.models.budget import BUDGET_SCOPES, DAILY_KINDS
from app.services.usage import aggregate, days, pricing

__all__ = ["check", "ensure_allowed", "get_all", "status", "update"]

#: 缺省告警阈值：用到 80% 就把界面变黄
DEFAULT_ALERT_RATIO = 0.8


def get_all() -> dict[str, Any]:
    """全部预算设置：`global` / `day` 各一条（没设过的补一条默认的），
    加上**每门配过预算的课各一条**。

    单课预算不补默认行：一条 `refId` 为空的单课预算就是「所有课程」，
    而那是 `global` 的意思（见 `update`）。设置页要「新建一条单课预算」时，
    课程是从课程列表里选的，不需要这里先给一个没有课的占位。

    返回里带着每条当前的用量：设置页要显示「日预算 10 元，今天已用 3.2 元」，
    分两次请求去拼这个界面只会让两半数字来自不同时刻。

    `budgets` 里的**单课预算各自带自己那门课的用量**（见 `_engagement`）——
    设置页列出三条单课预算时，它们比的必须是各自那门课花掉的钱。
    拿一个全局的数铺在三行上是另一种意思，而且看起来完全正常。
    """
    used = _used()
    return {
        "budgets": [
            _payload(row, used=_engagement(row, used=used), course_id=row.ref_id)
            for row in _rows()
        ],
        "current": status(),
        "note": "估算值，以账单为准",
    }


def status(course_id: str = "") -> dict[str, Any]:
    """三个作用域各自「用了多少 / 还剩多少 / 到没到告警线」。

    `course` 那一档说的是**传入的这门课**；不给课程时是一条全 0 的默认项
    （代表「还没指定哪门课」）。单课预算可以有好几条，一个 `course` 键装不下，
    逐条的用量在 `get_all()["budgets"]` 里。
    """
    used = _used(course_id=course_id)
    out: dict[str, Any] = {}
    for row in _rows():
        if row.scope == "course" and row.ref_id != course_id:
            continue
        out[row.scope] = _payload(
            row, used=_engagement(row, used=used, course_id=course_id), course_id=course_id
        )
    # 没设过单课预算时也要有个位置，与另两个作用域对齐（不然界面得判三种情况）
    out.setdefault(
        "course",
        _payload(
            Budget(scope="course", ref_id=course_id, limit_tokens=0, limit_cost=0.0,
                   alert_ratio=DEFAULT_ALERT_RATIO, enabled=True),
            used=used.get("course", {}),
            course_id=course_id,
        ),
    )
    return out


def _engagement(
    row: Budget, *, used: Mapping[str, Mapping[str, Any]] | None = None, course_id: str = ""
) -> dict[str, Any]:
    """这条预算该拿哪一份用量去比。

    `course` 那条**必须按它自己的课程查**：拿一个月总量去比单课上限，
    是把「这门课要花超了」与「这个账号要花超了」混成一件。

    `used["course"]` 是**某一门**课的量（调用方指定的那一门），所以只有
    当这条预算说的正是那一门时才复用；列一批单课预算（`get_all`）时
    那个格子是空的，逐条自己查 —— 否则「这门课已用 0 元」会出现在每一行上，
    而用户会据此把预算调小。
    """
    if row.scope == "course" and row.ref_id and row.ref_id != course_id:
        return _tally(aggregate.totals(course_id=row.ref_id))
    return dict((used or {}).get(row.scope) or {})


def check(*, course_id: str = "", owner_id: str = "") -> dict[str, Any]:
    """三个作用域都比一遍。返回 `{allowed, scope, ...}`，**不抛异常**。

    返回而不抛，是因为调用方要用两种方式处理同一个判断：
    生成任务那一边要**拒绝**（`ensure_allowed`），
    设置页那一边要**显示**（`status`）。抛异常的版本只是它的一层薄封装。

    同一个作用域的两个上限（金额 / token）取**或**：先撞上哪个就按哪个拒，
    报出来的也是那个数 —— 「你超了 0.3 元」和「你超了 12 万 token」
    是两个不同的动作（改预算 / 少生成几页）。
    """
    used = _used(course_id=course_id, owner_id=owner_id)
    for row in _rows():
        if not row.enabled:
            continue
        if row.scope == "course" and row.ref_id != course_id:
            # **别的课的单课预算与这一门无关。** 漏掉这一条的话，
            # 「第 3 课最多花 2 块」会拦住用户开第 4 课 —— 而他改第 3 课的预算
            # 根本解决不了，因为拦住他的是另一门课的额度。这是最难排查的一类误拒。
            continue
        spent = used.get(row.scope, {})
        cost = float(spent.get("cost") or 0.0)
        tokens = int(spent.get("tokens") or 0)
        if row.covers(tokens=tokens, cost=cost):
            continue
        by_tokens = bool(row.limit_tokens and tokens > row.limit_tokens)
        return {
            "allowed": False,
            "scope": row.scope,
            "used": round(cost, 6),
            "usedTokens": tokens,
            "limitCost": round(float(row.limit_cost or 0.0), 6),
            "limitTokens": int(row.limit_tokens or 0),
            "by": "tokens" if by_tokens else "cost",
            "reason": _reason(row, tokens=tokens if by_tokens else 0),
        }
    return {
        "allowed": True,
        "scope": "",
        "used": round(float(used.get("day", {}).get("cost") or 0.0), 6),
        "usedTokens": int(used.get("day", {}).get("tokens") or 0),
        "by": "",
        "reason": "",
    }


def ensure_allowed(*, course_id: str = "", owner_id: str = "") -> None:
    """超预算就抛 40902（F5-8 / P5-A8）。

    文案要说清**是哪一条**超了、超了多少 —— 「已达预算上限」这句话
    在三个作用域下是三个不同的动作（去改日预算 / 去改这门课的预算 / 去改全局）。
    """
    verdict = check(course_id=course_id, owner_id=owner_id)
    if verdict["allowed"]:
        return
    raise StateError(
        verdict["reason"],
        details={
            "ok": False,
            "error": "budget_exceeded",
            "scope": verdict["scope"],
            # 撞的是哪一条线：前端据此决定提示语与「去改预算」的落点
            "by": verdict["by"],
            "used": verdict["used"],
            "usedTokens": verdict["usedTokens"],
            "limitCost": verdict["limitCost"],
            "limitTokens": verdict["limitTokens"],
        },
    )


def update(payload: Any) -> dict[str, Any]:
    """改预算（设置页）。按作用域增量更新，`refId` 为空时只认 day / global。

    `course` 那一档必须带 `refId`：不带就是「所有课程的预算」，
    而那是 `global` 的意思 —— 让它悄悄退化成全局，用户会以为设的是单课。
    """
    if not isinstance(payload, dict):
        raise ValidationError("请求体必须是一个 JSON 对象")
    rows = payload.get("budgets")
    if rows is None:
        rows = [payload]
    if not isinstance(rows, list):
        raise ValidationError("budgets 必须是数组")

    for item in rows:
        if not isinstance(item, Mapping):
            raise ValidationError("budgets 的每一项都必须是对象")
        _apply(item)
    return get_all()


def _apply(item: Mapping[str, Any]) -> None:
    scope = str(item.get("scope") or "").strip()
    if scope not in BUDGET_SCOPES:
        raise ValidationError(
            f"scope 必须是 {' / '.join(BUDGET_SCOPES)} 之一", details={"scope": scope}
        )
    ref_id = str(item.get("refId") or "").strip()
    if scope == "course":
        if not ref_id:
            raise ValidationError("单课预算必须指定 refId", details={"scope": scope})
        if db.session.get(Course, ref_id) is None:
            raise ValidationError("课程不存在", details={"refId": ref_id})

    row = _row(scope, ref_id)
    if row is None:
        row = Budget(scope=scope, ref_id=ref_id)
    if "limitTokens" in item:
        row.limit_tokens = _non_negative_int(item.get("limitTokens"), "limitTokens")
    if "limitCost" in item:
        row.limit_cost = _non_negative_float(item.get("limitCost"), "limitCost")
    if "alertRatio" in item:
        ratio = _non_negative_float(item.get("alertRatio"), "alertRatio")
        if ratio > 1:
            raise ValidationError("alertRatio 必须在 0~1 之间", details={"field": "alertRatio"})
        row.alert_ratio = ratio
    if "enabled" in item:
        row.enabled = bool(item.get("enabled"))

    def _work() -> None:
        db.session.add(row)

    db_write(_work)


# --------------------------------------------------------------------------
# 读
# --------------------------------------------------------------------------


def _rows() -> list[Budget]:
    """三个作用域的行，齐的。缺的**只在内存里补**，不落库。

    不落库是因为这里被读得比写得勤（每次生成任务都要问一遍）：
    为一个从没设过的限额写一行，等于把「用户的默认状态」变成一堆库里的噪声，
    而它和「用户点过保存」在设置页上长得一模一样。
    """
    rows = list(Budget.query.all())
    by_key = {(row.scope, row.ref_id): row for row in rows}
    out: list[Budget] = []
    for scope in BUDGET_SCOPES:
        if scope == "course":
            out.extend(row for row in rows if row.scope == "course")
        elif (scope, "") in by_key:
            out.append(by_key[(scope, "")])
        else:
            out.append(Budget(scope=scope, ref_id="", limit_tokens=0, limit_cost=0.0,
                              alert_ratio=DEFAULT_ALERT_RATIO, enabled=True))
    return out


def _row(scope: str, ref_id: str) -> Budget | None:
    return Budget.query.filter_by(scope=scope, ref_id=ref_id).first()


def _used(*, course_id: str = "", owner_id: str = "") -> dict[str, dict[str, Any]]:
    """三个作用域各自已经花了多少：`{cost, tokens, units}`。

    三处都问 `aggregate.totals` —— 预算与看板是同一份口径、同一段代码，
    这是「看板上的数」与「拦住你的那条线」永远一致的全部理由。

    `global` 那次查询把「今天」与「这门课」都包含在内了，看起来可以省掉两次查询，
    但三者答的是三个问题（今天 / 全部 / 这门课），**各自的窗口不同**，
    省下来的是两次索引扫描，赔进去的是一段「谁是谁的子集」的心智负担。
    """
    span = days.window(days.today(), days.today())
    return {
        "day": _tally(aggregate.totals(date_from=span.first, date_to=span.last, owner_id=owner_id)),
        "global": _tally(aggregate.totals(owner_id=owner_id)),
        "course": _tally(aggregate.totals(course_id=course_id)) if course_id else _tally({}),
    }


def _tally(totals: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "cost": round(float(totals.get("estCost") or 0.0), 6),
        "tokens": int(totals.get("totalTokens") or 0),
        "units": int(totals.get("totalUnits") or 0),
    }


def _payload(row: Budget, *, used: Mapping[str, Any] | None = None, course_id: str = "") -> dict[str, Any]:
    """一条预算 + 它当前的用量。`over` / `alert` 两个布尔是给界面用的，
    判据与 `check()` **同源**（都走 `Budget.covers` 与 `alert_ratio`），
    免得出现「设置页说没超、生成却说你超了」。"""
    spent = dict(used or {})
    cost = float(spent.get("cost") or 0.0)
    tokens = int(spent.get("tokens") or 0)
    limit = float(row.limit_cost or 0.0)
    limit_tokens = int(row.limit_tokens or 0)
    ratio = float(row.alert_ratio or 0.0)

    data = row.to_dict()
    data["usedCost"] = round(cost, 6)
    data["usedTokens"] = tokens
    data["remainingCost"] = round(max(0.0, limit - cost), 6) if limit else 0.0
    data["remainingTokens"] = max(0, limit_tokens - tokens) if limit_tokens else 0
    data["over"] = bool(row.enabled and not row.covers(tokens=tokens, cost=cost))
    # 「接近上限」只在**配了那条线**时才有意义：没配的 0 用了多少都到不了 80%
    data["alert"] = bool(
        row.enabled
        and not data["over"]
        and (
            (limit and cost >= limit * ratio)
            or (limit_tokens and tokens >= limit_tokens * ratio)
        )
    )
    data["priced"] = all(pricing.priced(kind) for kind in DAILY_KINDS)
    data["courseId"] = course_id
    return data


def _reason(row: Budget, *, tokens: int = 0) -> str:
    """拒绝的理由。**说清是哪条线**、以及怎么改 —— 「已达预算上限」在三个作用域下
    是三个不同的动作，用户看到它只能去猜。"""
    what = {"day": "今日", "course": "这门课", "global": "总额"}.get(row.scope, "")
    if tokens:
        return (
            f"{what}预算已用完（上限 {int(row.limit_tokens)} token，已用 {tokens}），"
            "请在设置里调整预算后再试"
        )
    return (
        f"{what}预算已用完（上限 {_money(float(row.limit_cost or 0.0))} 元），"
        "请在设置里调整预算后再试"
    )


def _money(amount: float) -> str:
    """钱怎么显示。小额的预算（测试里设 0.0001）按两位小数会显示成 `0.00` ——
    一句「上限 0.00 元」等于什么都没说。"""
    return f"{amount:.2f}" if amount >= 0.01 or amount == 0 else f"{amount:.4f}"


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field} 必须是数字", details={"field": field})
    if float(value) < 0:
        raise ValidationError(f"{field} 不能是负数", details={"field": field})
    return int(value)


def _non_negative_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field} 必须是数字", details={"field": field})
    if float(value) < 0:
        raise ValidationError(f"{field} 不能是负数", details={"field": field})
    return round(float(value), 6)
