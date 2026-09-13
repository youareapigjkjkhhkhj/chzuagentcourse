"""用量与成本接口（P5 §4.2 / F5-7）。

三条只读路由：

    GET /api/usage/summary       看板的数（按天 / 课程 / 链路分组）
    GET /api/usage/courses/{id}  单课明细：每一次 LLM / 语音调用
    GET /api/usage/models        价目表与「哪几个模型在用」

`GET/PUT /api/settings/budget` 不在这里 —— 它按 §4.2 挂在设置蓝图下
（`api/settings.py`），因为「改预算」与「改音色」是同一类动作：
都是设置页上那个「保存」按钮。这里只读，那边只写。

**所有金额都是估算。** 每个响应里都带一句 `note`，不是客套话：
本机价目表乘出来的数，与上游账单不会逐分对上（阶梯价、赠送额度、舍入
都不在这里）。会话**不返回价格能算出的任何「实际花费」字样** ——
文案上一旦出现「费用」，就会有人拿它去对账。
"""

from __future__ import annotations

from flask import Blueprint, request

from app.common.identity import current_owner_id
from app.common.response import ok
from app.services.courses import library
from app.services.usage import aggregate, pricing

bp = Blueprint("usage", __name__, url_prefix="/api/usage")

#: 一次最多回多少条明细。**这是接口层的上限，不是分页**（见 `aggregate.DETAIL_LIMIT`）：
#: 单课明细是给「这门课到底花在哪了」用的，几百条足够定位问题；
#: 上万条则说明该按天看，而不是把一屏拉成一条无限长的列表。
MAX_DETAIL = 1000


@bp.get("/summary")
def usage_summary():
    """成本看板的数（F5-7）。

    请求示例：
        GET /api/usage/summary?from=2026-09-01&to=2026-09-13&groupBy=day
        GET /api/usage/summary?groupBy=course

    `groupBy` 三选一：`day`（缺省）/ `course` / `kind`。不认识的取值退回 `day`，
    而不是报 400 —— 看板是打开的**第一屏**，为拼错的参数把它变成一页报错，
    不如给一份能看的图（同一个理由见 `services/usage/days.clean`）。

    日期缺省是「最近 30 天」；只给一头时另一头按今天补齐。
    日界是**本地日**（缺省东八区，`USAGE_DAY_OFFSET_HOURS` 可改）——
    「今天的用量」按 UTC 日算的话，会在北京时间早上 8 点重置。
    """
    return ok(
        aggregate.summary(
            date_from=str(request.args.get("from") or ""),
            date_to=str(request.args.get("to") or ""),
            group_by=str(request.args.get("groupBy") or "day"),
            owner_id=current_owner_id(),
        )
    )


@bp.get("/courses/<course_id>")
def usage_of_course(course_id: str):
    """单课明细：每一次 LLM / 语音调用，各带 token、耗时、估算金额（P5 §4.2）。

    请求示例：
        GET /api/usage/courses/c_01H…?limit=200

    课程不存在或不属于当前用户时返回 404（P3-F4：越权与不存在同一个答案）。
    """
    course = library.course_or_404(course_id, current_owner_id())
    limit = _int_arg("limit", aggregate.DETAIL_LIMIT)
    return ok(
        aggregate.course_detail(
            course.id,
            limit=max(1, min(limit, MAX_DETAIL)),
            offset=max(0, _int_arg("offset", 0)),
        )
    )


@bp.get("/models")
def usage_models():
    """支持的模型与价目表（P5 §4.2，设置页维护）。

    请求示例：
        GET /api/usage/models

    两张清单合在一起回：
    - `pricing` 是价目表本身（`promptPer1k` / `completionPer1k` / 每千字符 / 每分钟）；
    - `models` 是**现在真的在用**的模型（已启用服务商的默认模型）——
      价目表里配了一个没人用的模型，与「有个模型没配价」是两件事，
      界面要能分别提示。

    `priced: false` 的链路意味着金额是**少报**的：界面这时该显示「未配置单价」，
    而不是一个 `¥0.00`。
    """
    return ok(
        {
            "pricing": pricing.rows(),
            "models": _active_models(),
            "unit": "CNY",
            "note": "估算值，以账单为准",
        }
    )


def _active_models() -> list[dict]:
    """已启用的服务商正在用哪个模型。读的是注册表（与生成时取模型同一处）。"""
    from app.services.provider_registry import get_registry

    out: list[dict] = []
    registry = get_registry()
    for name in registry.names("llm"):
        provider = registry.get_llm(name)
        if not provider.configured:
            continue
        out.append(
            {
                "provider": name,
                "model": str(getattr(provider, "default_model", "") or ""),
                "active": name == registry.active_llm_name(),
            }
        )
    return out


def _int_arg(name: str, default: int) -> int:
    """取一个整数查询参数。取值不是整数就用缺省值 —— 与 `groupBy` 同一个口径：
    看板上的参数拼错，用户要的是「给我默认的」，不是「给我一句报错」。"""
    try:
        return int(str(request.args.get(name) or default))
    except (TypeError, ValueError):
        return default


__all__ = ["bp"]
