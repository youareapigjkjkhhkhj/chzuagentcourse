"""带校验与记账的模型调用（P1-12 / P1-F4 / AGENTS §4.5）。

生成管线里**每一次**模型调用都走这里，因为它同时承担三件别处做不了的事：

1. **结构化输出的守门人**：要求 `response_format=json_object`，拿到文本后
   必须过 `schema.py` 的校验才算数。不合格把理由**回喂给模型**重写一次 ——
   这是 P1-12 明写的动作，不重试就等于把「模型偶尔手滑」变成「整页失败」。
2. **记账**：无论成败，每一次真正发出去的调用都在 `model_calls` 留一行
   （provider / model / tokens / latency / ok / error_code）。P5 的成本看板
   只认这张表，漏记一次就是系统性少报一次。重试的两次都要记 ——
   第一次的 token 是**真的花掉了**的。
3. **超时**：每页独立 60s（可配），按请求下发而不是靠共享客户端 ——
   一次生成里并发的三页各自计时，谁慢谁超时，不互相拖累。

超时为什么不会漏线程：超时是由上游 HTTP 客户端抛出来的（见
`providers/llm/openai_compatible.py` 把 timeout 交给 SDK），不是我们在外层
起看门狗线程再把它掐掉 —— 后者才会留下一个永远等不到结果的线程。
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

from flask import current_app

from app.common.dbw import db_write
from app.common.errors import AppError
from app.common.logging import get_logger
from app.extensions import db
from app.models import ModelCall
from app.providers.base import LLMProvider, ProviderError
from app.services.generation.schema import (
    SchemaInvalid,
    load_json,
    parse_page,
    schema_for_kind,
)

logger = get_logger("app.generation.llm")

#: 单页生成的超时缺省值（秒）。技术方案 §8 的风险对策：每页独立 60s，
#: 慢的一页到点就放弃，不让整门课等它。
DEFAULT_PAGE_TIMEOUT = 60.0

#: 首次 + 一次重试。不设更多：连续两次写不对，第三次通常也写不对，
#: 而每次重试都是真金白银的 token（P1-12 写的就是「自动重试 1 次」）。
MAX_ATTEMPTS = 2

#: 回喂时把上一次的输出截到这里。给模型看它自己写了什么是有用的，
#: 但一个 8k 的跑题输出会把上下文挤满，反而更容易写错。
_FEEDBACK_CHARS = 1500

_RETRY_TEMPLATE = (
    "你上一次的输出不符合要求：{reason}\n"
    "请重新输出**完整的 JSON**（不要解释、不要 Markdown 围栏、不要省略字段），"
    "并严格满足上面给出的 JSON Schema。"
)


@dataclass(frozen=True)
class JsonCall:
    """一次成功的结构化调用。"""

    data: dict
    text: str
    model: str
    provider: str
    tokens: int
    latency_ms: int
    #: 实际尝试次数（1 = 一次过，2 = 靠重试救回来的）。
    #: 它进 gen_steps.detail_json，P1 验收要看「重试是否真的救回来了」。
    attempts: int


class OutputInvalidError(ProviderError):
    """连续两次都没给出符合 Schema 的输出（50201）。

    由管线捕获并把这一页标记为 `failed` —— 一页写不出来不该拖垮整门课
    （P1 验收 A8 / F1-10：单页失败跳过并标记，其余照常生成）。
    """

    def __init__(self, reason: str, *, attempts: int = MAX_ATTEMPTS) -> None:
        super().__init__(
            f"模型输出不符合页面要求：{reason}",
            details={
                "ok": False,
                "error": "schema_invalid",
                "attempts": attempts,
                "reason": reason,
            },
        )
        self.reason = reason


def page_timeout() -> float:
    """单页生成的超时（秒）。`GEN_PAGE_TIMEOUT` 可改，改完不用重启代码。"""
    return float(current_app.config.get("GEN_PAGE_TIMEOUT") or DEFAULT_PAGE_TIMEOUT)


def call_json(
    provider: LLMProvider,
    messages: Sequence[Mapping[str, Any]],
    *,
    schema: Mapping[str, Any] | None = None,
    parse: Callable[[str], dict] | None = None,
    timeout: float | None = None,
    job_id: str = "",
    owner_id: str = "",
) -> JsonCall:
    """要一次结构化输出，并保证它要么是合格的、要么是记过账的失败。

    Args:
        provider: 已经取好的文本模型（`registry.current_llm()`）。
        messages: 本次对话。**不得包含凭据**，材料片段必须已加分隔符（§4.1）。
        schema: 发给模型的 JSON Schema。由 `schema.schema_for_kind()` 生成。
        parse: 文本 → 校验后的字典。抛 `SchemaInvalid` 即视为不合格。
               缺省只要求是合法 JSON 对象。
        timeout: 单次调用超时（秒）。缺省读 `GEN_PAGE_TIMEOUT`。
        job_id / owner_id: 记账用。账本不建外键，删课也不会丢账。

    Raises:
        OutputInvalidError: 重试后仍不合格。
        ProviderError: 上游失败（含超时 50401）—— 这类失败**不重试**，
            多等一个超时周期只会让用户更久地看到一个卡住的进度条。
    """
    limit = float(timeout or page_timeout())
    validate = parse or load_json
    conversation: list[Mapping[str, Any]] = [dict(message) for message in messages]
    reason = ""
    attempts = 0

    while attempts < MAX_ATTEMPTS:
        attempts += 1
        started = perf_counter()

        try:
            result = provider.chat(conversation, json_schema=schema, timeout=limit)
        except AppError as exc:
            _record(
                provider, result=None, tokens=0, latency_ms=_elapsed_ms(started),
                ok=False, error_code=_error_code(exc), job_id=job_id, owner_id=owner_id,
            )
            raise
        except Exception as exc:
            # 适配器只该抛 AppError；真漏出来别的，也要变成能看懂的 50201，
            # 而不是让一个 KeyError 一路冒到 SSE 里变成 50001。
            _record(
                provider, result=None, tokens=0, latency_ms=_elapsed_ms(started),
                ok=False, error_code="upstream_error", job_id=job_id, owner_id=owner_id,
            )
            raise ProviderError(
                f"服务商 {provider.name} 调用失败：{type(exc).__name__}",
                details={"ok": False, "error": "upstream_error", "provider": provider.name},
            ) from exc

        latency_ms = _elapsed_ms(started)
        tokens = count_tokens(result.usage)

        try:
            data = validate(result.text)
        except SchemaInvalid as exc:
            reason = exc.reason
            _record(
                provider, result=result, tokens=tokens, latency_ms=latency_ms,
                ok=False, error_code="schema_invalid", job_id=job_id, owner_id=owner_id,
            )
            conversation = _with_feedback(conversation, result.text, reason)
            continue

        _record(
            provider, result=result, tokens=tokens, latency_ms=latency_ms,
            ok=True, error_code="", job_id=job_id, owner_id=owner_id,
        )
        return JsonCall(
            data=data,
            text=result.text,
            model=result.model or getattr(provider, "default_model", ""),
            provider=result.provider or provider.name,
            tokens=tokens,
            latency_ms=latency_ms,
            attempts=attempts,
        )

    raise OutputInvalidError(reason, attempts=attempts)


def call_page(
    provider: LLMProvider,
    messages: Sequence[Mapping[str, Any]],
    *,
    kind: str,
    page_no: int = 0,
    chapter_no: int = 0,
    timeout: float | None = None,
    job_id: str = "",
    owner_id: str = "",
) -> JsonCall:
    """要一页内容。

    `call_json` 的 `schema` 与 `parse` 必须配套 —— 只传 schema 等于「让模型
    照着写，但我们不查」。生成页面的调用点很多（初稿、重写、补页），
    把这对参数绑在 kind 上，调用方就没有写错的余地。
    """
    return call_json(
        provider,
        messages,
        schema=schema_for_kind(kind),
        parse=lambda text: parse_page(
            kind, text, page_no=page_no, chapter_no=chapter_no
        ),
        timeout=timeout,
        job_id=job_id,
        owner_id=owner_id,
    )


def count_tokens(usage: Mapping[str, Any] | None) -> int:
    """从上游的 usage 里数 token。

    total 缺失或为 0 时用 prompt+completion 补上：有的兼容实现只认真填这两项，
    直接读 total 会把它们记成 0，成本看板就成了摆设。
    """
    usage = usage or {}
    total = _as_int(usage.get("total_tokens"))
    if total:
        return total
    return _as_int(usage.get("prompt_tokens")) + _as_int(usage.get("completion_tokens"))


def clip_feedback(text: str) -> str:
    """把一段模型输出裁成「可以回喂的长度」。

    公开它是因为回喂不只发生在 Schema 校验失败时：内容合规命中之后，
    管线也要把上一版还给模型看（「就是这一版有问题，重写」），
    让模型知道自己写了什么，比让它凭空再猜一遍有效得多。
    """
    return _clip(text)


def _with_feedback(
    conversation: Sequence[Mapping[str, Any]], previous: str, reason: str
) -> list[Mapping[str, Any]]:
    """把「你哪里写错了」拼进对话，重试时一并发出。"""
    return [
        *conversation,
        {"role": "assistant", "content": _clip(previous)},
        {"role": "user", "content": _RETRY_TEMPLATE.format(reason=reason)},
    ]


def _clip(text: str) -> str:
    clean = (text or "").strip()
    if len(clean) <= _FEEDBACK_CHARS:
        return clean
    return clean[:_FEEDBACK_CHARS] + "\n…（输出过长，已截断）"


def _record(
    provider: LLMProvider,
    *,
    result: Any,
    tokens: int,
    latency_ms: int,
    ok: bool,
    error_code: str,
    job_id: str,
    owner_id: str,
) -> None:
    """写一行 model_calls。

    记账失败**不阻断生成**：内容已经生成好了，因为一次写库冲突把它丢掉，
    比少记一笔账更糟。但一定要留下 error 级日志 —— P5 对账时那是线索。
    """
    model = ""
    if result is not None:
        model = str(getattr(result, "model", "") or "")
    model = model or str(getattr(provider, "default_model", "") or provider.name)

    def _write() -> None:
        db.session.add(
            ModelCall(
                kind="llm",
                provider=provider.name,
                model=model[:64],
                tokens=tokens,
                latency_ms=latency_ms,
                ok=ok,
                error_code=error_code or None,
                job_id=job_id or None,
                owner_id=owner_id or None,
            )
        )

    try:
        db_write(_write)
    except Exception as exc:
        logger.error("写入 model_calls 失败（job=%s）：%s", job_id or "-", type(exc).__name__)


def _error_code(exc: BaseException) -> str:
    """失败原因归类。优先用适配器给的那份（timeout / rate_limit / …）。"""
    details = getattr(exc, "details", None)
    if isinstance(details, Mapping):
        code = details.get("error")
        if isinstance(code, str) and code.strip():
            return code.strip()[:32]
    return {
        50401: "timeout",
        42901: "rate_limit",
        40201: "missing_api_key",
    }.get(getattr(exc, "code", 0), "upstream_error")


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "DEFAULT_PAGE_TIMEOUT",
    "MAX_ATTEMPTS",
    "JsonCall",
    "OutputInvalidError",
    "call_json",
    "call_page",
    "clip_feedback",
    "count_tokens",
    "page_timeout",
]
