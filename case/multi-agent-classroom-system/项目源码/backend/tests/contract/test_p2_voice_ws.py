"""P2-B1 实时语音契约：`start → ready → audio/reply → done` 全序列。

**打在这一层，不是打在 WS 路由上**：Flask 的测试客户端做不了 WebSocket 升级
（§4.2 那条路径只能靠真浏览器验）。在测试里起一个真端口再拉一个真 WebSocket
客户端，等于给这条契约加一个「端口绑不绑得上」的额外失败面，而它要验的
是协议本身。所以语义层 `RealtimeChannel` 是传输无关的，路由那一层只剩
`Server.accept()` 与两个转发（见 `app/api/voice.py`）。

三件事在这里被钉死，它们都是**前端会直接看到**的东西：

1. **下行只出现我们自己的词**（§4.2 的 `DOWN_TYPES`）—— 上游事件名一旦漏出去，
   前端就会开始依赖厂商的协议，换一家全崩；
2. **二进制音频帧与 `{"type":"audio","seq":n}` 交替**，前端按 `seq` 排序播放；
3. **任何 `error` 都带 `fallback`**（P2-B2），前端据此决定退到文字还是浏览器合成 ——
   降级路径由服务端说了算。
"""

from __future__ import annotations

import json
from collections import deque

import pytest

from app.providers.tts.mock import MockRealtime, MockRealtimeSession
from app.services.voice.realtime import (
    DOWN_TYPES,
    MODE_MAP,
    ChannelClosed,
    RealtimeChannel,
)

pytestmark = pytest.mark.contract


@pytest.fixture()
def seeded(app_factory):
    """一台刚部署好的机器（音色 / 角色 / 示例课程都在）。"""
    return app_factory(seed=True)


class FakeClock:
    """每读一次走一秒的钟。

    「这节课上了几秒」这种账必须能确定地验到，而真等几秒的测试没人会跑。
    步子取 1 秒而不是更小：`_settle` 是**按整秒**记账的，步子太小会算出 0 秒，
    而「不足一秒不计费」本来就是那条规则的一部分。
    """

    def __init__(self, step: float = 1.0) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


class FakeTransport:
    """一个假的浏览器。两个方法就够 —— `Transport` 协议窄到这个程度是有意的。

    空闲 `idle_limit` 次之后**主动断线**，而不是一直返回 None：真实的
    `receive(timeout)` 会阻塞到超时，假的要是立刻返回 None，`run()` 的轮询
    就成了死循环，测试挂在那儿谁也看不出来。
    """

    def __init__(self, inbox: list | None = None, *, idle_limit: int = 3) -> None:
        self.inbox = deque(inbox or [])
        self.sent: list[dict] = []
        self.audio: list[bytes] = []
        #: 发出的东西的真实顺序：`("json", 事件名)` / `("bytes", "bytes")`
        self.log: list[tuple[str, str]] = []
        self.idle_limit = idle_limit
        self._idle = 0
        self.closed_by_client = False

    def receive(self, timeout: float):
        if not self.inbox:
            self._idle += 1
            if self._idle > self.idle_limit:
                self.closed_by_client = True
                raise ChannelClosed("学生关掉了页面")
            return None
        self._idle = 0
        return self.inbox.popleft()

    def send(self, data) -> None:
        if isinstance(data, (bytes, bytearray)):
            self.audio.append(bytes(data))
            self.log.append(("bytes", "bytes"))
        else:
            payload = json.loads(data)
            self.sent.append(payload)
            self.log.append(("json", payload["type"]))

    @property
    def types(self) -> list[str]:
        return [item["type"] for item in self.sent]

    def of(self, kind: str) -> list[dict]:
        return [item for item in self.sent if item["type"] == kind]


class SpyRealtime(MockRealtime):
    """离线会话，但记下「被要求提交了几次」。

    「松开按键 → 判停」在真上游是一条 `input_audio_buffer.commit`，
    Mock 里只是把脚本排上队 —— 不数一下，这条契约就没被真正验到。
    """

    def start_session(self, **options):
        session = _SpySession(**options)
        self.sessions.append(session)
        return session


class _SpySession(MockRealtimeSession):
    def __init__(self, **options) -> None:
        super().__init__(**options)
        self.commits = 0

    def commit_audio(self) -> None:
        self.commits += 1
        super().commit_audio()


def _channel(provider=None, *, inbox: list | None = None, **kwargs):
    """一条建好的通道 + 它的假浏览器 + 上游会话。"""
    upstream = provider or MockRealtime()
    transport = FakeTransport(inbox)
    channel = RealtimeChannel(upstream, emit=transport.send, clock=FakeClock(), **kwargs)
    return channel, transport, upstream


def _start(**payload) -> str:
    return _json({"type": "start", "sessionId": "s_test", **payload})


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _course_with_page():
    """一门有标题和要点的课 —— 提示词与热词都从这两样东西来（P2-A20）。"""
    from app.extensions import db
    from app.models import Course, CoursePage

    course = Course(title="机器学习入门", topic="学习率", status="ready")
    db.session.add(course)
    db.session.flush()
    page = CoursePage(
        course_id=course.id,
        chapter_no=1,
        page_no=1,
        kind="concept",
        title="学习率衰减",
        status="ready",
        rev=1,
    )
    page.dsl = {
        "title": "学习率衰减",
        "points": ["学习率决定每一步走多远", "衰减是为了收敛"],
        "narration": [{"beatId": "p1-b1", "text": "这一页讲学习率衰减。"}],
    }
    db.session.add(page)
    db.session.commit()
    return course


# --- 全序列 ---


def test_full_turn_sequence(seeded):
    """P2-B1 的原文：`start → ready → audio/reply → done` 一整轮走通。

    顺序也要对：`ready` 在最前（前端据此才允许按空格），`done` 在一轮的最后
    （前端据此收字幕），中间是识别、回答与音频。
    """
    chunk = b"\x01\x02" * 320  # 一段上行音频（PCM 16k/16bit/单声道）
    channel, transport, upstream = _channel(
        inbox=[
            _start(mode="voice_chat"),
            chunk,
            _json({"type": "audio", "seq": 1, "final": True}),  # 学生松开按键
            _json({"type": "stop"}),
        ]
    )
    channel.run(transport)

    assert transport.types == [
        "ready",
        "asr",
        "asr",
        "reply",
        "reply",
        "audio",
        "audio",
        "done",
        "closed",
    ]
    assert set(transport.types) <= set(DOWN_TYPES), "下行不许出现上游事件名"

    session = upstream.sessions[0]
    assert chunk in session.sent, "上行音频要真的送到会话里"
    assert session.closed is True, "收工时必须告诉上游，否则会被判成异常取消"


def test_ready_carries_the_session_identity(seeded):
    """`ready` 里的 `dialogId` 是上游会话号，排障时要靠它去上游查日志。"""
    channel, transport, _ = _channel(inbox=[_start(), _json({"type": "stop"})])
    channel.run(transport)

    ready = transport.of("ready")[0]
    assert ready["sessionId"] == "s_test"
    assert ready["dialogId"].startswith("mock-dialog-")
    assert isinstance(ready["ttsFirstFrameMs"], int)


def test_audio_frames_are_sequenced(seeded):
    """二进制帧与 `{"type":"audio","seq":n}` 交替、seq 递增 —— 前端按它排序播放。

    顺序有讲究：说明帧在前、二进制帧在后。反过来发的话，前端拿到一帧音频
    却不知道该把它接在哪儿。
    """
    channel, transport, _ = _channel(
        inbox=[
            _start(),
            _json({"type": "audio", "seq": 1, "final": True}),
            _json({"type": "stop"}),
        ]
    )
    channel.run(transport)

    notices = transport.of("audio")
    assert [item["seq"] for item in notices] == [1, 2], "两个分片 → 两个序号"
    assert [name for _, name in transport.log] == [
        "ready",
        "asr",
        "asr",
        "reply",
        "reply",
        "audio",
        "bytes",
        "audio",
        "bytes",
        "done",
        "closed",
    ], "每个 audio 说明帧的后面紧跟它的二进制帧"
    assert all(len(item) > 0 for item in transport.audio)


def test_done_reports_this_turn_only(seeded):
    """`done.usage` 报的是**这一轮**的量（字幕与计费都按轮算）。"""
    channel, transport, _ = _channel(
        inbox=[
            _start(),
            _json({"type": "audio", "seq": 1, "final": True}),
            _json({"type": "stop"}),
        ]
    )
    channel.run(transport)

    usage = transport.of("done")[0]["usage"]
    assert usage["asrChars"] > 0, "识别到的字数"
    assert usage["replyChars"] > 0, "老师回答的字数"
    assert usage["firstFrameMs"] > 0, "第一帧声音的延迟（P2-D1 就看它）"


def test_mode_is_translated_for_upstream(seeded):
    """前端的 `mode` → 上游的 `input_mod`，翻译只此一处（§5.3-B6 / P2-A18）。"""
    channel, transport, upstream = _channel(
        inbox=[_start(mode="discussion"), _json({"type": "stop"})]
    )
    channel.run(transport)

    assert upstream.sessions[0].mode == MODE_MAP["discussion"]


def test_student_release_commits_the_utterance(seeded):
    """`final` 的上行音频 = 「我说完了」→ 必须下发 commit，且只在松手时发。

    `push_to_talk` 模式下服务端 VAD 被屏蔽（§5.3 的映射表：`audio` 结束 →
    `input_audio_buffer.commit`），判停完全靠这一条：不发的话学生松开按键之后
    **永远等不到回答**，而界面上只是「按了没反应」。
    """
    channel, transport, upstream = _channel(
        provider=SpyRealtime(),
        inbox=[
            _start(),
            b"\x00" * 64,
            _json({"type": "audio", "seq": 2}),  # 还在说：不提交
            _json({"type": "audio", "seq": 3, "final": True}),  # 松手
            _json({"type": "stop"}),
        ]
    )
    channel.run(transport)

    session = upstream.sessions[0]
    assert session.commits == 1, "一轮只说一次「说完了」"
    assert transport.of("asr"), "松手之后才该有识别结果"


# --- 打断 ---


def test_barge_in_is_acknowledged(seeded):
    """学生插话：撤掉正在播的那一轮，并回执告诉前端「可以说了」（300ms 目标）。"""
    channel, transport, upstream = _channel(
        inbox=[_start(), _json({"type": "barge_in"}), _json({"type": "stop"})]
    )
    channel.run(transport)

    assert upstream.sessions[0].barge_ins == 1
    ack = transport.of("barge_in_ack")[0]
    assert isinstance(ack["latencyMs"], int) and ack["latencyMs"] >= 0


# --- 降级与容错 ---


def test_missing_key_degrades_to_the_browser(seeded):
    """上游没配好：`error` 带 `fallback: browser` —— 服务端没声音但设备有。"""
    from app.providers.base import not_configured

    class Unconfigured(MockRealtime):
        @property
        def configured(self) -> bool:
            return False

        def start_session(self, **options):
            raise not_configured(self)

    channel, transport, _ = _channel(provider=Unconfigured(), inbox=[_start()])
    channel.run(transport)

    error = transport.of("error")[0]
    assert error["fallback"] == "browser"
    assert error["code"] == "40201"
    assert not transport.of("audio"), "失败之后不该再有声音"


def test_broken_message_is_reported_and_the_session_survives(seeded):
    """一条坏消息不该打断整节课：报错、带 fallback、通道继续活着。"""
    channel, transport, upstream = _channel(
        inbox=[
            _start(),
            "这不是 JSON",
            _json({"type": "future_thing"}),  # 协议扩展期的新消息
            _json({"type": "stop"}),
        ]
    )
    channel.run(transport)

    error = transport.of("error")[0]
    assert error["fallback"] == "text"
    assert transport.types.count("closed") == 1, "坏消息没有把通道打散"
    assert upstream.sessions[0].closed is True


def test_client_hangup_closes_the_channel(seeded):
    """学生关掉页面：通道收摊、告诉上游、把这一节课的账结掉。"""
    channel, transport, upstream = _channel(inbox=[_start()])
    channel.run(transport)

    assert transport.closed_by_client is True, "假客户端应当空转几次后断开"
    assert transport.of("closed")[0]["reason"] == "transport_closed"
    assert upstream.sessions[0].closed is True


def test_errors_before_start_are_reported(seeded):
    """还没 `start` 就发音频：报错并说清要先建会话，而不是抛一个 500。"""
    channel, transport, _ = _channel(inbox=[b"\x00" * 32, _json({"type": "stop"})])
    channel.run(transport)

    error = transport.of("error")[0]
    assert error["fallback"] == "text"
    assert "start" in error["message"]


# --- 记账 ---


def test_a_session_is_billed_by_the_second(seeded):
    """一次会话写一笔账（P2-A11）：按秒、挂在会话号上。"""
    from app.services.voice import usage

    channel, transport, _ = _channel(inbox=[_start(), _json({"type": "stop"})])
    channel.run(transport)

    summary = usage.summary(ref_type="session", ref_id="s_test")
    realtime = next(item for item in summary["kinds"] if item["kind"] == "realtime")
    assert realtime["unitName"] == "seconds"
    assert realtime["units"] >= 1
    assert realtime["calls"] == 1


def test_a_session_that_never_started_is_not_billed(seeded):
    """只连上、没 `start` 就断开：没有会话，就没有时长可计。"""
    from app.services.voice import usage

    channel, transport, _ = _channel(inbox=[_json({"type": "future_thing"})])
    channel.run(transport)

    summary = usage.summary(ref_type="session")
    assert summary["totalCost"] == 0
    assert all(item["units"] == 0 for item in summary["kinds"])


# --- 课程上下文 ---


def test_course_context_reaches_the_teacher(seeded):
    """`start.context` 里的课程会让老师知道「现在上到哪一页」（P2-A20）。

    前端手里只有一个 pageNo，这一页讲什么在库里 —— 老师答非所问最常见的原因
    就是它不知道现在上到哪儿了。
    """
    course = _course_with_page()
    channel, transport, upstream = _channel(
        resolve_course=lambda course_id: course if course_id == course.id else None,
        inbox=[
            _start(systemPrompt="你是沈老师。", context={"courseId": course.id, "pageNo": 1}),
            _json({"type": "stop"}),
        ],
    )
    channel.run(transport)

    session = upstream.sessions[0]
    assert "你是沈老师。" in session.instructions
    assert course.title in session.instructions
    assert "学习率决定每一步走多远" in session.instructions
    assert session.hotwords, "热词表与 TTS 纠音表是同一份课程术语表"
    assert "学习率衰减" in session.hotwords


def test_unknown_course_is_not_fatal(seeded):
    """courseId 对不上（转发、手滑）：当作没有上下文，课照上。"""
    channel, transport, upstream = _channel(
        resolve_course=lambda _course_id: None,
        inbox=[_start(context={"courseId": "不存在的课"}), _json({"type": "stop"})],
    )
    channel.run(transport)

    assert transport.of("error") == []
    assert upstream.sessions[0].instructions == ""


# --- 一个人的并发上限（P2-F5）---


@pytest.fixture(autouse=True)
def _release_slots():
    """名额是模块级状态（`owner_id` → 会话号），不清会跨到下一个用例。

    影响是「下一条用例的第一句话被拒」，与它要验的事毫无关系 ——
    那种失败最费时间，因为报错离原因很远。
    """
    from app.services.voice import sessions

    sessions.clear()
    yield
    sessions.clear()


def test_a_second_session_for_the_same_person_is_refused(seeded):
    """同一个人开第二条：`42901` 带 `fallback: text`，第一条继续用（P2-F5）。

    两个老师同时说话是听得出的事故，所以这条要在通道层拦住。上行走
    `handle()` 而不是 `run()`：要验的是「第一条还开着时第二条进不来」，
    而 `run()` 跑完就把第一条自己关掉了。
    """
    first, first_transport, _ = _channel(owner_id="u_1", inbox=[_start()])
    second, second_transport, second_upstream = _channel(owner_id="u_1", inbox=[_start()])

    first.handle(_start())
    second.handle(_start())

    error = second_transport.of("error")[0]
    assert error["code"] == "42901"
    assert error["fallback"] == "text", "P2-B2：前端据此退到文字问答，而不是干等"
    assert second_upstream.sessions == [], "被拒的那条不该白白开一条上游会话"
    # 第一条没被牵连：它自己的 ready 正常发出去了，而且没收到任何 error
    assert first_transport.types == ["ready"]


def test_the_slot_is_released_when_the_first_session_ends(seeded):
    """前一条收工后名额要还回去。

    漏还的后果不是报错，而是「这个人的语音从此打不开」—— 症状是
    「昨天还好好的」，最难查的一种。
    """
    first, first_transport, _ = _channel(owner_id="u_1", inbox=[_start()])
    first.handle(_start())
    first.close()

    second, second_transport, _ = _channel(owner_id="u_1", inbox=[_start()])
    second.handle(_start())

    assert second_transport.of("error") == []
    assert second_transport.types == ["ready"]
    second.close()
    # 第一条通道自己那条路没受影响：ready 之后正常收尾（`closed`），全程没有 error
    assert first_transport.types == ["ready", "closed"]


def test_another_person_can_talk_at_the_same_time(seeded):
    """别人不受影响 —— 这条上限是**按人**的，不是全局只许一个人用语音。"""
    mine, _, _ = _channel(owner_id="u_1", inbox=[_start()])
    yours, yours_transport, _ = _channel(owner_id="u_2", inbox=[_start()])

    mine.handle(_start())
    yours.handle(_start())

    assert yours_transport.of("error") == []
    assert yours_transport.types == ["ready"]
    mine.close()
    yours.close()
