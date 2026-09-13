"""课堂运行时（§2.1 / §2.2 / §4.2 / P3-A1~A13 的服务端那半边）。

运行时是「一条连接的语义层」：WS 路由只做收发，所以契约打在这一层上 ——
用一个 `Client` 门面（连接层那一拍的替身）把「这个连接收到了什么」收进列表，
逐条断言。断言 `client.last("speak")` 断的就是**前端看到了什么**，因为交付
只有留档这一条路径（运行时的模块 docstring 第 2 条）。这一层钉住的是：

- **P3-A2 单写者**：任何时刻只有一条在说（`speak` 与 `speak_end` 严格成对），
  被抢占的不补播；
- **P3-A1 状态机**：`idle → lecture → …→ ended` 走的是 §2.1 那张表；
- **P3-A5/A6/A7 的三个来回**：举手 → 点名 → 提问 → 答疑；弹题 → 作答 → 继续；
- **P3-B2 `seq` 单调**：每个下行帧都带一个递增的号（补发与去重靠它）。

**作答不走 WS**：§4.2 的上行清单里没有交卷这一项，前端用 §4.1 的
`POST /quiz-submit`，所以这里直接调 `submit_quiz`（P3-4 的路由也调它）。
交卷结果怎么广播给同课堂的其他人是连接中心（P3-3）的事，不是这一层的。

模型一律走离线桩（`LLM_PROVIDER=mock`）：课堂的四类调用（插话/答疑/讨论/板书）
都发生在真实课堂上，测试也不该去连上游。
"""

from __future__ import annotations

import json

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.common.errors import ConflictError, ValidationError
from app.extensions import db
from app.models import (
    AgentRole,
    AuditLog,
    BoardStroke,
    ClassroomMessage,
    ClassroomSession,
    Course,
    CoursePage,
    QuizAttempt,
    User,
)
from app.services.classroom import board, recorder, scheduler, sessions, state
from app.services.classroom.runtime import (
    ClassroomRuntime,
    PeerGone,
    _audio_grace_ms,
    raise_hand,
    submit_quiz,
)

pytestmark = pytest.mark.unit

#: 课堂里的两个人。**必须是真用户行**：`session_participants.user_id` 与
#: `hand_queue.user_id` 都是指向 `users` 的外键，而 SQLite 这边
#: `PRAGMA foreign_keys=ON` 开着（`app/extensions.py`）。
ME = "u1"
GUEST = "u2"

#: 测验用的四个选项与正确答案（照示例课 §技术实现方案 的形状：整句话）。
#: 用例里一律引这几个常量，别写 "A"/"B"：写短了，判定那条路上
#: 「选项有多长」就不再是这批用例的覆盖面。
QUIZ_OPTIONS = (
    "给人标注过的数据，让程序自己找规则",
    "把业务规则一条条写进程序里",
    "先写规则，再用数据验证规则对不对",
    "把历史数据存起来，用的时候直接查",
)
QUIZ_ANSWER = QUIZ_OPTIONS[0]

#: 拨一段比两个间隔设置（`CLASSROOM_BEAT_GAP` / `CLASSROOM_PAGE_GAP`）都长的假时间。
#: 「报完这一拍，下一拍会不会来」的地方拨它就够了 —— 断的是「会不会来」，
#: 不是「几秒后来」，所以只要比那口气长，具体多久无所谓。
GAP = 2.0


@pytest.fixture()
def app(app_factory):
    app = app_factory(env={"LLM_PROVIDER": "mock"})
    with app.app_context():
        _users()
    return app


class Clock:
    """假单调钟：计时类断言不必真的等 20 秒。"""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = float(now)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class Client:
    """一条课堂连接：一个运行时 + 它**收到**的帧。

    这里替 P3-3 那条连接循环做了两件事：每一拍扫一次留档
    （`take_pending()`）把新事件收下来，以及把只发给本人的 `error` 帧接住。
    之所以在测试里也这么走一遍，是因为**交付只走这一条路径**（运行时模块
    docstring 第 2 条）—— 断言 `client.last("speak")` 断的就是「前端看到了什么」。
    """

    def __init__(
        self,
        session: ClassroomSession,
        *,
        user_id: str = "",
        name: str = "",
        clock: Clock | None = None,
    ) -> None:
        self.session = session
        self.clock = clock if clock is not None else Clock()
        self.frames: list[dict] = []
        self.runtime = ClassroomRuntime(
            session, emit=self._private, clock=self.clock, user_id=user_id, name=name
        )

    # --- 上行 ---

    def handle(self, message) -> None:
        self.runtime.handle(message)
        self.pump()

    def tick(self, *, wait: float = 0.0) -> bool:
        """走一拍（`tick` 是下行的唯一出口）。

        `wait` 是先把假钟往前拨几秒再走 —— 两拍之间有一口气
        （`runtime._gap_before`：同页 `CLASSROOM_BEAT_GAP`、翻页
        `CLASSROOM_PAGE_GAP`），钟不动就永远等不到那口气过去。
        等「下一句会不会来」（而不是「几秒后来」）的地方拨 `GAP` 就行。
        """
        if wait:
            self.clock.advance(wait)
        done = self.runtime.tick()
        self.pump()
        return done

    def hello(self, **extra) -> None:
        """`hello`：带 `afterSeq` 就是重连（从那儿接着收），不带就是新来的。"""
        after = int(extra.get("afterSeq") or 0)
        if after > 0:
            # 连接层在这里做的是「把游标挪到客户端已收到的位置」，
            # 于是 `take_pending` 补出来的正好是缺的那几条
            self.runtime.deliver_after = after
        self.handle({"type": "hello", **extra})

    def play(self) -> None:
        """开讲并让老师说出第一句（`tick` 是唯一的出口）。"""
        self.handle({"type": "play"})
        self.tick()

    def finish_page(self, *, beats: int = 2) -> None:
        """把当前这一页的讲稿一条条报完（第一句已由 `play` 说出来）。

        一页 N 句要报 N 次：前 N-1 次只是往后挪一句（挪到过半才允许插话），
        第 N 次才叫「这一页讲完了」—— 插话与章末讨论都挂在那一下上。
        """
        for _ in range(beats):
            self.handle({"type": "beat_done"})
        self.tick()

    def close(self, *, reason: str = "closed") -> None:
        """断线（路由在路由协程收尾时做的最后一件事）。"""
        self.runtime.close(reason=reason)
        self.pump()

    # --- 下行 ---

    def pump(self) -> None:
        """把留档里还没收到的事件收下来（连接层每一拍做的事）。"""
        for event in self.runtime.take_pending():
            self.frames.append(event)

    def _private(self, data: str) -> None:
        self.frames.append(json.loads(data))

    def types(self) -> list[str]:
        return [frame["type"] for frame in self.frames]

    def of(self, kind: str) -> list[dict]:
        return [frame for frame in self.frames if frame["type"] == kind]

    def last(self, kind: str) -> dict | None:
        found = self.of(kind)
        return found[-1] if found else None

    def clear(self) -> None:
        """「从现在起我看到什么」—— 只是清空列表，收件游标不动。"""
        self.frames.clear()

    # --- 直通运行时（测试里读起来短一些）---

    @property
    def speaking(self) -> bool:
        return self.runtime.speaking

    @property
    def alive(self) -> bool:
        return self.runtime.alive

    @property
    def finished(self) -> bool:
        return self.runtime.finished


# --- 布景 ---


def _users() -> None:
    """课堂里的两个人（见 `ME` / `GUEST`）。"""
    db.session.add_all(
        [
            User(id=ME, name="小明", role="student"),
            User(id=GUEST, name="小红", role="student"),
        ]
    )
    db.session.commit()


def _roles() -> None:
    """一个老师 + 两个同学。`persona.tendency` 决定插话说什么（§2.3）。

    `systemHint` 里那句「主讲老师」不是装饰：讨论轮由模型驱动，
    桩靠人设行里的这几个字判断「这一轮是老师还是学生」（`fixture._personas_of`）。
    """
    db.session.add_all(
        [
            AgentRole(
                code="shen",
                name="沈老师",
                role="teacher",
                persona={
                    "style": "沉稳",
                    "tone": "循循善诱",
                    "systemHint": "你是主讲老师，负责讲解、答疑与收束讨论。",
                },
                sort_order=1,
            ),
            AgentRole(
                code="xiaoxiao",
                name="林晓",
                role="student",
                persona={"tendency": "question", "style": "好奇"},
                sort_order=2,
            ),
            AgentRole(
                code="chenmo",
                name="陈默",
                role="student",
                persona={"tendency": "supplement", "style": "沉稳"},
                sort_order=3,
            ),
        ]
    )
    db.session.commit()


def _page(
    *,
    page_no: int = 1,
    kind: str = "concept",
    title: str = "",
    beats: tuple[str, ...] = ("第一句讲稿。", "第二句讲稿。"),
    est: int = 4,
    quiz: bool = False,
    board_plan: bool = False,
) -> dict:
    """一页的 DSL。默认两句话、4 秒一句 —— 与 `test_classroom_sessions` 同一套口径。"""
    dsl: dict = {
        "pageNo": page_no,
        "kind": kind,
        "title": title or f"第 {page_no} 页",
        "bullets": [{"text": "本页要点"}],
        "narration": [
            {"beatId": f"p{page_no}-b{index}", "text": text, "estSec": est}
            for index, text in enumerate(beats, start=1)
        ],
    }
    if quiz:
        # 选项是**整句话**，答案也是其中一句话（§ 技术实现方案 161）——
        # 别为了好写换成 "A"/"B"：那样测不出「选项长过一个短上限」这类错
        # （真发生过：`option` 列曾经只有 16 字符，于是每道题都判错）。
        dsl["quiz"] = {
            "stem": "下面哪一项最接近机器学习的做法？",
            "options": list(QUIZ_OPTIONS),
            "answer": QUIZ_ANSWER,
            "explain": "机器学习的核心是「从数据里找规则」，规则不写在代码里。",
            "conceptTag": "什么是机器学习",
        }
    if board_plan:
        dsl["boardPlan"] = [
            {"tool": "polyline", "desc": "画一条横轴", "atBeat": f"p{page_no}-b1"}
        ]
    return dsl


def _course(pages: list[dict], *, chapters: list[dict] | None = None) -> Course:
    """按页描述建一门 ready 的课（`{beats: (...), chapter: 2, ...}`）。"""
    course = Course(
        title="机器学习入门", topic="机器学习入门", status="ready",
        dsl={"chapters": chapters or []},
    )
    db.session.add(course)
    db.session.commit()
    for index, spec in enumerate(pages, start=1):
        options = dict(spec)
        chapter_no = int(options.pop("chapter", 1))
        dsl = _page(page_no=index, **options)
        db.session.add(
            CoursePage(
                course_id=course.id,
                page_no=index,
                chapter_no=chapter_no,
                kind=dsl["kind"],
                title=dsl["title"],
                status="ready",
                dsl=dsl,
            )
        )
    db.session.commit()
    return course


def _runtime(
    session: ClassroomSession,
    *,
    user_id: str = "",
    name: str = "",
    clock: Clock | None = None,
) -> Client:
    return Client(session, user_id=user_id, name=name, clock=clock)


# --- 连接（§4.2 `hello`）---


def test_hello_puts_me_in_the_room_and_sends_what_i_should_see(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}, {}]), ME)
        client = _runtime(session, user_id=ME)

        client.hello()

        assert client.last("presence")["online"] == 1
        assert client.last("state")["status"] == state.IDLE
        assert client.last("state")["pageNo"] == 1
        assert client.last("subtitle")["beatId"] == "p1-b1", "重连要知道停在哪一句"
        assert client.last("hand_queue")["queue"] == []
        assert client.last("hand_queue")["called"] is None


def test_every_downlink_frame_carries_a_growing_seq(app):
    """P3-B2：`seq` 单调递增 —— 补发、去重、对账都靠它。

    （`error` 是唯一不带 `seq` 的帧：它只发给发信人、不进留档，见运行时 docstring。）
    """
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)

        client.hello()
        client.play()

        seqs = [frame["seq"] for frame in client.frames if "seq" in frame]
        assert len(seqs) == len(client.frames), "只有 error 帧可以不带 seq"
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs), "同一个 seq 不能出现两次"


def test_a_message_that_fails_comes_back_to_the_sender_only(app):
    """`error` 只发给发信人，而且不占 `seq`（占了他就重连不上正确的号）。"""
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        me = _runtime(session, user_id=ME)
        other = _runtime(session, user_id=GUEST)
        me.hello()
        other.hello()
        other.clear()

        me.handle({"type": "ask", "text": "老师？"})  # 还没开讲，40901

        assert me.last("error")["code"] == "40901"
        assert other.of("error") == [], "别人的失误不该广播给全班"
        assert "seq" not in me.last("error")


def test_hello_replays_what_the_client_missed(app):
    """P3-A10：重连带上 `afterSeq`，只补缺的那几条，不重发整堂课。"""
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        first = _runtime(session, user_id=ME)
        first.hello()
        first.play()
        # 「断线前我收到了这里」：`typing` 之后那几条（`speak` / `message`）是漏掉的
        missed_after = first.of("typing")[0]["seq"]

        second = _runtime(session, user_id=ME)
        second.hello(afterSeq=missed_after)

        assert [frame for frame in second.frames if frame.get("seq", 0) <= missed_after] == []
        assert second.of("typing") == [], "已经收到过的不再重发"
        assert [frame["seq"] for frame in second.of("speak")] == [missed_after + 1], "漏掉的那条补回来"


def test_a_fresh_connection_is_not_flooded_with_history(app):
    """新来的不带 `afterSeq`：补发从「此刻」起，历史走 `GET /messages`。"""
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}, {}]), ME)
        first = _runtime(session, user_id=ME)
        first.hello()
        first.play()
        first.finish_page()

        late = _runtime(session, user_id=GUEST)
        late.hello()

        assert late.of("message") == [], "整堂课的消息不由 WS 重放"
        assert late.last("state")["pageNo"] == 2, "但得知道现在讲到哪"
        assert late.last("subtitle")["pageNo"] == 2


# --- 开讲与单写者（P3-A1 / A2）---


def test_play_starts_the_lecture_and_the_teacher_says_the_first_beat(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.clear()

        client.play()

        assert session.status == state.LECTURE
        assert client.types().count("speak") == 1
        speak = client.last("speak")
        assert speak["speaker"] == {"code": "shen", "name": "沈老师"}
        assert speak["kind"] == "lecture"
        assert speak["beats"] == ["p1-b1"]
        assert speak["text"] == "第一句讲稿。"
        assert speak["priority"] == scheduler.PRIORITY_LECTURE
        assert speak["audioUrl"] == "", "没合成过音频就老实说没有"


def test_a_speak_is_followed_by_a_message_on_the_same_turn(app):
    """`speak` 是给播放器的，`message` 是给讨论区的 —— 一条发言两处都要落。"""
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.clear()

        client.play()

        msg = client.last("message")["msg"]
        assert msg["text"] == "第一句讲稿。"
        assert msg["speakerKind"] == "teacher"
        assert msg["type"] == "lecture"
        assert msg["beatId"] == "p1-b1"
        assert ClassroomMessage.query.count() == 1


def test_the_next_beat_waits_for_the_current_turn_to_end(app):
    """前后两句不重叠（P3-A2）：不报 `beat_done`，第二句不会自己冒出来。"""
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()

        for _ in range(5):
            client.tick()

        assert client.types().count("speak") == 1, "还在说第一句"
        assert client.speaking is True


def test_beat_done_closes_the_turn_and_the_next_beat_follows(app):
    """**两页**：一页的话第一句报完就到头了（最后一页最后一个 beat → 下课）。"""
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}, {}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        first_turn = client.last("speak")["turnId"]

        client.handle({"type": "beat_done"})
        client.tick(wait=GAP)  # 两拍之间那口气过去，下一句才开口

        assert client.of("speak_end")[-1]["turnId"] == first_turn
        assert client.last("state")["beatIdx"] == 1
        assert client.last("speak")["beats"] == ["p1-b2"], "接着念第二句"


def test_the_script_message_carries_its_place_on_the_timeline(app):
    """讲稿消息的 `ts` 是它在时间线上的位置（0:00 起算），不是落库那一刻。

    两处细节都是为了把这一条钉死：第一页只有一句（报一次 `beat_done` 就翻页，
    一页两句的话那一下只是往后挪一句），且不是概念页（概念页讲到最后一 beat
    会带出一句同学插话，优先级比讲稿高，会把第 2 页那句挤到下一拍）。
    """
    with app.app_context():
        _roles()
        session = sessions.start(
            _course([{"beats": ("这一页就一句。",), "kind": "example"}, {}]), ME
        )
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        client.handle({"type": "beat_done"})  # 走到下一页
        client.tick(wait=GAP)  # 翻页还要多留一会儿看幻灯片，第 2 页那句才开口

        messages = [frame["msg"] for frame in client.of("message")]
        assert messages[0]["ts"] < messages[-1]["ts"]
        assert messages[-1]["pageNo"] == 2


def test_finishing_the_last_beat_ends_the_class(app):
    """最后一页最后一句说完 → `ended`（§2.1 的终态），连接据此收尾。"""
    with app.app_context():
        _roles()
        session = sessions.start(_course([{"beats": ("就这一句。",)}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        client.clear()

        client.handle({"type": "beat_done"})

        assert session.status == state.ENDED
        assert session.ended_at is not None
        assert client.last("state")["status"] == state.ENDED
        assert client.finished is True


# --- 暂停 / 跳页（§2.2 / P3-A9）---


def test_pause_stops_the_current_turn_and_play_resumes_it(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()

        client.handle({"type": "pause"})

        assert session.status == state.PAUSED
        assert client.of("speak_end")[-1]["preempted"] is True, "老师立刻停口"
        assert client.speaking is False
        client.tick()
        assert client.types().count("speak") == 1, "暂停期间不该有新的话"

        client.handle({"type": "play"})
        client.tick(wait=GAP)

        assert session.status == state.LECTURE, "从暂停回来回到暂停前那个状态"
        assert client.types().count("speak") == 2, "接着把刚才那句重念一遍"
        assert client.last("speak")["beats"] == ["p1-b1"]


def test_pausing_twice_is_not_an_error(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()

        client.handle({"type": "pause"})
        client.handle({"type": "pause"})
        client.handle({"type": "play"})

        assert session.status == state.LECTURE


def test_every_uplink_reads_the_classroom_back_from_the_database(app):
    """P3-A13：每条上行之前先把这堂课的状态从库里读回来。

    **每个连接有自己的运行时**（生产里还各有一份 identity map：一个 WS 线程
    一个 app context，一份 scoped session），`self.session` 是它入场那一刻
    加载的那一行。另一个标签页把这堂课开起来，这条连接手上还是 `idle` ——
    按它去判，一条合法的 `pause` 会被 `require_live` 当成「课还没上」挡回去，
    前端看到的只是「点了没反应」。

    测试里只有一份 Session，凑不出「另一条连接手里那个旧对象」；能凑出来的是
    「库里已经变了、手上还是旧的」—— 这里用一个**独立的 Session** 改库，
    正好等价于另一个标签页那次提交（它自己那条连接、自己那份 Session）。
    """
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        assert session.status == state.IDLE

        # 另一个标签页点了「开始上课」
        with Session(db.engine) as other:
            other.execute(
                sa.update(ClassroomSession)
                .where(ClassroomSession.id == session.id)
                .values(status=state.LECTURE)
            )
            other.commit()
        assert session.status == state.IDLE, "这条连接手上那一份还是入场时的样子"

        client.handle({"type": "pause"})

        assert "error" not in client.types(), "不该回一条「状态不允许」"
        assert client.last("state")["status"] == state.PAUSED
        assert session.status == state.PAUSED
        with Session(db.engine) as other:
            assert other.get(ClassroomSession, session.id).status == state.PAUSED, "落库的也是暂停"


def test_seek_terminates_the_current_turn_and_moves_the_page(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}, {}, {}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        client.clear()

        client.handle({"type": "seek", "pageNo": 3})

        assert client.of("speak_end")[-1]["preempted"] is True
        assert client.last("state")["pageNo"] == 3
        assert client.last("state")["beatIdx"] == 0
        assert client.last("subtitle")["beatId"] == "p3-b1"
        assert session.elapsed_ms == 16000, "位置按时间线算（前两页各 8 秒）"
        # 跳页不是「停在那儿」：老师接着念目标页的第一句，否则客户端只能靠
        # 再报一次 beat_done 让课堂动起来 —— 那一下正好跳过这一页的第一句
        client.tick(wait=GAP)
        assert client.last("speak")["beats"] == ["p3-b1"]


def test_seeking_to_a_page_that_does_not_exist_is_rejected(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()

        client.handle({"type": "seek", "pageNo": 99})

        assert client.last("error")["code"] == str(ValidationError.code)
        assert client.last("error")["recoverable"] is True


def test_seeking_before_the_class_starts_is_allowed(app):
    """课前翻一遍是正常动作 —— 它只改位置，不改状态。"""
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}, {}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()

        client.handle({"type": "seek", "pageNo": 2})
        client.tick()

        assert session.status == state.IDLE
        assert client.last("state")["pageNo"] == 2
        assert client.of("error") == []
        assert client.of("speak") == [], "课前翻页不开口"


# --- 举手 / 提问 / 答疑（P3-A5 / A6）---


def test_raising_a_hand_stops_the_teacher_and_calls_the_student(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME, name="小明")
        client.hello()
        client.play()
        client.clear()

        client.handle({"type": "hand"})

        assert client.of("speak_end")[-1]["preempted"] is True, "P3-A6：老师 ≤1s 内停口"
        queue = client.last("hand_queue")
        assert queue["queue"] == [], "点到名的那位不再排在队里"
        assert queue["called"]["userId"] == ME
        assert queue["called"]["name"] == "小明"


def test_raising_a_hand_twice_only_takes_one_slot(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()

        raise_hand(session, ME)
        raise_hand(session, ME)

        assert len(recorder.hand_queue(session.id)["queue"]) == 1


def test_a_question_is_answered_by_the_teacher(app):
    """P3-A5 的完整来回：举手 → 点名 → 提问 → 老师答 → 队列收尾。"""
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME, name="小明")
        client.hello()
        client.play()
        client.handle({"type": "hand"})
        client.clear()

        client.handle({"type": "ask", "text": "为什么要先归一化？"})

        asked = client.of("message")[0]["msg"]
        assert asked["speakerKind"] == "me", "学生自己说的话"
        assert asked["type"] == "question"
        assert asked["text"] == "为什么要先归一化？"
        assert client.last("speak")["kind"] == "barge", "学生的提问优先级最高"

        client.clock.advance(4)  # 提问那句说完（一句话按字数估两三秒）
        client.tick()

        answer = client.last("speak")
        assert answer["kind"] == "answer"
        assert answer["speaker"]["code"] == "shen"
        assert "为什么要先归一化？" in answer["text"], "离线桩的回答要接住问的那件事"

        client.clock.advance(60)
        client.tick()

        assert client.last("hand_queue")["called"] is None, "问完了就收队"


#: 一条假音频：答案的 URL 与时长。时长取一个与字数估出来的值**差得很远**的数
#: （Mock 答疑的文本按字数估只有几秒），这样「按音频计时」与「按字数估」
#: 在时钟上分得开 —— 分不开的话，这条用例对 `duration_ms` 什么都没验到。
ANSWER_AUDIO = {"url": "/api/voice/voices/vp_teacher/preview?v=abcd1234", "durationMs": 30_000}


def test_a_teacher_answer_can_carry_its_own_audio(app, monkeypatch):
    """P3-A5 的后半句：教师**语音**回答。答疑是当场合成的，时长随 Turn 一起进来。

    这里断的就是「有音频用音频时长」：30 秒的音频在第 29 秒还没说完，
    按字数估的话早就收尾了 —— 会把老师的话从中间截断，且不报任何错。
    """
    with app.app_context():
        _roles()
        monkeypatch.setattr(
            "app.services.classroom.speech.answer_audio", lambda text: dict(ANSWER_AUDIO)
        )
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME, name="小明")
        client.hello()
        client.play()
        client.handle({"type": "ask", "text": "为什么要先归一化？"})
        client.clear()

        client.tick()  # 队列里就这一条：老师接话

        answer = client.last("speak")
        assert answer["kind"] == "answer"
        assert answer["audioUrl"] == ANSWER_AUDIO["url"]

        client.clock.advance(29)
        client.tick()
        assert client.speaking is True, "30 秒的音频，29 秒时不该收尾"

        # 收尾比音频本身还要晚一截（`_audio_grace_ms`：30 秒的音频走比例那一档，
        # 见那两个常量）：清单里的时长只到最后一个字，文件比它长，兜底计时
        # 不能卡着 30.000 秒掐。
        client.clock.advance(2 + _audio_grace_ms(ANSWER_AUDIO["durationMs"]) / 1000)
        client.tick()
        assert client.speaking is False
        assert client.of("speak_end")[-1]["turnId"] == answer["turnId"]


def test_a_teacher_answer_without_audio_still_gets_spoken(app, monkeypatch):
    """配不上声音就按纯文字走：`audioUrl` 是空串、按字数估时，话照说。

    这一条是上一条的反面，也是**默认部署**下的样子（没加密钥时 TTS 是离线 Mock，
    但只要哪个环节配不上，`speech.answer_audio` 就给空 dict）。前端据此
    只显示文字、等 `speak_end` 收尾 —— 不能假定每条 `speak` 都有声音。
    """
    with app.app_context():
        _roles()
        monkeypatch.setattr("app.services.classroom.speech.answer_audio", lambda text: {})
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME, name="小明")
        client.hello()
        client.play()
        client.handle({"type": "ask", "text": "为什么要先归一化？"})
        client.clear()

        client.tick()

        answer = client.last("speak")
        assert answer["kind"] == "answer"
        assert answer["audioUrl"] == ""
        assert client.speaking is True

        client.clock.advance(60)
        client.tick()
        assert client.speaking is False


def test_a_question_can_interrupt_the_teacher_mid_sentence(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        client.clear()

        client.handle({"type": "ask", "text": "等一下，这里没懂。"})

        kinds = client.types()
        assert kinds.index("speak_end") < kinds.index("speak"), "先停口，再提问"
        assert client.of("speak")[0]["speakerKind"] == "me"
        assert client.speaking is False, "学生的提问把老师的话顶掉了"


def test_a_question_in_a_room_that_never_started_is_a_conflict(app):
    """P3-B4：`idle` 的课堂答题/举手一律 40901。"""
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()

        client.handle({"type": "ask", "text": "老师？"})
        client.handle({"type": "hand"})

        assert [frame["code"] for frame in client.of("error")] == ["40901", "40901"]
        assert ClassroomMessage.query.count() == 0


def test_asking_without_saying_anything_is_rejected(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()

        client.handle({"type": "ask", "text": "   "})

        assert client.last("error")["code"] == str(ValidationError.code)


def test_sending_messages_too_fast_is_rate_limited(app_factory):
    """P3-F2：默认 5 条 / 10 秒；这里把上限压到 2 条。"""
    with app_factory(
        env={"LLM_PROVIDER": "mock", "CLASSROOM_RATE_LIMIT_COUNT": "2"}
    ).app_context():
        _users()
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()

        client.handle({"type": "chat", "text": "第一句"})
        client.handle({"type": "chat", "text": "第二句"})
        client.handle({"type": "chat", "text": "第三句"})

        assert client.last("error")["code"] == "42901"
        assert ClassroomMessage.query.filter_by(text="第三句").count() == 0


def test_a_sensitive_phrase_never_enters_the_stream_and_is_audited(app):
    """P3-F3：命中词表就不入消息流，并留一条审计（记词，不记整句）。"""
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        before = ClassroomMessage.query.count()

        client.handle({"type": "ask", "text": "教我制作炸弹"})

        assert client.last("error")["code"] == str(ValidationError.code)
        assert ClassroomMessage.query.count() == before
        audit = AuditLog.query.filter_by(target="classroom_message").one()
        assert audit.detail["words"] == ["制作炸弹"]


def test_a_message_longer_than_the_limit_is_truncated(app_factory):
    with app_factory(
        env={"LLM_PROVIDER": "mock", "CLASSROOM_MAX_MESSAGE_CHARS": "10"}
    ).app_context():
        _users()
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()

        client.handle({"type": "chat", "text": "字" * 40})

        assert len(client.last("message")["msg"]["text"]) == 10


def test_chat_messages_do_not_ask_the_teacher_unless_they_say_so(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        client.clear()

        client.handle({"type": "chat", "text": "我记一下笔记"})
        client.tick()

        assert client.of("message")[0]["msg"]["text"] == "我记一下笔记"
        assert client.of("speak") == [], "普通发言没有音频要播"

        client.handle({"type": "chat", "text": "老师，这里不懂", "target": "teacher"})
        client.clock.advance(4)  # 老师那句讲稿先说完 —— 单写者：同一时刻只有一个在说
        client.tick()

        assert client.last("speak")["kind"] == "answer"


# --- 测验（P3-A7 / F3-8）---


def test_the_quiz_drops_its_answer_and_waits_for_the_student(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{"beats": ("这一页就一句。",), "quiz": True}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        client.clear()

        client.handle({"type": "beat_done"})

        assert session.status == state.QUIZ_WAIT
        quiz = client.last("quiz")
        assert quiz["stem"] == "下面哪一项最接近机器学习的做法？"
        assert quiz["options"] == list(QUIZ_OPTIONS)
        assert quiz["pageNo"] == 1
        assert "answer" not in quiz and "explain" not in quiz, "答案不能发给学生"


def test_submitting_the_right_answer_comes_back_with_the_explain(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{"beats": ("就一句。",), "quiz": True}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        client.handle({"type": "beat_done"})

        result = submit_quiz(session, option=QUIZ_ANSWER, response_ms=3200)

        assert result["type"] == "quiz_result"
        assert result["correct"] is True
        assert result["branch"] == "pass"
        assert result["answer"] == QUIZ_ANSWER
        assert result["explain"] == "机器学习的核心是「从数据里找规则」，规则不写在代码里。"
        assert session.status == state.LECTURE
        attempt = QuizAttempt.query.one()
        assert attempt.correct is True
        assert attempt.response_ms == 3200


def test_a_wrong_answer_says_so_and_leaves_the_record(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{"beats": ("就一句。",), "quiz": True}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        client.handle({"type": "beat_done"})

        result = submit_quiz(session, option=QUIZ_OPTIONS[1])

        assert result["correct"] is False
        assert result["branch"] == "remedial"
        assert QuizAttempt.query.one().correct is False


def test_after_answering_the_next_beat_report_moves_on(app):
    """答完之后客户端再报一次 `beat_done` —— 那是「继续」，不是「再弹一次题」。"""
    with app.app_context():
        _roles()
        session = sessions.start(_course([{"beats": ("就一句。",), "quiz": True}, {}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        client.handle({"type": "beat_done"})
        submit_quiz(session, option=QUIZ_ANSWER)
        client.clear()

        client.handle({"type": "beat_done"})

        assert client.of("quiz") == [], "答过的页不再弹题"
        assert client.last("state")["pageNo"] == 2


def test_another_beat_done_while_waiting_is_a_skip(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{"beats": ("就一句。",), "quiz": True}, {}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        client.handle({"type": "beat_done"})
        client.clear()

        client.handle({"type": "beat_done"})  # 跳过这道题

        assert client.of("quiz") == []
        assert client.last("state")["pageNo"] == 2
        assert QuizAttempt.query.count() == 0, "跳过就是没答"


def test_submitting_where_there_is_no_quiz_is_a_conflict(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()

        with pytest.raises(ConflictError) as caught:
            submit_quiz(session, option=QUIZ_OPTIONS[1])

        assert caught.value.code == 40901
        assert QuizAttempt.query.count() == 0


# --- 插话与章末讨论（§2.3 / P3-A3 / A4）---


def test_a_concept_page_gets_one_interjection_from_a_classmate(app):
    with app.app_context():
        _roles()
        session = sessions.start(
            _course([{"beats": ("一。", "二。", "三。"), "kind": "concept"}, {}]), ME
        )
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        client.clear()

        client.finish_page(beats=3)

        interjections = [frame for frame in client.of("speak") if frame["kind"] == "interject"]
        assert len(interjections) == 1, "每页最多一位（P3-A3）"
        assert interjections[0]["speakerKind"] == "student_ai"
        assert interjections[0]["speaker"]["code"] in ("xiaoxiao", "chenmo")
        assert interjections[0]["pageNo"] == 1
        # 插话不是讲稿，不带 beat（`beatId` 空）
        said = [frame["msg"] for frame in client.of("message") if not frame["msg"]["beatId"]]
        assert said and said[-1]["speakerKind"] == "student_ai"


def test_a_page_that_interjected_does_not_interject_again(app):
    with app.app_context():
        _roles()
        session = sessions.start(
            _course([{"beats": ("一。", "二。", "三。"), "kind": "concept"}, {}]), ME
        )
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        client.finish_page(beats=3)

        client.handle({"type": "seek", "pageNo": 1})  # 回头再讲一遍这一页
        client.finish_page(beats=3)

        assert len([f for f in client.of("speak") if f["kind"] == "interject"]) == 1
        assert state.get_flag(session, "interjectedPages") == [1]


def test_a_chapter_end_page_runs_the_discussion_and_returns_to_the_lecture(app):
    with app.app_context():
        _roles()
        session = sessions.start(
            _course(
                # 第二页开新章：讨论点挂在**每章最后一页**上（`timeline` 的口径），
                # 两页同章的话它会挂到第 2 页去，而这里要的是第 1 页章末
                [{"beats": ("这一章讲完了。",)}, {"chapter": 2}],
                chapters=[{"no": 1, "discussion": ["为什么先定标准再动手？"]}],
            ),
            ME,
        )
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        client.clear()

        client.handle({"type": "beat_done"})

        assert session.status == state.DISCUSSING
        client.tick()
        first = client.last("speak")
        assert first["kind"] == "discussion"
        assert first["speakerKind"] == "student_ai", "先由同学开口"

        speakers = {first["speakerKind"]}
        for _ in range(24):  # 每转一拍代表一句说完
            client.clock.advance(10)
            client.tick()
            speak = client.last("speak")
            if speak is not None:
                speakers.add(speak["speakerKind"])
            if session.status != state.DISCUSSING:
                break

        assert speakers == {"student_ai", "teacher"}, "一轮由同学开口、老师收束"
        assert session.status == state.LECTURE
        assert client.last("state")["pageNo"] == 2, "讨论完接着讲下一页"
        assert state.get_flag(session, "discussedPages") == [1]


def test_a_page_that_was_discussed_does_not_discuss_again(app):
    with app.app_context():
        _roles()
        session = sessions.start(
            _course(
                [{"beats": ("讲完了。",)}, {"chapter": 2}],
                chapters=[{"no": 1, "discussion": ["聊两句？"]}],
            ),
            ME,
        )
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        client.handle({"type": "beat_done"})
        for _ in range(24):
            client.clock.advance(10)
            client.tick()
            if session.status != state.DISCUSSING:
                break
        client.clear()

        client.handle({"type": "seek", "pageNo": 1})
        client.handle({"type": "beat_done"})

        assert [f for f in client.of("speak") if f["kind"] == "discussion"] == []
        assert session.status != state.DISCUSSING


def test_a_stale_beat_report_does_not_move_the_timeline(app):
    """多标签各报一次 `beat_done`：报的不是现在这一拍就不往前走（P3-A13）。

    两个标签页各自播各自的那一拍，谁先播完谁先报。不判 `beatId` 的话，同一句会被
    报两次，时间线凭空多走一格 —— 前端那道 `claimBeatReport` 只管得住一个标签页。
    """
    with app.app_context():
        _roles()
        session = sessions.start(_course([{"beats": ("一。", "二。", "三。")}, {}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()

        ids = [beat.id for beat in client.runtime.timeline.page(1).beats]
        assert len(ids) >= 3, "这一页要够三句才试得出「报的是别的一拍」"
        assert session.current_beat_idx == 0

        # 一个跑在前面的标签页报的是第 3 句 —— 现在还在第 1 句上
        client.handle({"type": "beat_done", "beatId": ids[2]})
        assert session.current_beat_idx == 0, "过期的上报不该让时间线往前走"

        # 报对了就照常走；整条时间线上都没有的号也照收（认不出来就不当陈旧）
        client.handle({"type": "beat_done", "beatId": ids[0]})
        assert session.current_beat_idx == 1
        client.handle({"type": "beat_done", "beatId": "认不出来的号"})
        assert session.current_beat_idx == 2


def test_the_discussion_ends_on_a_teacher_line(app):
    """讨论的最后一句必须是老师说的（P3-A4）。

    「同学提问 → 教师答 → 另一同学补充 → **教师收尾**」是 §7 A4 写的形状。
    轮数一用完就散场的话，讨论会停在一个同学的话头上，下一页的讲稿接上来像是
    把话岔开了 —— 回到讲授需要一个台阶，老师那句「回应 + 收束 + 递回话头」就是它。
    """
    with app.app_context():
        _roles()
        session = sessions.start(
            _course(
                [{"beats": ("这一章讲完了。",)}, {"chapter": 2}],
                chapters=[{"no": 1, "discussion": ["为什么先定标准再动手？"]}],
            ),
            ME,
        )
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        client.clear()

        client.handle({"type": "beat_done"})

        spoken: list[str] = []
        seen: set[str] = set()
        for _ in range(24):  # 每转一拍代表一句说完
            client.clock.advance(10)
            client.tick()
            speak = client.last("speak")
            # 按 turnId 去重：讨论收尾那一拍不再有新发言，`last("speak")` 拿到的
            # 还是上一条 —— 不去重就会把它数两遍。
            turn_id = str((speak or {}).get("turnId") or "")
            if speak is not None and speak.get("kind") == "discussion" and turn_id not in seen:
                seen.add(turn_id)
                spoken.append(str(speak.get("speakerKind") or ""))
            if session.status != state.DISCUSSING:
                break

        # 适中 = 2 轮：同学 → 老师 → 同学 → 老师（收尾）
        print("DEBUG spoken=", spoken, "clock=", client.clock.now)
        assert spoken == ["student_ai", "teacher", "student_ai", "teacher"]
        assert session.status == state.LECTURE, "收尾之后回到讲授"


def test_the_intensity_scale_is_bridged_to_the_scheduler(app):
    """设置里是 `low|medium|high`，调度器认 `低/适中/高`（桥在 `normalize_level`）。"""
    with app.app_context():
        assert scheduler.normalize_level("low") == "低"
        assert scheduler.normalize_level("medium") == "适中"
        assert scheduler.normalize_level("high") == "高"
        assert scheduler.normalize_level("高") == "高"
        assert scheduler.normalize_level("") == scheduler.DEFAULT_LEVEL
        assert scheduler.normalize_level("乱填的") == scheduler.DEFAULT_LEVEL


# --- 板书（§2.4 / P3-A8）---


def test_a_page_with_a_board_plan_publishes_its_strokes(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{"board_plan": True}]), ME)
        board.append_client_strokes(
            session,
            1,
            [
                {"tool": "polyline", "points": [[0.1, 0.1], [0.6, 0.2]]},
                {"tool": "text", "points": [[0.2, 0.3]], "text": "标准"},
            ],
        )
        client = _runtime(session, user_id=ME)

        client.hello()

        assert client.last("board")["pageNo"] == 1
        strokes = client.last("board")["strokes"]
        assert [item["tool"] for item in strokes] == ["polyline", "text"]
        assert strokes[1]["text"] == "标准"


def test_client_strokes_are_cleaned_and_broadcast(app):
    """学生端教具条的笔画：清洗一遍再落库回播（`board_sync` 是上课中的动作）。"""
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()
        client.clear()

        client.handle(
            {
                "type": "board_sync",
                "pageNo": 1,
                "strokes": [
                    {"tool": "polyline", "points": [[0.1, 0.1], [0.9, 0.9]]},
                    {"tool": "不认的工具", "points": [[0, 0], [1, 1]]},
                    {"tool": "polyline", "points": [[5, -3], [0.5, 0.5]]},
                ],
            }
        )

        strokes = client.last("board")["strokes"]
        assert [item["tool"] for item in strokes] == ["polyline", "polyline"]
        assert strokes[1]["points"] == [[1.0, 0.0], [0.5, 0.5]], "越界的点夹回边界"
        assert BoardStroke.query.count() == 2


def test_board_sync_with_a_broken_payload_is_rejected(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()

        client.handle({"type": "board_sync", "strokes": "两笔"})

        assert client.last("error")["code"] == str(ValidationError.code)


# --- 倍速与杂项 ---


def test_speed_is_clamped_and_announced(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()

        client.handle({"type": "speed", "value": 9})
        assert client.last("state")["speed"] == 2.0

        client.handle({"type": "speed", "value": 0.1})
        assert client.last("state")["speed"] == 0.5


def test_an_unknown_uplink_type_is_ignored_quietly(app):
    """P3-B3 的向前兼容：新版本前端多发一种消息，不该把课打断。"""
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.clear()

        client.handle({"type": "nonsense", "whatever": 1})

        assert client.frames == []
        assert client.alive is True


def test_a_frame_that_is_not_json_gets_an_error(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()

        client.handle("{不是 JSON")

        assert client.last("error")["code"] == "bad_message"


def test_a_speak_without_audio_is_timed_by_its_text(app):
    """没有音频时按字数估时长：到点自动收尾，课堂不会卡在一句话上。"""
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        client.play()

        client.clock.advance(1.0)
        client.tick()
        assert client.speaking is True, "一秒还没说完"

        client.clock.advance(60)
        client.tick()
        assert client.speaking is False
        assert len(client.of("speak_end")) == 1


def test_a_dead_peer_raises_instead_of_being_swallowed(app):
    """连接没了就得让路由知道 —— 吞掉它等于继续往一条断掉的 socket 喂事件。

    触发点是**只发给本人的那条 `error`**：它是这一层唯一还需要往 socket 上
    写字的地方（其余事件都是留档，由连接层自己扫着发）。
    """
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        runtime = ClassroomRuntime(session, emit=_explode, clock=Clock(), user_id=ME)

        with pytest.raises(PeerGone):
            runtime.handle({"type": "ask", "text": "老师？"})  # 还没开讲：要回一条 40901


def test_close_is_idempotent_and_takes_me_off_the_list(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()

        client.close(reason="bye")
        client.close(reason="bye")

        assert client.alive is False
        assert client.last("presence")["online"] == 0
        assert client.tick() is False
        assert sessions.summary(session)["presence"]["online"] == 0


def test_a_finished_class_refuses_playback_controls(app):
    with app.app_context():
        _roles()
        session = sessions.start(_course([{}]), ME)
        client = _runtime(session, user_id=ME)
        client.hello()
        sessions.end(session)
        client.clear()

        client.handle({"type": "play"})
        client.handle({"type": "pause"})
        client.handle({"type": "speed", "value": 1.5})

        assert [frame["code"] for frame in client.of("error")] == ["40901", "40901", "40901"]


def _explode(_data: str) -> None:
    raise OSError("对端没了")
