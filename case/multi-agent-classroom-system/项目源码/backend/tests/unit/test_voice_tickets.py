"""会话票据（P2-F4）。

票据是「准不准开语音」的唯一凭证，所以这里盯的是它**什么时候必须失效**：

- 过期了还能用 → 一张票据留在浏览器历史里就是长期通行证；
- 用过还能再用 → 抄走一次等于永久可用；
- 谁的票都能验过 → 票据就完全没意义了（它至少要认归属人，P2-F5 按人算名额）。

认不出来时**必须抛异常**（而不是返回一个空归属人）：「没带票」和「带了一张
无效票」要落进同一条拒绝路径，任何一种变成放行都是这条防线上的洞。
"""

from __future__ import annotations

import pytest

from app.common.errors import UnauthorizedError
from app.services.voice import tickets

pytestmark = pytest.mark.unit


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def clean():
    """票据是模块级状态：不清的话上一个用例的票会活到下一个用例里。"""
    tickets.clear()
    yield
    tickets.clear()


def test_a_ticket_can_be_used_exactly_once():
    clock = FakeClock()
    ticket = tickets.issue("user_demo_teacher", clock=clock)["ticket"]

    assert tickets.consume(ticket, clock=clock) == "user_demo_teacher"
    with pytest.raises(UnauthorizedError):
        tickets.consume(ticket, clock=clock)


def test_a_ticket_expires():
    clock = FakeClock()
    ticket = tickets.issue("u1", ttl=60, clock=clock)["ticket"]

    clock.now += 60  # 到期那一刻就不算数（`<=` 而不是 `<`）
    with pytest.raises(UnauthorizedError):
        tickets.consume(ticket, clock=clock)


def test_a_ticket_still_works_just_before_it_expires():
    clock = FakeClock()
    ticket = tickets.issue("u1", ttl=60, clock=clock)["ticket"]

    clock.now += 59.9
    assert tickets.consume(ticket, clock=clock) == "u1"


def test_an_unknown_or_empty_ticket_is_rejected():
    for value in ("", "   ", "not-a-ticket"):
        with pytest.raises(UnauthorizedError):
            tickets.consume(value)


def test_the_answer_carries_the_fallback_the_client_needs():
    """P2-B2：拒绝也要告诉前端退到哪条路 —— 这条路上能退的只有文字。"""
    clock = FakeClock()
    ticket = tickets.issue("u1", clock=clock)["ticket"]
    tickets.consume(ticket, clock=clock)

    with pytest.raises(UnauthorizedError) as caught:
        tickets.consume(ticket, clock=clock)

    assert caught.value.http_status == 401
    assert caught.value.details["fallback"] == "text"


def test_tickets_of_different_people_do_not_mix():
    clock = FakeClock()
    mine = tickets.issue("owner_a", clock=clock)["ticket"]
    yours = tickets.issue("owner_b", clock=clock)["ticket"]

    assert tickets.consume(yours, clock=clock) == "owner_b"
    assert tickets.consume(mine, clock=clock) == "owner_a"


def test_tickets_are_unguessable_and_unique():
    values = {tickets.issue("u1")["ticket"] for _ in range(50)}

    assert len(values) == 50
    assert all(len(value) >= 32 for value in values)


def test_expired_tickets_do_not_pile_up():
    """过期的票据在下次读写时被顺手捞掉：内存不该随次数无限涨。"""
    clock = FakeClock()
    for _ in range(10):
        tickets.issue("u1", ttl=1, clock=clock)
    assert tickets.live_count(clock=clock) == 10

    clock.now += 5
    assert tickets.live_count(clock=clock) == 0


# --- 用途（P3-F1）---


def test_a_scoped_ticket_only_opens_its_own_room():
    """为 A 课签的票接不进 B 课 —— 改一个 URL 就换个课堂是不行的。"""
    clock = FakeClock()
    ticket = tickets.issue("u1", clock=clock, scope="sess_a")["ticket"]

    assert tickets.consume(ticket, clock=clock, scope="sess_a") == "u1"

    other = tickets.issue("u1", clock=clock, scope="sess_a")["ticket"]
    with pytest.raises(UnauthorizedError):
        tickets.consume(other, clock=clock, scope="sess_b")


def test_a_scoped_ticket_is_not_interchangeable_with_an_unscoped_one():
    """语音的票（无用途）换不到课堂里去，反之亦然。一张票只对签发它的那条路有效。"""
    clock = FakeClock()
    plain = tickets.issue("u1", clock=clock)["ticket"]
    classroom = tickets.issue("u1", clock=clock, scope="sess_a")["ticket"]

    with pytest.raises(UnauthorizedError):
        tickets.consume(plain, clock=clock, scope="sess_a")
    with pytest.raises(UnauthorizedError):
        tickets.consume(classroom, clock=clock)


def test_scope_mismatch_burns_the_ticket_anyway():
    """用错了地方也算用掉：留着它等下一次「万一对了」是没必要的余地。"""
    clock = FakeClock()
    ticket = tickets.issue("u1", clock=clock, scope="sess_a")["ticket"]

    with pytest.raises(UnauthorizedError):
        tickets.consume(ticket, clock=clock, scope="sess_b")
    with pytest.raises(UnauthorizedError):
        tickets.consume(ticket, clock=clock, scope="sess_a")
