"""实时语音的**语义层**（P2-B1 / §4.2）。

浏览器那条通道（`/ws/voice/realtime`）收发的不是火山的事件名，而是本项目自己的
一套词：`start / audio / barge_in / stop` 上行，`ready / asr / reply / audio /
barge_in_ack / error / done` 下行。前端出现任何上游事件名都算我们没翻译干净 ——
翻译只在 `providers/tts/volc_realtime.py` 与本模块两处发生，而且各翻各的一半：
Provider 把上游 JSON 翻成语义事件（`RealtimeEvent`），本模块把语义事件翻成
**给浏览器的帧**（JSON 文本帧 + 二进制音频帧）。

为什么这一层要被单独拎出来、而不是写在 WS 路由里：

1. **它要能被测。** Flask 的测试客户端不能做 WebSocket 升级，契约测试
   （P2-B1：start → ready → audio/reply → done 全序列）只能打在语义层上 ——
   路由里只剩 `Server.accept()` 与两个转发。测一条协议，不该先起一个真端口。
2. **它要认业务。** `start` 里带的是 `roleCode` / `context.courseId`，
   服务端据此定音色、拼系统提示词、从课程术语表取热词（P2-A20）。
3. **它要管账。** 一次会话算多少钱，得在会话关闭时写进 `usage_records`
   （P2-A11/C3）—— 这件事与「怎么把帧转给浏览器」无关。

**收发是单线程轮询**：每轮先收上游（最多 `POLL_SECONDS`），再看浏览器有没有
发东西来。两端都在推流的场景通常用两个线程，但 `VolcRealtimeSession` 的
`receive(timeout)` 本来就是非阻塞的（它的 docstring 写着「让调用方（WS 代理）
有机会做别的事」），单线程轮询因此实现简单、没有共享状态、也不会有两个线程
同时往一条 socket 上写。代价是 ~100ms 量级的往返延迟，课堂对话里听不出来。
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any, Protocol
from uuid import uuid4

from app.common.errors import AppError, RateLimitError, StateError
from app.common.logging import get_logger
from app.models import Course
from app.providers.base import MODE_KEEP_ALIVE, MODE_PUSH_TO_TALK
from app.services.voice import prefs as voice_prefs
from app.services.voice import sessions
from app.services.voice.assets import glossary_for
from app.services.voice.policy import FALLBACK_BROWSER, FALLBACK_TEXT, fallback_for
from app.services.voice.usage import model_of
from app.services.voice.usage import record as record_usage

logger = get_logger("app.voice.realtime")

#: 轮询间隔（秒）。上游一次收包最多等这么久，浏览器一侧同理。
#: 它同时是「一轮的往返延迟上限」：两端各等一次，最坏 ~2×。
POLL_SECONDS = 0.05

#: 学生松开按键之后，我们替他继续推静音的上限（秒）。
#:
#: **上游是「有音频流才判停出回答」的**：松开按键就断流的话，这一轮永远等不到
#: 回答 —— 前端看起来是「按了没反应」。真机对照实验（同一段 3 秒语音）：
#: commit 之后断流 → 30 秒里只回 `barge_in`，没有任何回答；commit 之后继续推
#: 静音 → 识别、字幕、语音、`done` 全到齐。上限只是兜底：正常一轮几秒就结束了。
TURN_FEED_SECONDS = 20.0

#: 一包 20ms 的静音（16k / int16 / mono = 640 字节），与 Provider 的分包一致。
SILENCE_PACKET = bytes(640)

#: 下行事件的完整集合。前端只认这些词（P2 §4.2）。
#: 与文档给的清单相比多两个，都是我们自己的词而非上游事件名：
#: - `barge_in`：服务端驱动的打断（上游识别到学生开口），前端据此立刻停播；
#: - `closed`：会话正常结束（`stop` 之后），前端据此收尾而不是当成掉线。
DOWN_TYPES = (
    "ready",
    "asr",
    "reply",
    "audio",
    "barge_in",
    "barge_in_ack",
    "error",
    "done",
    "closed",
)

#: 前端的 `mode` → 上游的 `input_mod`（§5.3-B6）。
#: 前端说的是业务语言（「语音问答」「研讨」），上游说的是输入模式 ——
#: 中间的翻译只此一处，认不出来的按默认的按住说话处理。
MODE_MAP: dict[str, str] = {
    "voice_chat": MODE_PUSH_TO_TALK,
    "push_to_talk": MODE_PUSH_TO_TALK,
    "discussion": MODE_KEEP_ALIVE,
    "keep_alive": MODE_KEEP_ALIVE,
}


class ChannelClosed(Exception):
    """浏览器那一端断了（关标签页、切网络）。"""


class Transport(Protocol):
    """通道面向的「另一头」：能收一条、能发一条。

    WS 路由用 `simple_websocket.Server` 实现它，测试用一只假的。
    故意只有两个方法 —— 接口越窄，假的那个越好写，越不容易假得不像。
    """

    def receive(self, timeout: float) -> str | bytes | None:
        """收一条消息。到点没数据返回 None（**不抛异常**）。"""

    def send(self, data: str | bytes) -> None:
        """发一条消息。对端已断时抛 `ChannelClosed`。"""


class Turn:
    """一轮对话的计数（`start` 到下一次 `done`）。

    字幕与用量都按轮算：`done` 里报的是**这一轮**说了多少字，
    整节课的量则累积在 `RealtimeChannel` 上（关闭时写成一条账）。
    """

    __slots__ = ("asr_chars", "first_frame_ms", "reply_chars")

    def __init__(self) -> None:
        self.asr_chars = 0
        self.reply_chars = 0
        self.first_frame_ms = 0


class RealtimeChannel:
    """一次浏览器连接 = 一个通道 = 一次上游会话。

    生命周期：`handle({"type": "start"})` 建会话，之后 `audio` / `barge_in` /
    `stop` 都是对这条会话的操作；`run()` 负责「收浏览器 → 发上游」与
    「收上游 → 发浏览器」的轮询。
    """

    def __init__(
        self,
        provider: Any,
        *,
        emit,
        course: Course | None = None,
        resolve_course=None,
        session_id: str = "",
        owner_id: str = "",
        clock=time.monotonic,
    ) -> None:
        self.provider = provider
        #: 下行出口。WS 路由给的是 `socket.send`，测试给的是往列表里追加。
        self._emit_raw = emit
        self.course = course
        #: `start.context.courseId` → 课程。**懒查**：路由在 `accept()` 那一刻
        #: 还不知道学生要上哪门课，那个 id 在 `start` 里才到。查不到返回 None。
        self._resolve_course = resolve_course
        self.session_id = str(session_id or "")
        #: 这一条通道算谁的（P2-F5 的并发上限按人算）。空串表示不判 ——
        #: 没有归属人就无从判断「同一个人」，那种情况下宁可放行。
        self.owner_id = str(owner_id or "")
        #: 名额凭据。**每条通道一个**，与服务端账本上的 `session_id` 无关：
        #: 那个值来自前端，两条连接报同一个就都成了「同一次会话」，上限白设。
        self._slot = f"{self.session_id or 'session'}:{uuid4().hex[:12]}"
        self._clock = clock

        self._session: Any = None
        self._closed = False
        #: 名额占上了没有。释放要按它来，否则一条从没 start 过的通道
        #: 也会去「还」一个不是它的名额（见 sessions.release 的说明）。
        self._claimed = False
        self._started_at = 0.0
        self._seq = 0
        self._turn = Turn()
        self._session_asr_chars = 0
        self._session_reply_chars = 0
        #: 替学生补静音的截止时刻（`None` = 不用补）。见 `TURN_FEED_SECONDS`。
        self._feed_until: float | None = None
        self._upstream_usage: dict[str, Any] = {}
        self._role_code = "teacher"
        self.last_error = ""

    # --- 对外 ---

    @property
    def alive(self) -> bool:
        return self._session is not None and not self._closed

    def run(self, transport: Transport) -> None:
        """轮询到结束（浏览器发 `stop`、断开，或上游彻底失败）。"""
        try:
            while not self._closed:
                try:
                    self._pump()
                except AppError as exc:
                    # 收包路径上的业务失败（上游连接断了、鉴权过期）。翻成 error 帧
                    # 带 `fallback` 发出去 —— 前端要的是「退到哪条路」，
                    # 而不是一个悄悄不响了的 socket。
                    self._fail(str(exc.code), exc.message, fallback=fallback_for(exc))
                    break
                if self._closed:
                    break
                self._feed_silence()
                message = transport.receive(timeout=POLL_SECONDS)
                if message is not None:
                    self.handle(message)
        except ChannelClosed:
            logger.debug("实时语音：浏览器一侧断开")
        finally:
            self.close(reason="transport_closed")

    def handle(self, message: str | bytes | Mapping[str, Any]) -> None:
        """处理一条上行消息：JSON 文本帧按 `type` 分派，二进制帧当作音频。

        **分派整段都在 `try` 里**：二进制那条路一样会失败（还没 `start` 就推流），
        把它留在 catch 外面，一次坏输入就抛穿到路由层 —— 而那里没人在听，
        前端看到的是 socket 悄悄断掉，没有 `fallback` 也没有原因。
        """
        audio_frame = bytes(message) if isinstance(message, (bytes, bytearray)) else None
        kind = "audio:binary" if audio_frame is not None else ""
        try:
            if audio_frame is not None:
                # 二进制帧 = 音频。文档里它前面还有一条 `{"type":"audio","seq":n}`，
                # 但浏览器直接 `ws.send(arrayBuffer)` 也是合法用法 —— 两种都收。
                self._on_audio(audio_frame)
                return

            payload = message if isinstance(message, Mapping) else _parse(message)
            if payload is None:
                self._fail("bad_message", "上行消息不是合法的 JSON 对象", fallback=FALLBACK_TEXT)
                return

            kind = str(payload.get("type") or "")
            handler = _UPLINK.get(kind)
            if handler is None:
                # 未知类型不致命：一次协议扩展期的新消息，不该把整节课打断
                logger.debug("实时语音：忽略未知上行类型 %r", kind)
                return
            handler(self, payload)
        except AppError as exc:
            self._fail(str(exc.code), exc.message, fallback=fallback_for(exc))
            self.close(reason="error")
        except Exception:  # 兜底：单条消息出错不该让整条通道崩掉
            logger.exception("实时语音上行处理失败 type=%s", kind)
            self._fail("internal", "实时语音处理失败", fallback=FALLBACK_BROWSER)

    def close(self, *, reason: str = "stopped") -> None:
        """关会话。**先告诉上游再断**（不等回执会被判成 55100001 一类取消）。

        一次会话只关一次；`stop` 与连接断开都走到这里，所以这里必须是幂等的。
        """
        if self._closed:
            return
        self._closed = True
        session, self._session = self._session, None
        if self._claimed:
            # 还名额：正常结束、浏览器断开、上游失败三条路都会走到这里
            self._claimed = False
            sessions.release(self.owner_id, self._slot)
        if session is not None:
            try:
                session.close()
            except Exception:  # 兜底：关闭失败不该拦住后面的记账
                logger.exception("实时语音会话关闭失败")
            try:
                self._emit({"type": "closed", "reason": reason})
            except ChannelClosed:
                # 对端已经走了（这正是 close 最常见的触发原因）。
                # 这一帧本就是「你可以收工了」的通知，收不到也无所谓 ——
                # 但它绝不能拦住下面的记账。
                logger.debug("实时语音：对端已断，closed 帧没发出去")
        self._settle()

    # --- 上行 ---

    def _on_start(self, payload: Mapping[str, Any]) -> None:
        """建会话并回 `ready`。重复的 `start` 直接忽略（同一条通道只有一个会话）。"""
        if self._session is not None:
            logger.debug("实时语音：重复的 start，已忽略")
            return
        # 会话号只用于记账（`usage_records.ref_id` 是 32 字符），客户端给不给都行
        self.session_id = str(payload.get("sessionId") or self.session_id or "session")[:32]
        # 占名额要在**建上游会话之前**：占了才发现建不起来，代价只是一次多余的
        # 上游连接；反过来（先建后用不了）会白留一条上游会话在那里。
        self._claimed = sessions.claim(self.owner_id, self._slot, clock=self._clock)
        if not self._claimed:
            # 抛出去由 handle() 翻成带 fallback 的 error 帧：前端据此退到文字问答，
            # 而这条通道自己收尾（close 会走 finally）
            raise RateLimitError(
                "你已有一个语音会话正在进行，请先结束它再开始新的",
                details={"ok": False, "error": "session_busy", "fallback": FALLBACK_TEXT},
            )
        self._role_code = str(payload.get("roleCode") or "teacher")
        mode = MODE_MAP.get(str(payload.get("mode") or ""), MODE_PUSH_TO_TALK)
        raw_context = payload.get("context")
        # 收窄成一个明确的类型：`context` 下面要传给两个都要求 Mapping 的地方，
        # 让 mypy 逐处再判一次「是不是 Mapping」没有意义。
        context: Mapping[str, Any] = raw_context if isinstance(raw_context, Mapping) else {}
        if self.course is None and self._resolve_course is not None:
            # 要在拼提示词与取热词**之前**：那两处都按 `self.course` 分叉
            self.course = self._resolve_course(str(context.get("courseId") or ""))

        started = self._clock()
        self._started_at = started
        session = self.provider.start_session(
            voice=voice_prefs.pick_realtime_voice(
                str(payload.get("voiceType") or ""), role_code=self._role_code
            ),
            instructions=self._instructions(str(payload.get("systemPrompt") or ""), context),
            hotwords=self._hotwords(context),
            mode=mode,
        )
        self._session = session
        # `start()` 在真实 Provider 上会建连并等 `session.created`；Mock 上是个空操作。
        starter = getattr(session, "start", None)
        if callable(starter):
            starter()
        self._emit(
            {
                "type": "ready",
                "sessionId": self.session_id,
                "dialogId": str(getattr(session, "dialog_id", "") or ""),
                # 从收到 start 到会话可用。真正的「老师第一帧声音」要等第一轮
                # 回答才量得到，那个数在 `done.usage.firstFrameMs` 里。
                "ttsFirstFrameMs": _ms(self._clock() - started),
            }
        )

    def _on_audio(self, chunk: bytes) -> None:
        """麦克风音频（PCM 16k/int16/mono）。分包与节奏由 Provider 负责。"""
        if not chunk:
            return
        # 学生又开口了，补静音这件事交回给他 —— 两条流叠在一起会推太快
        self._feed_until = None
        session = self._require_session()
        session.send_audio(chunk)

    def _on_audio_notice(self, payload: Mapping[str, Any]) -> None:
        """`{"type":"audio","seq":n}` —— 「后面那帧是音频」的提示。

        带 `final` 时代表**这一轮说完了**（学生松开按键），要显式下发
        `commit_audio()`：`push_to_talk` 模式下服务端 VAD 被屏蔽，判停完全由
        客户端这一条决定（P2-A18 / §5.3 的映射表「`audio` 结束 →
        `input_audio_buffer.commit`」）—— 不传的话这一轮永远等不到回答，
        而前端看起来是「按了没反应」。

        序号不校验：它在前端只是「按序播放」的依据，服务端拿它做一致性
        检查只会多一处会误判的地方（丢包重传、页面切后台都会让它跳号）。
        """
        if _truthy(payload.get("final")):
            self._require_session().commit_audio()
            # 松开按键之后前端就不再发音频了，但上游要「有流」才判停出回答，
            # 所以由我们替他把静音推上去（见 TURN_FEED_SECONDS）。
            self._feed_until = self._clock() + TURN_FEED_SECONDS

    def _on_barge_in(self, _payload: Mapping[str, Any]) -> None:
        """学生插话：撤掉模型正在播的这一轮，并回执告诉前端可以继续说了。"""
        session = self._require_session()
        started = self._clock()
        session.barge_in()
        self._emit({"type": "barge_in_ack", "latencyMs": _ms(self._clock() - started)})

    def _on_stop(self, _payload: Mapping[str, Any]) -> None:
        self.close(reason="stopped")

    # --- 下行 ---

    def _pump(self) -> None:
        session = self._session
        if session is None:
            return
        for event in session.receive(timeout=POLL_SECONDS):
            self._on_event(event)

    def _on_event(self, event: Any) -> None:
        """一个语义事件 → 一条（或两条）下行帧。

        走表不走 if 链（与 `_UPLINK` 同一个理由）：上游每加一种事件就多一个分支，
        而分支一多，「哪一个先判」就开始变成没人说得清的隐式规则。
        """
        kind = str(getattr(event, "type", "") or "")
        handler = _DOWNLINK.get(kind)
        if handler is None:
            logger.debug("实时语音：不向前端转发的事件 %s", kind)
            return
        handler(self, event)

    # --- 下行：语义事件 → 给浏览器的帧 ---

    def _on_asr_event(self, event: Any) -> None:
        text = str(getattr(event, "text", "") or "")
        self._turn.asr_chars += len(text)
        self._session_asr_chars += len(text)
        self._emit({"type": "asr", "text": text, "final": bool(event.final)})

    def _on_reply_event(self, event: Any) -> None:
        text = str(getattr(event, "text", "") or "")
        self._turn.reply_chars += len(text)
        self._session_reply_chars += len(text)
        self._emit({"type": "reply", "text": text, "final": bool(event.final)})

    def _on_audio_event(self, event: Any) -> None:
        audio = bytes(getattr(event, "audio", b"") or b"")
        if audio:
            self._emit_audio(audio)

    def _on_barge_in_event(self, _event: Any) -> None:
        # 服务端 VAD 触发的打断（研讨模式的常开麦）：告诉前端立刻停播
        self._emit({"type": "barge_in"})

    def _on_done_event(self, _event: Any) -> None:
        self._emit({"type": "done", "usage": self._turn_usage()})
        self._turn = Turn()
        # 这一轮答完了，不用再补静音 —— 继续推的话下一轮会被它自己「打断」
        self._feed_until = None

    def _on_usage_event(self, event: Any) -> None:
        # 上游的计量口径原样收着（排障与对账用），不往前端透传
        raw = getattr(event, "raw", None)
        if isinstance(raw, Mapping):
            self._upstream_usage.update(raw)

    def _feed_silence(self) -> None:
        """替松开按键的学生把静音推上去（见 `TURN_FEED_SECONDS`）。

        一轮 tick 补 3 包 = 60ms 音频，比 `POLL_SECONDS`（50ms）略多一点：
        略快于实时没关系（上游有缓冲），**慢了就判不出「说完了」**。
        """
        if self._feed_until is None:
            return
        if self._clock() >= self._feed_until:
            logger.debug("实时语音：补静音到点了，这一轮不再等")
            self._feed_until = None
            return
        try:
            session = self._require_session()
            for _ in range(3):
                session.send_audio(SILENCE_PACKET)
        except AppError as exc:
            # 上游不认了（会话被释放之类）：补静音就此打住，
            # 别让一个兜底动作把整条通道搞崩 —— 真正的失败由收包路径报。
            logger.debug("实时语音：补静音失败，停止补齐：%s", exc)
            self._feed_until = None

    def _on_upstream_closed(self, _event: Any) -> None:
        self._emit({"type": "closed", "reason": "upstream"})

    def _on_upstream_error(self, event: Any) -> None:
        text = str(getattr(event, "text", "") or "")
        self._fail("upstream", text or "实时语音上游报错", fallback=FALLBACK_BROWSER)

    def _emit_audio(self, audio: bytes) -> None:
        """先发一条带 `seq` 的说明，再发二进制帧（P2 §4.2 的「用 seq 关联」）。"""
        if not self._turn.first_frame_ms and self._started_at:
            self._turn.first_frame_ms = _ms(self._clock() - self._started_at)
        self._seq += 1
        self._emit({"type": "audio", "seq": self._seq})
        self._emit_raw(audio)

    def _emit(self, payload: Mapping[str, Any]) -> None:
        self._emit_raw(json.dumps(dict(payload), ensure_ascii=False))

    def _fail(self, code: str, message: str, *, fallback: str) -> None:
        """任何错误都必须带 `fallback`（P2-B2）—— 前端不猜。"""
        self.last_error = message
        logger.warning("实时语音错误 code=%s msg=%s", code, message)
        self._emit({"type": "error", "code": code, "message": message, "fallback": fallback})

    def _require_session(self) -> Any:
        if self._session is None:
            raise StateError("实时语音会话还没建立，请先发 start")
        return self._session

    # --- 上下文 ---

    def _instructions(self, system_prompt: str, context: Mapping[str, Any]) -> str:
        """系统提示词 = 前端给的人设 + 服务端知道的课堂上下文。

        为什么要加上后半段：前端手里只有「第 7 页」，而这一页讲什么在库里。
        老师答非所问最常见的原因就是它不知道现在上到哪儿了。
        """
        from app.services.courses import store

        parts = [system_prompt.strip()]
        if self.course is None:
            return "\n".join(part for part in parts if part)

        parts.append(f"你正在讲《{self.course.title}》。")
        page_no = _int_of(context.get("pageNo"))
        page = store.page_by_no(self.course, page_no) if page_no else None
        if page is not None:
            points = [str(item) for item in (page.dsl or {}).get("points") or []]
            if points:
                parts.append("这一页的要点：" + "、".join(points[:6]) + "。")
        return "\n".join(part for part in parts if part)

    def _hotwords(self, context: Mapping[str, Any]) -> list[str]:
        """学科热词：与 TTS 纠音表同一份课程术语表（P2-A20）。"""
        if self.course is None:
            return []
        page_no = _int_of(context.get("pageNo"))
        terms = glossary_for(self.course, page_no=page_no or None).get("hotwords") or []
        return [str(item) for item in terms]

    # --- 记账 ---

    def _turn_usage(self) -> dict[str, Any]:
        return {
            "durationMs": _ms(self._clock() - self._started_at) if self._started_at else 0,
            "asrChars": self._turn.asr_chars,
            "replyChars": self._turn.reply_chars,
            "firstFrameMs": self._turn.first_frame_ms,
        }

    def _settle(self) -> None:
        """会话结束写一笔账（P2-A11）。写不进去只记日志（见 usage.record）。

        时长用**我们自己量的**：从 `start` 到关闭的墙钟秒数，
        与上游按会话时长计费的口径一致；上游给的 usage 原样留在
        `_upstream_usage` 里，用于对账时看差多少。
        """
        if not self._started_at:
            return
        seconds = round(self._clock() - self._started_at)
        if seconds <= 0:
            return
        record_usage(
            "realtime",
            provider=self.provider.name,
            model=model_of(self.provider),
            units=seconds,
            ref_type="session",
            ref_id=self.session_id or "session",
        )


# --- 上行分派表（与 Provider 的 `_EVENT_HANDLERS` 同一个理由：一张表比一条 if 链好读）---

_UPLINK = {
    "start": RealtimeChannel._on_start,
    "audio": RealtimeChannel._on_audio_notice,
    "barge_in": RealtimeChannel._on_barge_in,
    "stop": RealtimeChannel._on_stop,
}

#: 下行分派表。**表里没有的事件不下发给前端**，这是有意的：
#: `ready` 是 `session.created` 的回执（我们自己的 ready 早就发过了）、
#: `canceled` / `reconnected` 是适配器自己处理的重连与内部状态
#: （P2-A17 要求重连对用户无感）—— 前端出现这三种词，就是在依赖上游的协议了。
_DOWNLINK = {
    "asr": RealtimeChannel._on_asr_event,
    "reply": RealtimeChannel._on_reply_event,
    "audio": RealtimeChannel._on_audio_event,
    "barge_in": RealtimeChannel._on_barge_in_event,
    "done": RealtimeChannel._on_done_event,
    "usage": RealtimeChannel._on_usage_event,
    "closed": RealtimeChannel._on_upstream_closed,
    "error": RealtimeChannel._on_upstream_error,
}


def _parse(raw: Any) -> Mapping[str, Any] | None:
    if not isinstance(raw, (str, bytes, bytearray)):
        return None
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, ValueError, TypeError):
        return None
    return data if isinstance(data, Mapping) else None


def _truthy(value: Any) -> bool:
    """前端的布尔值：`true` / `"true"` / `1` / `"on"` 都算真。"""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _int_of(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _ms(seconds: float) -> int:
    return max(0, round(float(seconds) * 1000))


__all__ = [
    "DOWN_TYPES",
    "MODE_MAP",
    "POLL_SECONDS",
    "ChannelClosed",
    "RealtimeChannel",
    "Transport",
    "Turn",
]
