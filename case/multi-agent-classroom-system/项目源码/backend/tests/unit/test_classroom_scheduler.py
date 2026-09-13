"""发言调度器（§2.2 / P3-A2 / P3-A6 / P3-A9）。

P3 最贵的一条 bug 是「两个 AI 同时出声」—— 课堂当场崩塌。所以这里逐条钉：

- 优先级：学生提问 > 教师答疑 > 同学插话 > 同学讨论 > 教师讲授；
- **单写者**：`next()` 在有 active 时不给第二条（不靠调用方自觉）；
- 抢占：能打断一切**除教师答疑**；被打断的发言**丢弃不补播**；
- TTL：排队超 20 秒自己消失（时钟可注入，不必真等）；
- 讨论轮次与时长按激烈程度映射。

没有数据库、没有 WebSocket：这一层是纯逻辑，所以测试里一个夹具都不需要。
"""

from __future__ import annotations

import pytest

from app.services.classroom import scheduler

pytestmark = pytest.mark.unit


class FakeClock:
    """可推进的单调钟。TTL 的断言不该真的睡 20 秒。"""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now += seconds


def _turn(kind: str, speaker: str = "teacher", text: str = "", **kwargs) -> scheduler.Turn:
    return scheduler.Turn(
        speaker_code=speaker, text=text or f"{kind} 说的话", kind=kind, **kwargs
    )


def test_priority_follows_the_documented_order():
    """五类发言的优先级就是 §2.2 那一行，大小关系不能乱。"""
    assert (
        scheduler.PRIORITY_BARGE
        > scheduler.PRIORITY_ANSWER
        > scheduler.PRIORITY_INTERJECT
        > scheduler.PRIORITY_DISCUSSION
        > scheduler.PRIORITY_LECTURE
    )


def test_only_one_speaker_at_a_time():
    """`next()` 不给第二条 —— 这就是「单写者」在代码里的样子（P3-A2）。"""
    queue = scheduler.SpeechScheduler()
    queue.enqueue(_turn("lecture"))
    queue.enqueue(_turn("interject", "xiaoxiao"))

    first = queue.next()
    assert first is not None
    assert queue.next() is None, "第一个人还在说，第二个不该开始"
    assert queue.speaking is True

    queue.finish(first.turn_id)
    assert queue.next() is not None


def test_higher_priority_jumps_the_queue():
    """后来的高优先级插到前面 —— 学生提问不该排在三十句讲稿后面。"""
    queue = scheduler.SpeechScheduler()
    queue.enqueue(_turn("lecture"))
    queue.enqueue(_turn("lecture"))
    queue.enqueue(_turn("barge", "u_1"))

    chosen = queue.next()

    assert chosen is not None and chosen.kind == "barge"


def test_same_priority_keeps_arrival_order():
    """同级按先来后到（FIFO）：讨论才有来有回，而不是最后一句抢在最前。"""
    queue = scheduler.SpeechScheduler()
    first = queue.enqueue(_turn("discussion", "xiaoxiao", text="第一句"))
    queue.enqueue(_turn("discussion", "chenmo", text="第二句"))

    chosen = queue.next()

    assert chosen is first


def test_barge_preempts_the_lecture():
    """学生举手：正在讲的被打断，排队的低优先级发言被丢掉（P3-A6）。"""
    queue = scheduler.SpeechScheduler()
    lecture = _turn("lecture")
    queue.begin(lecture)
    queue.enqueue(_turn("lecture"))
    queue.enqueue(_turn("discussion", "suyu"))

    result = queue.interrupt("barge")

    assert result["preempted"] is lecture
    assert result["dropped"], "排队的低优先级发言要一起清掉"
    assert queue.speaking is False


def test_barge_does_not_interrupt_the_teachers_answer():
    """§2.2 的原话：可抢占**除教师答疑外**的所有发言。

    老师正在回答另一个同学的问题，这时再打断，两个问题会一起烂掉。
    """
    queue = scheduler.SpeechScheduler()
    answer = _turn("answer")
    queue.begin(answer)

    result = queue.interrupt("barge")

    assert result["preempted"] is None
    assert queue.active is answer


def test_another_barge_does_not_preempt_a_pending_barge():
    """`barge` 自己也是受保护的：两个学生同时提问，先来的那个不该被顶掉。"""
    queue = scheduler.SpeechScheduler()
    first = _turn("barge", "u_1")
    queue.begin(first)

    result = queue.interrupt("barge")

    assert result["preempted"] is None
    assert queue.active is first


def test_preempted_turns_are_dropped_not_replayed():
    """被打断的发言**丢弃、不补播** —— 那句话的时机已经过去了。"""
    queue = scheduler.SpeechScheduler()
    queue.begin(_turn("lecture"))
    queue.enqueue(_turn("discussion", "suyu"))

    queue.interrupt("barge")

    assert queue.pending == ()
    assert queue.active is None


def test_queued_turns_expire_after_the_ttl():
    """排队超过 20 秒自己消失（§2.2 的 TTL）。

    没有这条，恢复播放时会一次性蹦出五条过期发言 —— 那是在补一段
    没人还记得的对话。
    """
    clock = FakeClock()
    queue = scheduler.SpeechScheduler(clock=clock)
    queue.enqueue(_turn("interject", "xiaoxiao"))

    clock.tick(21)

    assert queue.next() is None
    assert queue.pending == ()


def test_turn_survives_inside_the_ttl():
    """19 秒还在队里 —— TTL 是 20 秒，不是「等一会儿就清空」。"""
    clock = FakeClock()
    queue = scheduler.SpeechScheduler(clock=clock)
    queue.enqueue(_turn("interject", "xiaoxiao"))

    clock.tick(19)

    assert queue.next() is not None


def test_ttl_is_measured_from_enqueue_time():
    """一秒钟排一条，排四条 —— 第一条不该因为「队列里有四条」而被判超时。"""
    clock = FakeClock()
    queue = scheduler.SpeechScheduler(clock=clock)
    for _ in range(4):
        queue.enqueue(_turn("lecture"))
        clock.tick(1)

    assert len(queue.pending) == 4


def test_late_speak_end_does_not_cut_the_next_turn():
    """迟到的 `speak_end` 不该把下一段已经开始的话掐掉。

    前端上报「上一段播完了」有可能晚到（网络抖动），而那时下一段已经开口。
    """
    queue = scheduler.SpeechScheduler()
    queue.begin(_turn("lecture"))
    stale = queue.finish("t_不存在的")
    assert stale is None
    assert queue.speaking is True

    queue.finish()  # 不带 id：认当前这条
    assert queue.speaking is False


def test_queue_cap_drops_the_weakest():
    """队满时按优先级挤掉最不重要的那条 —— 不是无脑拒绝新来的。"""
    queue = scheduler.SpeechScheduler(max_pending=3)
    for _ in range(3):
        queue.enqueue(_turn("lecture"))

    kept = queue.enqueue(_turn("barge", "u_1"))

    assert kept is not None
    assert len(queue.pending) == 3
    assert any(turn.kind == "barge" for turn in queue.pending)


def test_queue_cap_rejects_an_equally_weak_newcomer():
    """队满且新来的同样不重要时，丢掉新来的并返回 None（调用方据此记日志）。"""
    queue = scheduler.SpeechScheduler(max_pending=2)
    queue.enqueue(_turn("lecture"))
    queue.enqueue(_turn("lecture"))

    assert queue.enqueue(_turn("lecture")) is None
    assert len(queue.pending) == 2


def test_clear_empties_everything():
    """下课/离开课堂时整堂课的发言都清掉，不留一条在内存里。"""
    queue = scheduler.SpeechScheduler()
    queue.begin(_turn("lecture"))
    queue.enqueue(_turn("discussion", "suyu"))

    queue.clear()

    assert queue.active is None and queue.pending == ()


def test_turn_payload_matches_the_speak_event():
    """`Turn.to_dict()` 就是 `speak` 事件的载荷（§4.2），字段名一个字都不能差。"""
    turn = _turn(
        "lecture",
        "shen",
        speaker_name="沈老师",
        speaker_kind="teacher",
        page_no=7,
        beat_ids=("p7-b1",),
        audio_url="/a.mp3",
    )

    payload = turn.to_dict()

    assert payload["speaker"] == {"code": "shen", "name": "沈老师"}
    assert payload["speakerKind"] == "teacher"
    assert payload["beats"] == ["p7-b1"]
    assert payload["pageNo"] == 7
    assert payload["priority"] == scheduler.PRIORITY_LECTURE
    assert payload["turnId"].startswith("t_")


def test_turn_ids_are_unique():
    """`turnId` 是前端的播放句柄：两条发言共用一个 id，`speak_end` 就认错了人。"""
    ids = {scheduler.Turn(speaker_code="shen", text="x").turn_id for _ in range(50)}
    assert len(ids) == 50


@pytest.mark.parametrize(
    ("level", "rounds", "seconds"),
    [("低", 1, 60.0), ("适中", 2, 90.0), ("高", 3, 120.0)],
)
def test_discussion_length_by_level(level: str, rounds: int, seconds: float):
    """讨论的轮数与总时长按「讨论激烈程度」映射（§2.2）。"""
    assert scheduler.rounds_for(level) == rounds
    assert scheduler.seconds_for(level) == seconds


@pytest.mark.parametrize("level", ["", "很激烈", None, "LOW"])
def test_unknown_level_falls_back_to_medium(level):
    """不认识的程度按「适中」—— 空值不该变成 0 轮（那等于不讨论）。"""
    assert scheduler.rounds_for(level or "") == 2
    assert scheduler.seconds_for(level or "") == 90.0
