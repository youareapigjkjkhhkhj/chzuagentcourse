"""OpenAI 兼容协议的文本模型适配器。

一家适配器覆盖 DeepSeek / OpenAI / Qwen / Kimi / 火山方舟 / 自建：
它们的 /chat/completions 请求与响应形状一致，差异只在 base_url 与模型名 ——
两者都是配置项，所以这里不需要任何厂商字面量（AGENTS.md §4.1）。

这是**唯一**允许 import openai SDK 的地方（AGENTS.md §14.2）。
"""

from __future__ import annotations

import json
import time
from typing import Any, Iterator, Mapping, Sequence

import httpx
import openai

from app.common.errors import AppError, RateLimitError, ValidationError
from app.common.logging import REDACTED, get_logger, redact
from app.providers.base import (
    LLMProvider,
    LLMResult,
    ProbeResult,
    ProviderError,
    ProviderTimeoutError,
    Secret,
    not_configured,
)

logger = get_logger("app.providers.llm")

#: 探活时只说一个字，把成本压到最低（1 token 级别）。
PROBE_PROMPT = "ping"

#: 探活错误的归类，给设置页显示用（不回传上游原文的完整结构）。
_CODE_UNAUTHORIZED = "unauthorized"
_CODE_RATE_LIMIT = "rate_limit"
_CODE_TIMEOUT = "timeout"
_CODE_NETWORK = "network"
_CODE_UPSTREAM = "upstream_error"
_CODE_MISSING_KEY = "missing_api_key"


class OpenAICompatibleLLM(LLMProvider):
    """走 OpenAI 兼容 HTTP 协议的文本模型。"""

    def __init__(
        self,
        name: str = "openai_compatible",
        *,
        api_key: str = "",
        base_url: str = "",
        default_model: str = "",
        timeout: float = 120.0,
        max_retries: int = 0,
        http_client: httpx.Client | None = None,
        **options: Any,
    ) -> None:
        # configured 由 missing_config() 推导（见下），所以这里不传 ——
        # 「缺什么」与「能不能用」必须只有一个事实来源。
        super().__init__(name, default_model=default_model, **options)
        self.base_url = (base_url or "").strip().rstrip("/")
        self.timeout = float(timeout)
        # 默认不重试：重试策略应该是部署方的决定（LLM_MAX_RETRIES），
        # 而且带退避的重试会让「探活」按钮转很久，体验上不可接受。
        self.max_retries = int(max_retries)
        self._secret = Secret(api_key)
        # 允许注入 HTTP 客户端：契约测试用 MockTransport 走真实 SDK 序列化路径，
        # 但完全不联网（AGENTS.md §23）。
        self._http_client = http_client
        self._client_cache: openai.OpenAI | None = None

    # --- 配置齐备性 ---

    def missing_config(self) -> list[str]:
        missing = []
        if not self._secret:
            missing.append("API Key")
        if not self.base_url:
            missing.append("接入地址")
        if not self.default_model:
            missing.append("模型名")
        return missing

    @property
    def configured(self) -> bool:
        return not self.missing_config()

    # --- 客户端 ---

    def _client(self) -> openai.OpenAI:
        if self._client_cache is None:
            self._client_cache = openai.OpenAI(
                api_key=self._secret.reveal(),
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=self.max_retries,
                http_client=self._http_client,
            )
        return self._client_cache

    def close(self) -> None:
        """释放底层连接池。owner 传进来的 http_client 由 owner 负责关。"""
        if self._client_cache is not None and self._http_client is None:
            self._client_cache.close()
        self._client_cache = None

    def _require_ready(self) -> None:
        """配置不齐就报 40201 —— 让用户知道该去设置页补什么，而不是等上游拒绝。"""
        if not self.configured:
            raise not_configured(self)

    # --- 对话 ---

    def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_schema: Mapping[str, Any] | None = None,
        timeout: float | None = None,
        **options: Any,
    ) -> LLMResult:
        # 先查配置再查入参：配置不对时上游必然拒绝，没必要先跑一遍参数校验
        self._require_ready()
        payload = self._build_payload(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_schema=json_schema,
            extra=options,
        )

        try:
            response = self._client().chat.completions.create(**payload, **_request_timeout(timeout))
        except Exception as exc:
            raise self._map_error(exc) from exc

        try:
            return self._to_result(response)
        except AppError:
            raise
        except Exception as exc:
            # 200 但结构不对（网关插页、代理改包）也要是能看懂的 50201
            raise ProviderError(
                f"服务商 {self.name} 返回了无法解析的响应：{type(exc).__name__}",
                details={"ok": False, "error": _CODE_UPSTREAM, "provider": self.name},
            ) from exc

    def chat_stream(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_schema: Mapping[str, Any] | None = None,
        timeout: float | None = None,
        **options: Any,
    ) -> Iterator[str]:
        self._require_ready()
        payload = self._build_payload(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_schema=json_schema,
            extra=options,
        )

        try:
            stream = self._client().chat.completions.create(
                stream=True, **payload, **_request_timeout(timeout)
            )
        except Exception as exc:
            raise self._map_error(exc) from exc

        try:
            for chunk in stream:
                delta = self._delta_text(chunk)
                if delta:
                    yield delta
        except AppError:
            raise
        except Exception as exc:
            raise self._map_error(exc) from exc

    def _build_payload(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        json_schema: Mapping[str, Any] | None,
        extra: Mapping[str, Any],
    ) -> dict:
        if not messages:
            raise ValidationError("messages 不能为空")

        payload_messages = [dict(message) for message in messages]
        chosen_model = (model or self.default_model).strip()

        payload: dict[str, Any] = {"model": chosen_model, "messages": payload_messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if json_schema is not None:
            # 只要求 JSON 模式，schema 本体写进提示词。
            # response_format=json_schema 是 OpenAI 的新参数，各家兼容程度参差，
            # 用它会把「能用」的范围缩小一大圈 —— 对我们来说不划算。
            payload["response_format"] = {"type": "json_object"}
            payload["messages"] = _with_json_rule(
                payload_messages,
                "只输出 JSON，且必须符合以下 JSON Schema：\n"
                + json.dumps(json_schema, ensure_ascii=False),
            )
        payload.update({k: v for k, v in extra.items() if v is not None})
        return payload

    def _to_result(self, response: Any) -> LLMResult:
        choices = getattr(response, "choices", None)
        if not choices:
            raise ProviderError(
                f"服务商 {self.name} 未返回任何候选结果",
                details={"ok": False, "error": _CODE_UPSTREAM, "provider": self.name},
            )
        choice = choices[0]
        message = getattr(choice, "message", None)
        text = getattr(message, "content", None)
        if text is None:
            # reasoning 模型有时把正文放在 reasoning_content，取不到再判失败
            text = getattr(message, "reasoning_content", None)
        if text is None:
            raise ProviderError(
                f"服务商 {self.name} 的响应里没有正文内容",
                details={"ok": False, "error": _CODE_UPSTREAM, "provider": self.name},
            )
        usage = getattr(response, "usage", None)
        return LLMResult(
            text=str(text),
            model=str(getattr(response, "model", "") or self.default_model),
            provider=self.name,
            usage=_usage_dict(usage),
            finish_reason=str(getattr(choice, "finish_reason", "") or ""),
        )

    @staticmethod
    def _delta_text(chunk: Any) -> str:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            return ""
        delta = getattr(choices[0], "delta", None)
        return str(getattr(delta, "content", "") or "")

    # --- 探活 ---

    def test(self) -> ProbeResult:
        """探活：**永不抛异常**（P0-A5）。

        返回的 error 已经过脱敏 —— 上游有时会把 Key 回显在报错里。
        """
        if not self._secret:
            return self._probe_failure(
                "未配置 API Key，请到「设置」页填写", _CODE_MISSING_KEY
            )
        if not self.base_url:
            return self._probe_failure("未配置接入地址（base_url）", "missing_base_url")
        if not self.default_model:
            return self._probe_failure("未配置模型名（model）", "missing_model")

        started = time.perf_counter()
        try:
            response = self._client().chat.completions.create(
                model=self.default_model,
                messages=[{"role": "user", "content": PROBE_PROMPT}],
                # 探活只要证明「这条路现在是通的」，多花的 token 都是浪费
                max_tokens=1,
            )
            # 解析一遍再算数：200 也可能是「base_url 指到了别的服务」
            # 这类假绿灯，用户看到打勾却在正式调用时才炸，是最难查的一种。
            self._to_result(response)
        except Exception as exc:
            return self._probe_failure(self._scrub(self._describe_error(exc)), _classify(exc))
        return ProbeResult(
            ok=True,
            latency_ms=int((time.perf_counter() - started) * 1000),
            model=self.default_model,
            provider=self.name,
        )

    def _scrub(self, text: str) -> str:
        """脱敏上游文案：先换掉**我们手里这一把**，再按形状兜底。

        顺序不能反：redact() 认的是「像 Key 的样子」（sk- / Bearer / volc-），
        而自建端点的不透明令牌可能长得毫无特征。若它恰好是 sk- 形状，
        先做整串替换也只会把「sk-****」变成一样的结果，不会更差。

        上游回显凭据并不是假设：错误体里抄一遍收到的 Authorization 头
        是常见做法，而这句话会被存进 probe.error、显示在设置页、写进日志。
        """
        key = self._secret.reveal()
        return redact(text.replace(key, REDACTED) if key else text)

    def _probe_failure(self, message: str, error_code: str) -> ProbeResult:
        return ProbeResult(
            ok=False,
            error=message,
            error_code=error_code,
            model=self.default_model,
            provider=self.name,
        )

    # --- 错误映射 ---

    def _map_error(self, exc: Exception) -> AppError:
        """把 SDK 异常翻译成本项目的异常体系。"""
        message = self._scrub(self._describe_error(exc))
        code = _classify(exc)
        details = {"ok": False, "error": code, "provider": self.name}
        if isinstance(exc, openai.APITimeoutError):
            return ProviderTimeoutError(f"服务商 {self.name} 响应超时：{message}", details=details)
        if isinstance(exc, openai.RateLimitError):
            return RateLimitError(f"服务商 {self.name} 触发了限流：{message}", details=details)
        return ProviderError(f"服务商 {self.name} 调用失败：{message}", details=details)

    def _describe_error(self, exc: Exception) -> str:
        if isinstance(exc, openai.APIStatusError):
            status = getattr(exc, "status_code", 0)
            return f"HTTP {status}：{_upstream_message(exc)}"
        if isinstance(exc, openai.APITimeoutError):
            return "上游在超时时间内没有响应"
        if isinstance(exc, openai.APIConnectionError):
            return "无法连接上游服务（网络不可达或地址不正确）"
        if isinstance(exc, openai.OpenAIError):
            return f"上游 SDK 报错：{type(exc).__name__}"
        return f"{type(exc).__name__}: {exc}"


def _with_json_rule(messages: list[dict], rule: str) -> list[dict]:
    """把「只输出 JSON，符合这个 Schema」并进**第一条 system 消息**里。

    这段要求原来是以一条 system 消息**追加在末尾**的：OpenAI、DeepSeek 都收，
    但按 Qwen 模板校验的服务商（vLLM 一类）直接 400 ——
    `System message must be at the beginning`。

    也不能简单地往前面再插一条 system 了事：那种校验认的是「**第一条**」而不是
    「开头附近」，两条连着的 system 会在第二条上翻车，等于换了个姿势报同一个错。
    所以并进已有的第一条，全程只有一条 system，且一定在 0 号位。
    """
    if messages and str(messages[0].get("role") or "") == "system":
        head = dict(messages[0])
        head["content"] = "\n\n".join(
            part for part in (str(head.get("content") or ""), rule) if part
        )
        return [head, *messages[1:]]
    return [{"role": "system", "content": rule}, *messages]


def _request_timeout(timeout: float | None) -> dict:
    """把单次调用的超时拼成 SDK 的请求参数。

    不能写 `timeout=None`：SDK 会把它当成「本次不设超时」，等于把请求
    挂死在连接上。None 的正确语义是「用客户端自带的那一份」，也就是不传。
    """
    if timeout is None:
        return {}
    return {"timeout": float(timeout)}


def _classify(exc: Exception) -> str:
    """把异常归类成设置页能显示的短码。"""
    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return _CODE_UNAUTHORIZED
    if isinstance(exc, openai.APITimeoutError):
        return _CODE_TIMEOUT
    if isinstance(exc, openai.RateLimitError):
        return _CODE_RATE_LIMIT
    if isinstance(exc, openai.APIConnectionError):
        # 超时也属于「连不上」大类，但单独区分更有助于排查
        return _CODE_NETWORK
    if isinstance(exc, openai.APIStatusError):
        return _CODE_UPSTREAM
    return _CODE_UPSTREAM


def _upstream_message(exc: Exception) -> str:
    """尽量从上游的报错体里挖出一句人话。挖不到就退回异常本身的文本。"""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if isinstance(error, str) and error:
            return error
        if body.get("message"):
            return str(body["message"])
    text = str(getattr(exc, "message", "") or exc)
    return text or type(exc).__name__


def _usage_dict(usage: Any) -> dict:
    if usage is None:
        return {}
    for attr in ("model_dump", "dict"):
        dump = getattr(usage, attr, None)
        if callable(dump):
            try:
                return dict(dump())
            except Exception:
                return {}
    return {}


__all__ = ["PROBE_PROMPT", "OpenAICompatibleLLM"]
