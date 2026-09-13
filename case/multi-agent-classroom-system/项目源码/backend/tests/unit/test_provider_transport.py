"""上游 WebSocket 连接层的异常翻译（P2 / AGENTS.md §14.2）。

这一层存在的意义就是「别让第三方库的异常漏到业务层」，而它自己漏过一次：
`simple_websocket` 的握手失败异常**也叫** `ConnectionError`，但继承的是
`SimpleWebsocketError(RuntimeError)`，跟内建那个 `ConnectionError`（`OSError`
的子类）没有半点亲缘。当初按内建名字 catch，于是 403 一路漏到路由层，
用户看到的是 500「服务器内部错误」外加一堆无从下手的堆栈。

所以这里钉住的是**翻译结果**，不是连接过程：全部 monkeypatch 掉库的连接入口，
不联网。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def _client_raising(exc: BaseException):
    def fake_client(url, **kwargs):
        raise exc

    return fake_client


def test_handshake_rejection_becomes_a_readable_transport_error(monkeypatch):
    """403 要变成「去开通服务」，而不是一个 500。"""
    from simple_websocket import ConnectionError as WsConnectionError

    from app.providers import transport

    monkeypatch.setattr("simple_websocket.Client", _client_raising(WsConnectionError(403)))
    with pytest.raises(transport.TransportError) as excinfo:
        transport.default_connector("wss://tts.example.invalid/api/v3/tts?token=secret-x")

    message = excinfo.value.message
    assert "403" in message
    assert "开通" in message, "状态码要翻成一句能照着查的话，否则用户只能来问"
    assert "token=secret-x" not in message, "query 可能带凭据，不该进错误文案"
    # 50201 / HTTP 502：业务层把它当「上游故障」，不是「我们崩了」
    assert excinfo.value.code == 50201


def test_the_library_connection_error_is_not_confused_with_the_builtin(monkeypatch):
    """这条是上一条的前提：库的 ConnectionError 确实**不是**内建那个。

    真去断言继承关系，而不是靠注释记着 —— 哪天库换了基类，这条会先响。
    """
    from simple_websocket import ConnectionError as WsConnectionError

    assert not issubclass(WsConnectionError, ConnectionError)
    assert issubclass(WsConnectionError, RuntimeError)


def test_builtin_connection_error_is_also_mapped(monkeypatch):
    """内建的 ConnectionError（OSError 子类）走「连不上」那支，文案要指地址。"""
    from app.providers import transport

    monkeypatch.setattr(
        "simple_websocket.Client", _client_raising(ConnectionError("refused"))
    )
    with pytest.raises(transport.TransportError) as excinfo:
        transport.default_connector("wss://asr.example.invalid/api/v3")

    assert "连接不上" in excinfo.value.message
    assert "asr.example.invalid" in excinfo.value.message


def test_a_non_websocket_response_is_mapped(monkeypatch):
    """代理塞回一页 HTML 时 wsproto 抛 ProtocolError —— 也得翻，不能漏出去。"""
    from wsproto.utilities import RemoteProtocolError

    from app.providers import transport

    monkeypatch.setattr(
        "simple_websocket.Client", _client_raising(RemoteProtocolError("bad response"))
    )
    with pytest.raises(transport.TransportError) as excinfo:
        transport.default_connector("wss://asr.example.invalid/api/v3")

    assert "握手响应" in excinfo.value.message


def test_a_successful_connect_is_returned_untouched(monkeypatch):
    """翻译层不能顺手把正常连接也吞了。"""
    from app.providers import transport

    sentinel = object()
    monkeypatch.setattr("simple_websocket.Client", lambda url, **kwargs: sentinel)

    assert transport.default_connector("wss://asr.example.invalid/api/v3") is sentinel
