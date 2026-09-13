"""实时语音的会话票据（P2-F4）。

WS 握手要带一张**服务端签发的、一次性的、有时效的**票据，没带就把这次握手
挡在升级之前（HTTP 401 / 40101），客户端连 101 都拿不到。

**它不是鉴权**，别当成鉴权读：本项目的 owner 来自 `X-Owner-Id` 请求头，
能改请求头就能换个人（见 `common/identity.py` 的注释）。票据回答的是另一个
问题 —— **「你有没有先走一趟 HTTP」**。那一趟里三件事都判过了：语音总开关、
上游有没有配好、这算谁的一次会话；WS 那条路因此不必再判一遍，也就不可能
和 HTTP 判得不一样。以前不是这样：`VOICE_ENABLED=false` 的部署里，
`/ws/voice/realtime` 照样能建会话（路由压根不看这个开关），
而这类分歧只有真连一次才发现。

**一次性 + 60 秒**：浏览器拿到票据就立刻建连（`useRealtimeVoice.open()` 里
两步是连着的），中间隔不下人。要是可重复使用，一张票据被抄走就等于长期通行证；
要是不过期，一张票据会留在历史记录里。

**存内存**：单进程部署（dev / demo）够用，多进程要换成共享存储（Redis）。
这条限制写在这里而不是藏在实现里 —— 换部署形态时它是第一个会坏的假设。

**`scope`：票据是开给哪条路的**（P3 加的）。语音的票不写 `scope`（空串），
课堂的票写**会话 id** —— 「这次握手进的是哪一堂课」。P3-F1 要的是「伪造
`sessionId` 接不进别人的课堂」，而已核销的票据只带回一个归属人；不带 `scope`
的话，一张为 A 课签的票改个 URL 就能连 B 课，而两堂课的门槛本来不一样。
核销时**两边必须一模一样**：空串也算一个值，所以语音的票换不到课堂里去，
反之亦然 —— 一张票只对签发它的那条路有效，这是最容易讲清楚的一条规则。
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any, Callable

from app.common.errors import UnauthorizedError

#: 票据有效期（秒）。比一次「点开麦克风」的间隔长得多，比一个午休短得多。
TICKET_TTL_SECONDS = 60

#: 票据长度（`secrets.token_urlsafe` 的字节数）。32 字节 = 256 位熵。
TICKET_BYTES = 32

#: `{票据: (归属人, 过期时刻, 用途)}`。过期的不主动清，读写时顺手捞掉。
_tickets: dict[str, tuple[str, float, str]] = {}
_lock = threading.Lock()


def issue(
    owner_id: str,
    *,
    ttl: int = TICKET_TTL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    scope: str = "",
) -> dict[str, Any]:
    """签发一张票据。返回 `{ticket, ttlSec}`。

    **不给绝对到期时刻**：过期是按单调钟算的（不随系统时间被改而变），
    把它换算成一个墙上时间只为了好看，反而会给出一个不准的时刻 ——
    而调用方拿到票据就立刻建连，本来也不需要这个数。

    `scope` 是这条路自己的用途标识（课堂用它写会话 id）。**票面值不回给
    调用方**：调用方本来就该知道自己签的是哪条路，而多回一个字段，
    浏览器就可能把它当成「可以改的东西」。
    """
    ttl = max(1, int(ttl))
    now = clock()
    ticket = secrets.token_urlsafe(TICKET_BYTES)
    with _lock:
        _prune(now)
        _tickets[ticket] = (str(owner_id or ""), now + ttl, str(scope or ""))
    return {"ticket": ticket, "ttlSec": ttl}


def consume(
    ticket: str,
    *,
    clock: Callable[[], float] = time.monotonic,
    scope: str = "",
    fallback: str = "text",
) -> str:
    """核销一张票据，返回它的归属人。**一次性**：核销过就没了。

    不认识 / 过期 / 已用过 / **用途对不上**，一律同一个错误、同一句话：
    说清「哪一步不对」会让人以为换个写法能绕过，而这个接口不该给这种暗示。

    用途对不上也走这一个分支（而不是给个更具体的错），理由同上 ——
    而且它顺带说明了一件事：票据在服务端是**一个**集合，不是两条路各存一份。

    `fallback`：票不对之后**退到哪条路**（P2-B2 的降级口径）。票据是两条路
    共用的一套，而退路不是 —— 语音退到文字问答（`text`），课堂退到逐页手动
    翻页（`manual`，P3-G3）。所以由调用方给，不在这里写死；默认值是语音的，
    因为语音是这条路的老主顾，改默认值等于悄悄改了 P2 的契约。
    """
    value = str(ticket or "").strip()
    now = clock()
    with _lock:
        _prune(now)
        claimed = _tickets.pop(value, None)
    if claimed is None or claimed[2] != str(scope or ""):
        raise UnauthorizedError(
            "会话票据无效或已过期，请重新发起连接",
            details={"ok": False, "error": "bad_ticket", "fallback": str(fallback or "text")},
        )
    return claimed[0]


def live_count(*, clock: Callable[[], float] = time.monotonic) -> int:
    """还没被用掉的票据数（观测与测试用）。"""
    with _lock:
        _prune(clock())
        return len(_tickets)


def clear() -> None:
    """清空（测试用：模块级状态不该跨用例残留）。"""
    with _lock:
        _tickets.clear()


def _prune(now: float) -> None:
    """捞掉过期的。调用方必须已经持有锁。"""
    for key in [key for key, (_, expiry, _scope) in _tickets.items() if expiry <= now]:
        _tickets.pop(key, None)


__all__ = ["TICKET_BYTES", "TICKET_TTL_SECONDS", "clear", "consume", "issue", "live_count"]
