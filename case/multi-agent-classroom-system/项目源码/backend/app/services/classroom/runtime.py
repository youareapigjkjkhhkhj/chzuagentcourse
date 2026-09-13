"""课堂运行时：一条连接的语义层（§2.1 / §2.2 / §4.2 / P3-A1）。

与 P2 的 `RealtimeChannel` 是同一个位置的东西：**路由只做收发，课堂逻辑都在这里**。
理由也一样 —— 它能被测（Flask 的测试客户端做不了 WS 升级，契约只能打在这一层上）、
它认业务、它管账。

| 上行（§4.2） | 这一层做什么 |
|---|---|
| `hello` | 进课堂、认下 `afterSeq`（补发从那儿续上）、把这个连接该看的补上 |
| `play` / `pause` | 状态机转移 + 起/停当前发言 |
| `seek` | 终止当前发言（P3-A9）、跳到目标页、重发字幕/板书/测验 |
| `beat_done` | 推进时间线，触发插话、章末讨论、测验、板书 |
| `ask` / `chat` | 学生发言入消息流（过滤 + 限流），教师答疑 |
| `hand` | 举手 / 撤回 / 点名 |
| `board_sync` | 收下客户端笔画并回播 |
| `speed` | 倍速 |

三条纪律：

1. **单写者**：所有发言都从 `SpeechScheduler` 出（§2.2）。谁都不能直接说话，
   只能入队；这一层的 `tick()` 是唯一把排队的东西放出来的地方。
   被抢占的话**丢弃不补播** —— 补播会让课堂拖沓，而且那句话的时机已经过去了。
2. **事件一律经 `recorder.publish`，但递送不归这一层管**：`publish` 只做三件事 ——
   分配 `seq`、留档、返回写进去的那一份。谁该收到什么由连接层按留档扫
   （`take_pending()`，P3-3 每一拍调一次）。**在线投递与断线补发因此是同一条路径、
   同一份 dict**（P3-B2/B3）：不需要「广播」这第二个出口，也就不会出现
   「当场发出去的」与「存下来的」不一致。副产品是 HTTP 接口（P3-4）改了什么，
   WS 上的人自然会看到 —— 它同样只 `publish`。**状态改动不单独提交**：它总跟着
   一条事件，`publish` 的写入把同一事务里的改动一起提交 —— 少了这道提交，
   前端看到的状态会比库里新，刷新之后就会跳回去。
3. **位置与状态以会话行为准，不以客户端报的为准**（P3-A13）。两个标签页各报各的
   `resumeFrom` 时，谁说了算必须只有一处，否则它们会互相把对方拽回去。
   客户端报的位置只用来对账（`_check_resume_hint`，差得多就记一条日志）。
   **`self.session` 是这一条连接自己的那一份**（每个连接一个运行时），所以
   每条上行之前都要 `_sync()` 一次 —— 否则另一个标签页改过的状态在这条连接
   眼里永远停在入场那一刻，多标签就成了各说各话。

`emit` 只发**属于这一条连接**的帧（`error`）。它不是会话事实：别人的合规拦截、
别人发言过快，都不该广播给全班；它也不该占一个 `seq` —— 客户端拿最后一个
`seq` 去重连（`resumeFrom`），而一个不在留档里的号会让它此后一直对不上账。
**`emit` 抛异常表示对端没了**，这一层把它翻成 `PeerGone` 抛出去由路由收尾 ——
不能当成一次业务失败吞掉，否则一条已经断掉的连接会继续被喂事件。

几个由协议形状决定的约定，前端要照着做：

- §4.2 的下行**没有「这一轮说完了」的上行**（`beat_done` 报的是一个 beat，
  而插话/讨论/答疑都不是 beat）。所以非讲稿类发言的收尾由**服务端计时**
  （`_speak_ms`）：有音频用音频时长，没有就按字数估。**这个计时是兜底**：
  有音频的那些，真正收尾的是客户端的 `ended` —— 所以计时要把「客户端把音频
  播起来」那一截也算进去（`SPEAK_AUDIO_GRACE_MS`），否则兜底会先于音频的
  尾巴到，前端按它收声，每句话都少半个字。
- **两拍之间留一口气**（`_gap_before`）：上一拍说完了不立刻接下一句，换页比换句
  停得久一点 —— 幻灯片换了，学生得先看一眼那张图。这个节奏由服务端定
  （`Turn.not_before`），不是让每个客户端各播各的：刷新一下、换台机器进来，
  听到的课应该是同一个速度。
- **讲稿的音频是预合成的，答疑的是当场合成的**（P3-A5，`speech.answer_audio`）。
  所以答疑的 `speak.audioUrl` 可能为空 —— 前端要按「没音频就只显示文字、
  按 `speak_end` 收尾」写，不能假定每条 `speak` 都有声音。
- `typing` 紧挨在 `speak` 之前发，中间不留 300ms —— §6 让前端自己等这 300ms：
  服务端睡 300ms 会把整条轮询循环堵住，而它每 50ms 还要收包。
- **测验页作答之后，客户端要再报一次 `beat_done`**（等同于「继续」）。
  答题期间位置**不动**，答过的那一页记在 `state_json.quizDonePages` 里，
  所以那一次上报不会把题再弹一遍 —— 它就是「翻到下一页」那一步。
  在 `quiz_wait` 里再报一次 `beat_done` 则是「跳过这道题」。
- **历史消息不走 WS**：连上之后前端用 `GET /messages`（§4.1）拉最近几十条，
  之后靠 `message` 事件增量拼接。把历史当新事件发一遍会让 `seq` 虚高，
  而且那条消息的补发序号与它真实的归档序号对不上。
- 一分钟里没人说话也照常（心跳在连接层）—— 课堂的「停」只有暂停与下课两种。
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Mapping, Sequence

from flask import current_app

from app.common.errors import (
    AppError,
    ConflictError,
    RateLimitError,
    ValidationError,
)
from app.common.logging import get_logger
from app.extensions import db
from app.models import ClassroomSession, Course
from app.services.classroom import (
    board,
    interjection,
    prompts,
    recorder,
    roster,
    scheduler,
    sessions,
    speech,
    state,
)
from app.services.classroom import timeline as timeline_module
from app.services.classroom.scheduler import SpeechScheduler, Turn
from app.services.courses import store
from app.services.generation import filter as sensitive
from app.services.generation.llm import call_json
from app.services.provider_registry import get_registry

logger = get_logger("app.classroom.runtime")

#: 没有音频时按字数估一句话说多久（见模块 docstring）。系数按中文口播的常见语速取，
#: 宁可估长一点 —— 估短了会把老师的下一句叠上去。
SPEAK_BASE_MS = 1200
SPEAK_PER_CHAR_MS = 190
SPEAK_MIN_MS = 1500
SPEAK_MAX_MS = 20_000

#: 有音频的发言，兜底计时在音频时长之外再留这么久（毫秒）；长音频另按比例加
#: （`SPEAK_AUDIO_TAIL_RATIO`）。两者都由 `_audio_grace_ms` 合成一个数。
#:
#: 一段音频从服务端 `speak` 出去，到学生的扬声器里响起来，中间还有一段路：
#: 投递（50ms 一跳）、客户端缓冲与解码、播放器启动。而清单里的 `durationMs`
#: 是**这句话说到最后一个字**的时刻（`volc_tts._duration_ms` 取字级时间戳的末位）
#: —— 音频文件本身比它长，多出来的是收字的余韵与尾静音（实测 83 条：长出
#: 189~941ms，占这一句的 4%~15%）。
#:
#: 这一段不留够，服务端的 `speak_end` 就会**先于**学生的耳朵到达句尾：前端按它
#: 收声，每句话的最后半句被削掉 —— 线上那堂课 47 条讲稿发言**全都是**这么收的尾，
#: 没有一条是客户端 `ended` 报完的，每条削掉 167~527ms（一句里的最后一两个词）。
#:
#: **正常播放时这段余量根本不会被等**：让这一拍收尾的是客户端的 `ended`
#: （它知道音频真的播完了），这里的计时只是「音频压根没响」时的兜底
#: （浏览器拦了自动播放、地址失效）。兜底多等一会儿，比每句话削掉半个字强。
SPEAK_AUDIO_GRACE_MS = 2500

#: 长音频（答疑那类当场合成的，几十秒）的尾音按比例给：`durationMs` 短掉的那一截
#: 是**按比例**长的（同一门课里短的 4%、最长的 15%），一个定值盖不住 30 秒的答疑。
#: 取 25% —— 比实测最坏的一条（15.4%）再宽一倍，剩下的留给播放器启动。
SPEAK_AUDIO_TAIL_RATIO = 0.25

#: 换拍之间留的那口气（秒）：上一拍说完了，隔一下再说下一拍。
#:
#: 0 不是「快」，是「赶」—— 两句话首尾相接，听着像一个人在念稿子而不是讲课。
#: 两个值都放配置里（`CLASSROOM_BEAT_GAP` / `CLASSROOM_PAGE_GAP`）：它纯粹是
#: 口味，「讲得快不快」每个人感觉不一样，值给得再合理也不如让人自己调。
DEFAULT_BEAT_GAP_SEC = 0.6
DEFAULT_PAGE_GAP_SEC = 1.5

#: 一口气的上限（秒）。配置写歪了（比如 600）不能把课堂卡死：讲稿压在队列里等
#: 一个到不了的时刻，而 TTL 一到它就被丢掉了 —— 课就停在那儿不动了。
MAX_GAP_SEC = 10.0

#: 板书催生成的最短间隔（秒）。课堂不能等模型，所以板书是「丢后台生成、好了再发」；
#: 这个间隔就是「隔多久问一次后台好了没有」。
BOARD_RETRY_SEC = 2.0

#: 模型一时答不上来时老师说的话。**不编内容**：宁可承认没接上，也不能让一句
#: 编出来的答案进课堂记录（P3-A5 要的是「有一句回答」，不是「有内容」）。
FALLBACK_ANSWER = "这个问题我一时没想好怎么讲最清楚，我们先记下来，课后再补一段。"

#: 消息类型白名单（`models/classroom.py` 的 `MESSAGE_TYPES`）。
#: 这里是**运行时**再收一次：提示词/模型给的 `type` 不合法时不该让落库 500。
MESSAGE_TYPES = ("lecture", "question", "supplement", "reflect", "answer", "comment")

#: 讨论里允许的发言类型。老师的收束句一律按 `comment` 收敛。
DISCUSSION_TYPES = ("question", "supplement", "reflect", "answer", "comment")

#: 收下的作答文本最多留多少字（与 `quiz_attempts.option` 一样长）。
#: 这是「别把一整段话存进来」的兜底，**不是选项的长度上限**：选项是整句话，
#: 上限卡小了，判定就会拿截断过的串去比答案。
OPTION_MAX_CHARS = 255


class PeerGone(Exception):
    """对端没了（`emit` 抛出来的）。这一层不处理它，交给路由收尾。"""


# --- 宣布一件事（WS 上行与 HTTP 接口共用，P3-4 也调这几个）---


def announce_state(session: ClassroomSession) -> dict:
    """把「现在的状态」发出去（§4.2 `state`）。"""
    return recorder.publish(session, "state", state.snapshot(session).to_dict())


def announce_presence(session: ClassroomSession) -> dict:
    return recorder.publish(session, "presence", recorder.presence(session.id))


def announce_hand_queue(session: ClassroomSession) -> dict:
    return recorder.publish(session, "hand_queue", recorder.hand_queue(session.id))


def announce_board(session: ClassroomSession, page_no: int) -> dict:
    """这一页的板书（`GET /board/{pageNo}` 也是这份数据）。"""
    return recorder.publish(
        session,
        "board",
        {"pageNo": int(page_no), "strokes": board.strokes_of(session, page_no)},
    )


def quiz_question(page: timeline_module.TimelinePage) -> dict:
    """发给学生的题：**去掉答案与解析**。

    答案留在服务端（提交时判定），解析在 `quiz_result` 里给。把答案一起发下去，
    前端看一眼 network 就有答案了 —— 而这道题的意义正是「学生先答，再看到解析」。
    """
    quiz = dict(page.quiz or {})
    quiz.pop("answer", None)
    quiz.pop("explain", None)
    quiz["pageNo"] = page.page_no
    return quiz


def submit_quiz(
    session: ClassroomSession,
    *,
    option: str,
    response_ms: int = 0,
    timeline: timeline_module.Timeline | None = None,
) -> dict:
    """判一次作答（§4.1 `POST /quiz-submit`，HTTP 与 WS 共用）。

    一次作答**一行**（P6.1 要分开算第一次答对率与最终答对率），判定结果就是
    `quiz_result` 事件的载荷。判完把课推回 `lecture`：MVP 的「答错分支」只到
    文案（`branch=remedial`），补救讲解在 P6。

    **位置不动**：答完之后由客户端再报一次 `beat_done` 继续（见模块 docstring）。
    """
    state.require_interactive(session)
    line = timeline if timeline is not None else sessions.timeline_of(session)
    page = line.page(int(session.current_page_no or 0))
    if page is None or page.quiz is None:
        raise ConflictError(
            "这一页没有测验题", details={"pageNo": int(session.current_page_no or 0)}
        )
    quiz = page.quiz

    # 比对的是**整句选项文本**（题面 DSL 的 `answer` 就是其中一句话）。
    # 截断过一个 16 字的上限 —— 那是把 `option` 当成 A/B 键的写法，而它从来
    # 不是：示例课里最短的正确选项有 17 个字，截断之后**没有一个答案判得对**。
    chosen = str(option or "").strip()[:OPTION_MAX_CHARS]
    answer = str(quiz.get("answer") or "")
    correct = bool(chosen) and chosen == answer
    recorder.record_quiz(
        session.id,
        course_id=session.course_id,
        page_no=page.page_no,
        option=chosen,
        correct=correct,
        node_id=str(quiz.get("conceptTag") or ""),
        response_ms=int(response_ms or 0),
    )
    # 「这一页答过了」记在状态口袋里：位置不动，全靠这个记号让下一次 beat_done
    # 走「继续」而不是「再弹一次题」。
    _mark(session, "quizDonePages", page.page_no)
    event = recorder.publish(
        session,
        "quiz_result",
        {
            "pageNo": page.page_no,
            "correct": correct,
            "option": chosen,
            "answer": answer,
            "explain": str(quiz.get("explain") or ""),
            "branch": "pass" if correct else "remedial",
        },
    )
    if str(session.status or "") == state.QUIZ_WAIT:
        state.transition(session, state.LECTURE, reason="测验作答完成")
        announce_state(session)
    return event


def raise_hand(session: ClassroomSession, user_id: str) -> dict:
    """举手入队（§4.1 `POST /raise-hand`，HTTP 与 WS 共用）。返回 `{hand, position}`。"""
    state.require_interactive(session)
    result = recorder.raise_hand(session.id, user_id)
    announce_hand_queue(session)
    return result


def lower_hand(session: ClassroomSession, user_id: str) -> dict:
    """撤回举手。没举过也当成功 —— 前端的「取消」按钮不该因为连点两次报错。"""
    state.require_interactive(session)
    dropped = recorder.lower_hand(session.id, user_id)
    announce_hand_queue(session)
    return {"lowered": dropped}


def call_student(session: ClassroomSession) -> dict | None:
    """点名：队首那位从 `waiting` 变 `called`。返回他那行（队空返回 None）。"""
    called = recorder.call_next(session.id)
    if called is None:
        return None
    announce_hand_queue(session)
    return called


# --- 运行时 ---


class ClassroomRuntime:
    """一条课堂连接 = 一个运行时。"""

    def __init__(
        self,
        session: ClassroomSession,
        *,
        emit: Callable[[str], Any],
        timeline: timeline_module.Timeline | None = None,
        course: Course | None = None,
        user_id: str = "",
        name: str = "",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session
        #: 这条连接的私有出口。只发文本帧 —— 课堂没有二进制帧（音频走 HTTP）。
        self._emit_raw = emit
        self._clock = clock
        self.user_id = str(user_id or "")
        self._name = str(name or "")
        self._timeline = timeline
        self._course = course
        self._closed = False
        #: 这条连接已经收到哪个 `seq`（`take_pending` 的起点）。
        #: 0 表示「什么都还没收到」，`hello` 一来就会被改掉。
        self.deliver_after = 0
        #: 最近一次错误（路由与验收脚本要能回看「刚才为什么失败」）
        self.last_error = ""

        config = current_app.config
        self._scheduler = SpeechScheduler(
            clock=clock,
            ttl_sec=float(config.get("CLASSROOM_TURN_TTL") or scheduler.DEFAULT_TTL_SEC),
        )
        #: 正在说的那条从什么时候开始、预计说多久（队列不管起止时刻）
        self._speaking_since = 0.0
        self._speaking_ms = 0
        #: 章末讨论的现场（不在讨论里就是 None）
        self._discussion: dict[str, Any] | None = None
        #: 学生发言的时刻（P3-F2 的限流窗口）
        self._sent_at: list[float] = []
        #: 已经排队的插话页号 —— 内存里记一份，避免同一页连问两次模型。
        #: 落库那份（`interjectedPages`）记的是「真的说出口了」。
        self._interjects_queued: set[int] = set()
        #: 上一条**说出口的**发言在第几页（0 = 还没说过）。换拍之间那口气的长短
        #: 看它：同一页只是喘口气，换了页得先让学生看一眼那张幻灯片。
        self._spoken_page_no = 0
        #: 已经发过板书的页号 / 下次催生成的最早时刻
        self._board_done: set[int] = set()
        self._board_ask_at = 0.0
        #: 音频清单（懒建，一门课一次）：`{beatId: {url, durationMs}}`
        self._manifest: dict[str, dict[str, Any]] | None = None

    # --- 对外 ---

    @property
    def alive(self) -> bool:
        return not self._closed

    @property
    def finished(self) -> bool:
        """这堂课结束了 —— 路由据此收尾（§2.1：`ended` 是终态）。"""
        return str(self.session.status or "") == state.ENDED

    @property
    def timeline(self) -> timeline_module.Timeline:
        if self._timeline is None:
            self._timeline = sessions.timeline_of(self.session, course=self.course)
        return self._timeline

    @property
    def course(self) -> Course | None:
        if self._course is None:
            self._course = db.session.get(Course, self.session.course_id)
        return self._course

    @property
    def speaking(self) -> bool:
        return self._scheduler.speaking

    def state_payload(self) -> dict:
        return state.snapshot(self.session).to_dict()

    def take_pending(self, limit: int = 200) -> list[dict]:
        """这个连接还没收到的事件（按 `seq` 升序）。连接层每一拍调它一次。

        **交付只有这一条路径**（见模块 docstring 第 2 条）：在线投递与断线补发
        扫的是同一份留档，所以「补发出去的」与「别人当场看到的」不可能不一致。
        `limit` 是防一次性灌爆：留档积压时剩下的下一拍再取，`seq` 序不变。
        """
        events = recorder.replay(self.session.id, self.deliver_after, limit=limit)
        if events:
            self.deliver_after = int(events[-1]["seq"])
        return events

    def handle(self, message: str | bytes | Mapping[str, Any]) -> None:
        """处理一条上行消息。

        业务失败翻成 `error` 帧（带 `recoverable`）而不是抛穿到路由：
        前端要的是「这一条没成，课还在」，而不是一条悄悄断掉的 socket。
        `PeerGone` 例外 —— 对端没了就没有可以回话的对象。
        """
        payload = message if isinstance(message, Mapping) else _parse(message)
        if payload is None:
            self._fail("bad_message", "上行消息不是合法的 JSON 对象")
            return
        kind = str(payload.get("type") or "")
        handler = _UPLINK.get(kind)
        if handler is None:
            # 未知类型不致命（P3-B3 的向前兼容）：新版本前端多发一种消息，
            # 不该把整节课打断
            logger.debug("课堂：忽略未知上行类型 %r", kind)
            return
        self._sync()
        try:
            handler(self, payload)
        except AppError as exc:
            self._fail(str(exc.code), exc.message)
        except PeerGone:
            raise
        except Exception:  # 兜底：单条消息出错不该让整条通道崩掉
            logger.exception("课堂上行处理失败 type=%s", kind)
            self._fail("internal", "课堂处理这条消息时出错了")

    def _sync(self) -> None:
        """上行之前，先把这堂课的当前状态从库里读回来（P3-A13）。

        **每个连接有自己的运行时**（`channel._enter` 给每条连接新建一个），
        `self.session` 是它入场那一刻加载的那一行。另一个标签页把这堂课
        暂停了，这条连接手上的那一行还停在 `lecture` —— 于是它会
        用旧状态去判新消息：一条完全合法的 `pause` / `speed` 被
        `require_live` 挡回去（前端看到的只是「点了没反应」），
        而 `beat_done` 会在暂停中照样把时间线推走。两个标签页各说各话，
        正是 P3-A13 要挡的那件事。

        只在**上行**这一刻同步，不挂在 `tick()` 上：连接层每 50ms 走一拍，
        挂在那儿就是每条连接每秒 20 次查询。而状态只会被**人**改，
        改的那一刻必然伴随一条上行 —— 代价一次一条 SELECT。

        读不回来（课被真删了）就照旧往下走：让业务层去报它该报的错，
        同步失败本身不该变成一条 `internal`。
        """
        try:
            db.session.refresh(self.session)
        except Exception:
            logger.warning("课堂状态同步失败，按手上的这一份继续 session=%s", self.session.id)

    def tick(self) -> bool:
        """推进一拍：该收尾的收尾、该说话的把话说出来、该催的板书催一下。

        返回「这一拍做了事」—— 路由据此决定要不要顺手多发一次心跳。
        **这是唯一能让 `scheduler` 出声的地方**（单写者）。
        """
        if self._closed:
            return False
        self._expire_speaking()
        if self._scheduler.speaking:
            return False
        self._poll_board()
        turn = self._scheduler.next()
        if turn is not None:
            self._speak(turn)
            return True
        return False

    def close(self, *, reason: str = "closed") -> None:
        """收摊：清发言队列、把人从在线名单里摘掉。幂等。"""
        if self._closed:
            return
        self._closed = True
        self._scheduler.clear()
        self._discussion = None
        try:
            sessions.leave(self.session, self.user_id)
            announce_presence(self.session)
        except Exception:  # 收摊失败不该拦住路由关闭连接
            logger.exception("课堂收摊失败 session=%s", self.session.id)
        logger.info(
            "课堂连接收摊：session=%s user=%s reason=%s", self.session.id, self.user_id, reason
        )

    # --- 上行 ---

    def _on_hello(self, payload: Mapping[str, Any]) -> None:
        """进课堂：在线名单、定补发起点、把这个连接该看的补上。

        `resumeFrom` 只用来对账（P3-A10/A13）—— 重连之后「现在讲到哪」
        以会话行为准。

        **补发不在这里做**：这里只把起点交给 `take_pending()`（连接层每一拍扫一次）。
        带 `afterSeq` 的（重连）从那儿接着发；不带的是新来的，起点设成「此刻」——
        整堂课的历史不由 WS 重放（前端用 `GET /messages` 拉），所以新连接
        不会一上来就收到几百条旧事件。

        **正在讲的那一句要重开一轮**（见下面那段注释）：光把状态补上不够，
        客户端还得有一条 `speak` 才能把课推下去。
        """
        resume = payload.get("resumeFrom")
        hint = resume if isinstance(resume, Mapping) else {}
        after_seq = _int_of(payload.get("afterSeq") or hint.get("afterSeq") or hint.get("seq"))

        # 先认下游标再动手：下面发的每一条（在线名单、状态、字幕…）都该被这一条
        # 连接收到。反过来先发再定游标的话，「落在这里之后」的那几条会被跳过 ——
        # 而它们恰恰是这次进课堂最该看到的东西。
        self.deliver_after = (
            after_seq if after_seq > 0 else max(0, recorder.next_seq(self.session.id) - 1)
        )
        sessions.join(self.session, self.user_id, name=self._name)
        announce_presence(self.session)
        if hint:
            self._check_resume_hint(hint)

        announce_state(self.session)
        self._send_page_context()
        # 讲解中进来的人（刷新、换标签、断线重连）收不到这一句的 `speak`，
        # 而**时间线只由客户端的 `beat_done` 推进**：没人收到这一句，就没人上报，
        # 整堂课停在原地——状态、字幕都对，就是再也不往前走。
        # 所以把当前这一句重新开一轮（`_on_seek` 处理的是同一件事，那里的注释
        # 写的是「不出声的话客户端只能靠再报一次 beat_done 让课堂动起来，
        # 而那一次会把第一句直接跳过去」）。先掐掉上一轮：它要么是掉线那位
        # 没来得及收尾的，要么是同一个 beat 的旧轮次，留着就是两个人同时在说。
        #
        # **只在讲解里做**：讨论有服务端计时（`_expire_speaking`）自己往下走，
        # 等作答有 HTTP 提交，板书有计划在跑 —— 它们都不靠这一条 speak 续命，
        # 这时候再开一口反而会把它们插断。`idle` 与 `ended` 同理。
        if str(self.session.status or "") == state.LECTURE:
            self._interrupt("resume")
            self._speak_current_beat()
        logger.info(
            "课堂连接就位：session=%s user=%s 从 seq %s 起收",
            self.session.id,
            self.user_id,
            self.deliver_after,
        )

    def _on_play(self, _payload: Mapping[str, Any]) -> None:
        """开始/继续讲课：`idle → lecture`、`paused → 暂停前那个状态`。

        **不能用 `require_live`**：它认的「正在上课」不含 `idle`，而
        「开课还没讲」正是要在这里开讲（P3-B4 把这两个状态分开，就是为了
        让答题/举手在 `idle` 被挡住，而不是把开讲也挡住）。
        """
        current = str(self.session.status or "")
        self._require_not_ended()
        if current == state.IDLE:
            state.transition(self.session, state.LECTURE, reason="开始上课")
        elif current == state.PAUSED:
            state.transition(self.session, state.resume_target(self.session), reason="继续上课")
        announce_state(self.session)
        # 队列空着才起头：两个标签页都点了「开始」，话不该说两遍
        if not self._scheduler.speaking and not self._scheduler.pending:
            self._speak_current_beat()

    def _on_pause(self, _payload: Mapping[str, Any]) -> None:
        """暂停：冻结时间线，把正在说的话停下（被抢占的不补播）。

        这里可以用 `require_live`：没开讲的课没什么可暂停的，
        而它会把 `idle` 挡在外面（P3-A1 的「暂停是上课中的一个状态」）。
        """
        state.require_live(self.session)
        if str(self.session.status or "") != state.PAUSED:
            state.transition(self.session, state.PAUSED, reason="用户暂停")
        self._interrupt("pause")
        # 讨论被暂停就等于作罢：回来时接着讲，而不是接一句没人还记得的话
        self._discussion = None
        announce_state(self.session)

    def _on_seek(self, payload: Mapping[str, Any]) -> None:
        """跳页（P3-A9）：教师当前发言立即终止，页号与字幕同步到目标页。

        与 `play` 一样不从 `idle` 里挡：课前翻页看一遍是正常的动作，
        而它不改变课堂状态（只改位置）。
        """
        self._require_not_ended()
        page_no = _int_of(payload.get("pageNo"))
        page = self.timeline.page(page_no)
        if page is None:
            raise ValidationError(f"这门课没有第 {page_no} 页", details={"pageNo": page_no})
        self._interrupt("seek")
        self._discussion = None
        state.progress(self.session, self.timeline, page_no=page.page_no, beat_idx=0)
        announce_state(self.session)
        self._send_page_context()
        # 跳页之后接着从新位置讲。不出声的话，「跳到第 3 页」这一步就没人念，
        # 而客户端只能靠再报一次 `beat_done` 让课堂动起来 —— 那一次会把
        # 第 3 页的第一句直接跳过去（beat_idx 从 0 涨到 1）。
        # `idle`（课前翻页）不在此列：那时还没有人在讲。
        if str(self.session.status or "") in state.LIVE_STATUSES:
            self._speak_current_beat()

    def _on_beat_done(self, payload: Mapping[str, Any]) -> None:
        """一个 beat 播完了（前端上报）。时间线在这里往前走。

        走之前先看这一页要不要停下来做别的事：测验页弹题、章末页进讨论。

        **报上来的 `beatId` 对不上现在这一拍就不往前走**（P3-A13）：多开一个标签页
        时，两个标签各自播各自的那一拍，谁先播完谁先报 —— 不判一下，同一句会被报两次、
        时间线凭空多走一格（前端也拦了一道 `claimBeatReport`，但那只在**一个**标签页
        里管用）。认不出来的 `beatId` 一律照收：宁可多走一格，也不能因为一个新格式
        把整个课堂卡死在这儿。
        """
        state.require_live(self.session)
        page = self.timeline.page(int(self.session.current_page_no or 1))
        if page is None:
            return
        beat_idx = max(0, int(self.session.current_beat_idx or 0))
        if not self._beat_report_is_current(page, beat_idx, payload):
            return
        last_beat = beat_idx >= max(0, len(page.beats) - 1)
        self._finish_speaking()

        # 正在等作答时再报一次 beat_done 就是「跳过」——否则它会被当成「再弹一次题」，
        # 前端那个「跳过」按钮按下去就成了死循环
        quizzing = str(self.session.status or "") == state.QUIZ_WAIT
        if (
            last_beat
            and page.quiz
            and not quizzing
            and page.page_no not in _flags(self.session, "quizDonePages")
        ):
            self._enter_quiz(page)
            return

        state.advance(self.session, self.timeline)
        if (
            last_beat
            and page.discussion
            and page.page_no not in _flags(self.session, "discussedPages")
        ):
            self._start_discussion(page)
            return
        # 讨论优先于插话：章末该讨论的时候，同学那句「插一句」就不必了
        self._maybe_interject(page, beat_idx)
        announce_state(self.session)
        if state.at_end(self.session, self.timeline):
            self._end_class()
            return
        self._speak_current_beat()

    def _beat_report_is_current(
        self,
        page: timeline_module.TimelinePage,
        beat_idx: int,
        payload: Mapping[str, Any],
    ) -> bool:
        """这条 `beat_done` 报的是不是**现在这一拍**（见 `_on_beat_done`）。

        三种情况照收：没带 `beatId`（老客户端与验收脚本就是这么发的）、报的正是
        当前这一拍、报的号整条时间线上都没有（认不出来 —— 不拿它当陈旧）。
        只有「报的是这条时间线上**别的**某一拍」才判陈旧。
        """
        reported = str(payload.get("beatId") or "")
        if not reported or not page.beats:
            return True
        index = max(0, min(beat_idx, len(page.beats) - 1))
        current = str(page.beats[index].id or "")
        if not current or reported == current:
            return True
        if not any(str(beat.id or "") == reported for item in self.timeline.pages for beat in item.beats):
            return True
        logger.debug(
            "课堂：忽略过期的 beat_done（报的是 %s，现在是 %s）page=%s",
            reported,
            current,
            page.page_no,
        )
        return False

    def _on_ask(self, payload: Mapping[str, Any]) -> None:
        """被点名之后的提问（F3-7 / P3-A5）：学生说，老师答。

        顺序是「先打断、再说话」：反过来的话前端会先收到学生的 `speak`、
        再收到老师的 `speak_end`，看着像老师抢在提问之后才停口。
        """
        state.require_interactive(self.session)
        text = self._student_text(payload)
        page = self.timeline.page(int(self.session.current_page_no or 1))
        self._interrupt("ask")  # 学生提问可抢占除教师答疑外的一切（§2.2）
        self._speak_text(
            speaker_code=self.user_id or "me",
            speaker_name=self._name or "我",
            speaker_kind="me",
            text=text,
            kind="barge",
            message_type="question",
            page_no=page.page_no if page is not None else 0,
            quote_msg_id=str(payload.get("quoteMsgId") or ""),
        )
        self._answer(text, page)

    def _on_chat(self, payload: Mapping[str, Any]) -> None:
        """讨论区里发的消息：进消息流；点名问老师时老师才回答。

        普通发言**不发 `speak`**（`silent=True`）：没有音频要播，
        发一条只会让所有人的播放器多一次空转。消息本身照发 —— 讨论区靠它。
        """
        state.require_interactive(self.session)
        text = self._student_text(payload)
        page = self.timeline.page(int(self.session.current_page_no or 1))
        self._speak_text(
            speaker_code=self.user_id or "me",
            speaker_name=self._name or "我",
            speaker_kind="me",
            text=text,
            kind="chat",
            message_type="comment",
            page_no=page.page_no if page is not None else 0,
            silent=True,
        )
        if str(payload.get("target") or "") == "teacher":
            self._answer(text, page)

    def _on_hand(self, payload: Mapping[str, Any]) -> None:
        """举手 / 撤回 / 点名（P3-A5/A6）。"""
        state.require_interactive(self.session)
        action = str(payload.get("action") or "raise")
        if action == "lower":
            lower_hand(self.session, self.user_id)
            return
        if action == "call":
            self._interrupt("call")
            call_student(self.session)
            return
        raise_hand(self.session, self.user_id)
        # 老师停下来听问题（P3-A6：≤1s 内停止当前 beat）
        self._interrupt("hand")
        call_student(self.session)

    def _on_board_sync(self, payload: Mapping[str, Any]) -> None:
        """学生端教具条的笔画：清洗后落库，并把这一页的完整板书回播给所有人。"""
        state.require_interactive(self.session)
        page_no = _int_of(payload.get("pageNo")) or int(self.session.current_page_no or 1)
        strokes = payload.get("strokes")
        if not isinstance(strokes, Sequence) or isinstance(strokes, (str, bytes)):
            raise ValidationError("strokes 要是一个数组", details={"pageNo": page_no})
        board.append_client_strokes(self.session, page_no, strokes)
        announce_board(self.session, page_no)

    def _on_speed(self, payload: Mapping[str, Any]) -> None:
        """倍速。0.5~2.0 之外的由 `state.set_speed` 夹住，不报错。"""
        state.require_live(self.session)
        state.set_speed(self.session, _float_of(payload.get("value") or payload.get("speed")))
        announce_state(self.session)

    # --- 内部：发言 ---

    def _speak_current_beat(self) -> None:
        """把当前 beat 交给老师念（入队，等 `tick` 放出来）。"""
        page = self.timeline.page(int(self.session.current_page_no or 1))
        if page is None or not page.beats:
            return
        index = max(0, min(int(self.session.current_beat_idx or 0), len(page.beats) - 1))
        beat = page.beats[index]
        teacher = self._teacher()
        entry = self._beat_audio(beat.id)
        gap = self._gap_before(page.page_no)
        self._scheduler.enqueue(
            Turn(
                speaker_code=str(teacher.get("code") or "teacher"),
                speaker_name=str(teacher.get("name") or "老师"),
                speaker_kind="teacher",
                text=beat.text,
                kind="lecture",
                message_type="lecture",
                page_no=page.page_no,
                beat_ids=(beat.id,),
                audio_url=str(entry.get("url") or ""),
                # 清单已经在这一步读出来了，时长顺手带上 —— 不带的话
                # `_speak_ms` 要再查一次同一份清单
                duration_ms=_int_of(entry.get("durationMs")),
                ts=beat_started_iso(self.session, beat.start_ms),
                # 「上一拍说完了」到「这一句开口」之间留的那口气（见 `_gap_before`）。
                # 计时的是 enqueue 这一刻 —— 调用它的那条路（`_on_beat_done`）正是
                # 上一拍收尾的那一刻，两者是同一件事。
                not_before=self._clock() + gap if gap else 0.0,
            )
        )

    def _gap_before(self, page_no: int) -> float:
        """这一句开口之前先停多久（秒）。0 = 接着就说。

        **翻页比换句停得久**：换了幻灯片，学生得先看一眼那张图再听讲解；同一页里
        的下一句只是接着上一句说，喘口气就行。

        **头一句不留白**（`_spoken_page_no` 还是 0）：那是刚按下「开始上课」或者
        刚刷新进来，幻灯片早就在那儿了，再等一秒只是发呆。

        这一层只管讲稿。答疑、插话、讨论都不走这里 —— 它们由 `enqueue` 直接入队，
        `not_before` 是 0。
        """
        if not self._spoken_page_no:
            return 0.0
        if int(page_no or 0) != self._spoken_page_no:
            return _config_seconds("CLASSROOM_PAGE_GAP", DEFAULT_PAGE_GAP_SEC)
        return _config_seconds("CLASSROOM_BEAT_GAP", DEFAULT_BEAT_GAP_SEC)

    def _speak_text(
        self,
        *,
        speaker_code: str,
        speaker_name: str,
        speaker_kind: str,
        text: str,
        kind: str,
        message_type: str,
        page_no: int = 0,
        quote_msg_id: str = "",
        silent: bool = False,
    ) -> dict:
        """学生自己说的话：只进消息流（**不进发言队列**）。

        队列是「老师与 AI 同学谁先开口」的仲裁器；学生说的话本人已经确认过了，
        再排队等 AI 说完才出现就成了「我发的消息卡住了」。
        真人说话也**不需要 300ms 的 `typing`** —— 那个停顿是给 AI 留的。
        """
        message = recorder.add_message(
            self.session,
            speaker_code=speaker_code,
            speaker_kind=speaker_kind,
            type=message_type if message_type in MESSAGE_TYPES else "comment",
            text=text,
            page_no=page_no or None,
            quote_msg_id=quote_msg_id,
        )
        event = self._publish("message", {"msg": message})
        if not silent:
            self._publish(
                "speak",
                Turn(
                    speaker_code=speaker_code,
                    speaker_name=speaker_name,
                    speaker_kind=speaker_kind,
                    text=text,
                    kind=kind,
                    page_no=page_no,
                ).to_dict(),
            )
        return event

    def _speak(self, turn: Turn) -> None:
        """把一条发言放出去：`typing` → `speak` → `message` →（讲稿才有）`subtitle`。

        顺序不是随手排的：前端拿 `speak` 起播音频、拿 `message` 落讨论区、
        拿 `subtitle` 换底部字幕，三条各管一块 UI。
        """
        page = self.timeline.page(int(turn.page_no or 0)) if turn.page_no else None
        self._publish(
            "typing",
            {
                "speaker": {"code": turn.speaker_code, "name": turn.speaker_name},
                "pageNo": turn.page_no,
            },
        )
        message = recorder.add_message(
            self.session,
            speaker_code=turn.speaker_code,
            speaker_kind=turn.speaker_kind,
            type=turn.message_type if turn.message_type in MESSAGE_TYPES else "comment",
            text=turn.text,
            page_no=turn.page_no or None,
            beat_id=turn.beat_ids[0] if turn.beat_ids else "",
            audio_url=turn.audio_url,
            ts=turn.ts or None,
        )
        # 插话是「真的说出口了」才记（`interjection.mark_interjected` 的口径）
        if turn.kind == "interject" and turn.page_no:
            interjection.mark_interjected(self.session, int(turn.page_no))
        self._publish("speak", turn.to_dict())
        self._publish("message", {"msg": message})
        if page is not None and turn.beat_ids:
            self._announce_subtitle(page, turn.beat_ids[0], turn.text)
        # 「上一条说出口的发言在哪一页」——下一句要不要留出翻页的那口气看它
        # （`_gap_before`）。记在**真的说出口**这一刻，而不是入队那一刻：
        # 被抢占、被 TTL 丢掉的那些说不出口，也就不算讲过那一页。
        if turn.page_no:
            self._spoken_page_no = int(turn.page_no)

        self._speaking_since = self._clock()
        self._speaking_ms = self._speak_ms(turn)
        if self._scheduler.active is not turn:  # 直接调用的路径（测试、验收脚本）
            self._scheduler.begin(turn)

    def _finish_speaking(self) -> None:
        """当前这条说完了：前端报完了 beat，或计时到了。"""
        turn = self._scheduler.active
        if turn is None:
            return
        self._scheduler.finish(turn.turn_id)
        self._speaking_since = 0.0
        self._speaking_ms = 0
        self._publish("speak_end", {"turnId": turn.turn_id})
        self._after_turn(turn)

    def _expire_speaking(self) -> None:
        """到点就收尾：非讲稿类发言没有「说完了」的上行，只能自己计时。"""
        if not self._scheduler.speaking or not self._speaking_since:
            return
        if self._clock() - self._speaking_since >= self._speaking_ms / 1000.0:
            self._finish_speaking()

    def _after_turn(self, turn: Turn) -> None:
        """一条发言说完之后的衔接：讨论继续，答疑收尾。"""
        if turn.kind in ("lecture", "interject"):
            return
        if self._discussion is not None:
            self._advance_discussion()
            return
        if turn.kind == "answer":
            # 被点名的那位问完了（P3-A5 的最后一环）
            recorder.finish_called(self.session.id)
            announce_hand_queue(self.session)

    def _interrupt(self, reason: str) -> None:
        """打断：清队列，必要时把正在说的停下并告诉前端停声（§2.2）。"""
        result = self._scheduler.interrupt(reason)
        preempted = result["preempted"]
        self._speaking_since = 0.0
        self._speaking_ms = 0
        if preempted is not None:
            self._publish("speak_end", {"turnId": preempted.turn_id, "preempted": True})

    def _speak_ms(self, turn: Turn) -> int:
        """这条发言大概说多久（**服务端的兜底计时**）。有音频用音频时长，没有按字数估。

        三个来源，按可靠程度排：Turn 自带的 `duration_ms`（造它的那一步手上
        就有真值，比如当场合成的答疑）→ 按 `beat_ids` 查音频清单（讲稿）→
        按字数估。中间那条的判据是 `audio_url` 而不是 `beat_ids`：插话与讨论
        也挂在某一页上，但它们念的不是那个 beat 的音频，拿它的时长会把节奏带偏。

        **前两条都要再加一截余量（`_audio_grace_ms`）**：那是「客户端把这段音频
        播起来、播完」需要的时间。计时尺量的是音频多长，而这一段是从「服务端
        派发」量起的，清单里的时长又只到最后一个字 —— 不加这一截，兜底收尾
        一定赶在音频的尾巴前面（见那两个常量的说明：线上 47 条讲稿发言全是
        这么被削掉尾巴的，没有一条等到客户端的 `ended`）。
        """
        duration = int(turn.duration_ms or 0)
        if duration <= 0 and turn.audio_url and turn.beat_ids:
            duration = _int_of(self._beat_audio(turn.beat_ids[0]).get("durationMs"))
        if duration > 0:
            return duration + _audio_grace_ms(duration)
        estimated = SPEAK_BASE_MS + SPEAK_PER_CHAR_MS * len(turn.text or "")
        return max(SPEAK_MIN_MS, min(estimated, SPEAK_MAX_MS))

    def _answer(self, question: str, page: timeline_module.TimelinePage | None) -> None:
        """教师答疑（P3-A5）：一次 LLM 调用，入队等 `tick` 说出来。

        **不编内容**：模型失败时用 `FALLBACK_ANSWER`，而不是拿问题本身拼一句
        看起来像答案的话 —— 那会进课堂记录，而记录是要能回看的。
        """
        text = FALLBACK_ANSWER
        if page is not None:
            try:
                result = call_json(
                    get_registry().current_llm(),
                    prompts.answer_messages(
                        question, self._page_dsl(page.page_no), self._teacher(), self._recent()
                    ),
                    schema=prompts.SCHEMA_ANSWER,
                    timeout=turn_timeout(),
                )
                said = " ".join(str(result.data.get("text") or "").split())
                follow = " ".join(str(result.data.get("followUp") or "").split())
                if said:
                    text = said[: prompts.MAX_ANSWER_CHARS]
                    if follow:
                        text = f"{text} {follow[:60]}"
            except AppError as exc:
                logger.info("教师答疑跳过（用兜底话术）：%s", exc.message)

        hits = sensitive.scan(text)
        if hits:
            sensitive.record_hit(
                target="classroom_answer",
                owner_id=str(self.session.owner_id or ""),
                words=hits,
                outcome=sensitive.OUTCOME_BLOCKED,
                extra={"sessionId": self.session.id},
            )
            text = FALLBACK_ANSWER

        # 答疑是**当场合成**的（讲稿才有预合成）：配不上就按纯文字走，
        # 这一层绝不能因为上游 TTS 抖动就把答案本身弄没
        entry = speech.answer_audio(text)
        teacher = self._teacher()
        self._scheduler.enqueue(
            Turn(
                speaker_code=str(teacher.get("code") or "teacher"),
                speaker_name=str(teacher.get("name") or "老师"),
                speaker_kind="teacher",
                text=text,
                kind="answer",
                message_type="answer",
                page_no=page.page_no if page is not None else 0,
                audio_url=str(entry.get("url") or ""),
                duration_ms=_int_of(entry.get("durationMs")),
            )
        )

    # --- 内部：插话（§2.3）---

    def _maybe_interject(self, page: timeline_module.TimelinePage, beat_idx: int) -> None:
        """规则先筛，再由一次 LLM 调用决定说什么（超时/失败就跳过这一轮）。"""
        if page.page_no in self._interjects_queued:
            return
        allowed, reason = interjection.should_interject(
            self.session,
            page,
            beat_idx=int(beat_idx),
            min_pages=int(current_app.config.get("CLASSROOM_INTERJECTION_MIN_PAGES") or 3),
        )
        if not allowed:
            logger.debug("课堂：这一轮不插话（%s）", reason)
            return
        said = interjection.decide(
            self.session,
            self._page_dsl(page.page_no),
            self._classmates(),
            timeline_page=page,
            recent=self._recent(),
        )
        if said is None:
            return
        self._interjects_queued.add(page.page_no)
        self._scheduler.enqueue(Turn(**said.as_turn_kwargs(page_no=page.page_no)))

    # --- 内部：章末讨论（§2.2 / P3-A4）---

    def _start_discussion(self, page: timeline_module.TimelinePage) -> None:
        """进入讨论：按激烈程度定轮数与总时长上限。"""
        level = scheduler.normalize_level(self._intensity())
        question = page.discussion[0] if page.discussion else ""
        now = self._clock()
        self._discussion = {
            "page": page,
            "question": question,
            "rounds": scheduler.rounds_for(level),
            "seconds": scheduler.seconds_for(level),
            "round_no": 0,
            "last_kind": "teacher",
            "closed": False,
            "history": [],
            "started": now,
            "deadline": now + scheduler.seconds_for(level),
        }
        _mark(self.session, "discussedPages", page.page_no)
        state.transition(self.session, state.DISCUSSING, reason=f"章末讨论：{question}")
        announce_state(self.session)
        logger.info(
            "章末讨论开始：page=%s 轮数=%s 时长上限=%ss",
            page.page_no,
            self._discussion["rounds"],
            self._discussion["seconds"],
        )
        self._next_discussion_turn(student=True)

    def _advance_discussion(self) -> None:
        """一轮说完之后的下一步：同学说完老师接，老师接完下一轮，轮数用完由老师收尾。

        **最后一句一定要是老师说的**（P3-A4：同学提问 → 教师答 → 另一同学补充 →
        教师收尾）。轮数用完就散场的话，讨论会停在一个同学的话头上，接着讲下一页
        像是把话岔开了 —— 老师那句「回应 + 收束 + 把话头递回讲授」才是回到讲授的
        那个台阶（`prompts.discussion_turn_messages` 里老师那一轮本来就是这么写的）。
        """
        context = self._discussion
        if context is None:
            return
        if self._clock() >= context["deadline"]:
            logger.info("章末讨论到时长上限，收尾：page=%s", context["page"].page_no)
            self._finish_discussion()
            return
        if context["last_kind"] == "student":
            if int(context["round_no"]) < int(context["rounds"]):
                self._next_discussion_turn(student=False)
                return
            if not context["closed"]:
                context["closed"] = True
                self._next_discussion_turn(student=False)  # 老师收尾
                return
            self._finish_discussion()
            return
        if context["closed"]:
            # 收尾那句已经说完了，讨论到此为止（不然会绕回「再来一轮同学发言」）
            self._finish_discussion()
            return
        self._next_discussion_turn(student=True)

    def _next_discussion_turn(self, *, student: bool) -> None:
        """生成并排队讨论里的下一条发言。"""
        context = self._discussion
        if context is None:
            return
        page: timeline_module.TimelinePage = context["page"]
        if student:
            context["round_no"] = int(context["round_no"]) + 1
            speaker = self._pick_classmate(int(context["round_no"]))
            context["last_kind"] = "student"
        else:
            speaker = self._teacher()
            context["last_kind"] = "teacher"
        turn = self._discussion_turn(speaker, page, context)
        if turn is None:
            self._finish_discussion()
            return
        self._scheduler.enqueue(turn)

    def _discussion_turn(
        self, speaker: Mapping[str, Any], page: timeline_module.TimelinePage, context: dict
    ) -> Turn | None:
        """一次 LLM 调用换一句话。失败就收尾 —— 讨论不能卡在模型上（P3-D3）。"""
        try:
            result = call_json(
                get_registry().current_llm(),
                prompts.discussion_turn_messages(
                    str(context["question"]),
                    speaker,
                    self._page_dsl(page.page_no),
                    context["history"],
                    round_no=int(context["round_no"] or 1),
                ),
                schema=prompts.SCHEMA_DISCUSSION_TURN,
                timeout=turn_timeout(),
            )
        except AppError as exc:
            logger.info("讨论这一轮跳过：%s", exc.message)
            return None
        text = " ".join(str(result.data.get("text") or "").split())
        if not text:
            return None
        hits = sensitive.scan(text)
        if hits:
            sensitive.record_hit(
                target="classroom_discussion",
                owner_id=str(self.session.owner_id or ""),
                words=hits,
                outcome=sensitive.OUTCOME_BLOCKED,
                extra={"sessionId": self.session.id, "speaker": speaker.get("code")},
            )
            return None

        is_teacher = str(speaker.get("role") or "") == "teacher"
        message_type = str(result.data.get("type") or ("comment" if is_teacher else "supplement"))
        if message_type not in DISCUSSION_TYPES:
            message_type = "comment"
        text = text[: prompts.MAX_INTERJECTION_CHARS]
        context["history"].append({"speaker": speaker.get("name"), "text": text})
        return Turn(
            speaker_code=str(speaker.get("code") or ""),
            speaker_name=str(speaker.get("name") or ""),
            speaker_kind="teacher" if is_teacher else "student_ai",
            text=text,
            kind="discussion",
            message_type=message_type,
            page_no=page.page_no,
        )

    def _finish_discussion(self) -> None:
        """讨论收尾：回讲授，接着讲当前这一页（位置在进讨论前已经推到下一页）。"""
        self._discussion = None
        if str(self.session.status or "") == state.DISCUSSING:
            state.transition(self.session, state.LECTURE, reason="讨论结束")
        announce_state(self.session)
        if state.at_end(self.session, self.timeline):
            self._end_class()
            return
        self._speak_current_beat()

    # --- 内部：测验与板书 ---

    def _enter_quiz(self, page: timeline_module.TimelinePage) -> None:
        """弹题并等作答（P3-A7）。**位置不动**（见 `submit_quiz`）。"""
        state.transition(self.session, state.QUIZ_WAIT, reason="测验")
        announce_state(self.session)
        self._publish("quiz", quiz_question(page))

    def _poll_board(self) -> None:
        """板书：这一页有计划但还没有笔画的，丢后台生成，好了下一拍发出去。

        课堂不能等模型（P3-D3），所以这里**不**同步生成 —— `board.ensure` 在
        后台线程里跑，生成完落库。每一拍查一下有没有了，但每 `BOARD_RETRY_SEC`
        才查一次，免得每 50ms 一次查询。
        """
        page = self.timeline.page(int(self.session.current_page_no or 1))
        if page is None or not page.board_plan or page.page_no in self._board_done:
            return
        if board.strokes_of(self.session, page.page_no):
            self._board_done.add(page.page_no)
            announce_board(self.session, page.page_no)
            return
        now = self._clock()
        if now < self._board_ask_at:
            return
        self._board_ask_at = now + BOARD_RETRY_SEC
        board.submit_pregeneration(self.session.id, page.page_no)

    def _send_page_context(self) -> None:
        """把这个连接此刻该看到的东西补上：字幕、板书、（题目）、举手队列。

        断线重连与 `hello` 都走它 —— 前端刷新之后不该靠「再点一次」才看到
        自己停在哪儿。**历史消息不在这里补**（见模块 docstring）。
        """
        page = self.timeline.page(int(self.session.current_page_no or 1))
        if page is None:
            return
        if page.beats:
            index = max(0, min(int(self.session.current_beat_idx or 0), len(page.beats) - 1))
            beat = page.beats[index]
            self._announce_subtitle(page, beat.id, beat.text)
        if page.board_plan:
            self._board_done.discard(page.page_no)
            self._board_ask_at = 0.0
            self._poll_board()
        if str(self.session.status or "") == state.QUIZ_WAIT and page.quiz:
            self._publish("quiz", quiz_question(page))
        announce_hand_queue(self.session)

    def _announce_subtitle(
        self, page: timeline_module.TimelinePage, beat_id: str, text: str
    ) -> None:
        self._publish("subtitle", {"beatId": beat_id, "text": text, "pageNo": page.page_no})

    # --- 内部：下课 ---

    def _end_class(self) -> None:
        """最后一页讲完：转 `ended` 并写下那条 `state`（§2.1 的终态）。

        走 `sessions.end`：它是唯一写 `ended_at` 的地方，也是唯一会把
        「已经结束了」当成功的地方（两处都判会各写一份结束时刻）。
        下课这件事不单独发：`state` 事件一落，所有连接下一拍都会收到
        （路由另外靠 `finished` 收尾，见连接层）。
        """
        self._scheduler.clear()
        self._discussion = None
        sessions.end(self.session, reason="讲完了")
        logger.info(
            "课堂结束：session=%s 共 %s 条消息",
            self.session.id,
            recorder.message_count(self.session.id),
        )

    # --- 内部：下行 ---

    def _publish(self, type: str, payload: Mapping[str, Any]) -> dict:
        """写进这条会话的事件流（留档即交付，见模块 docstring 第 2 条）。"""
        return recorder.publish(self.session, type, payload)

    def _emit(self, data: str) -> None:
        try:
            self._emit_raw(data)
        except Exception as exc:  # 对端没了：交给路由收尾，别在这儿当成业务失败
            raise PeerGone(str(exc)) from exc

    def _fail(self, code: str, message: str, *, recoverable: bool = True) -> None:
        """一条**只发给发信人**的 `error` 帧（不落库、不带 `seq`，见模块 docstring）。"""
        self.last_error = message
        logger.warning("课堂错误 code=%s msg=%s", code, message)
        self._emit(
            json.dumps(
                {"type": "error", "code": code, "message": message, "recoverable": recoverable},
                ensure_ascii=False,
            )
        )

    # --- 内部：上下文 ---

    def _student_text(self, payload: Mapping[str, Any]) -> str:
        """学生发来的话：截断到上限、过敏感词（P3-F3）、过限流（P3-F2）。"""
        raw = " ".join(str(payload.get("text") or "").split())
        if not raw:
            raise ValidationError("说点什么再发")
        limit = int(current_app.config.get("CLASSROOM_MAX_MESSAGE_CHARS") or 500)
        text = raw[:limit]
        hits = sensitive.scan(text)
        if hits:
            sensitive.record_hit(
                target="classroom_message",
                owner_id=self.user_id,
                words=hits,
                outcome=sensitive.OUTCOME_BLOCKED,
                extra={"sessionId": self.session.id},
            )
            raise ValidationError("这句话里有不适合课堂出现的内容，换一种说法吧")
        self._check_rate()
        return text

    def _check_rate(self) -> None:
        """连续发言限流（P3-F2：默认 > 5 条 / 10s 触发）。"""
        window = float(current_app.config.get("CLASSROOM_RATE_LIMIT_WINDOW") or 10.0)
        limit = int(current_app.config.get("CLASSROOM_RATE_LIMIT_COUNT") or 5)
        now = self._clock()
        self._sent_at = [moment for moment in self._sent_at if now - moment < window]
        if limit > 0 and len(self._sent_at) >= limit:
            raise RateLimitError(
                "发得太快了，等一会儿再说",
                details={"windowSec": window, "limit": limit},
            )
        self._sent_at.append(now)

    def _page_dsl(self, page_no: int) -> dict[str, Any]:
        """这一页的 DSL（提示词要的 `bullets` / `narration` / `boardPlan`）。"""
        course = self.course
        if course is None:
            return {}
        row = store.page_by_no(course, int(page_no))
        if row is None:
            return {}
        dsl = dict(row.dsl or {})
        dsl.setdefault("pageNo", row.page_no)
        dsl.setdefault("kind", row.kind)
        dsl.setdefault("title", row.title or "")
        return dsl

    def _recent(self, limit: int = prompts.RECENT_TURNS) -> list[dict]:
        """最近几条发言（提示词的上下文）。"""
        return recorder.messages(self.session.id, size=max(1, int(limit)))[0]

    def _teacher(self) -> dict[str, Any]:
        return roster.teacher()

    def _classmates(self) -> list[dict[str, Any]]:
        """这堂课的同学。**与在线名单同源**（`roster`）—— 讨论里第 4 位同学
        开口、名单上却只列着 3 位，是同一件事的两种说法对不上。"""
        return roster.classmates()

    def _pick_classmate(self, index: int) -> dict[str, Any]:
        """讨论里轮流让同学发言（不是同一个人说三轮）。"""
        people = self._classmates()
        if not people:
            return {"code": "student", "name": "同学", "role": "student", "persona": {}}
        return people[(max(1, int(index)) - 1) % len(people)]

    def _intensity(self) -> str:
        """讨论激烈程度：设置里的那一档（P1 生成时用的就是它）。"""
        from app.services import settings_service

        try:
            return str(settings_service.get_generation().get("intensity") or "")
        except Exception:  # 设置读不出来不该让讨论开不起来
            logger.debug("课堂：读不到生成设置，讨论按默认激烈程度")
            return ""

    def _beat_audio(self, beat_id: str) -> dict[str, Any]:
        """这个 beat 的音频（`{url, durationMs}`）。没有就返回空 dict。

        清单懒建一次：`assets.manifest` 要为每个 beat 查一次资产，
        每句话都查一遍就成了「讲得越久越慢」。
        """
        if not beat_id:
            return {}
        if self._manifest is None:
            self._manifest = self._build_manifest()
        return self._manifest.get(beat_id) or {}

    def _build_manifest(self) -> dict[str, dict[str, Any]]:
        from app.services.voice import assets as voice_assets
        from app.services.voice import prefs as voice_prefs

        course = self.course
        if course is None:
            return {}
        try:
            manifest = voice_assets.manifest(
                course,
                voice_prefs.narration_settings(course),
                provider=voice_prefs.tts_provider_or_none(),
            )
        except Exception:  # 音频查不到就当没有声音：课堂不靠音频也能走
            logger.exception("课堂：读音频清单失败 course=%s", course.id)
            return {}
        return {str(item.get("beatId") or ""): item for item in (manifest.get("beats") or [])}

    def _require_not_ended(self) -> None:
        """下课的课不能再动（§2.1 的终态）。

        `idle` 与五个进行中的状态都放行 —— 这条判据只在回答「还能不能动」，
        「现在该不该动」由各自的转移规则决定。
        """
        if str(self.session.status or "") == state.ENDED:
            raise ConflictError("课堂已结束", details={"status": state.ENDED})

    def _check_resume_hint(self, hint: Mapping[str, Any]) -> None:
        """客户端报的恢复位置只用来对账（P3-A10/A13）。

        位置以会话行为准：两个标签页各报各的，若客户端说了算，
        它们会互相把对方拽回去。
        """
        page_no = _int_of(hint.get("pageNo"))
        actual = int(self.session.current_page_no or 0)
        if page_no and page_no != actual:
            logger.info(
                "课堂重连：客户端报第 %s 页，会话在 %s 页，按会话行恢复", page_no, actual
            )


# --- 上行分派表（与 P2 的 `_UPLINK` 同一个理由：一张表比一条 if 链好读）---

_UPLINK: dict[str, Callable[[ClassroomRuntime, Mapping[str, Any]], None]] = {
    "hello": ClassroomRuntime._on_hello,
    "play": ClassroomRuntime._on_play,
    "pause": ClassroomRuntime._on_pause,
    "seek": ClassroomRuntime._on_seek,
    "beat_done": ClassroomRuntime._on_beat_done,
    "ask": ClassroomRuntime._on_ask,
    "chat": ClassroomRuntime._on_chat,
    "hand": ClassroomRuntime._on_hand,
    "board_sync": ClassroomRuntime._on_board_sync,
    "speed": ClassroomRuntime._on_speed,
}


# --- 小工具 ---


def turn_timeout() -> float:
    """课堂里等一次模型的上限（秒）。

    与插话决策共用 `CLASSROOM_INTERJECTION_TIMEOUT`：两个数是同一件事 ——
    **课堂不能等模型**（P3-D3）。分开配只会让两边慢慢配成不同的值。
    """
    return float(current_app.config.get("CLASSROOM_INTERJECTION_TIMEOUT") or 3.0)


def beat_started_iso(session: ClassroomSession, start_ms: int) -> str:
    """beat 在时间线上的位置换算成墙上时间（讲稿消息的 `ts`）。

    讲稿消息的时间戳是**它在课堂时间线上的位置**，不是落库的那一刻
    （`ClassroomMessage` 的模型注释写着为什么）。`started_at` 是这节课的零点：
    讲稿从 0:00 开始，进度条上的 07:32 与记录里第 7 分钟那句话因此对得上。
    """
    from datetime import timedelta

    from app.common.timeutil import parse_iso, to_iso

    base = parse_iso(str(session.started_at or ""))
    if base is None:
        return ""
    return to_iso(base + timedelta(milliseconds=max(0, int(start_ms or 0))))


def _mark(session: ClassroomSession, key: str, page_no: int) -> None:
    """往状态口袋里记一个页号（`quizDonePages` / `discussedPages`），只留最近 20 个。"""
    pages = _flags(session, key)
    pages.add(int(page_no))
    state.set_flags(session, **{key: sorted(pages)[-20:]})


def _flags(session: ClassroomSession, key: str) -> set[int]:
    return {int(item) for item in (state.get_flag(session, key) or [])}


def _audio_grace_ms(duration_ms: int) -> int:
    """一段音频的兜底余量（毫秒）：定值起步，长的按比例加。

    两个常量各自管一半：`SPEAK_AUDIO_GRACE_MS` 盖住「播放器启动 + 短句的尾音」，
    `SPEAK_AUDIO_TAIL_RATIO` 盖住「几十秒的音频尾巴上按比例长出来的那一截」。
    取大的那个 —— 这一头宁可贵一点（音频没响时多等一会儿），也不能削掉尾音。
    """
    return max(SPEAK_AUDIO_GRACE_MS, int(int(duration_ms) * SPEAK_AUDIO_TAIL_RATIO))


def _config_seconds(name: str, default: float) -> float:
    """配置里的一段时间（秒），夹在 `[0, MAX_GAP_SEC]` 里。

    读不出来（没配、配成空串、配成别的字）就用默认值 —— 一个配错的数不该把
    整堂课停住，而这几处都是「多等一会儿」和「不等」的区别，不值得报错。
    """
    try:
        raw = current_app.config.get(name)
        if raw is None or not str(raw).strip():
            return float(default)
        return max(0.0, min(float(raw), MAX_GAP_SEC))
    except (TypeError, ValueError):
        return float(default)


def _parse(raw: Any) -> Mapping[str, Any] | None:
    if not isinstance(raw, (str, bytes, bytearray)):
        return None
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, ValueError, TypeError):
        return None
    return data if isinstance(data, Mapping) else None


def _int_of(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_of(value: Any) -> float:
    try:
        return float(value or 1.0)
    except (TypeError, ValueError):
        return 1.0


__all__ = [
    "FALLBACK_ANSWER",
    "OPTION_MAX_CHARS",
    "PeerGone",
    "announce_board",
    "announce_hand_queue",
    "announce_presence",
    "announce_state",
    "beat_started_iso",
    "call_student",
    "lower_hand",
    "quiz_question",
    "raise_hand",
    "submit_quiz",
    "turn_timeout",
]
