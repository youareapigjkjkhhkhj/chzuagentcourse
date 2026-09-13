"""`model_calls` 的唯一写入点（P5-C2 / F5-7 / F5-10）。

**四种外部调用都从这里进账本**：LLM、TTS、ASR、实时语音。之前只有 LLM 走
（P1 的 `generation/llm.py::_record`），三条语音链路各自把用量记进
`usage_records` 却没有调用事件 —— 于是「上游挂了、重试了几次、每次多慢」
这些问题的答案在语音那一半是空的。P5-C2 要求账本覆盖全部四种，
就把落笔的地方收到这里一处。

### 与 `usage_records` 的分工（口径写在 P5 文档 §10.2）

一次 TTS 合成会写**两**张表，这不是重复记账：

- `model_calls` 记「**调用发生了一次**」—— 含耗时、成败、错误码。它回答
  「系统稳不稳、哪一步慢」，失败的那次也在（那才是排障时最想看的一行）。
- `usage_records` 记「**按量计费的东西用了多少**」—— 字符数 / 秒数 + 金额。
  它回答「这门课花了多少钱」，只在调用成功且上游给了计量口径时才写。

**所以金额与用量的合计只认一个来源**：LLM 取 `model_calls`，语音取
`usage_records`。`aggregate.py` 按这条口径算，两边相加不会把语音算两遍。

### 为什么写账失败不能抛

账本记得好不好，与「这次生成/合成成没成」是两件事。因为一次写库冲突把
已经生成好的内容丢掉，比少记一笔账糟得多（P1 起就是这个口径）。所以这里
把异常吃成 error 级日志 —— **但它一定是 error**：漏记一次就是看板系统性少报一次。
"""

from __future__ import annotations

from typing import Any

from app.common.dbw import db_write
from app.common.logging import get_logger
from app.extensions import db
from app.models.telemetry import CALL_UNIT_NAMES, MODEL_CALL_KINDS, ModelCall
from app.services.usage import pricing

logger = get_logger("app.usage.ledger")

#: kind → 计量单位的缺省值。写死在这里的理由与 `voice/usage.KIND_UNITS` 同源：
#: 让调用方传「TTS 用了多少秒」不会报错，只会让看板的数字从此没有意义。
KIND_UNITS: dict[str, str] = {
    "llm": "tokens",
    "tts": "chars",
    "asr": "seconds",
    "realtime": "seconds",
}


def record(
    kind: str,
    *,
    provider: str = "",
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    tokens: int | None = None,
    units: int = 0,
    unit_name: str = "",
    latency_ms: int = 0,
    ok: bool = True,
    error_code: str = "",
    ref_type: str = "",
    ref_id: str = "",
    step_id: str = "",
    job_id: str = "",
    owner_id: str = "",
) -> ModelCall | None:
    """写一行账。返回落库的那一行；写不进去时返回 None 并记 error 日志。

    Args:
        kind: `llm` / `tts` / `asr` / `realtime`，别的值直接 `ValueError`
            —— 那一定是写错了调用点，而 CHECK 约束会在几毫秒后以一句
            看不懂的 IntegrityError 说出来。
        prompt_tokens / completion_tokens: LLM 的输入输出拆分。给不出就都给 0。
        tokens: 总数。**缺省由输入+输出加出来**，传了就以传的为准 ——
            上游 `usage.total_tokens` 有时比自己加更准（含缓存命中等口径）。
        units: 非 token 链路的用量（TTS 字符数 / ASR 与实时语音秒数）。
        ref_type / ref_id / step_id: 这笔账「为谁花的」。弱引用，见模型 docstring。
    """
    if kind not in MODEL_CALL_KINDS:
        raise ValueError(f"未知的调用类型：{kind!r}")

    prompt = _non_negative(prompt_tokens, "prompt_tokens")
    completion = _non_negative(completion_tokens, "completion_tokens")
    total = _non_negative(tokens, "tokens") if tokens is not None else prompt + completion
    quantity = _non_negative(units, "units")
    unit = unit_name or KIND_UNITS[kind]
    if unit not in CALL_UNIT_NAMES:  # pragma: no cover - 上面的映射已保证
        unit = KIND_UNITS[kind]

    row = ModelCall(
        kind=kind,
        provider=str(provider or "")[:32],
        model=str(model or "")[:64],
        tokens=total,
        prompt_tokens=prompt,
        completion_tokens=completion,
        units=quantity,
        unit_name=unit,
        est_cost=_cost(kind, model, prompt, completion, quantity),
        latency_ms=_non_negative(latency_ms, "latency_ms"),
        ok=bool(ok),
        error_code=(str(error_code or "")[:32] or None),
        job_id=job_id or None,
        owner_id=owner_id or None,
        ref_type=ref_type or "",
        ref_id=ref_id or "",
        step_id=step_id or "",
    )

    def _work() -> ModelCall:
        db.session.add(row)
        return row

    try:
        return db_write(_work)
    except Exception as exc:
        logger.error(
            "写 model_calls 失败（kind=%s ref=%s）：%s", kind, ref_id or "-", type(exc).__name__
        )
        return None


def _cost(kind: str, model: str, prompt: int, completion: int, units: int) -> float:
    if kind == "llm":
        return pricing.estimate_llm(model, prompt, completion)
    return pricing.estimate_units(kind, units)


def _non_negative(value: Any, field: str) -> int:
    """账本里的量必须非负。

    模型那三列（`prompt_tokens` 等）**故意没加 CHECK 约束**：SQLite 加 CHECK
    要整表重建，而这是 P1 起就在写热的账本（见 `models/telemetry.py` 的注）。
    约束那条路走不通，就由唯一的写入点保证 —— 也就是这里。

    负数是上游给的脏数据或我们自己算错，**夹成 0 并留一条 warning**：
    抛异常会让一次已经成功的调用变成失败，而账本少一行比业务失败轻得多。
    """
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        number = 0
    if number < 0:
        logger.warning("账本收到负的 %s（%s），已按 0 记", field, number)
        return 0
    return number


__all__ = ["KIND_UNITS", "record"]
