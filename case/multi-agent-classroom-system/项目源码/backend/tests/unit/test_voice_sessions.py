"""单用户语音会话并发上限（P2-F5）。

「一个人同时只能有一条会话」这条规则有两种坏法，都不是报错，而是**用不了**：

- 该拦的没拦 → 两条会话同时响，学生听到两个老师在说话；
- 不该拦的拦了 → 一次异常之后名额一直占着，那个人的语音从此打不开，
  而症状是「昨天还好好的」。所以这里除了「第二条被拒」，
  还盯死了两条**必然要放行**的路：同一条会话重复 start，以及超时后的接手。
"""

from __future__ import annotations

import pytest

from app.services.voice import sessions

pytestmark = pytest.mark.unit


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def clean():
    sessions.clear()
    yield
    sessions.clear()


def test_the_second_session_of_the_same_person_is_refused():
    clock = FakeClock()

    assert sessions.claim("u1", "s_1", clock=clock) is True
    assert sessions.claim("u1", "s_2", clock=clock) is False
    assert sessions.holder("u1") == "s_1"


def test_other_people_are_not_affected():
    clock = FakeClock()
    sessions.claim("u1", "s_1", clock=clock)

    assert sessions.claim("u2", "s_2", clock=clock) is True


def test_releasing_lets_the_next_session_in():
    clock = FakeClock()
    sessions.claim("u1", "s_1", clock=clock)

    sessions.release("u1", "s_1")

    assert sessions.holder("u1") == ""
    assert sessions.claim("u1", "s_2", clock=clock) is True


def test_the_same_slot_can_claim_again():
    """同一条通道再走一遍 `start`：认成同一次会话，不把自己锁在门外。"""
    clock = FakeClock()
    sessions.claim("u1", "slot_1", clock=clock)

    assert sessions.claim("u1", "slot_1", clock=clock) is True


def test_a_late_release_does_not_free_someone_elses_slot():
    """晚到的收尾不能撤掉接手者的名额 —— 撤了的话两个人就都能开，上限等于没有。"""
    clock = FakeClock()
    sessions.claim("u1", "s_1", clock=clock)
    clock.now += 700  # 超时，s_2 接手
    assert sessions.claim("u1", "s_2", clock=clock) is True

    sessions.release("u1", "s_1")

    assert sessions.holder("u1") == "s_2"
    assert sessions.claim("u1", "s_3", clock=clock) is False


def test_a_stale_slot_is_taken_over():
    """进程被杀 / close() 抛异常时名额会漏，超时是最后一道兜底。"""
    clock = FakeClock()
    sessions.claim("u1", "s_1", ttl=600, clock=clock)

    clock.now += 601

    assert sessions.claim("u1", "s_2", clock=clock) is True
    assert sessions.holder("u1") == "s_2"


def test_without_an_owner_nothing_is_blocked():
    """没有归属人就无从判「同一个人」，宁可放行 —— 挡错了是一整个功能不可用。"""
    clock = FakeClock()

    assert sessions.claim("", "s_1", clock=clock) is True
    assert sessions.claim("", "s_2", clock=clock) is True
