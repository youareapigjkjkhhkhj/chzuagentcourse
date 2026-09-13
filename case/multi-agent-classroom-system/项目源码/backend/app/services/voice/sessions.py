"""一个用户同时只开一条语音会话（P2-F5）。

一个人同时开着两条实时语音，两端都在推麦克风、都在放老师的回答，结果是
**他自己**听到两个老师在说话，而账按两条会话记。所以第二条要挡掉：
`start` 的时候发现这个人已经有一条活着的会话，就回 `42901`（`RateLimitError`），
前端照例按 `fallback` 退到文字问答 —— 一条会话在跑，不影响他继续上课。

三件事写在这里，因为它们的取舍都不明显：

1. **认的是 owner，不是连接。** 同一浏览器开两个标签页就是两条连接，
   上限管的是「这个人」，所以键取 `owner_id`（`X-Owner-Id`，与 HTTP 一路同源）。
2. **释放的时机是「会话关闭」，而不是「连接关闭」。** `RealtimeChannel.close()`
   在正常结束、浏览器断开、上游失败三条路上都会跑到（`run()` 的 finally），
   所以浏览器崩掉、网线拔掉都不会把名额永久占住。
3. **还有一道 TTL 兜底。** 万一哪条路径真的漏了释放（进程被杀、`close()`
   抛异常），十分钟后名额自动作废 —— 上游本来就会在这个时候释放会话
   （`45000003`，P2 §8），拿它当兜底的分界正好。**这条兜底是必要的**：
   没有它，一次异常就能让那个人的语音永久不可用，而症状是「昨天还好好的，
   今天一直提示忙」。

**占用凭据由服务端生成，不取前端给的 sessionId。** 那个值客户端说了算：
两条连接报同一个 `sessionId` 就都算「同一次会话」，上限于是形同虚设。
现在前端压根不发 `start.sessionId`（它只用于记账），谁发谁不发都不该
决定这条防线在不在。

**存内存**：与 `tickets` 同一条限制（单进程）。多进程部署要换成共享存储。
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from app.common.logging import get_logger

logger = get_logger("app.voice.sessions")

#: 名额超时（秒）。与上游「会话超 10 分钟无交互即释放」同量级（P2 §8）。
SESSION_TTL_SECONDS = 600

#: `{归属人: (占用凭据, 占用时刻)}`
_holds: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()


def claim(
    owner_id: str,
    slot: str,
    *,
    ttl: int = SESSION_TTL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """占一个会话名额。这个人已经有别的通道占着就返回 False。

    `slot` 是**这条通道自己的**凭据（`RealtimeChannel` 建实例时生成一个），
    不是前端的会话号：同一个凭据重复占算成功 —— 那是同一条通道又走了一遍
    `start`，不是第二条会话。
    """
    owner = str(owner_id or "")
    if not owner:  # 没归属人就没法判「同一个人」，不拦（见模块 docstring）
        return True

    slot = str(slot or "session")
    now = clock()
    with _lock:
        held = _holds.get(owner)
        if held is not None:
            current, since = held
            if current == slot:
                return True
            if now - since < max(1, int(ttl)):
                logger.warning("实时语音：%s 已有一条会话在跑（%s），拒绝 %s", owner, current, slot)
                return False
            logger.warning("实时语音：%s 的名额已超时（%s），由 %s 接手", owner, current, slot)
        _holds[owner] = (slot, now)
        return True


def release(owner_id: str, slot: str) -> None:
    """还名额。**只有当前占着的那一条能还** —— 不然一条晚到的收尾会把
    接手者的名额一起撤掉（两个人于是都能开，而上限等于没有）。
    """
    owner = str(owner_id or "")
    if not owner:
        return
    with _lock:
        held = _holds.get(owner)
        if held is not None and held[0] == str(slot or "session"):
            _holds.pop(owner, None)


def holder(owner_id: str) -> str:
    """当前占着名额的凭据（没占着就是空串）。排障与测试用。"""
    with _lock:
        held = _holds.get(str(owner_id or ""))
    return held[0] if held is not None else ""


def clear() -> None:
    """清空（测试用）。"""
    with _lock:
        _holds.clear()


__all__ = ["SESSION_TTL_SECONDS", "claim", "clear", "holder", "release"]
