"""价目表与估算金额（P5 §5 / F5-7）。

**这里算出来的每一个数都是估算，不是账单。** 列名带 `est_`、接口字段叫 `estCost`、
前端文案写「估算费用」—— 全是同一件事在三个地方的重复，因为这是最容易被误用的一处：
阶梯价、赠送额度、舍入、汇率都不在这张表里，拿它去和上游对账必然对不上。

### 两处来源，一个出口

- **配置**（`.env` 的 `LLM_PRICE_*` / `VOICE_*_PRICE_*`）是**部署级**默认值：
  运维知道这个部署签的是哪档价，改环境变量就行。
- **`settings_kv.pricing`** 是**用户级**覆盖：设置页里改，改完立刻生效。

合并顺序是「配置打底、设置覆盖」，与 `settings_service._merged` 同一条口径：
多一个键就多一个能改的地方，而**只有一处**做合并，两边就不会算出不同的数。

### 为什么单价要按模型分

输入与输出的价差通常有好几倍（这也是 `model_calls` 补 `prompt_tokens` /
`completion_tokens` 的原因，见 `models/telemetry.py`）。一个笼统的「每千 token 若干元」
只能解释「这次花了多少」，解释不了「为什么这次特别贵」。
`llm` 那一档因此是 `{模型名: {promptPer1k, completionPer1k}}`，
并支持一个 `"*"` 通配项兜住没单独配价的模型。
"""

from __future__ import annotations

from typing import Any, Mapping

from flask import current_app

from app.common.dbw import db_write
from app.common.errors import ValidationError
from app.extensions import db
from app.models.settings_kv import SettingsKV

__all__ = [
    "KEY_PRICING",
    "KIND_UNIT_PRICES",
    "effective",
    "estimate_llm",
    "estimate_units",
    "priced",
    "rows",
    "update",
]

#: `settings_kv` 里的键名（P5 §5 写的就是这个键）
KEY_PRICING = "pricing"

#: 语音三条链路在价目表里的**计价单位**。与 `services/voice/usage.KIND_UNITS`
#: 是两回事：那边是「用了多少」（字符 / 秒），这边是「多少钱一份」。
#: tts 按千字符、asr 与 realtime 按分钟 —— 两家上游各自的计费方式，不是我们选的。
KIND_UNIT_PRICES: Mapping[str, tuple[str, float]] = {
    # kind: (价目表里的字段名, 一份是多少个计量单位)
    "tts": ("perKChars", 1000),
    "asr": ("perMinute", 60),
    "realtime": ("perMinute", 60),
}

#: 单价为 0 时的口径与预算的「0 = 不限」是同一种表达：**0 = 没配**。
#: 界面据此说「未配置单价」，而不是显示 `¥0.00` 让人以为这门课真的不要钱。
#: 它是靠 `_config_defaults()` 的缺省值与 `priced()` 一起实现的，
#: 没有单独的形状 —— 别在这里放一个空表当兜底，那只会让人以为读的是它。


def _config_defaults() -> dict[str, Any]:
    """从配置读出的一张价目表。缺的键就是 0（没配）。"""
    cfg = current_app.config
    return {
        "llm": {
            "*": {
                "promptPer1k": _float(cfg.get("LLM_PRICE_PROMPT_PER_1K")),
                "completionPer1k": _float(cfg.get("LLM_PRICE_COMPLETION_PER_1K")),
            }
        },
        # 语音那三项的配置键 P2 就在用了（`VOICE_*_PRICE_*`），这里沿用不改名 ——
        # 老部署的 .env 不用动，估值口径也不会因为 P5 换了模块而变。
        "tts": {"perKChars": _float(cfg.get("VOICE_TTS_PRICE_PER_KCHARS"))},
        "asr": {"perMinute": _float(cfg.get("VOICE_ASR_PRICE_PER_MINUTE"))},
        "realtime": {"perMinute": _float(cfg.get("VOICE_REALTIME_PRICE_PER_MINUTE"))},
    }


def effective() -> dict[str, Any]:
    """当前生效的价目表 = 配置打底 + 设置覆盖。"""
    merged = _config_defaults()
    stored = _stored()
    for kind, bucket in stored.items():
        if kind not in merged or not isinstance(bucket, Mapping):
            continue
        for key, value in bucket.items():
            if isinstance(value, Mapping):
                merged[kind][str(key)] = {
                    **merged[kind].get(str(key), {}),
                    **_prices_of(value),
                }
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                merged[kind][str(key)] = float(value)
    return merged


def _stored() -> dict[str, Any]:
    row = db.session.get(SettingsKV, KEY_PRICING)
    value = row.value if row is not None else None
    return value if isinstance(value, dict) else {}


def _write_stored(value: dict[str, Any]) -> None:
    """整段替换 `settings_kv.pricing`。调用方负责先合并（与 `settings_service` 同口径）。"""

    def _work() -> None:
        row = db.session.get(SettingsKV, KEY_PRICING)
        if row is None:
            row = SettingsKV(key=KEY_PRICING)
            db.session.add(row)
        row.value = value

    db_write(_work)


def estimate_llm(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """一次 LLM 调用的估算费用（元）。

    模型没单独配价时落到 `"*"`：看板上出现一个没配价的模型是**常态**
    （用户随时能在设置页换一个），落到 0 只会让整门课的成本凭空少一块。
    """
    table = effective().get("llm") or {}
    price = table.get(str(model or "")) or table.get("*") or {}
    if not isinstance(price, Mapping):
        return 0.0
    return round(
        _float(price.get("promptPer1k")) * max(0, int(prompt_tokens or 0)) / 1000.0
        + _float(price.get("completionPer1k")) * max(0, int(completion_tokens or 0)) / 1000.0,
        6,
    )


def estimate_units(kind: str, units: int) -> float:
    """一次语音调用的估算费用（元）。`units` 的单位由 `kind` 决定（字符 / 秒）。"""
    field, per = KIND_UNIT_PRICES.get(kind, ("", 1))
    if not field:
        return 0.0
    price = _float((effective().get(kind) or {}).get(field))
    quantity = max(0, int(units or 0))
    if price <= 0 or quantity <= 0:
        return 0.0
    return round(price * quantity / per, 6)


def priced(kind: str) -> bool:
    """这一类配了非零单价吗。没配就别说「本次课堂花了 ¥0.00」。"""
    if kind == "llm":
        table = effective().get("llm") or {}
        return any(
            _float((row or {}).get("promptPer1k")) > 0 or _float((row or {}).get("completionPer1k")) > 0
            for row in table.values()
            if isinstance(row, Mapping)
        )
    field, _ = KIND_UNIT_PRICES.get(kind, ("", 1))
    return bool(field) and _float((effective().get(kind) or {}).get(field)) > 0


def rows() -> list[dict[str, Any]]:
    """价目表摊平成一行行 —— `GET /api/usage/models` 直接发它。"""
    table = effective()
    out: list[dict[str, Any]] = []
    for model, price in sorted((table.get("llm") or {}).items()):
        if not isinstance(price, Mapping):
            continue
        out.append(
            {
                "kind": "llm",
                "model": str(model),
                "unitName": "tokens",
                "promptPer1k": _float(price.get("promptPer1k")),
                "completionPer1k": _float(price.get("completionPer1k")),
                "priced": _float(price.get("promptPer1k")) > 0
                or _float(price.get("completionPer1k")) > 0,
            }
        )
    for kind, (field, per) in KIND_UNIT_PRICES.items():
        price = _float((table.get(kind) or {}).get(field))
        out.append(
            {
                "kind": kind,
                "model": "",
                "unitName": "chars" if kind == "tts" else "seconds",
                "unitPrice": price,
                # 一份是多少个单位：前端要按它把「每千字符 / 每分钟」讲清楚
                "unitSize": per,
                "priceField": field,
                "priced": price > 0,
            }
        )
    return out


def update(payload: Any) -> dict[str, Any]:
    """改价目表（设置页）。**只认已知的档位与字段** —— 拼错的键必须报错。

    负数一律拒绝：负单价会让账本出现负金额，而「花了 -3 元」在聚合里
    会把别的链路花掉的钱抵掉一半，且极难查。
    """
    if not isinstance(payload, dict):
        raise ValidationError("请求体必须是一个 JSON 对象")
    stored = _stored()

    llm = payload.get("llm")
    if llm is not None:
        if not isinstance(llm, Mapping):
            raise ValidationError("pricing.llm 必须是对象")
        stored["llm"] = {
            str(model): _prices_of(row, where=f"pricing.llm.{model}")
            for model, row in llm.items()
            if isinstance(row, Mapping)
        }

    for kind, (field, _per) in KIND_UNIT_PRICES.items():
        if kind not in payload:
            continue
        bucket = payload[kind]
        if not isinstance(bucket, Mapping):
            raise ValidationError(f"pricing.{kind} 必须是对象")
        if field in bucket:
            stored[kind] = {field: _price(bucket.get(field), f"pricing.{kind}.{field}")}
        else:
            stored.setdefault(kind, {})

    _write_stored(stored)
    return effective()


def _prices_of(row: Mapping[str, Any], *, where: str = "pricing.llm") -> dict[str, float]:
    out: dict[str, float] = {}
    for key in ("promptPer1k", "completionPer1k"):
        if key in row:
            out[key] = _price(row.get(key), f"{where}.{key}")
    return out


def _price(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{where} 必须是数字", details={"field": where})
    if float(value) < 0:
        raise ValidationError(f"{where} 不能是负数", details={"field": where})
    return round(float(value), 6)


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
