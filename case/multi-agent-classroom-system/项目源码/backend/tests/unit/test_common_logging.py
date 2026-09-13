"""日志脱敏测试（AGENTS.md §4.1 / §24）。

日志、异常栈里不得出现 API Key 原文；不得记录完整提示词与音频帧。
"""

from __future__ import annotations

import io
import logging

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def captured_logs(app):
    """把 root logger 的输出抓进内存。"""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)

    root = logging.getLogger()
    old_level = root.level
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)

    yield stream

    root.removeHandler(handler)
    root.setLevel(old_level)


def test_api_key_in_message_is_redacted(app, captured_logs):
    from app.common.logging import get_logger

    logger = get_logger("test")
    logger.info("调用上游 key=sk-9f2c4a1b7e8d4f6a0011223344556677")

    out = captured_logs.getvalue()
    assert "sk-9f2c4a1b7e8d4f6a0011223344556677" not in out
    assert "****" in out


def test_bearer_token_is_redacted(app, captured_logs):
    from app.common.logging import get_logger

    get_logger("test").warning(
        "Authorization: Bearer abcdef0123456789abcdef0123456789"
    )

    out = captured_logs.getvalue()
    assert "abcdef0123456789abcdef0123456789" not in out


def test_x_api_key_header_value_is_redacted(app, captured_logs):
    """火山引擎走的是单头 X-Api-Key，必须同样脱敏。"""
    from app.common.logging import get_logger

    get_logger("test").error('headers={"X-Api-Key": "volc-1234567890abcdef"}')

    out = captured_logs.getvalue()
    assert "volc-1234567890abcdef" not in out


def test_logger_exception_does_not_leak_key(app, captured_logs):
    """异常栈里带 Key 也不能漏。"""
    from app.common.logging import get_logger

    logger = get_logger("test")
    try:
        raise RuntimeError("upstream rejected api_key=sk-leak1234567890abcdef")
    except RuntimeError:
        logger.exception("上游调用失败")

    out = captured_logs.getvalue()
    assert "sk-leak1234567890abcdef" not in out


def test_redaction_mask_utility():
    from app.common.logging import redact

    text = "key=sk-abcdef0123456789 token=bearer-zzzzzzzzzzzzzzzz end"
    cleaned = redact(text)
    assert "sk-abcdef0123456789" not in cleaned
    assert "bearer-zzzzzzzzzzzzzzzz" not in cleaned
    assert "end" in cleaned


def test_redact_preserves_ordinary_text():
    from app.common.logging import redact

    text = "生成课程《光合作用》共 12 页，耗时 3.2s"
    assert redact(text) == text


def test_classroom_ticket_in_a_request_line_is_redacted():
    """课堂票据走 URL 查询串（§4.2），WSGI 服务器的访问日志会把请求行原样记下来。

    它一次性的、只活 60 秒 —— 但「有效期短」不该变成「可以进日志」：看日志的人
    不该顺手拿到这堂课的钥匙。这条走的是**根 handler 上的 Filter**（werkzeug 的
    logger 不经过 `get_logger`，`configure_logging` 装的就是这一份），所以这里
    照那个形状把记录喂进去。
    """
    from app.common.logging import RedactingFilter

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter())

    logger = logging.getLogger("werkzeug")
    logger.addHandler(handler)
    try:
        logger.warning(
            '%s - - "GET /ws/classroom/4e85e815?ticket=0yMCkLzZFKXyxObZTW9Gl7W5KnNJpUS0K0fvriPt0mo HTTP/1.1" 101 -',
            "127.0.0.1",
        )
    finally:
        logger.removeHandler(handler)

    out = stream.getvalue()
    assert "0yMCkLzZFKXyxObZTW9Gl7W5KnNJpUS0K0fvriPt0mo" not in out
    assert "ticket=****" in out
    # 同一行里的课号不是凭据，留着（不然排查时看不出是哪堂课）
    assert "4e85e815" in out


def test_logger_carries_request_id(app, captured_logs):
    """日志要带 requestId，便于把一次请求的日志串起来。"""
    from app.common.logging import get_logger

    with app.test_request_context("/api/health", headers={"X-Request-Id": "rid-42"}):
        get_logger("test").info("开始处理")

    assert "rid-42" in captured_logs.getvalue()


def test_registered_secret_is_redacted_from_any_text(app, captured_logs):
    """没有前缀的不透明令牌也要能脱敏（P0-F3：含异常栈）。

    形状匹配（sk- / Bearer）对自建端点的不透明令牌是无效的，
    所以 Secret 在被取出使用时会登记原文，redact() 按原文替换。
    """
    from app.common.logging import get_logger
    from app.providers.base import Secret

    opaque = "AbCd1234EfGh5678IjKl9012MnOp"
    Secret(opaque).reveal()
    get_logger("test").warning("上游回了：Authentication Fails (%s)", opaque)

    assert opaque not in captured_logs.getvalue()
    assert "Authentication Fails" in captured_logs.getvalue()


def test_configure_logging_is_idempotent(app):
    """重复配置不得叠加 handler（否则日志翻倍）。"""
    from app.common.logging import configure_logging

    configure_logging(app)
    before = len(logging.getLogger().handlers)
    configure_logging(app)
    after = len(logging.getLogger().handlers)

    assert after == before
