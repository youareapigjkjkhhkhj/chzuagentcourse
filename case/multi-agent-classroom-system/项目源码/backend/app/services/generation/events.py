"""生成事件中心（P1 §4 SSE / AGENTS §17）。

管线只知道「发生了什么」，不关心「怎么传出去」。这一层负责三件事：

1. **定序**：每个 job 的 seq 从 1 单调递增，且**落库**。断线重连时前端带的
   `Last-Event-ID` 要能对上一条确定的记录 —— 没有 seq，补发就只能靠猜
   （AGENTS §4.3：服务端是唯一状态源）。
2. **留档**：每一帧都进 `gen_events`。SSE 是「送达」而不是「存储」，
   连上之前的进度、断线期间的进度都只能从这张表里补。
3. **扇出**：把帧投给当前订阅者。每个订阅者一个 Queue，满了就丢**最旧的**
   那一帧 —— 一个只顾着读网络的前端不该把服务端的内存拖垮，
   而丢了队头的老帧正好让位给新的状态（丢的是它已经看不到的过去，
   不是它正需要的现在）。

传输层（HTTP 响应头、心跳、`Last-Event-ID` 解析）在 P1-4 的 SSE 路由里，
本模块不碰 Flask 的响应对象，因此可以被同步测试直接驱动。
"""

from __future__ import annotations

import contextlib
import queue
import threading
from typing import Any, Callable, Mapping

from app.common.dbw import db_write
from app.common.logging import get_logger
from app.extensions import db
from app.models import GenEvent

logger = get_logger("app.generation.events")

#: 订阅者的队列长度。够放下一屏进度就好：前端没在消费时，
#: 攒着几十帧只说明它已经掉队了，补发交给 gen_events 更省事。
QUEUE_SIZE = 256

_subscribers: dict[str, list[queue.Queue]] = {}
_lock = threading.Lock()


def emit(job_id: str, event: str, payload: Mapping[str, Any] | None = None) -> dict:
    """记一帧并广播出去，返回落库后的帧。"""
    body = dict(payload or {})
    # 帧在事务**内**成形：提交会让行过期，出了事务再读字段就得多跑一次 SELECT
    frame = db_write(lambda: _append(job_id, event, body).to_dict())
    _fan_out(job_id, frame)
    return frame


def subscribe(job_id: str) -> queue.Queue:
    """订阅一个 job 的后续帧。返回的队列由调用方负责取消订阅。"""
    channel: queue.Queue = queue.Queue(maxsize=QUEUE_SIZE)
    with _lock:
        _subscribers.setdefault(job_id, []).append(channel)
    return channel


def unsubscribe(job_id: str, channel: queue.Queue) -> None:
    with _lock:
        channels = _subscribers.get(job_id)
        if not channels:
            return
        if channel in channels:
            channels.remove(channel)
        if not channels:
            _subscribers.pop(job_id, None)


def replay(job_id: str, after_seq: int = 0) -> list[dict]:
    """补发 `after_seq` 之后的帧。断线重连与「连上之前已经发生的进度」都走它。"""
    rows = (
        GenEvent.query.filter(GenEvent.job_id == job_id, GenEvent.seq > int(after_seq))
        .order_by(GenEvent.seq)
        .all()
    )
    return [row.to_dict() for row in rows]


def last_seq(job_id: str) -> int:
    row = (
        GenEvent.query.filter(GenEvent.job_id == job_id)
        .order_by(GenEvent.seq.desc())
        .first()
    )
    return int(row.seq) if row is not None else 0


def subscriber_count(job_id: str) -> int:
    with _lock:
        return len(_subscribers.get(job_id, ()))


def drop_subscribers() -> None:
    """清空所有订阅（测试之间复用；进程退出时也没人用得上它们了）。"""
    with _lock:
        _subscribers.clear()


def _append(job_id: str, event: str, payload: Mapping[str, Any]) -> GenEvent:
    """分配 seq 并落库。

    在 db_write 里读 `max(seq)` 再写 —— 两个线程同时发帧时，
    SQLite 的单写者 + 这把写锁保证它们不会拿到同一个号。
    """
    row = GenEvent(job_id=job_id, seq=last_seq(job_id) + 1, event=event)
    row.payload = dict(payload)
    db.session.add(row)
    db.session.flush()
    return row


def _fan_out(job_id: str, frame: Mapping[str, Any]) -> None:
    with _lock:
        channels = list(_subscribers.get(job_id, ()))
    for channel in channels:
        try:
            channel.put_nowait(frame)
        except queue.Full:
            _drop_oldest(channel, frame)


def _drop_oldest(channel: queue.Queue, frame: Mapping[str, Any]) -> None:
    """队列满时丢掉**最旧**的一帧，把新的一帧放进去。

    反过来（丢新的、留旧的）会让一个读得慢的前端永远停在旧进度上：
    它只是没跟上，不是不该看到最新状态。丢掉的那一段可以由 `gen_events`
    按 `Last-Event-ID` 补 —— 那正是这张表存在的理由。
    """
    with contextlib.suppress(queue.Empty):  # 另一个线程刚好把它取空了
        channel.get_nowait()
    try:
        channel.put_nowait(frame)
    except queue.Full:  # pragma: no cover - 极端竞态下只能放弃这一帧
        logger.warning("SSE 订阅队列拥塞，丢弃了一帧")


def iter_frames(channel: queue.Queue, *, timeout: float, stopping: Callable[[], bool]):
    """从队列里取帧，取不到就按 `timeout` 返回 None（调用方据此发心跳）。

    None 是**信号**不是事件：SSE 路由收到它就发一行 `: ping`，
    而不是把它当成一帧 payload 为空的事件推给前端。
    """
    while True:
        if stopping():
            return
        try:
            frame = channel.get(timeout=timeout)
        except queue.Empty:
            yield None
            continue
        yield frame


__all__ = [
    "QUEUE_SIZE",
    "drop_subscribers",
    "emit",
    "iter_frames",
    "last_seq",
    "replay",
    "subscribe",
    "subscriber_count",
    "unsubscribe",
]
