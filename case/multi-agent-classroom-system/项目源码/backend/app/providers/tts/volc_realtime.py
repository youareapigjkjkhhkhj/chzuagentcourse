"""火山引擎端到端实时语音大模型（全双工对话）。

=== 与 TTS / ASR 的关键差别（决定它为什么必须单独一个适配器）===

1. **帧编码完全不同。** 端到端实时语音走的是**纯 JSON 文本帧 + Base64 音频**
   （`{"type": "input_audio_buffer.append", "audio": "<base64>"}` 这一形状），
   不共用 volc_tts.py / volc_asr.py 的二进制私有帧编解码器。
   三套 codec 互为「看起来很像但一对就对不上」的陷阱，不要试图合并。

2. **音色池是独立的。** 本适配器的音色只能来自实时语音池
   （`_jupiter_bigtts`，中文仅 4 个），与 TTS 2.0 池（`_uranus_bigtts`）
   完全不通用。用错池子 → `ClientError:InvalidSpeaker`。

3. **10 分钟空闲会被服务端断连（错误码 45000003）。** 断连是**常规路径**，
   不是异常分支：课堂里学生沉默几分钟太正常了。所以重连是 `_ensure_session()`
   里的一条正常代码路径（连接复用，只重发 `session.create`），
   而不是包在 except 里的补丁（P2-A17）。

4. **分包 20ms / 640 字节**，与 ASR 的 200ms 不通用（P2-A16）。
   且**发送速率必须跟着真实时间走**：推太快推太慢都会触发服务端错误。
"""

from __future__ import annotations

import base64
import json
import threading
import time
import uuid
from typing import Any, Callable, Iterator, Mapping, Sequence

from app.common.errors import RateLimitError
from app.common.logging import get_logger
from app.providers.base import (
    MODE_KEEP_ALIVE,
    MODE_PUSH_TO_TALK,
    ProviderError,
    RealtimeEvent,
    RealtimeProvider,
    Secret,
    Voice,
    not_configured,
)
from app.providers.transport import (
    Connector,
    TransportClosed,
    TransportTimeout,
    WsTransport,
    default_connector,
    wrap,
)

logger = get_logger("app.providers.realtime")

#: 上行音频规格：16k / int16 / mono，20ms 一包 = 640 字节（§5.3-B8 ②）。
#: **这两个常量只属于本模块** —— ASR 是 200ms/6400 字节，谁都不许共用一个数。
PACKET_MS = 20
PACKET_BYTES = 16000 * 2 * PACKET_MS // 1000  # 640

#: 等 `session.created` / `session.closed` 回执的上限（秒）。
#: 关闭回执等不到就是 `ContextCanceled`（55000001），所以这个超时不能省。
SESSION_ACK_TIMEOUT = 3.0
#: 单次收包等待上限（秒）。到点没数据就返回，让调用方（WS 代理）有机会做别的事。
RECV_TIMEOUT = 0.5

#: 会话被服务端释放的错误码：遇到就重建会话，不打扰用户（P2-A17）。
_SESSION_RELEASED_CODES = frozenset({45000003})
#: 「听不清」：提示学生重说，而不是报系统错误。
_UNINTELLIGIBLE_CODES = frozenset({"audio_unintelligible", 45000002})
#: 5xx 类错误统一重连（4xx 停止重试并核对配置）。
_RETRYABLE_PREFIX = "55"

# 输入模式（`MODE_PUSH_TO_TALK` / `MODE_KEEP_ALIVE`）从 `providers/base.py` 导入，
# 本模块**再导出**（见 `__all__`）：它的定义属于抽象层（业务层要能说这两个词，
# 又不该 import 具体适配器），而把值填进 `extension.dialog.extra.input_mod`
# 是这里的事 —— 厂商协议字段名只在本模块出现。


class VolcRealtime(RealtimeProvider):
    """豆包端到端实时语音（全双工）。"""

    def __init__(
        self,
        name: str = "volc_realtime",
        *,
        api_key: str = "",
        endpoint: str = "",
        model: str = "",
        speaker: str = "",
        qpm_limit: int = 60,
        voices: Mapping[str, str] | None = None,
        connect: Connector | None = None,
        **options: Any,
    ) -> None:
        super().__init__(name, **options)
        self.endpoint = endpoint
        self.model = model
        self.speaker = speaker
        #: 每分钟请求上限，超了在客户端先拒绝，别等服务端回 429
        self.qpm_limit = int(qpm_limit)
        self._secret = Secret(api_key)
        self._connect: Connector = connect or default_connector
        self._voices = dict(voices or {})
        self._guard = _QpmGuard(self.qpm_limit)

    # --- 配置齐备性 ---

    def missing_config(self) -> list[str]:
        missing = []
        if not self._secret:
            missing.append("API Key")
        if not self.endpoint:
            missing.append("接入地址")
        if not self.speaker and not self._voices:
            missing.append("音色 ID")
        return missing

    @property
    def configured(self) -> bool:
        return not self.missing_config()

    # --- 会话 ---

    def start_session(self, **options: Any) -> VolcRealtimeSession:
        """建一次会话。返回的对象既管收发，也管「会话被释放后重建」。

        参数（都可由调用方按学生/角色区分）：
        - `voice`：实时语音池的音色 ID
        - `instructions`：系统提示词（人设、本页要点、约束）
        - `hotwords`：学科热词（与 TTS 纠音共用同一份课程术语表）
        - `mode`：`push_to_talk`（默认）/ `keep_alive`
        """
        if not self.configured:
            raise not_configured(self)
        self._guard.check()
        return VolcRealtimeSession(
            self,
            voice=str(options.get("voice") or self.speaker),
            instructions=str(options.get("instructions") or ""),
            hotwords=[str(w) for w in (options.get("hotwords") or []) if str(w).strip()],
            mode=str(options.get("mode") or MODE_PUSH_TO_TALK),
            timeout=float(options.get("timeout") or SESSION_ACK_TIMEOUT),
        )

    def list_voices(self) -> list[Voice]:
        """本项目配置里认得的实时语音音色（上游没有列音色的接口，只报配置的）。"""
        return [
            Voice(id=voice_id, name=display, provider=self.name)
            for display, voice_id in self._voices.items()
            if voice_id
        ]

    def headers(self) -> dict[str, str]:
        """鉴权头。**唯一读取 Key 明文的地方。**"""
        return {"X-Api-Key": self._secret.reveal()}


class VolcRealtimeSession:
    """一次全双工会话：JSON 帧收发、Base64 音频编解码、空闲重连。"""

    def __init__(
        self,
        provider: VolcRealtime,
        *,
        voice: str = "",
        instructions: str = "",
        hotwords: Sequence[str] = (),
        mode: str = MODE_PUSH_TO_TALK,
        timeout: float = SESSION_ACK_TIMEOUT,
    ) -> None:
        self.provider = provider
        self.voice = voice
        self.instructions = instructions
        self.hotwords = list(hotwords)
        self.mode = mode
        self.timeout = float(timeout)

        self._conn: WsTransport | None = None
        self._dialog_id = ""
        self._event_seq = 0
        self._closed = False
        #: 上一包音频的发送时刻，用来把发送节奏压成真实的 20ms 一包
        self._last_send = 0.0
        #: 上行余量：不足一包的音频留到下一包（前端传上来的块大小不由我们定）
        self._pending = bytearray()
        self._lock = threading.RLock()

    # --- 生命周期 ---

    @property
    def dialog_id(self) -> str:
        """上游会话 ID（`session.created` 的 `session.id`），用于接续历史。"""
        return self._dialog_id

    @property
    def alive(self) -> bool:
        return self._conn is not None and not self._closed

    def start(self) -> None:
        """建连 + 建会话（幂等：已经活着就什么都不做）。"""
        self._ensure_session()

    def send_audio(self, chunk: bytes) -> None:
        """推一段麦克风音频（PCM 16k/int16/mono）。

        调用方给多大的块都行，这里按 20ms / 640 字节重新分包并**按真实时间节奏**发送。
        """
        if not chunk:
            return
        with self._lock:
            self._pending += chunk
            while len(self._pending) >= PACKET_BYTES:
                packet = bytes(self._pending[:PACKET_BYTES])
                del self._pending[:PACKET_BYTES]
                self._send_paced(packet)

    def commit_audio(self) -> None:
        """松开按键：显式告诉服务端「说完了」。

        `push_to_talk` 模式下服务端 VAD 被屏蔽，判停完全由这一条决定（P2-A18）。
        尾巴（不足一包的部分）先补一包再 commit —— 不补的话最后半个字会丢。
        """
        with self._lock:
            if self._pending:
                self._send_paced(bytes(self._pending))
                self._pending.clear()
            self._send({"type": "input_audio_buffer.commit"})

    def send_text(self, text: str) -> None:
        """让模型按给定文本发声（AI 同学点名发言、开场白）。"""
        with self._lock:
            self._send({"type": "speech_text_buffer.append", "text": text})
            self._send({"type": "speech_text_buffer.commit", "text": text})

    def send_context(self, pairs: Sequence[tuple[str, str]]) -> None:
        """注入上下文（用户/助手成对，长度必须为偶数）。"""
        items = [
            {
                "id": uuid.uuid4().hex[:8],
                "type": "message",
                "role": role,
                "content": [{"type": "input_text", "text": text}],
            }
            for role, text in pairs
        ]
        if items:
            self._send({"type": "conversation.item.create", "items": items})

    def barge_in(self) -> None:
        """打断：学生再次按空格说话时清掉模型正在播的这一轮（P2-A8）。"""
        with self._lock:
            self._send({"type": "response.cancel"})

    def keep_alive(self, muted: bool = True) -> None:
        """静音保活 / 取消静音（模式 2 的常开麦用它）。

        首选机制是 `input_mod: "keep_alive"`（官方错误码 52000042 点名的解药），
        这个事件是它的显式版 —— 两条路都留，首日实测取生效的那条（§12 第 3e 条）。
        """
        event = "input_audio_mute.commit" if muted else "input_audio_unmute.commit"
        self._send({"type": event})

    def receive(self, timeout: float | None = None) -> Iterator[RealtimeEvent]:
        """收上游事件，**不阻塞**：等不到就到点返回，让调用方能做别的事。

        `timeout=None` 用默认的 `RECV_TIMEOUT`。会话不在时先自动重建（P2-A17）。
        """
        deadline = time.monotonic() + (RECV_TIMEOUT if timeout is None else timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                raw = self._conn_or_rebuild().receive(timeout=remaining)
            except TransportTimeout:
                return
            except TransportClosed:
                # 连接断了：这条是常规路径（10 分钟空闲、网络抖动），
                # 重建之后继续收 —— 前端不该看到「连接断开」这种字眼。
                logger.info("实时语音连接断开，正在重建会话")
                self._reconnect()
                continue
            for event in self._translate(raw):
                yield event

    def close(self) -> None:
        """优雅关闭：先 `session.close` 并**等 `session.closed` 回执**，再断连。

        不等回执直接断开会触发 `ContextCanceled`（55000001）——
        日志里从此多一条每次上课都出现、但没人能修的报错（P2-A13）。
        """
        with self._lock:
            if self._closed:
                return
            self._closed = True
            conn = self._conn
            self._conn = None
            if conn is None:
                return
            try:
                conn.send(_dumps({"event_id": _event_id(), "type": "session.close"}))
                deadline = time.monotonic() + self.timeout
                while time.monotonic() < deadline:
                    raw = conn.receive(timeout=max(0.0, deadline - time.monotonic()))
                    if _msg_type(raw) == "session.closed":
                        break
            except (TransportClosed, TransportTimeout, OSError) as exc:
                logger.debug("关闭实时语音会话时未见回执：%s", exc)
            finally:
                conn.close()

    # --- 内部控制 ---

    def _ensure_session(self) -> None:
        """保证「连接在 + 会话在」。任何一步缺了就补哪一步。"""
        conn = self._conn_or_rebuild()
        if self._dialog_id:
            return
        conn.send(_dumps(self._session_create_payload()))
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                raw = conn.receive(timeout=max(0.0, deadline - time.monotonic()))
            except TransportTimeout:
                raise ProviderError("实时语音会话创建超时（未收到 session.created）") from None
            except TransportClosed as exc:
                raise ProviderError(f"实时语音连接在会话创建前断开：{exc}") from exc
            for event in self._translate(raw):
                if event.type == "ready":
                    return
                if event.type == "error":
                    raise ProviderError(event.text or "实时语音会话创建失败", details={"stage": "create"})

    def _conn_or_rebuild(self) -> WsTransport:
        if self._conn is not None:
            return self._conn
        provider = self.provider
        # 取连接工厂不走 getter：本类的 role 就是 provider 的执行体，不是外部调用方
        conn = wrap(
            provider._connect(provider.endpoint, headers=provider.headers(), timeout=self.timeout)
        )
        self._conn = conn
        self._last_send = 0.0
        return conn

    def _reconnect(self) -> None:
        """连接没了：丢掉旧的，下一次 `_conn_or_rebuild()` 会重建。

        会话 ID 一并清掉 —— 新连接上没有那条会话，`_ensure_session()` 会重发
        `session.create`。**这就是 P2-A17 要的那条路径。**
        """
        conn, self._conn = self._conn, None
        self._dialog_id = ""
        self._pending.clear()
        if conn is not None:
            conn.close()
        self._ensure_session()

    def _send(self, payload: Mapping[str, Any]) -> None:
        body = {"event_id": _event_id(), **payload}
        try:
            self._conn_or_rebuild().send(_dumps(body))
        except TransportClosed:
            logger.info("实时语音上行失败（连接已断），重建会话后重发一次")
            self._reconnect()
            self._conn_or_rebuild().send(_dumps(body))

    def _send_paced(self, packet: bytes) -> None:
        """按 20ms 的真实节奏发包：推太快上游报「节奏异常」，推太慢被判超时。"""
        if self._last_send:
            wait = PACKET_MS / 1000 - (time.monotonic() - self._last_send)
            if wait > 0:
                time.sleep(wait)
        self._send(
            {
                "type": "input_audio_buffer.append",
                # ⚠️ 上行音频字段名是 `audio`（不是 data），Base64 内嵌，不带格式字段
                "audio": base64.b64encode(packet).decode("ascii"),
            }
        )
        self._last_send = time.monotonic()

    def _session_create_payload(self) -> dict[str, Any]:
        """`session.create` 的完整报文（§5.3-B2）。"""
        return {
            "event_id": _event_id(),
            "type": "session.create",
            "session": {
                "model": self.provider.model,
                "instructions": self.instructions,
                "audio": {
                    "input": {"format": {"type": "pcm", "rate": 16000}},
                    # ⚠️ 输出固定 pcm_s16le：`pcm` 是 32bit，浏览器播不了（B8 ②）
                    "output": {
                        "format": {"type": "pcm_s16le", "rate": 24000},
                        "voice": self.voice,
                    },
                },
            },
            "extension": {
                # ⚠️ 这三个 extra **不能是 null、也不能省**：置空即报 42000020，
                #    不需要配置也要传 {}。
                "asr": {
                    "extra": {
                        "enable_asr_twopass": True,
                        "context": {"hotwords": [{"word": w} for w in self.hotwords]},
                    }
                },
                "tts": {"extra": {"max_length_to_filter_parenthesis": 30}},
                "dialog": {
                    "extra": {
                        "strict_audit": True,
                        "audit_response": "抱歉，这个问题我无法回答，你可以换个其他话题。",
                        "enable_loudness_norm": True,
                        "input_mod": self.mode,
                        "model": self.provider.model,
                    }
                },
            },
        }

    # --- 下行事件翻译 ---

    def _translate(self, raw: bytes | str) -> list[RealtimeEvent]:
        """上游 JSON → 语义事件。未知事件记一笔就走，**不抛异常**。

        事件名到处理函数的对应关系在 `_EVENT_HANDLERS` —— 上游事件有二十来个，
        写成一条 if 链会长到看不清「哪些事件是我们关心的、各自翻成什么」，
        而这恰恰是这个文件最该一眼看懂的地方。
        """
        data = _loads(raw)
        if data is None:
            return []
        kind = str(data.get("type") or "")
        if not kind:
            # 上游偶尔只回一个 error 对象，没有 type
            return [RealtimeEvent(type="error", text=_error_text(data), raw=data)] if data.get(
                "error"
            ) else []
        handler = _EVENT_HANDLERS.get(kind)
        if handler is None:
            logger.debug("实时语音未知事件，已跳过：%s", kind)
            return []
        return handler(self, data)

    def _released(self, data: Mapping[str, Any]) -> RealtimeEvent:
        """会话被服务端释放（45000003）→ 重建会话，前端无感（P2-A17）。"""
        logger.info("实时语音会话被服务端释放（%s），重建中", _error_code(data))
        self._dialog_id = ""
        try:
            self._ensure_session()
        except ProviderError as exc:  # 重建失败也要把原因带到前端
            return RealtimeEvent(type="error", text=str(exc), raw=data)
        return RealtimeEvent(type="reconnected", raw=data)


class _QpmGuard:
    """会话创建频率闸门（滑动窗口）。

    上游按分钟限并发，撞上去就是 429。在这里先拦一下：
    拿到的是「我们这边的一句话」，而不是让用户对着上游错误码猜。
    """

    def __init__(self, limit: int, window: float = 60.0) -> None:
        self.limit = int(limit)
        self.window = float(window)
        self._hits: list[float] = []
        self._lock = threading.Lock()

    def check(self) -> None:
        if self.limit <= 0:
            return
        now = time.monotonic()
        with self._lock:
            self._hits = [t for t in self._hits if now - t < self.window]
            if len(self._hits) >= self.limit:
                raise RateLimitError(
                    f"实时语音会话太频繁（每分钟上限 {self.limit} 次），请稍后再试",
                    details={"limit": self.limit, "windowSeconds": int(self.window)},
                )
            self._hits.append(now)


# --- 下行事件 → 语义事件（对应关系集中在这一张表里）---

#: 处理函数签名：`(会话, 上游 JSON) -> [语义事件]`。
_Handler = Callable[["VolcRealtimeSession", Mapping[str, Any]], list[RealtimeEvent]]


def _on_session_created(session: VolcRealtimeSession, data: Mapping[str, Any]) -> list[RealtimeEvent]:
    inner = data.get("session")
    session_id = inner.get("id") if isinstance(inner, Mapping) else None
    session._dialog_id = str(session_id or data.get("session_id") or session.dialog_id)
    logger.debug("实时语音会话已建立 dialog_id=%s", session.dialog_id)
    return [RealtimeEvent(type="ready", raw=data)]


def _on_asr_started(session: VolcRealtimeSession, data: Mapping[str, Any]) -> list[RealtimeEvent]:
    # 学生开口了 —— 这就是打断点：前端收到即清空播放队列（§5.3-B5-3，P2-A8）
    return [RealtimeEvent(type="barge_in", raw=data)]


def _on_asr_text(session: VolcRealtimeSession, data: Mapping[str, Any]) -> list[RealtimeEvent]:
    """`.delta` / `.completed` 共用：只差一个 final 标志。"""
    final = str(data.get("type") or "").endswith(".completed")
    return [RealtimeEvent(type="asr", text=_delta_text(data), final=final, raw=data)]


def _on_asr_failed(session: VolcRealtimeSession, data: Mapping[str, Any]) -> list[RealtimeEvent]:
    return [RealtimeEvent(type="error", text=_unintelligible_message(data), raw=data)]


def _on_reply(session: VolcRealtimeSession, data: Mapping[str, Any]) -> list[RealtimeEvent]:
    """`response.output_text.delta` / `.done`：给学生看的字幕。"""
    final = str(data.get("type") or "").endswith(".done")
    return [RealtimeEvent(type="reply", text=_delta_text(data), final=final, raw=data)]


def _delta_text(data: Mapping[str, Any]) -> str:
    """取增量事件里的文本。

    上游**同一个字段名分两处用**（实测口径，别只认 `text`）：
    `.delta` 事件把增量放在 `delta` 里，`.done` / `.completed` 事件才用 `text`。
    只读 `text` 的表现是「事件一直在来，字幕一直空白」—— 真机踩过。
    """
    return str(data.get("text") or data.get("delta") or "")


def _on_audio_delta(session: VolcRealtimeSession, data: Mapping[str, Any]) -> list[RealtimeEvent]:
    audio = _decode_audio(data)
    return [RealtimeEvent(type="audio", audio=audio, raw=data)] if audio else []


def _on_audio_done(session: VolcRealtimeSession, data: Mapping[str, Any]) -> list[RealtimeEvent]:
    # status_code 是可选字段（打招呼场景就没有），别按必填解析
    return [RealtimeEvent(type="done", text=str(data.get("status_code") or ""), raw=data)]


def _on_response_done(session: VolcRealtimeSession, data: Mapping[str, Any]) -> list[RealtimeEvent]:
    usage = data.get("usage")
    return [RealtimeEvent(type="usage", raw=dict(usage) if isinstance(usage, Mapping) else dict(data))]


def _on_error(session: VolcRealtimeSession, data: Mapping[str, Any]) -> list[RealtimeEvent]:
    """错误事件：会话被释放是常规路径，其余按 4xx/5xx 分流（P2-A17）。"""
    if _error_code(data) in _SESSION_RELEASED_CODES:
        return [session._released(data)]
    retryable = str(_error_code(data)).startswith(_RETRYABLE_PREFIX)
    return [
        RealtimeEvent(type="error", text=_error_text(data), raw={**dict(data), "retryable": retryable})
    ]


def _on_plain(kind: str) -> _Handler:
    """没有额外处理的一类：原样翻成同名语义事件（closed / canceled）。"""

    def handler(session: VolcRealtimeSession, data: Mapping[str, Any]) -> list[RealtimeEvent]:
        return [RealtimeEvent(type=kind, raw=data)]

    return handler


_EVENT_HANDLERS: Mapping[str, _Handler] = {
    "session.created": _on_session_created,
    "conversation.item.input_audio_transcription.started": _on_asr_started,
    "conversation.item.input_audio_transcription.delta": _on_asr_text,
    "conversation.item.input_audio_transcription.completed": _on_asr_text,
    "conversation.item.input_audio_transcription.failed": _on_asr_failed,
    "response.output_text.delta": _on_reply,
    "response.output_text.done": _on_reply,
    "response.output_audio.delta": _on_audio_delta,
    "response.output_audio.done": _on_audio_done,
    "response.done": _on_response_done,
    "session.closed": _on_plain("closed"),
    "response.canceled": _on_plain("canceled"),
    "error": _on_error,
}


def _loads(raw: bytes | str) -> Mapping[str, Any] | None:
    """一条下游消息 → 字典。非 JSON / 不是对象都返回 None（记一笔就走）。"""
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        logger.warning("实时语音收到非 JSON 帧，已忽略：%s", str(raw)[:120])
        return None
    return data if isinstance(data, Mapping) else None


def _dumps(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def _event_id() -> str:
    """每条上行都带一个 —— 建议如此，链路追踪时能一眼对上（§5.3-B2）。"""
    return f"event_{uuid.uuid4().hex[:12]}"


def _msg_type(raw: bytes | str) -> str:
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return ""
    return str(data.get("type") or "") if isinstance(data, Mapping) else ""


def _decode_audio(data: Mapping[str, Any]) -> bytes:
    """下游音频：Base64 → PCM。

    ⚠️ **下行**的字段名是 `delta`（和文本增量同一套命名），不是上行那个 `audio`
    —— 两个方向不对称，按上行去读会一片音频都收不到（实测下行 event 的键是
    `delta` / `event_id` / `response_id`）。`audio`/`data` 留作兼容。
    """
    encoded = data.get("delta") or data.get("audio") or data.get("data") or ""
    if not isinstance(encoded, str) or not encoded:
        return b""
    try:
        return base64.b64decode(encoded)
    except (ValueError, TypeError):
        logger.warning("实时语音音频片段不是合法 Base64，已丢弃")
        return b""


def _error_code(data: Mapping[str, Any]) -> Any:
    error = data.get("error")
    if isinstance(error, Mapping):
        for key in ("code", "status_code", "type"):
            if error.get(key):
                return error[key]
    for key in ("code", "status_code"):
        if data.get(key):
            return data[key]
    return ""


def _error_text(data: Mapping[str, Any]) -> str:
    error = data.get("error")
    if isinstance(error, Mapping):
        message = error.get("message") or error.get("code") or ""
        if message:
            return f"实时语音报错：{message}"
    return f"实时语音报错：{data.get('message') or data.get('code') or '（上游未给原因）'}"


def _unintelligible_message(data: Mapping[str, Any]) -> str:
    """「听不清」是用户的问题不是系统的故障 —— 文案要说人话（§5.3-B7）。"""
    code = _error_code(data)
    if code in _UNINTELLIGIBLE_CODES:
        return "没有听清，请再说一次"
    return _error_text(data)


__all__ = [
    "MODE_KEEP_ALIVE",
    "MODE_PUSH_TO_TALK",
    "PACKET_BYTES",
    "PACKET_MS",
    "RealtimeEvent",
    "VolcRealtime",
    "VolcRealtimeSession",
]
