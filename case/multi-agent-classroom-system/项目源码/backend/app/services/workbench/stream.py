"""会话级 SSE 扇出（P4 §3.3）。

与 `generation/events.py` 的差别只有一处，但这一处很关键：**这里的帧不落库**。

生成事件要落库，是因为断线重连的客户端要靠 `gen_events` 补齐整门课的过程；
而工作台的一轮对话，**归档就在 `chat_messages` 里** —— Agent 说的最后一句话
是完整的一条消息，中间那些 `agent.delta` 只是它怎么一个字一个字地出现。
为它们再建一张表，只会得到一份与消息表重复、又比它短命的日志。

所以这里只保留**一轮之内的积压**（`BACKLOG` 帧）：

- 用户 POST 完消息、EventSource 才连上来，这中间发出去的帧不能丢 —— 积压就是
  为这个几百毫秒的窗口准备的（`begin()` 在开一轮时清空上一轮的）。
- 补发的窗口再长就没意义了：真要「看这一轮发生了什么」，读消息表更准。

队列满了丢**最旧**的一帧（同 events.py）：前端只顾读网络时，攒着几十帧只说明
它已经掉队了，而丢掉队头正好给新帧让位。
"""

from __future__ import annotations

import queue
import threading
from collections import deque
from typing import Any, Mapping

#: 每个会话的订阅队列长度。
QUEUE_SIZE = 128

#: 补发窗口：一轮对话最多回放多少帧。
BACKLOG = 256


class _Channel:
    """一个会话的扇出状态：订阅者 + 本轮积压 + 帧序号。"""

    def __init__(self) -> None:
        self.subscribers: list[queue.Queue] = []
        self.backlog: deque[dict] = deque(maxlen=BACKLOG)
        self.seq = 0


_channels: dict[str, _Channel] = {}
_lock = threading.Lock()


def begin(channel: str) -> None:
    """开一轮新对话：清掉上一轮的积压。

    必须在**这一轮的第一帧之前**调用（`chat.send` 里落完用户消息就调）。
    不这么做的话，用户连上来时会先看到上一轮的回放 —— 界面上一闪而过一段
    早就结束了的对话，然后才是新消息。
    """
    with _lock:
        state = _channels.setdefault(channel, _Channel())
        state.backlog.clear()


def publish(channel: str, event: str, payload: Mapping[str, Any] | None = None) -> dict:
    """造一帧、记进积压、广播。返回这一帧（带 `seq`）。"""
    with _lock:
        state = _channels.setdefault(channel, _Channel())
        state.seq += 1
        frame = {"seq": state.seq, "event": event, "payload": dict(payload or {})}
        state.backlog.append(frame)
        targets = list(state.subscribers)
    for target in targets:
        _offer(target, frame)
    return frame


def subscribe(channel: str, *, since: int = 0) -> tuple[queue.Queue, list[dict]]:
    """订阅，并取回 `since` 之后的积压。

    两件事在**同一把锁**里做完：注册之后发的帧会进队列，注册之前发的在积压里 ——
    中间没有缝，所以既不会丢帧，也不会重复（各归各的）。
    """
    with _lock:
        state = _channels.setdefault(channel, _Channel())
        target: queue.Queue = queue.Queue(maxsize=QUEUE_SIZE)
        state.subscribers.append(target)
        pending = [frame for frame in state.backlog if int(frame["seq"]) > since]
    return target, pending


def unsubscribe(channel: str, target: queue.Queue) -> None:
    with _lock:
        state = _channels.get(channel)
        if state is not None and target in state.subscribers:
            state.subscribers.remove(target)


def reset() -> None:
    """清空全部会话状态（测试之间复位；真实进程里没有第二个用户会来清它）。"""
    with _lock:
        _channels.clear()


def frame_text(frame: Mapping[str, Any]) -> str:
    """一帧落成 SSE 文本。`data` 必须是**单行** —— 换行会把它切成两帧。

    与 `app/api/generation.py` 的 `_format` 同形：两条流在前端用同一个
    EventSource 封装读，格式分叉只会让那份代码长出两个分支。
    """
    import json

    data = json.dumps(frame.get("payload") or {}, ensure_ascii=False, separators=(",", ":"))
    return f"id: {frame.get('seq')}\nevent: {frame.get('event')}\ndata: {data}\n\n"


def _offer(target: queue.Queue, frame: dict) -> None:
    try:
        target.put_nowait(frame)
    except queue.Full:
        try:
            target.get_nowait()  # 丢最旧的一帧，给新的让位
            target.put_nowait(frame)
        except (queue.Empty, queue.Full):  # pragma: no cover - 极端并发下让这一帧过去
            pass


__all__ = ["BACKLOG", "QUEUE_SIZE", "begin", "frame_text", "publish", "reset", "subscribe", "unsubscribe"]
