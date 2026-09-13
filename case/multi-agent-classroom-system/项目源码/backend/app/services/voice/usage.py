"""语音用量记账与汇总（P2-A11 / P2-C3）。

一笔账 = 一次真实的计量事件：合成了一段文字、识别了一段语音、对话了若干秒。
写账的时机是**调用返回之后**，拿到上游给的计量口径再写 —— 不是调用之前估一笔。
理由与 `TTSResult.usage` 那段注释同源：估出来的数和账单对不上，那这笔账就是假的。

三条口径：

1. **单位跟着数值走**（`kind → unit_name` 固定映射，不给调用方自由发挥）。
   TTS 按字符、实时语音与 ASR 按秒，是两家上游各自的计费方式，不是我们的选择。
2. **金额是估算**。价目表在配置里（`VOICE_*_PRICE_*`），默认 0 = 没配。
   没配时 `summary()` 的 `priced` 是 False，界面据此说「未配置单价」，
   而不是显示一个 `¥0.00` 让人以为这门课真的不要钱。
3. **账写不进去不能把业务弄挂**。合成已经成功了，音频也在盘上，
   这时因为写账失败而抛异常，用户看到的是「合成失败」—— 而重试一次要花钱。
   所以写账失败只记日志（见 `record`）。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.common.dbw import db_write
from app.common.logging import get_logger
from app.extensions import db
from app.models.usage_record import USAGE_KINDS, UsageRecord
from app.services.usage import ledger, pricing

logger = get_logger("app.voice.usage")

#: 每条链路的计量单位（P2 §5 的 `unit_name`）。写死在这里，不让调用方传 ——
#: 传错一次（TTS 记成 seconds）不会报错，只会让看板的数字从此没有意义。
KIND_UNITS: Mapping[str, str] = {"tts": "chars", "realtime": "seconds", "asr": "seconds"}

#: 价目表的配置键（元）。0 表示没配。
#: **P5 起真正读它们的是 `services/usage/pricing.py`**（同一批键名），
#: 这里留着是因为它是这套键最早的家，且 `__all__` 里已经导出了；
#: 两份常量指向同一个配置，改一处即可，不会分叉。
PRICE_KEYS: Mapping[str, str] = {
    "tts": "VOICE_TTS_PRICE_PER_KCHARS",  # 每千字符
    "realtime": "VOICE_REALTIME_PRICE_PER_MINUTE",  # 每分钟
    "asr": "VOICE_ASR_PRICE_PER_MINUTE",  # 每分钟
}


def estimate_cost(kind: str, units: int) -> float:
    """按价目表估算金额（元）。没配价目就是 0。

    P5 起**单价的计算只有一处**（`services/usage/pricing.py`）：它比这里多认一层
    设置页的覆盖，而看板、预算、账本三处都要用同一个数。这两份算出来的金额
    一旦分叉，用户看到的是「用量表说 3 块、预算说 2 块」，而那时谁也不知道该信哪个。
    这里的函数保留下来，是因为 P2 的调用点与测试都用它。
    """
    return pricing.estimate_units(kind, units)


def priced(kind: str) -> bool:
    """这一类配了单价吗。没配就别说「本次课堂花了 ¥0.00」。"""
    return pricing.priced(kind)


def model_of(provider: Any, *, voice: str = "", model: str = "") -> str:
    """账本那格 `model` 填什么（P5-C2）。

    语音这条链路上「型号」不是一个统一的东西：合成认的是**音色**（换一个音色
    就是另一份产物、另一套价格），实时语音认的是上游的版本标识
    （火山那边是资源 ID）。所以按「调用方给的 → 这一嗓子用的音色 →
    适配器自报的版本 / 默认音色 → 适配器名」依次取，取到第一个非空的为止。

    兜到适配器名是**故意**的：账本里一行不写型号的调用，事后回答不了
    「是哪一档花的钱」；而它至少要说得出是哪个上游。
    """
    for candidate in (
        model,
        voice,
        getattr(provider, "version", ""),
        getattr(provider, "default_voice", ""),
        getattr(provider, "name", ""),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def record(
    kind: str,
    *,
    provider: str = "",
    model: str = "",
    units: int = 0,
    ref_type: str = "course",
    ref_id: str = "",
    latency_ms: int = 0,
) -> UsageRecord | None:
    """写一笔账。返回落库的那一行；写不进去时返回 None 并记日志（见模块 docstring 第 3 条）。

    `units <= 0` 直接不写：零字符的合成、零秒的识别都不是计量事件，
    写进去只会给「本次课堂用了多少」添一行噪声。

    **同时往 `model_calls` 记一行调用事件**（P5-C2）：这张表回答「花了多少钱」，
    那张表回答「调了几次、多慢、成没成」。`kind` 与 `units` 原样带过去，
    金额由账本那边按同一张价目表算 —— 两边不会出现两个数。

    账本那一行**不参与金额合计**（见 `services/usage/aggregate.py` 的分工表）：
    否则一次合成会在看板上被算两遍。
    """
    if kind not in USAGE_KINDS:
        raise ValueError(f"未知的用量类型：{kind!r}")
    units = int(units or 0)
    if units <= 0:
        return None

    row = UsageRecord(
        kind=kind,
        provider=provider,
        units=units,
        unit_name=KIND_UNITS[kind],
        est_cost=estimate_cost(kind, units),
        ref_type=ref_type,
        ref_id=ref_id or "",
    )

    def _work() -> UsageRecord:
        db.session.add(row)
        return row

    try:
        saved = db_write(_work)
    except Exception:  # 账写失败不该让已经成功的合成变成失败
        logger.exception("语音用量记账失败 kind=%s units=%s ref=%s", kind, units, ref_id)
        return None

    record_call(
        kind,
        provider=provider,
        model=model,
        units=units,
        ref_type=ref_type,
        ref_id=ref_id,
        latency_ms=latency_ms,
    )
    return saved


def record_call(
    kind: str,
    *,
    provider: str = "",
    model: str = "",
    units: int = 0,
    ok: bool = True,
    error_code: str = "",
    ref_type: str = "course",
    ref_id: str = "",
    latency_ms: int = 0,
) -> None:
    """只在**账本**里留一行，不写用量表（P5-C2）。

    三种情形要用它，共同点是「没有可计费的量」：

    - 调用**失败**了（`ok=False`）。「上游挂了三次」只在账本上看得到，
      而它正是排障时最先要看的（`record_failure` 是这个调用的别名）。
    - 调用成功了，但**上游没给计量口径**（比如 ASR 没回 `duration_ms`）。
      这时用量表一个字都不该写（写 0 没有意义），但「调了一次」是事实。
    - 将来某条链路只想知道次数、不关心金额。
    """
    if kind not in USAGE_KINDS:
        raise ValueError(f"未知的用量类型：{kind!r}")
    ledger.record(
        kind,
        provider=provider,
        model=model,
        units=int(units or 0),
        ok=ok,
        error_code=error_code,
        latency_ms=latency_ms,
        ref_type=ref_type,
        ref_id=ref_id or "",
    )


def record_failure(
    kind: str,
    *,
    provider: str = "",
    model: str = "",
    error_code: str = "",
    ref_type: str = "course",
    ref_id: str = "",
    latency_ms: int = 0,
) -> None:
    """记一次**失败的**调用：账本留一行，用量表不写（见 `record_call`）。"""
    record_call(
        kind,
        provider=provider,
        model=model,
        ok=False,
        error_code=error_code,
        ref_type=ref_type,
        ref_id=ref_id,
        latency_ms=latency_ms,
    )


def summary(*, ref_type: str | None = None, ref_id: str | None = None) -> dict:
    """汇总用量。给了 ref 就只算这一门课 / 这一次课堂（P2-A11）。

    返回按链路分组的 `{units, estCost}` 与合计。金额一律由 `usage_records` 求和得出
    （不是另算一遍），这样界面上的数字和账本永远一致。
    """
    query = UsageRecord.query
    if ref_type:
        query = query.filter_by(ref_type=ref_type)
    if ref_id:
        query = query.filter_by(ref_id=ref_id)
    rows: Sequence[UsageRecord] = query.all()

    by_kind: dict[str, dict[str, Any]] = {
        kind: {"kind": kind, "units": 0, "unitName": KIND_UNITS[kind], "estCost": 0.0, "calls": 0}
        for kind in USAGE_KINDS
    }
    for row in rows:
        bucket = by_kind.get(row.kind)
        if bucket is None:  # pragma: no cover - CHECK 约束拦着，理论上到不了
            continue
        bucket["units"] += int(row.units or 0)
        bucket["estCost"] = round(bucket["estCost"] + float(row.est_cost or 0.0), 6)
        bucket["calls"] += 1

    return {
        "kinds": [by_kind[kind] for kind in USAGE_KINDS],
        "totalCost": round(sum(item["estCost"] for item in by_kind.values()), 6),
        # 只要有一类没配单价，合计就是**少报**的 —— 界面得说出来
        "priced": all(priced(kind) for kind in USAGE_KINDS),
        "refType": ref_type or "",
        "refId": ref_id or "",
    }


__all__ = [
    "KIND_UNITS",
    "PRICE_KEYS",
    "estimate_cost",
    "model_of",
    "priced",
    "record",
    "record_call",
    "record_failure",
    "summary",
]
