"""上游 WebSocket 传输层（Provider 层内部件）。

存在的理由有两个：

1. **厂商隔离**：`simple_websocket` 是第三方库，按 AGENTS.md §14.2 只能出现在
   `app/providers/` 里。语音三件套要连上游 WS，于是把它关在这一层，
   适配器只认本模块的 `WsTransport` 协议与三个异常类型。
2. **可注入**：没有火山 Key 也要能把协议逻辑跑到字节级（验收 P2-A15/A21/A22）。
   适配器构造时收一个 `connect=` 参数，测试塞个假连接进来，
   真协议代码一行不改就跑完了 —— 这比"没 Key 就整段跳过"可信得多。

三个异常类型刻意不直接暴露 `simple_websocket` 的异常：
适配器按 `TransportTimeout`（超时，收到一半没下文）与 `TransportClosed`
（对端关了，可重连）分流即可，**不做字符串匹配**。
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from app.common.logging import get_logger
from app.providers.base import ProviderError, ProviderTimeoutError

logger = get_logger(__name__)


class TransportError(ProviderError):
    """传输层故障（50201）：连不上、写失败、协议层报错。"""


class TransportClosed(TransportError):
    """对端关闭了连接，或连接已断。

    实时语音会话超 10 分钟无交互被服务端释放就走这条路 —— 在 P3 课堂里
    **这是必然路径而不是异常分支**（P2-A17 要求自动重建会话，前端无感）。
    """


class TransportTimeout(ProviderTimeoutError):
    """等上游响应超时（50401）。上游没崩，只是这次没在预期时间内回来。"""


@runtime_checkable
class WsTransport(Protocol):
    """一条已连上的 WebSocket。收发都是整条消息（不做分片重组，协议层管）。"""

    def send(self, data: bytes | str) -> None:
        """发一条消息。失败抛 `TransportClosed` / `TransportError`。"""

    def receive(self, timeout: float | None = None) -> bytes | str:
        """收一条消息。超时抛 `TransportTimeout`，对端关闭抛 `TransportClosed`。"""

    def close(self, reason: str | None = None) -> None:
        """关闭连接。重复调用应当无害。"""


#: 连接工厂签名：`connect(url, headers=..., timeout=...)`。
Connector = Callable[..., WsTransport]


def default_connector(
    url: str,
    *,
    headers: Mapping[str, str] | Sequence[tuple[str, str]] | None = None,
    timeout: float | None = None,
    ping_interval: float | None = None,
    receive_bytes: int = 8192,
    **options: Any,
) -> WsTransport:
    """默认连接工厂：`simple_websocket.Client`。

    `receive_bytes` 是**单次读的字节数**而不是消息上限：消息由库自己拼完整，
    音频帧动辄几 KB，默认的 4096 会让大帧多读几轮，这里放宽到 8KB。

    握手失败时 `simple_websocket` 抛的是**它自带的** `ConnectionError`，
    统一翻译成 `TransportError`，并按状态码补一句可排障的提示。

    注意它是按自己的类接的，不是按内建名字：库那个 `ConnectionError` 继承的是
    `SimpleWebsocketError(RuntimeError)`，而内建的 `ConnectionError` 是 `OSError`
    的子类 —— 两者毫无亲缘。写成 `except ConnectionError` 接不到它，异常会一路
    漏到业务层，最后变成用户看到的「服务器内部错误」（真实踩过）。
    """
    from simple_websocket import Client, ConnectionClosed
    from simple_websocket.errors import SimpleWebsocketError
    from wsproto.utilities import ProtocolError

    try:
        return Client(url, headers=headers, ping_interval=ping_interval, receive_bytes=receive_bytes)
    except ConnectionClosed as exc:  # 握手阶段对端就关了
        raise TransportError(f"上游 WebSocket 握手被关闭：{_detail(exc)}") from exc
    except ProtocolError as exc:
        # 对端回的不是 WebSocket 握手响应（网关/代理插了一页 HTML 就这样）
        raise TransportError(
            f"上游返回的不是合法的 WebSocket 握手响应（{_safe_url(url)}）：{exc}"
        ) from exc
    except OSError as exc:
        # 内建 ConnectionError 也走这里（它是 OSError 的子类）：连不上、超时、TLS 失败
        raise TransportError(f"连接不上上游 WebSocket（{_safe_url(url)}）：{exc}") from exc
    except SimpleWebsocketError as exc:
        # 握手被上游拒绝（库拿 RejectConnection 事件换来的状态码）
        raise _handshake_error(exc, url) from exc
    finally:
        _ = (timeout, options)  # 连接超时由 socket 默认值兜底，参数留着统一签名


#: 握手被拒时按状态码补的一句「接下来查哪儿」。
#: 上游**不把响应体交给我们**（见 `_handshake_error`），这句只能自己写 ——
#: 少了它，用户看到的就是一个裸的 403，只能来问「服务器内部错误是怎么回事」。
_HANDSHAKE_HINTS: dict[int, str] = {
    401: "凭据不对：检查 API Key 是否填对、是否属于当前账号",
    403: "该账号没有开通这项服务，或资源 ID（X-Api-Resource-Id）与服务对不上",
    404: "接入地址不对：检查 endpoint 的路径与区域",
    429: "上游限流，稍后再试",
}


def _handshake_error(exc: BaseException, url: str) -> TransportError:
    """握手被拒 → 一句能照着排障的话。

    只拿得到状态码：握手失败在协议层是个 `RejectConnection` **事件**，
    wsproto 把它压成状态码 + 响应头，响应体到这一步已经丢了。所以别指望
    从这里透出上游的 error body，提示按状态码给。
    """
    where = _safe_url(url)
    try:
        status = int(getattr(exc, "status_code", 0) or 0)
    except (TypeError, ValueError):
        status = 0
    if not status:
        return TransportError(f"上游 WebSocket 握手失败（{where}）：{exc}")
    hint = _HANDSHAKE_HINTS.get(status, "")
    return TransportError(
        f"上游 WebSocket 握手被拒：HTTP {status}"
        + (f"；{hint}" if hint else "")
        + f"（{where}）"
    )


def wrap(ws: Any) -> WsTransport:
    """把一个第三方连接对象包成 `WsTransport`（异常翻译）。

    适配器拿到的连接可能来自注入（测试假件不需要翻译），所以翻译放在这里、
    而不是在适配器里对每种连接各写一遍。
    """
    from simple_websocket import ConnectionClosed

    class _Wrapped:
        def send(self, data: bytes | str) -> None:
            try:
                ws.send(data)
            except ConnectionClosed as exc:
                raise TransportClosed(f"连接已关闭：{_detail(exc)}") from exc

        def receive(self, timeout: float | None = None) -> bytes | str:
            try:
                data = ws.receive(timeout=timeout)
            except TimeoutError as exc:
                raise TransportTimeout("等待上游响应超时") from exc
            except ConnectionClosed as exc:
                raise TransportClosed(f"连接已关闭：{_detail(exc)}") from exc
            if data is None:
                # `simple_websocket` 超时**不抛异常，返回 None**（读了源码才敢信）。
                # 不在这儿翻译的话，None 会一路漏到协议解析器里，变成一句
                # 「object of type 'NoneType' has no len()」—— 既不是超时也不是
                # 断链，排查时完全看不出上游只是没吭声（真实踩过）。
                raise TransportTimeout("等待上游响应超时")
            return data

        def close(self, reason: str | None = None) -> None:
            try:
                ws.close(reason=reason)
            except Exception:
                # 关闭是收尾动作：它抛异常往往是因为连接早就断了，
                # 而调用方此刻正在处理一个更要紧的错（比如上游报错码）。
                logger.debug("关闭上游 WebSocket 时出错，已忽略", exc_info=True)

    return _Wrapped()


def _detail(exc: BaseException) -> str:
    """`ConnectionClosed` 的 reason/message 拼成人能看的一句话。"""
    reason = getattr(exc, "reason", "") or ""
    message = getattr(exc, "message", "") or ""
    if isinstance(message, (bytes, bytearray)):
        message = message.decode("utf-8", errors="replace")
    return f"{reason} {message}".strip() or exc.__class__.__name__


def _safe_url(url: str) -> str:
    """URL 进日志前掐掉 query：火山把某些参数放在 query 里，不是凭据也别全抄。"""
    return url.split("?", 1)[0]


__all__ = [
    "Connector",
    "TransportClosed",
    "TransportError",
    "TransportTimeout",
    "WsTransport",
    "default_connector",
    "wrap",
]
