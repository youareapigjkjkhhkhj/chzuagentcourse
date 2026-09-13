"""P3-B1 课堂推送契约：§4.2 的全部上下行 + 三条异常分支。

**打在这一层，不是打在 WS 路由上**：Flask 的测试客户端做不了 WebSocket 升级
（P2 §4.2 的同一条限制）。所以连接层只认一个三方法的 `Transport` 协议
（`receive` / `send` / `close`），这里用一只假的浏览器驱动它；真路由那一头
只剩 `Server.accept()` 与转发。

三件事在这里被钉死，它们都是**前端会直接看到**的东西：

1. **入场**：票据认人（P3-F1）—— 为别的课签的票、已经用过的票、这堂课不该
   他看的票，一律 4403；没带票的连接先发 `hello` 再说（不然它不知道自己是谁）。
2. **心跳与在线**：20s 一次 `ping`，60s 没动静就摘掉这个人的在线（P3-B5），
   而同一个人的另一个标签页还开着的时候**不能**摘（P3-A12：数的是人）。
3. **收尾**：下课先补完留档再关（前端要看到最后那条 `state.status=ended`），
   关的时候按理由给关闭码。

第 4 组是路由那半边：票据不对、这堂课不给他看、推送开关关着 —— 这三条都在
`accept()` **之前**判掉，所以它们能用一个普通的测试客户端验到（客户端连
101 都拿不到，拿到的是错误信封）。

时间全在手里：`Clock` 是假的，`FakeTransport` 每空转一拍就让世界过去
`seconds_per_idle` 秒 —— 「20 秒后打心跳」「60 秒后判死」因此不用真的等。
"""

from __future__ import annotations

import json
from collections import deque

import pytest

from app.extensions import db
from app.models import AgentRole, ClassroomSession, Course, CoursePage, User
from app.services.classroom import channel as channel_module
from app.services.classroom import recorder, sessions, state
from app.services.classroom.channel import (
    CLOSE_FORBIDDEN,
    CLOSE_NORMAL,
    CLOSE_TIMEOUT,
    CLOSE_TOO_MANY,
    ChannelClosed,
    ClassroomChannel,
    ConnectionRegistry,
)
from app.services.classroom.runtime import PeerGone
from app.services.voice import tickets

pytestmark = pytest.mark.contract

#: 课堂里的两个人（必须是真用户行：参与者的 `user_id` 是外键）。
ME = "u1"
GUEST = "u2"

#: 第 4 组要用它把测试客户端伪装成一次 WebSocket 升级。
#:
#: 不带的后果是**视图压根不会被调用**：werkzeug 匹配到 `websocket=True` 的规则
#: 却收到普通 GET 时抛 `WebsocketMismatch`，测试客户端看到的是 400 —— 而它验的
#: 本该是「票据在 `accept()` 之前被核销」，那时连路由都没进去，等于没测。
#: 判据在 `MapAdapter.websocket`：它看 scheme，而 `bind_to_environ` 见到
#: `Upgrade: websocket` 就把 scheme 改成 ws。`base_url="ws://localhost"` 是
#: 同一个效果的另一写法，但这样一来整条请求都变了，不如只加两个头直白。
WS_UPGRADE = {"Upgrade": "websocket", "Connection": "Upgrade"}


@pytest.fixture()
def app(app_factory):
    """一台刚部署好的机器 + 两个用户 + 一位老师（模型走离线桩）。"""
    application = app_factory(env={"LLM_PROVIDER": "mock"})
    with application.app_context():
        db.session.add_all(
            [
                User(id=ME, name="小明", role="student"),
                User(id=GUEST, name="小红", role="student"),
                AgentRole(
                    code="shen",
                    name="沈老师",
                    role="teacher",
                    persona={"style": "沉稳", "systemHint": "你是主讲老师，负责讲解。"},
                    sort_order=1,
                ),
            ]
        )
        db.session.commit()
        tickets.clear()
        channel_module.connections.clear()
    return application


class Clock:
    """假单调钟：心跳与判死要验的是「过去了多久」，不必真的等。"""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = float(now)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class FakeTransport:
    """一只假的浏览器：能收、能发、能被关掉。

    **空转一拍就让世界过去一段时间**（`seconds_per_idle`），心跳与判死因此
    是在一个能被推着走的时钟上验的；`idle_limit` 之后主动断线，则是因为
    真的 `receive(timeout)` 会阻塞到超时，假的要是永远返回 None，
    `run()` 的循环就成了死循环（P2 的假浏览器同一条理由）。
    """

    def __init__(
        self,
        inbox: list | None = None,
        *,
        clock: Clock | None = None,
        seconds_per_idle: float = 0.0,
        idle_limit: int | None = 3,
    ) -> None:
        self.inbox = deque(inbox or [])
        self.sent: list[dict] = []
        self.clock = clock
        self.seconds_per_idle = seconds_per_idle
        self.idle_limit = idle_limit
        self._idle = 0
        #: `(code, reason)`，没关过就是 None
        self.closed: tuple[int, str] | None = None
        self.close_count = 0
        self.hangup = False
        self.fail_send = False

    def receive(self, timeout: float):
        if self.inbox:
            self._idle = 0
            return self.inbox.popleft()
        self._idle += 1
        if self.clock is not None:
            self.clock.advance(self.seconds_per_idle)
        if self.hangup or (self.idle_limit is not None and self._idle > self.idle_limit):
            self.hangup = True
            raise ChannelClosed("学生关掉了页面")
        return None

    def send(self, data: str | bytes) -> None:
        if self.fail_send:
            raise ChannelClosed("对端已经断了")
        payload = json.loads(data)
        self.sent.append(payload)

    def close(self, code: int, reason: str) -> None:
        self.close_count += 1
        if self.closed is None:
            self.closed = (int(code), str(reason))

    # --- 断言用 ---

    @property
    def types(self) -> list[str]:
        return [item["type"] for item in self.sent]

    def of(self, kind: str) -> list[dict]:
        return [item for item in self.sent if item["type"] == kind]

    def last(self, kind: str) -> dict | None:
        found = self.of(kind)
        return found[-1] if found else None

    def say(self, **payload) -> None:
        """往收件箱里塞一条上行（下一条 `receive` 会拿到它）。"""
        self.inbox.append(json.dumps(payload, ensure_ascii=False))


# --- 布景 ---


def _course(pages: list[dict]) -> Course:
    """按页描述建一门 ready 的课（与 `test_classroom_runtime._course` 同一套口径）。"""
    course = Course(
        title="机器学习入门", topic="机器学习入门", status="ready", dsl={"chapters": []}
    )
    db.session.add(course)
    db.session.commit()
    for index, spec in enumerate(pages, start=1):
        beats = tuple(spec.get("beats") or ("第一句讲稿。", "第二句讲稿。"))
        dsl = {
            "pageNo": index,
            "kind": spec.get("kind", "example"),
            "title": f"第 {index} 页",
            "bullets": [{"text": "本页要点"}],
            "narration": [
                {"beatId": f"p{index}-b{number}", "text": text, "estSec": 4}
                for number, text in enumerate(beats, start=1)
            ],
        }
        db.session.add(
            CoursePage(
                course_id=course.id,
                page_no=index,
                chapter_no=1,
                kind=dsl["kind"],
                title=dsl["title"],
                status="ready",
                dsl=dsl,
            )
        )
    db.session.commit()
    return course


def _session(pages: list[dict] | None = None, *, owner: str = ME) -> ClassroomSession:
    return sessions.start(_course(pages or [{}, {}]), owner)


def _open(
    session: ClassroomSession,
    transport: FakeTransport,
    *,
    user_id: str | None = ME,
    registry: ConnectionRegistry | None = None,
    **kwargs,
) -> ClassroomChannel:
    """建一条连接并接上（对应路由的 `accept()` + `channel.run()` 的第一步）。"""
    channel = ClassroomChannel(
        session,
        owner_id=user_id,
        clock=transport.clock,
        registry=registry,
        **kwargs,
    )
    assert channel.attach(transport) is True
    return channel


def _drive(channel: ClassroomChannel, transport: FakeTransport, *, steps: int = 200) -> None:
    """把这条连接跑到底（直到对端断线、判死或下课）。

    等价于路由里的 `channel.run()` —— 只是**拍**由测试数，好在断言里说
    「世界过去了多久」。收尾那一步（对端断开 → 收摊）也照 `run()` 补上。
    """
    done = False
    try:
        for _ in range(steps):
            if not channel.step():
                done = True
                break
    except (ChannelClosed, PeerGone):
        done = True
        channel.close(reason="transport_closed")
    assert done, "连接没有在限定拍数内结束"


def _settle(channel: ClassroomChannel, transport: FakeTransport, *, steps: int = 2) -> None:
    """走几拍让入场的那几条落到连接上（`hello` 是**收**到的，不是送进去的）。"""
    for _ in range(steps):
        assert channel.step() is True


def _enter(transport: FakeTransport, **extra) -> None:
    transport.say(type="hello", **extra)


# --- 1. 入场（P3-F1）---


def test_a_valid_ticket_lets_me_in_and_i_see_the_classroom(app):
    """一张为这堂课签的票接进来：先是状态与在线名单，然后才是课本身。"""
    with app.app_context():
        session = _session()
        clock = Clock()
        transport = FakeTransport(clock=clock)
        ticket = sessions.ws_ticket(session, ME)
        _enter(transport, token=ticket["ticket"])
        channel = _open(session, transport, user_id=None)

        _settle(channel, transport)

        assert channel.entered is True
        # 进课堂该看到的东西：在线名单、状态、字幕（§4.2 的三条下行）
        assert {"presence", "state", "subtitle"} <= set(transport.types)
        assert transport.last("presence")["online"] == 1
        assert transport.last("state")["status"] == state.IDLE
        assert recorder.presence(session.id)["online"] == 1

        # 走到底（学生关掉页面）：这个人立刻从在线名单里出去（P3-B5）
        _drive(channel, transport)
        assert recorder.presence(session.id)["online"] == 0


def test_a_token_for_another_class_is_refused_with_4403(app):
    """为 A 课签的票接不进 B 课（P3-F1 的原话）。"""
    with app.app_context():
        first = _session()
        second = _session()
        clock = Clock()
        transport = FakeTransport(clock=clock)
        stolen = sessions.ws_ticket(first, ME)
        _enter(transport, token=stolen["ticket"])
        channel = _open(second, transport, user_id=None)

        _drive(channel, transport)

        assert channel.entered is False
        assert channel.runtime is None
        assert transport.closed is not None and transport.closed[0] == CLOSE_FORBIDDEN
        error = transport.last("error")
        assert error is not None and error["code"] == "40101"
        # 越权的连接不该在任何人眼里出现
        assert recorder.presence(second.id)["online"] == 0


def test_a_ticket_can_only_be_used_once(app):
    """票据是一次性的：同一张票接第二次是 4403。"""
    with app.app_context():
        session = _session()
        ticket = sessions.ws_ticket(session, ME)

        first = FakeTransport(clock=Clock())
        _enter(first, token=ticket["ticket"])
        _drive(_open(session, first, user_id=None), first)
        assert first.last("presence") is not None

        second = FakeTransport(clock=Clock())
        _enter(second, token=ticket["ticket"])
        _drive(_open(session, second, user_id=None), second)

        assert second.closed is not None and second.closed[0] == CLOSE_FORBIDDEN


def test_a_ticket_for_someone_who_cannot_see_the_class_is_refused(app):
    """**伪造出来的票**也一样挡得住：这张票的归属人不是这堂课的人。

    `sessions.ws_ticket` 不会给外人签票（签之前先判可见性），所以这里直接
    找票据服务要一张 —— 模拟「票据泄露 / 伪造」那种越权（P3-F1 要挡的正是它）。
    """
    with app.app_context():
        session = _session(owner=ME)
        clock = Clock()
        transport = FakeTransport(clock=clock)
        forged = tickets.issue(GUEST, scope=session.id)
        _enter(transport, token=forged["ticket"])
        channel = _open(session, transport, user_id=None)

        _drive(channel, transport)

        assert transport.closed is not None and transport.closed[0] == CLOSE_FORBIDDEN
        assert recorder.presence(session.id)["online"] == 0


def test_the_first_frame_must_be_hello(app):
    """还没 `hello` 的连接不知道自己是谁，所以它什么都做不了。"""
    with app.app_context():
        session = _session()
        transport = FakeTransport(clock=Clock())
        transport.say(type="play")  # 早到的一帧：那时它还没认人
        _enter(transport)
        channel = _open(session, transport)

        _settle(channel, transport, steps=3)

        errors = [item["code"] for item in transport.of("error")]
        assert errors[0] == "not_entered"
        # 报完错照常进课堂：一条早到的 `play` 不该把整条连接废掉
        assert channel.entered is True
        # 但那一帧**被丢掉了**（它还说不清是谁要开讲）：课还停在 idle
        assert transport.last("state")["status"] == state.IDLE

        # 认完人再发一次就作数
        transport.say(type="play")
        _settle(channel, transport)
        assert transport.last("state")["status"] == state.LECTURE
        _drive(channel, transport)


def test_a_connection_over_the_limit_is_refused_with_4429(app):
    """单会话连接数上限（P3-F5）：到顶的连接进不来，而且不占在线数。"""
    with app.app_context():
        session = _session()
        registry = ConnectionRegistry()
        registry.attach(session.id, "elsewhere", GUEST, limit=0)

        transport = FakeTransport(clock=Clock())
        _enter(transport)
        channel = ClassroomChannel(
            session, owner_id=ME, clock=transport.clock, registry=registry, max_connections=1
        )

        assert channel.attach(transport) is False
        channel.run(transport)  # run 也要能安全地什么都不做

        assert transport.closed is not None and transport.closed[0] == CLOSE_TOO_MANY
        assert transport.last("error")["code"] == "too_many_connections"
        assert registry.count(session.id) == 1


def test_the_slot_is_released_when_the_connection_ends(app):
    """收摊要把连接位还回去，否则这堂课的名额会越用越少。"""
    with app.app_context():
        session = _session()
        registry = ConnectionRegistry()
        transport = FakeTransport(clock=Clock())
        _enter(transport)
        channel = _open(session, transport, registry=registry, max_connections=1)
        _drive(channel, transport)

        assert registry.count(session.id) == 0

        again = FakeTransport(clock=Clock())
        _enter(again)
        second = _open(session, again, registry=registry, max_connections=1)
        _drive(second, again)
        assert second.entered is True


# --- 2. 交付（§4.2 / P3-B2）---


def test_events_reach_the_socket_in_order_and_without_gaps(app):
    """下行的每一条都带单调的 `seq`，而且和留档里的一模一样。"""
    with app.app_context():
        session = _session()
        transport = FakeTransport(clock=Clock())
        _enter(transport)
        transport.say(type="play")
        transport.say(type="beat_done")
        transport.say(type="pause")
        channel = _open(session, transport)

        _drive(channel, transport)

        seqs = [item["seq"] for item in transport.sent if "seq" in item]
        assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))
        assert {"state", "typing", "speak", "message", "subtitle"} <= set(transport.types)
        # 发出去的就是存下来的：断线补发拿到的会是同一份 dict
        recorded = [row["seq"] for row in recorder.replay(session.id, 0)]
        assert seqs == recorded[: len(seqs)]


def test_reconnecting_resumes_from_where_i_left_off(app):
    """断线重连：`resumeFrom` 之后的事件补齐，且不重发已经收到的。"""
    with app.app_context():
        session = _session([{}, {}, {}])
        first = FakeTransport(clock=Clock())
        _enter(first)
        first.say(type="play")
        channel = _open(session, first)
        _drive(channel, first)

        seen = [item["seq"] for item in first.sent if "seq" in item]
        # 断线的位置就是**第一条连接收到的最大 seq**：学生拿它去重连
        missed_after = max(seen)

        # 断线期间课还在上（HTTP 那一侧改了东西），留档里多了几条
        state.progress(session, sessions.timeline_of(session), page_no=2, beat_idx=0)
        recorder.publish(session, "presence", recorder.presence(session.id))

        second = FakeTransport(clock=Clock())
        _enter(second, afterSeq=missed_after)
        resumed = _open(session, second)
        _drive(resumed, second)

        replayed = [item["seq"] for item in second.sent if "seq" in item]
        # 只补漏掉的：从断点之后的下一条开始，连着来
        assert replayed and replayed[0] == missed_after + 1
        assert replayed == [item for item in replayed if item > missed_after]
        assert replayed == list(range(missed_after + 1, replayed[-1] + 1))
        # 已经收到过的（`seen`）一条都没有再来一遍
        assert not (set(seen) & set(replayed))


def test_reconnecting_mid_lecture_gets_the_line_again(app):
    """断线重连时，正在讲的那一句要**重开一轮** —— 不然整堂课停在原地。

    时间线只由客户端的 `beat_done` 推进，而客户端要有这一句的 `speak` 才会
    播完上报。刷新之后进来的那条连接手上没有这一条（它落在断点之前，
    补发够不着），于是没人上报；服务端这边状态、字幕、板书都对，
    就是再也不往前走 —— 这是最难看的一种坏：界面看起来一切正常。
    """
    with app.app_context():
        session = _session()
        first = FakeTransport(clock=Clock())
        _enter(first)
        first.say(type="play")
        channel = _open(session, first)
        _drive(channel, first)

        # 断线之前老师正在念第 1 页第 1 句
        assert session.status == state.LECTURE
        assert int(session.current_beat_idx or 0) == 0
        before = [item for item in first.of("speak") if item["kind"] == "lecture"]
        assert before, "第一句讲稿没发出去，后面的断言无从谈起"
        # `_drive` 跑到底就是「对端断线」：这一断，**运行时跟着一起没了**
        # （运行时是每条连接一个），正在讲的那一轮也一起 `scheduler.clear()` 掉，
        # **不发收尾** —— 留档里于是留下了一轮只有 `speak` 没有 `speak_end` 的
        # 「孤儿轮次」（§10.2）。
        assert first.of("speak_end") == [], "断线不该替那一轮收尾：它已经没人可收了"

        # 第二条连接（刷新/换标签）：`idle_limit=None` —— 它要活到断言做完，
        # 不能被假浏览器的「空转三拍就断线」rule 提前收掉（那样下面那条
        # `beat_done` 会落进一条已经关掉的通道，位置一动不动，看着像产品坏了）。
        second = FakeTransport(clock=Clock(), idle_limit=None)
        _enter(second, afterSeq=max(item["seq"] for item in first.sent if "seq" in item))
        resumed = _open(session, second)
        _settle(resumed, second, steps=6)

        # 1) 这一句重开了一轮：新连接拿到的是一条新的 lecture speak
        again = [item for item in second.of("speak") if item["kind"] == "lecture"]
        assert again, "重连之后没有把当前这一句再讲一遍：客户端等不来 beat_done 的由头"
        assert again[-1]["pageNo"] == 1
        assert again[-1]["turnId"] != before[-1]["turnId"], "重开的是同一轮，客户端会把它当成听过的"

        # 2) 新连接上**没有**替别人那一轮收尾的 `speak_end`。
        #    **运行时是每条连接一个**（`channel._enter` 里新建），上一轮活在旧连接的
        #    运行时里，那条连接一关就跟着没了 —— 新运行时是空的，
        #    `hello` 里的那次 `_interrupt` 没有东西可掐。真发过来才是坏事：
        #    客户端会把一条自己没听过的讲稿报成「播完了」，时间线于是空走一格。
        assert second.of("speak_end") == []

        # 3) 于是课还能往前走：报一条 beat_done，位置真的动了
        second.say(type="beat_done")
        _settle(resumed, second, steps=4)
        assert int(session.current_beat_idx or 0) == 1


def test_a_brand_new_connection_is_not_flooded_with_history(app):
    """新连接不该收到整堂课的旧事件 —— 历史走 `GET /messages`（§4.2 契约要点）。"""
    with app.app_context():
        session = _session()
        for _ in range(4):
            recorder.publish(session, "subtitle", {"beatId": "b", "text": "旧字幕", "pageNo": 1})

        transport = FakeTransport(clock=Clock())
        _enter(transport)
        channel = _open(session, transport)
        _drive(channel, transport)

        assert channel.entered is True
        assert [item for item in transport.of("subtitle") if item.get("text") == "旧字幕"] == []


def test_a_private_error_is_not_written_into_the_log(app):
    """`error` 只回发信人：不落库、不带 `seq`（带了客户端的游标就对不上账）。"""
    with app.app_context():
        session = _session()
        transport = FakeTransport(clock=Clock())
        _enter(transport)
        transport.say(type="seek", pageNo=99)  # 这门课没有第 99 页
        channel = _open(session, transport)

        _settle(channel, transport)

        error = transport.last("error")
        assert error is not None and "seq" not in error
        assert [row for row in recorder.replay(session.id, 0) if row["type"] == "error"] == []
        # 报错归报错，这条连接照旧在课堂上（它不是失败，只是这一条没成）
        assert channel.runtime is not None and channel.runtime.alive
        _drive(channel, transport)


# --- 3. 心跳、判死与在线（P3-B5 / P3-A12）---


def test_a_quiet_client_gets_a_ping_after_the_heartbeat(app):
    """20s 打一次心跳（§4.2）。`pong` 只是最常见的那种上行，任何上行都算活着。"""
    with app.app_context():
        session = _session()
        clock = Clock()
        transport = FakeTransport(clock=clock, seconds_per_idle=1.0, idle_limit=120)
        _enter(transport)
        channel = _open(session, transport, heartbeat=20.0, timeout=60.0)

        # 只在**看到新心跳**时才回一条：每拍都塞一条的话收件箱永远非空，
        # 收件箱非空世界就不往前走（假钟只在空转时前进），20s 永远也到不了
        answered = 0
        for _ in range(25):
            if len(transport.of("ping")) > answered:
                answered += 1
                transport.say(type="pong")
            assert channel.step() is True
            if transport.of("ping"):
                break

        assert len(transport.of("ping")) == 1
        assert channel.closed is False


def test_a_client_that_never_answers_is_dropped_from_the_room(app):
    """60s 没动静就摘掉（P3-B5）—— 而且不留幽灵在线。"""
    with app.app_context():
        session = _session()
        clock = Clock()
        transport = FakeTransport(clock=clock, seconds_per_idle=1.0, idle_limit=None)
        _enter(transport)
        channel = _open(session, transport, heartbeat=20.0, timeout=60.0)
        assert recorder.presence(session.id)["online"] == 1

        _drive(channel, transport, steps=200)

        assert transport.closed is not None and transport.closed[0] == CLOSE_TIMEOUT
        assert transport.last("error")["code"] == "timeout"
        # 心跳发过好几次，但一条 pong 都没有 ⇒ 到期摘人
        assert len(transport.of("ping")) >= 2
        assert recorder.presence(session.id)["online"] == 0


def test_answering_the_ping_keeps_me_in_the_class(app):
    """回了 `pong` 就一直在线：安静听课的学生不该被摘掉。"""
    with app.app_context():
        session = _session()
        clock = Clock()
        transport = FakeTransport(clock=clock, seconds_per_idle=1.0, idle_limit=None)
        _enter(transport)
        channel = _open(session, transport, heartbeat=20.0, timeout=60.0)

        answered = 0
        for _ in range(300):
            if len(transport.of("ping")) > answered:
                answered += 1
                transport.say(type="pong")  # 每条心跳回一条 —— 前端就这一件事
            assert channel.step() is True

        assert answered >= 2
        assert clock.now > 60  # 世界已经过去了一分多钟
        assert channel.closed is False
        assert recorder.presence(session.id)["online"] == 1


def test_a_dead_socket_takes_the_person_out_of_the_room(app):
    """对端断开（关标签页、拔网线）：这条连接立刻从在线名单里消失。"""
    with app.app_context():
        session = _session()
        transport = FakeTransport(clock=Clock(), idle_limit=1)
        _enter(transport)
        channel = _open(session, transport)
        _settle(channel, transport)
        assert recorder.presence(session.id)["online"] == 1

        channel.run(transport)

        assert channel.closed is True
        assert recorder.presence(session.id)["online"] == 0
        assert channel_module.connections.count(session.id) == 0


def test_closing_one_tab_keeps_the_person_online_in_the_other(app):
    """P3-A12：「在线」数的是**人**。关掉一个标签页，另一个还开着就还在线。"""
    with app.app_context():
        session = _session()
        first = FakeTransport(clock=Clock(), idle_limit=1)
        _enter(first)
        one = _open(session, first)
        _settle(one, first)
        second = FakeTransport(clock=Clock(), idle_limit=1)
        _enter(second)
        two = _open(session, second)
        _settle(two, second)
        assert recorder.presence(session.id)["online"] == 1

        one.run(first)  # 关掉第一个标签页

        assert two.closed is False
        assert recorder.presence(session.id)["online"] == 1

        two.run(second)

        assert recorder.presence(session.id)["online"] == 0


# --- 4. 收尾 ---


def test_the_class_ends_before_the_socket_closes(app):
    """下课：把留档里最后几条发完再关 —— 顺序反了，前端最后看到的是「断了」。"""
    with app.app_context():
        session = _session([{"beats": ("就这一句。",)}])
        transport = FakeTransport(clock=Clock())
        _enter(transport)
        transport.say(type="play")
        transport.say(type="beat_done")
        channel = _open(session, transport)

        _drive(channel, transport)

        assert transport.last("state")["status"] == state.ENDED
        assert transport.closed is not None and transport.closed[0] == CLOSE_NORMAL
        assert transport.close_count == 1
        assert session.status == state.ENDED


def test_a_broken_socket_does_not_escape_the_connection(app):
    """写帧时对端没了：收摊收干净，异常不外抛（WSGI 线程的最外层）。"""
    with app.app_context():
        session = _session()
        transport = FakeTransport(clock=Clock())
        _enter(transport)
        channel = _open(session, transport)
        transport.fail_send = True

        channel.run(transport)  # 不抛异常就是这条断言

        assert channel.closed is True
        assert channel_module.connections.count(session.id) == 0
        assert recorder.presence(session.id)["online"] == 0


# --- 5. 路由那半边（握手之前就能判掉的四种）---


def test_the_route_refuses_a_bad_ticket_before_the_handshake(app, client):
    """票据不对：走普通的错误信封，浏览器连 101 都拿不到（P2 路由的同一条经验）。"""
    with app.app_context():
        session = _session()

        response = client.get(
            f"/ws/classroom/{session.id}?ticket=nonsense", headers=WS_UPGRADE
        )

        assert response.status_code == 401
        assert response.get_json()["code"] == 40101
        # 退到哪条路由**这条路**说了算：课堂退到逐页手动翻页（P3-G3），
        # 而不是语音那句 `text`（票据是两条路共用的一个服务，退路不是）
        assert response.get_json()["data"]["details"]["fallback"] == "manual"


def test_the_route_refuses_a_ticket_signed_for_another_class(app, client):
    """为 A 课签的票接不进 B 课（P3-F1 的原话），走 URL 这条入口也一样。"""
    with app.app_context():
        mine = _session(owner=ME)
        theirs = _session(owner=GUEST)
        ticket = sessions.ws_ticket(mine, ME)

        response = client.get(
            f"/ws/classroom/{theirs.id}?ticket={ticket['ticket']}", headers=WS_UPGRADE
        )

        # 用途对不上与票不对是同一句话（票据服务只给一个分支）：连「我是谁」
        # 都没认出来，就谈不上可不可见
        assert response.status_code == 401
        assert response.get_json()["code"] == 40101


def test_the_route_hides_a_class_i_cannot_see(app, client):
    """票认得出来人、但这堂课不该给他看：404，与记录页同一个口径（P3-F4）。

    `sessions.ws_ticket` 不会给外人签票（签之前先判可见性），所以这里直接找
    票据服务要一张 —— 模拟票据泄露之后被拿来接别人的课（P3-F1 要挡的正是它）。
    """
    with app.app_context():
        session = _session(owner=ME)
        leaked = tickets.issue(GUEST, scope=session.id)

        response = client.get(
            f"/ws/classroom/{session.id}?ticket={leaked['ticket']}", headers=WS_UPGRADE
        )

        assert response.status_code == 404


def test_the_route_says_so_when_the_push_channel_is_off(app, client):
    """`CLASSROOM_WS=false`：说清退到哪条路，而不是白屏（P3-G3）。"""
    with app.app_context():
        session = _session()
    app.config["CLASSROOM_WS"] = False
    with app.app_context():
        response = client.get(f"/ws/classroom/{session.id}", headers=WS_UPGRADE)

    assert response.status_code == 403
    # 平铺的 `ok/error/fallback`（与语音的 40302 同一个形状）：前端一段代码处理两种「能力没了」
    body = response.get_json()["data"]
    assert body["error"] == "ws_disabled"
    assert body["fallback"] == "manual"


def test_the_route_says_when_the_class_does_not_exist(app, client):
    """没有这堂课就是 404 —— 与有没有票据无关（它本来就只是「这个 id 不存在」）。"""
    with app.app_context():
        response = client.get("/ws/classroom/cs_nope", headers=WS_UPGRADE)

    assert response.status_code == 404
