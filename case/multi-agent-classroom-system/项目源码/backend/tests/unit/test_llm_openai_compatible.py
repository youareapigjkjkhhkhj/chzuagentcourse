"""OpenAI 兼容 LLM 适配器测试（F0-6 / F0-8）。

用 httpx.MockTransport 拦在 HTTP 层：走的是真实 openai SDK 的序列化路径，
但完全不联网（AGENTS.md §23）。
"""

from __future__ import annotations

import json

import httpx
import pytest

pytestmark = pytest.mark.unit

FAKE_KEY = "sk-9f2c4a1b7e8d4f6a0011223344556677"
FAKE_BASE = "https://llm.example.invalid/v1"

CHAT_OK = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "created": 1700000000,
    "model": "deepseek-chat",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "光合作用发生在叶绿体。"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
}


def make_provider(handler, **overrides):
    """构造一个走 MockTransport 的适配器。"""
    from app.providers.llm.openai_compatible import OpenAICompatibleLLM

    defaults = {
        "name": "deepseek",
        "api_key": FAKE_KEY,
        "base_url": FAKE_BASE,
        "default_model": "deepseek-chat",
    }
    defaults.update(overrides)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatibleLLM(http_client=client, **defaults)


def json_handler(payload: dict, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handler


# --- 身份 ---


def test_provider_reports_identity(app):
    with app.app_context():
        provider = make_provider(json_handler(CHAT_OK))

        assert provider.name == "deepseek"
        assert provider.kind == "llm"
        assert provider.configured is True
        assert provider.default_model == "deepseek-chat"


def test_provider_without_key_is_not_configured(app):
    with app.app_context():
        provider = make_provider(json_handler(CHAT_OK), api_key="")
        assert provider.configured is False


def test_provider_never_exposes_plain_key_as_attribute(app):
    """密钥只能是私有属性 —— 防止有人顺手把它写进日志或响应体。"""
    with app.app_context():
        provider = make_provider(json_handler(CHAT_OK))
        assert "api_key" not in vars(provider)


def test_repr_does_not_leak_key(app):
    with app.app_context():
        provider = make_provider(json_handler(CHAT_OK))
        assert FAKE_KEY not in repr(provider)
        assert "9f2c" not in repr(provider)


# --- chat ---


def test_chat_returns_text_and_usage(app):
    with app.app_context():
        result = make_provider(json_handler(CHAT_OK)).chat(
            [{"role": "user", "content": "什么是光合作用"}]
        )

    assert result.text == "光合作用发生在叶绿体。"
    assert result.model == "deepseek-chat"
    assert result.provider == "deepseek"
    assert result.usage["total_tokens"] == 20
    assert result.finish_reason == "stop"


def test_chat_sends_model_and_temperature(app):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        seen["path"] = request.url.path
        return httpx.Response(200, json=CHAT_OK)

    with app.app_context():
        make_provider(handler).chat(
            [{"role": "user", "content": "你好"}], temperature=0.3
        )

    assert seen["body"]["model"] == "deepseek-chat"
    assert seen["body"]["temperature"] == 0.3
    assert seen["body"]["messages"] == [{"role": "user", "content": "你好"}]
    assert seen["auth"] == f"Bearer {FAKE_KEY}"
    assert seen["path"].endswith("/chat/completions")


def test_chat_model_override(app):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=CHAT_OK)

    with app.app_context():
        make_provider(handler).chat(
            [{"role": "user", "content": "hi"}], model="deepseek-reasoner"
        )

    assert seen["body"]["model"] == "deepseek-reasoner"


def test_chat_json_schema_requests_structured_output(app):
    """P1 生成课程大纲要靠它拿到稳定 JSON，不能靠提示词祈祷。"""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=CHAT_OK)

    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    }

    with app.app_context():
        make_provider(handler).chat(
            [{"role": "user", "content": "出个大纲"}], json_schema=schema
        )

    assert seen["body"]["response_format"]["type"] == "json_object"
    # schema 本体塞进提示词，兼容不支持的厂商
    dumped = json.dumps(seen["body"], ensure_ascii=False)
    assert "required" in dumped


def test_json_schema_rule_rides_in_the_first_system_message(app):
    """这段要求必须并进 0 号位那条 system 消息里。

    它原先是**追加在末尾**的一条 system：OpenAI、DeepSeek 都收，但按 Qwen 模板
    校验的服务商（vLLM）直接 400 `System message must be at the beginning`。
    """
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=CHAT_OK)

    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    talk = [{"role": "system", "content": "你是老师"}, {"role": "user", "content": "出个大纲"}]

    with app.app_context():
        make_provider(handler).chat(talk, json_schema=schema)

    messages = seen["body"]["messages"]
    assert [row["role"] for row in messages] == ["system", "user"]
    assert "你是老师" in messages[0]["content"]
    assert "JSON Schema" in messages[0]["content"]


def test_chat_without_messages_raises_validation_error(app):
    from app.common.errors import ValidationError

    with app.app_context(), pytest.raises(ValidationError):
        make_provider(json_handler(CHAT_OK)).chat([])


def test_chat_without_key_raises_40201(app):
    from app.providers.base import ProviderNotConfiguredError

    with app.app_context(), pytest.raises(ProviderNotConfiguredError) as excinfo:
        make_provider(json_handler(CHAT_OK), api_key="").chat(
            [{"role": "user", "content": "hi"}]
        )

    assert excinfo.value.code == 40201


def test_chat_without_base_url_raises_40201(app):
    from app.providers.base import ProviderNotConfiguredError

    with app.app_context(), pytest.raises(ProviderNotConfiguredError):
        make_provider(json_handler(CHAT_OK), base_url="").chat(
            [{"role": "user", "content": "hi"}]
        )


# --- 上游错误映射 ---


def test_chat_401_maps_to_provider_error_and_hides_key(app):
    from app.providers.base import ProviderError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"error": {"message": "Invalid API key", "type": "invalid_request_error"}}
        )

    with app.app_context(), pytest.raises(ProviderError) as excinfo:
        make_provider(handler).chat([{"role": "user", "content": "hi"}])

    assert "401" in excinfo.value.message or "Invalid API key" in excinfo.value.message
    assert FAKE_KEY not in str(excinfo.value)
    assert "9f2c" not in str(excinfo.value)


def test_chat_429_maps_to_rate_limit(app):
    from app.common.errors import RateLimitError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    with app.app_context(), pytest.raises(RateLimitError):
        make_provider(handler).chat([{"role": "user", "content": "hi"}])


def test_chat_500_maps_to_provider_error(app):
    from app.providers.base import ProviderError

    with app.app_context(), pytest.raises(ProviderError):
        make_provider(json_handler({"error": {"message": "boom"}}, status=500)).chat(
            [{"role": "user", "content": "hi"}]
        )


def test_chat_timeout_maps_to_timeout_error(app):
    from app.providers.base import ProviderTimeoutError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with app.app_context(), pytest.raises(ProviderTimeoutError):
        make_provider(handler).chat([{"role": "user", "content": "hi"}])


def test_chat_puts_the_per_call_timeout_on_the_request(app):
    """单页 60s 是**按请求**下发的（P1-F4），不是靠外层看门狗线程去掐。

    断言的是请求上的 timeout 扩展，而不是「慢上游会不会被掐断」：
    `httpx.MockTransport` 把 handler 直接叫起来，压根不走真正的传输层，
    也就不会施加超时 —— 在这里等一个超时等到的是幻觉。
    扩展值直接对应 `httpcore` 在实际连接上用的读超时，所以它就是那条路径。

    正反两面都验：不传时用客户端自带的 120s，传了就换成这一次的 0.05s。
    只验后者的话，一个「永远返回 120」的实现也能过。
    """
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions.get("timeout") or {})
        return httpx.Response(200, json=CHAT_OK)

    messages = [{"role": "user", "content": "hi"}]

    with app.app_context():
        provider = make_provider(handler, timeout=120.0)
        provider.chat(messages)
        provider.chat(messages, timeout=0.05)

    assert seen[0]["read"] == 120.0, "不传超时时应沿用客户端的设置"
    assert seen[1]["read"] == 0.05, "单次超时没有下发到请求上"


def test_chat_connection_error_maps_to_provider_error(app):
    from app.providers.base import ProviderError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns failure", request=request)

    with app.app_context(), pytest.raises(ProviderError):
        make_provider(handler).chat([{"role": "user", "content": "hi"}])


def test_chat_malformed_response_maps_to_provider_error(app):
    """上游返回 200 但结构不对，也要是可读的 50201，而不是 KeyError。"""
    from app.providers.base import ProviderError

    with app.app_context(), pytest.raises(ProviderError):
        make_provider(json_handler({"unexpected": "shape"})).chat(
            [{"role": "user", "content": "hi"}]
        )


# --- 探活 ---


def test_test_returns_latency_on_success(app):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=CHAT_OK)

    with app.app_context():
        probe = make_provider(handler).test()

    assert probe.ok is True
    assert probe.latency_ms >= 0
    assert probe.model == "deepseek-chat"
    assert probe.provider == "deepseek"
    assert probe.error == ""
    # 探活只花 1 个 token
    assert seen["body"]["max_tokens"] == 1


def test_test_never_raises_on_bad_key(app):
    """P0-A5：填错 Key 必须显示失败原因，而不是抛异常或弹「操作成功」。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Invalid API key"}})

    with app.app_context():
        probe = make_provider(handler).test()

    assert probe.ok is False
    assert probe.error
    assert probe.error_code == "unauthorized"
    assert FAKE_KEY not in probe.error


# --- 上游回显 Key 时也要脱敏（P0-F3）---
#
# redact() 认的是「像 Key 的样子」（sk- / Bearer / volc- …）。可是自建端点
# 或换了厂商之后，Key 完全可能是一串没有前缀的不透明令牌；而有的厂商
# 会把收到的令牌原样抄进错误体。那句话会进 probe.error、显示在设置页、
# 也可能落进日志 —— 所以除了按形状匹配，还得把**我们手里这一把**换掉。


def _echoing_handler(status: int, message: str):
    """上游把收到的令牌原样回显（去掉 Bearer 前缀）—— 模拟最坏情况。"""

    def handler(request: httpx.Request) -> httpx.Response:
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        return httpx.Response(status, json={"error": {"message": f"{message} ({token})"}})

    return handler


def test_probe_scrubs_an_echoed_opaque_token(app):
    """无前缀的不透明令牌被回显时，也必须脱敏 —— 光靠形状匹配拦不住它。"""
    opaque = "AbCd1234EfGh5678IjKl9012MnOp"

    probe = make_provider(
        _echoing_handler(401, "Authentication Fails for the provided credentials"),
        api_key=opaque,
    ).test()

    assert probe.ok is False
    assert opaque not in probe.error, f"上游回显的 Key 泄漏到了探活结果：{probe.error}"
    assert "AbCd1234" not in probe.error


def test_chat_error_scrubs_an_echoed_opaque_token(app):
    from app.providers.base import ProviderError

    opaque = "AbCd1234EfGh5678IjKl9012MnOp"

    with pytest.raises(ProviderError) as excinfo:
        make_provider(_echoing_handler(403, "Permission denied"), api_key=opaque).chat(
            [{"role": "user", "content": "hi"}]
        )

    assert opaque not in str(excinfo.value)


def test_the_message_survives_when_the_upstream_does_not_echo_the_key(app):
    """脱敏不能误伤正常文案：没提 Key 的消息要原样显示。"""
    probe = make_provider(json_handler({"error": {"message": "rate limited"}}, status=429)).test()

    assert probe.ok is False
    assert "rate limited" in probe.error


def test_test_never_raises_on_network_failure(app):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    with app.app_context():
        probe = make_provider(handler).test()

    assert probe.ok is False
    assert probe.error_code in {"network", "timeout"}


def test_test_never_raises_on_timeout(app):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with app.app_context():
        probe = make_provider(handler).test()

    assert probe.ok is False
    assert probe.error_code == "timeout"


def test_test_reports_missing_key_without_calling_upstream(app):
    """没配 Key 就不该发请求（省一次必然失败的往返）。"""
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, json=CHAT_OK)

    with app.app_context():
        probe = make_provider(handler, api_key="").test()

    assert probe.ok is False
    assert probe.error_code == "missing_api_key"
    assert called["n"] == 0


def test_test_never_raises_on_malformed_response(app):
    with app.app_context():
        probe = make_provider(json_handler({"nope": True})).test()

    assert probe.ok is False
    assert probe.error


# --- 流式 ---


def test_chat_stream_yields_deltas(app):
    sse = (
        b'data: {"id":"1","object":"chat.completion.chunk","created":1,"model":"deepseek-chat",'
        b'"choices":[{"index":0,"delta":{"content":"\xe5\x85\x89"},"finish_reason":null}]}\n\n'
        b'data: {"id":"1","object":"chat.completion.chunk","created":1,"model":"deepseek-chat",'
        b'"choices":[{"index":0,"delta":{"content":"\xe5\x90\x88"},"finish_reason":null}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=sse, headers={"content-type": "text/event-stream"}
        )

    with app.app_context():
        chunks = list(make_provider(handler).chat_stream([{"role": "user", "content": "hi"}]))

    assert "".join(chunks) == "光合"


def test_chat_stream_raises_provider_error_on_upstream_failure(app):
    from app.providers.base import ProviderError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    with app.app_context(), pytest.raises(ProviderError):
        list(make_provider(handler).chat_stream([{"role": "user", "content": "hi"}]))
