"""事件中心：定序、留档、扇出（P1 §4.1 / AGENTS §17）。

三个断言各自对应一种线上会看到的现象：

- **seq 不重复**（并发也要）：前端靠它判断有没有漏帧，重复与跳号都会让它错判
- **落库**：SSE 是「送达」不是「存储」，断线期间的进度只能从库里补
- **扇出不拖垮服务端**：订阅者读得慢时丢最旧的帧，而不是把内存撑爆

帧挂在真任务上（`gen_events.job_id` 有外键）—— 造一个不存在的 job_id
只会验到外键约束。
"""

from __future__ import annotations

import queue
import threading
import time

import pytest

from app.models import GenEvent
from app.services.courses import store
from app.services.generation import events
from app.services.generation.pipeline import DEFAULT_OPTIONS, start_job

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean(app):
    events.drop_subscribers()
    yield
    events.drop_subscribers()


@pytest.fixture()
def flow(app):
    """两个真任务：seq 是**按任务**排的，很多用例都要两门课来对照。"""
    ids = []
    for index in (1, 2):
        course = store.create_course(
            title=f"课 {index}", topic="机器学习入门", options=DEFAULT_OPTIONS
        )
        ids.append(start_job(course, options=DEFAULT_OPTIONS).id)
    return ids


def test_emit_persists_the_frame_with_a_monotonic_seq(app, flow):
    first, second = flow

    one = events.emit(first, "job.start", {"jobId": first})
    two = events.emit(first, "step.start", {"type": "parse"})

    assert (one["seq"], two["seq"]) == (1, 2)
    assert one["event"] == "job.start"
    assert one["payload"] == {"jobId": first}

    rows = GenEvent.query.filter_by(job_id=first).order_by(GenEvent.seq).all()
    assert [row.seq for row in rows] == [1, 2], "落库的那一份才决定 seq"
    assert second != first


def test_seq_is_per_job(app, flow):
    first, second = flow

    events.emit(first, "job.start", {})
    events.emit(second, "job.start", {})

    assert [events.last_seq(first), events.last_seq(second)] == [1, 1]
    assert events.last_seq("job-不存在") == 0, "没发过帧的任务从 0 起"


def test_concurrent_emits_never_collide_on_a_seq(app, flow):
    """多线程同时发帧时，SQLite 的单写者 + 写锁必须让它们拿到不同的号。

    真实场景里这些线程就是写页的那些 worker：它们各自往同一个任务上发
    `page.ready`。撞号会让前端的进度条直接错乱。
    """
    (job_id,) = flow[:1]
    start = threading.Barrier(4)
    seen: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        with app.app_context():
            start.wait(5)
            for _ in range(5):
                frame = events.emit(job_id, "step.progress", {})
                with lock:
                    seen.append(frame["seq"])

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)

    assert sorted(seen) == list(range(1, 21)), f"seq 撞了或跳号：{sorted(seen)}"
    assert GenEvent.query.filter_by(job_id=job_id).count() == 20


# --- 订阅与扇出 ---


def test_a_subscriber_receives_later_frames(app, flow):
    (job_id,) = flow[:1]

    channel = events.subscribe(job_id)
    events.emit(job_id, "step.start", {"type": "parse"})

    assert channel.get_nowait()["event"] == "step.start"
    assert events.subscriber_count(job_id) == 1


def test_unsubscribe_stops_delivery(app, flow):
    (job_id,) = flow[:1]
    channel = events.subscribe(job_id)

    events.unsubscribe(job_id, channel)
    events.emit(job_id, "step.start", {})

    assert channel.empty()
    assert events.subscriber_count(job_id) == 0


def test_unsubscribing_twice_is_harmless(app, flow):
    (job_id,) = flow[:1]
    channel = events.subscribe(job_id)

    events.unsubscribe(job_id, channel)
    events.unsubscribe(job_id, channel)
    events.unsubscribe("job-不存在", channel)

    assert events.subscriber_count(job_id) == 0


def test_a_slow_subscriber_loses_the_oldest_frames_not_the_newest(app, flow):
    """读得慢的前端不该把服务端的内存拖垮 —— 丢最旧的，保最新的。"""
    (job_id,) = flow[:1]
    channel = events.subscribe(job_id)
    total = events.QUEUE_SIZE + 5

    for index in range(total):
        events.emit(job_id, "step.progress", {"n": index})

    frames = _drain(channel)
    assert len(frames) == events.QUEUE_SIZE
    assert frames[-1]["payload"]["n"] == total - 1, "最新的一帧必须留着"
    assert all(frame for frame in frames), "占位帧不该被当成事件交出去"


def _drain(channel: queue.Queue) -> list[dict]:
    out = []
    while not channel.empty():
        out.append(channel.get_nowait())
    return out


# --- 补发 ---


def test_replay_returns_everything_after_the_given_seq(app, flow):
    (job_id,) = flow[:1]
    for name in ("job.start", "step.start", "step.done"):
        events.emit(job_id, name, {})

    assert [frame["event"] for frame in events.replay(job_id, 1)] == ["step.start", "step.done"]
    assert events.replay(job_id, 3) == []
    assert len(events.replay(job_id)) == 3


def test_replay_is_ordered_by_seq(app, flow):
    (job_id,) = flow[:1]
    for name in ("a", "b", "c"):
        events.emit(job_id, name, {})

    assert [frame["seq"] for frame in events.replay(job_id, 0)] == [1, 2, 3]


# --- 取帧 ---


def test_iter_frames_yields_none_when_the_queue_is_idle(app, flow):
    """None 是「该发心跳了」的信号，不是一帧事件。"""
    (job_id,) = flow[:1]
    channel = events.subscribe(job_id)
    stream = events.iter_frames(channel, timeout=0.01, stopping=lambda: False)

    assert next(stream) is None

    events.emit(job_id, "step.start", {})
    assert next(stream)["event"] == "step.start"


def test_iter_frames_stops_when_asked(app, flow):
    """客户端断线后这条生成器要被收掉，不能留着空转。"""
    (job_id,) = flow[:1]
    channel = events.subscribe(job_id)
    flag = {"stop": False}
    stream = events.iter_frames(channel, timeout=0.01, stopping=lambda: flag["stop"])

    assert next(stream) is None
    flag["stop"] = True

    assert list(stream) == [], "stopping 之后应立刻结束"


def test_a_frame_that_nobody_reads_does_not_block_the_emitter(app, flow):
    """没有订阅者时 emit 照常写库 —— 事件是留档，不是广播才存在。"""
    (job_id,) = flow[:1]

    started = time.monotonic()
    events.emit(job_id, "job.start", {})

    assert time.monotonic() - started < 1
    assert GenEvent.query.filter_by(job_id=job_id).count() == 1
