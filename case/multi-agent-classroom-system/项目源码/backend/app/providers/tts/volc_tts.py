"""火山引擎大模型语音合成（双向流式，二进制私有帧）。

用法上它不是流式播放，而是**整课批量预生成**：一条 WebSocket 上逐个 beat 走
`StartSession → TaskRequest → 收 TTSSentenceEnd`，音频落盘供课堂页直接播放。

=== 实现这一版之前必须记住的坑（来自接口文档，别重新踩）===

1. **帧编码是私有的，和 ASR 不通用。** 别把两边的编解码器合并成一个：
   TTS 的 payload 在音频数据前多一段 `4 字节 session_id 长度 + session_id`，
   ASR 没有这一段。共用一个 codec 会写出「两个都对不上」的实现。
   本适配器只用 `frames.py`，ASR 那套在 `providers/asr/frames.py`。

2. **音色池不通用。** 本适配器的音色必须来自 TTS 2.0 池（`_uranus_bigtts` 一族），
   实时语音那边是另一个池（`_jupiter_bigtts`，中文只有 4 个）。拿错池子的 ID
   会直接 `ClientError:InvalidSpeaker`。音色 ID 一律走配置/数据库注入，
   代码里不写字面量。

3. **必须打开 `disable_markdown_filter`。** 否则讲稿里的 `**重点**`
   会被读成「星星重点星星」。讲稿是 Markdown 生成的，这条不是可选项。

4. **一次请求文本 ≤ 300 字**（本项目经验值）。超长的由调用方按句切分 ——
   本适配器不偷偷替你切：切错了句子，音频接缝处的语调会明显发僵。

路径 A（预生成）与路径 B（实时对话）的分工见 `项目文档/P2-语音能力接入.md`。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Iterator, Mapping

from app.common.logging import get_logger
from app.providers.base import (
    ProviderError,
    Secret,
    Subtitle,
    TTSProvider,
    TTSResult,
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
from app.providers.tts import frames

logger = get_logger("app.providers.tts")

#: 单次合成的默认等待上限（秒）。一个 ≤300 字的 beat 正常情况下几秒就出完；
#: 60s 是「上游卡住了」与「网络慢」之间的分界。
DEFAULT_TIMEOUT = 60.0

#: 上行载荷里的命名空间。官方样例里每个事件都带，缺了上游认不出这是什么服务。
_NAMESPACE = "BidirectionalTTS"

#: 一段 mp3 的时长估算用到的默认码率（bps）。仅在**没有字级时间戳**时兜底 ——
#: 开了 enable_subtitle 就有真时间戳，那个才是准的。
_DEFAULT_BIT_RATE = 64000

#: 「语调起伏」三档 → 上游的绝对音调（`pitch`，[-12, 12]）。
#:
#: 上游**没有「起伏」这个参数**，只有音调高低；三档（settings 页的滑杆）是
#: 本项目对它的落地口径，所以映射写在这里而不是业务层 —— 只有这一层知道
#: 上游参数的形状，与 `_speech_rate` 同一个理由。
#: `natural` 不在表里 = 不传这个参数，与 P2 之前的请求完全一致。
#:
#: ⚠️ `additions` 里放 `pitch` 是按《语音合成》接口文档的层级写的（`pitch` 出现在
#: `additions` 的子字段之间），**待首日实测**：上游对 `additions` 里不认识的键
#: 是忽略而不是报错，所以最坏的结果是「滑杆没效果」，与不传时一样，不会更难用。
_TONE_PITCH: dict[str, int] = {"flat": -3, "expressive": 4}


class VolcTTS(TTSProvider):
    """火山大模型 TTS 2.0（双向流式 WebSocket）。"""

    def __init__(
        self,
        name: str = "volc_tts",
        *,
        api_key: str = "",
        endpoint: str = "",
        resource_id: str = "",
        speaker: str = "",
        audio_format: str = "mp3",
        sample_rate: int = 24000,
        speech_rate: int = 0,
        enable_subtitle: bool = True,
        voices: Mapping[str, str] | None = None,
        connect: Connector | None = None,
        timeout: float | None = None,
        keep_alive: bool = True,
        **options: Any,
    ) -> None:
        super().__init__(
            name,
            default_voice=speaker,
            audio_format=audio_format,
            sample_rate=sample_rate,
            version=resource_id,
            **options,
        )
        self.endpoint = endpoint
        self.resource_id = resource_id
        self.speech_rate = int(speech_rate)
        self.enable_subtitle = bool(enable_subtitle)
        #: 缺省值留在本模块：配置层不填时不该自己再抄一遍这个数
        self.timeout = float(timeout or DEFAULT_TIMEOUT)
        #: 复用连接：整课几十个 beat 共用一个 WebSocket，省掉每 beat 一次握手
        #: （握手要钱也要时间，而 beat 之间几乎没有间隔）。
        self.keep_alive = bool(keep_alive)
        #: 展示名 → 音色 ID。列表由配置注入（控制台才能看到全量音色，
        #: 这里只认识「本项目要用的那几个」）。
        self._voices = dict(voices or {})
        self._secret = Secret(api_key)
        #: 连接工厂可注入 —— 没有火山 Key 也能把协议逻辑跑到字节级（P2-A21/A22）。
        self._connect: Connector = connect or default_connector
        self._conn: WsTransport | None = None
        #: 一条连接同一时刻只能跑一个会话，锁把并发请求排成队。
        #: 这比开一堆连接更接近上游的并发配额（一个 Key 的并发是有数的）。
        self._lock = threading.Lock()

    # --- 配置齐备性 ---

    def missing_config(self) -> list[str]:
        missing = []
        if not self._secret:
            missing.append("API Key")
        if not self.endpoint:
            missing.append("接入地址")
        if not self.default_voice and not self._voices:
            missing.append("音色 ID")
        return missing

    @property
    def configured(self) -> bool:
        return not self.missing_config()

    # --- 合成 ---

    def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float | None = None,
        **options: Any,
    ) -> TTSResult:
        """整段合成：拿到音频 + 字级时间戳。

        `speed` 是倍速（0.5~2.0），映射到上游的 `speech_rate`（-50~100，100 = 2 倍速）。
        """
        self._require(text)
        speaker = str(voice or options.get("speaker") or self.default_voice)
        params = self._req_params(
            speaker=speaker,
            speed=speed,
            pronunciation=options.get("pronunciation"),
            latex=bool(options.get("latex", False)),
            tone=str(options.get("tone") or ""),
        )
        with self._lock:
            return self._run_with_retry(text, params, speaker=speaker, speed=speed, options=options)

    def stream(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float | None = None,
        **options: Any,
    ) -> Iterator[bytes]:
        """逐块出音频。

        字幕只有整段合成才拿得到（时间戳在**结束**时才齐），所以边合成的场景
        不要指望它 —— 需要字幕的调用方请用 `synthesize()`。
        """
        self._require(text)
        speaker = str(voice or options.get("speaker") or self.default_voice)
        params = self._req_params(
            speaker=speaker,
            speed=speed,
            pronunciation=options.get("pronunciation"),
            tone=str(options.get("tone") or ""),
        )
        with self._lock:
            session_id = uuid.uuid4().hex
            conn = self._ensure_conn()
            try:
                self._start_session(conn, session_id, params)
                for chunk, _words, _usage in self._iter_frames(conn, session_id, text, params):
                    if chunk:
                        yield chunk
            except (TransportClosed, TransportTimeout):
                self._drop_conn()
                raise
            except GeneratorExit:
                # 调用方半路不要了：这次会话还欠着尾巴，留在缓冲里的残帧会串到
                # 下一次合成（表现是「莫名其妙只合成了一半」）。直接弃连接。
                self._drop_conn()
                raise

    def list_voices(self) -> list[Voice]:
        """本项目配置里认得的音色。

        火山没有「列出全部音色」的接口（音色 ID 在控制台里看），
        所以这里只回配置注入的那几个，不编造。
        """
        return [
            Voice(id=voice_id, name=display, provider=self.name)
            for display, voice_id in self._voices.items()
            if voice_id
        ]

    # --- 连接管理 ---

    def close(self) -> None:
        """断开复用的连接。进程退出或 Provider 被换掉时调用。"""
        with self._lock:
            self._drop_conn()

    def _ensure_conn(self) -> WsTransport:
        """拿到一条**已经握手完成**的连接，没有就建一条。

        建完连接还要走一次 `StartConnection` 并把连接回执读到，之后才允许发会话
        —— 这步只在新建时做，复用连接时直接返回。每条 beat 都重发一次
        `StartConnection` 的话，上游第二条就会报「连接已建立」。
        """
        if self._conn is not None:
            return self._conn
        if not self.endpoint:
            raise not_configured(self, "接入地址")
        conn = wrap(self._connect(self.endpoint, headers=self._headers(), timeout=self.timeout))
        try:
            conn.send(frames.encode_client_frame("StartConnection", {}))
            ack = _wait_for(conn, self.timeout, {frames.EV_CONNECTION_STARTED}, "连接")
            if ack.msg_type == frames.MSG_ERROR or ack.event != frames.EV_CONNECTION_STARTED:
                raise ProviderError(
                    f"火山 TTS 连接建立失败：{_frame_reason(ack)}",
                    details={"provider": self.name, "event": ack.event},
                )
        except Exception:
            # 握手没走完的连接不能留在 `self._conn` 上：留着等于把半个状态
            # 当成可用连接，后面每一次合成都会先踩到它的残帧。
            conn.close()
            raise
        self._conn = conn
        logger.debug("已连接火山 TTS：%s（connect_id=%s）", self.endpoint, ack.connect_id or "-")
        return conn

    def _drop_conn(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # 断链时的收尾不该再抛一次
                logger.debug("关闭火山 TTS 连接时出错，忽略", exc_info=True)

    def _headers(self) -> dict[str, str]:
        """鉴权与追踪头。**这是唯一读取 Key 明文的地方。**

        - `X-Api-Connect-Id`：连接追踪 ID，排障时凭它让上游定位链路；
        - `X-Control-Require-Usage-Tokens-Return: *`：让响应回传计费字符数。
          不开这个，P2-A11 的「用量可查」就只能靠估 —— 估的和账单对不上。
        """
        headers = {
            "X-Api-Key": self._secret.reveal(),
            "X-Api-Connect-Id": uuid.uuid4().hex,
            "X-Control-Require-Usage-Tokens-Return": "*",
        }
        if self.resource_id:
            headers["X-Api-Resource-Id"] = self.resource_id
        return headers

    # --- 一次会话 ---

    def _run_with_retry(
        self,
        text: str,
        params: Mapping[str, Any],
        *,
        speaker: str,
        speed: float | None,
        options: Mapping[str, Any],
    ) -> TTSResult:
        """跑一次合成；连接断了就重连再来一次。

        合成是幂等的（同样输入同样输出，服务端无副作用），所以重试是安全的。
        只重试一次：第二次还断，那就是上游或网络真有问题，如实报错。
        """
        try:
            return self._run_once(text, params, speaker=speaker, speed=speed, options=options)
        except (TransportClosed, TransportTimeout) as exc:
            logger.warning("火山 TTS 连接中断（%s），重连后重试一次", exc.__class__.__name__)
            self._drop_conn()
            return self._run_once(text, params, speaker=speaker, speed=speed, options=options)

    def _run_once(
        self,
        text: str,
        params: Mapping[str, Any],
        *,
        speaker: str,
        speed: float | None,
        options: Mapping[str, Any],
    ) -> TTSResult:
        session_id = str(options.get("session_id") or uuid.uuid4().hex)
        conn = self._ensure_conn()
        try:
            self._start_session(conn, session_id, params)
            audio = bytearray()
            subtitles: list[Subtitle] = []
            usage: dict[str, Any] = {}
            for chunk, words, used in self._iter_frames(conn, session_id, text, params):
                audio += chunk
                subtitles.extend(words)
                usage.update(used)
            if not self.keep_alive:
                self._drop_conn()
        except Exception:
            # 任何异常之后这条连接的状态都不确定了：丢掉，下次重连。
            # 留着一条「可能还有半截音频在路上」的连接，会污染下一次合成。
            self._drop_conn()
            raise

        if not audio:
            raise ProviderError(
                "火山 TTS 没有返回音频",
                details={"provider": self.name, "sessionId": session_id},
            )
        result = TTSResult(
            audio=bytes(audio),
            fmt=self.audio_format,
            duration_ms=self._duration_ms(bytes(audio), subtitles),
            provider=self.name,
            subtitles=tuple(subtitles),
            usage=usage,
        )
        logger.debug(
            "火山 TTS 合成完成 session=%s 字数=%d 音频=%d 字节 字幕=%d 段",
            session_id,
            len(text),
            len(result.audio),
            len(subtitles),
        )
        _ = (speaker, speed)  # 已写进 req_params，这里只在日志里出现过
        return result

    def _start_session(self, conn: WsTransport, session_id: str, params: Mapping[str, Any]) -> None:
        """开一个会话，并等到 `SessionStarted` 才返回。

        载荷形状和 `session_id` 的位置都是实测钉死的（见 `frames` 模块 docstring）：
        形状不对时上游回一个 `45000000` 的错误帧，比「等超时」早得多地暴露问题。
        """
        conn.send(
            frames.encode_client_frame(
                "StartSession",
                {"event": 100, "namespace": _NAMESPACE, "req_params": dict(params)},
                session_id=session_id,
            )
        )
        ack = _wait_for(conn, self.timeout, {frames.EV_SESSION_STARTED}, "会话")
        if ack.msg_type == frames.MSG_ERROR or ack.event != frames.EV_SESSION_STARTED:
            raise ProviderError(
                f"火山 TTS 会话未建立：{_frame_reason(ack)}",
                details={"provider": self.name, "sessionId": session_id, "event": ack.event},
            )

    def _finish_session(self, conn: WsTransport, session_id: str) -> None:
        """告诉上游「这个会话的文本发完了」，连接留着下一个 beat 接着用。

        **这一步是出音频的关键**，不是可有可无的收尾：末段音频和句子文本
        （`TTSSentenceEnd`，带 `text` 和字级 `words`）都是上游收到它之后才吐的。
        实测：在 `TaskRequest` 之后立刻发，拿到的音频与「等音频出完再发」等长。

        所以这里**吞掉异常是不行的** —— 发不出去就等于拿不到音频，让调用方
        按连接故障处理（重连重试一次）比返回半截音频强。
        """
        conn.send(frames.encode_client_frame("FinishSession", {}, session_id=session_id))

    def _iter_frames(
        self, conn: WsTransport, session_id: str, text: str, params: Mapping[str, Any]
    ) -> Iterator[tuple[bytes, list[Subtitle], Mapping[str, Any]]]:
        """投递文本、收帧，直到本次会话结束。

        每次 yield 是 `(音频片段, 新增字幕, 新增用量)`。
        """
        conn.send(
            frames.encode_client_frame(
                "TaskRequest",
                {
                    "event": 200,
                    "namespace": _NAMESPACE,
                    "req_params": {**params, "text": text},
                },
                session_id=session_id,
            )
        )
        self._finish_session(conn, session_id)

        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransportTimeout(f"等待火山 TTS 响应超时（{self.timeout:g}s）")
            raw = conn.receive(timeout=remaining)
            if isinstance(raw, str):  # 纯文本帧不是本协议的一部分
                logger.warning("火山 TTS 收到文本帧，已忽略：%s", raw[:120])
                continue
            frame = frames.parse_server_frame(raw)

            if frame.msg_type == frames.MSG_ERROR:
                raise ProviderError(
                    f"火山 TTS 报错：{_frame_reason(frame)}",
                    details={
                        "provider": self.name,
                        "sessionId": frame.session_id or session_id,
                        "errorCode": frame.error_code,
                    },
                )
            if frame.is_audio:
                yield frame.audio, [], {}
                continue

            payload = frame.payload if isinstance(frame.payload, Mapping) else {}
            words = _subtitles(payload)
            reported = payload.get("usage")
            usage: Mapping[str, Any] = reported if isinstance(reported, Mapping) else {}
            if words or usage:
                yield b"", words, dict(usage)

            if frame.event == frames.EV_SESSION_FAILED:
                raise ProviderError(
                    f"火山 TTS 会话失败：{_frame_reason(frame)}",
                    details={"provider": self.name, "sessionId": session_id},
                )
            if frame.event in (frames.EV_SESSION_FINISHED, frames.EV_TTS_ENDED):
                # 读到 152 才算收干净：提前返回会把尾帧留给下一次会话，
                # 下一轮在音频流里撞到它就会「提前结束、只拿到半截音频」。
                return
            error = payload.get("error")
            if error:
                raise ProviderError(
                    f"火山 TTS 报错：{error}",
                    details={"provider": self.name, "sessionId": session_id},
                )
            logger.debug(
                "火山 TTS 帧已跳过：event=%s(%s) flags=%#06x payload=%s",
                frame.event,
                _event_name(payload, frame.event),
                frame.flags,
                # 记 **键名** 而不是字节数：JSON 帧的长度永远是 0（载荷已经是对象了），
                # 而「这一帧到底带了什么」才是排障时要看的。
                sorted(payload) if payload else f"{len(frame.payload)}B",
            )

    # --- 请求参数 ---

    def _req_params(
        self,
        *,
        speaker: str,
        speed: float | None,
        pronunciation: Any = None,
        latex: bool = False,
        tone: str = "",
    ) -> dict[str, Any]:
        """按 §5.3-A3/A4 组装 `req_params`。"""
        additions: dict[str, Any] = {
            # 讲稿是 Markdown 生成的：不开这个，`**重点**` 会被念成「星星重点星星」
            "disable_markdown_filter": True,
            # 讲稿里的 `（停顿）` 一类括注不朗读
            "max_length_to_filter_parenthesis": 30,
        }
        pitch = _TONE_PITCH.get(str(tone or ""))
        if pitch:
            additions["pitch"] = pitch
        if latex:
            # 官方明说 latex_parser 适用于教育场景，但会增加时延 ——
            # 只在数学/物理课上开（由调用方判断），且必须同时开 markdown 过滤（已开）
            additions["latex_parser"] = "v2"
        tones = _pronunciation_tones(pronunciation)
        if tones:
            additions["pronunciation_dict"] = {"tone": tones}

        return {
            "speaker": speaker,
            "audio_params": {
                "format": self.audio_format,
                "sample_rate": self.sample_rate,
                "speech_rate": self._speech_rate(speed),
                "loudness_rate": 0,
                # ⚠️ `enable_subtitle` 属于 `audio_params`，**不是** `req_params` 的兄弟。
                # 放错层级上游不报错、静默忽略，表现是「拿得到音频、字级时间戳一个没有」
                # —— 前端于是永远退回整句高亮。实测：挪进来立刻回 21 段字级时戳。
                "enable_subtitle": self.enable_subtitle,
            },
            # ⚠️ additions 是 **JSON 字符串**，不是对象。序列化时别漏了转义。
            "additions": _dumps(additions),
        }

    def _speech_rate(self, speed: float | None) -> int:
        """倍速 → 上游语速。上游量程 `[-50, 100]`，100 即 2.0 倍速。"""
        if speed is None:
            return self.speech_rate
        return max(-50, min(100, round((float(speed) - 1.0) * 100)))

    def _duration_ms(self, audio: bytes, subtitles: list[Subtitle]) -> int:
        """时长：优先取字级时间戳的末位；没有时间戳就按码率估。

        「估」这件事必须说明白：它只用于播放器进度条与列表上的分钟数，
        不参与计费（计费看 `usage`）。字幕时间戳才是权威值。
        """
        if subtitles:
            return int(max(s.end_ms for s in subtitles))
        if self.audio_format == "mp3":
            return int(len(audio) * 8 * 1000 / _DEFAULT_BIT_RATE)
        # pcm 16bit 单声道
        bytes_per_second = self.sample_rate * 2
        return int(len(audio) / bytes_per_second * 1000)

    def _require(self, text: str) -> None:
        if not self.configured:
            raise not_configured(self)
        if not text.strip():
            raise ProviderError("待合成的文本是空的", details={"provider": self.name})


# --- 帧载荷解析的小工具（只服务于本适配器）---


#: 事件号 → 名字。只用于**日志和错误文案**，判断逻辑一律用事件号
#: （号是实测钉死的，名字是给人看的）。表外的号回 `""`，不当成错误。
_EVENT_NAMES: Mapping[int, str] = {
    frames.EV_CONNECTION_STARTED: "ConnectionStarted",
    frames.EV_CONNECTION_FAILED: "ConnectionFailed",
    frames.EV_CONNECTION_FINISHED: "ConnectionFinished",
    frames.EV_SESSION_STARTED: "SessionStarted",
    frames.EV_SESSION_FINISHED: "SessionFinished",
    frames.EV_SESSION_FAILED: "SessionFailed",
    frames.EV_SENTENCE_START: "TTSSentenceStart",
    frames.EV_SENTENCE_END: "TTSSentenceEnd",
    frames.EV_TTS_RESPONSE: "TTSResponse",
    frames.EV_TTS_ENDED: "TTSEnded",
}


def _event_name(payload: Mapping[str, Any], event: int | None) -> str:
    """事件名：先认载荷里的 `EventType` 文案，再按事件号查表。"""
    for key in ("EventType", "event_type"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return _EVENT_NAMES.get(event or 0, f"event={event}") if event is not None else ""


def _frame_reason(frame: frames.ServerFrame, fallback: str = "（上游未给原因）") -> str:
    """从一帧里拼出一句能照着查的报错。

    错误帧的文案可能是空的（上游只给错误码），这时**必须把码带上** ——
    「上游未给原因」对排障等于没说。
    """
    if frame.error:
        return frame.error
    if isinstance(frame.payload, Mapping):
        text = _reason(frame.payload)
        if text != "（上游未给原因）":
            return text
    return fallback


def _wait_for(
    conn: WsTransport, timeout: float, stop: set[int], what: str
) -> frames.ServerFrame:
    """读到 `stop` 里的事件号为止，返回那一帧。

    途中的音频帧、别的事件帧一律跳过（同一个连接上跑过多次会话时，
    上一轮的尾帧可能还没读完）。错误帧和会话失败帧**立即返回**，由调用方判。
    超时抛 `TransportTimeout`，调用方按「连接不可信」处理。
    """
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TransportTimeout(f"等待火山 TTS {what}回执超时（{timeout:g}s）")
        raw = conn.receive(timeout=remaining)
        if isinstance(raw, str):
            logger.warning("火山 TTS 收到文本帧，已忽略：%s", raw[:120])
            continue
        frame = frames.parse_server_frame(raw)
        if frame.msg_type == frames.MSG_ERROR or frame.event == frames.EV_SESSION_FAILED:
            return frame
        if frame.event in stop:
            return frame
        logger.debug("等待 %s 回执时跳过一帧：event=%s", what, frame.event)


def _subtitles(payload: Mapping[str, Any]) -> list[Subtitle]:
    """从任意事件帧里捞出字级时间戳。

    为什么不在「TTSSubtitle 事件号」上判断：规范没给这个号（只说有这个事件）。
    而 `words[]` 的形状是写明的，所以按载荷特征识别比按事件号识别可靠。
    时间单位：`startTime/endTime` 是**秒**，`start_time/end_time` 是**毫秒**。
    """
    words = payload.get("words")
    if not isinstance(words, list):
        return []
    out: list[Subtitle] = []
    for item in words:
        if not isinstance(item, Mapping):
            continue
        word = str(item.get("word") or item.get("text") or "")
        if not word:
            continue
        if "startTime" in item or "endTime" in item:
            start = _to_ms(item.get("startTime"), per_second=True)
            end = _to_ms(item.get("endTime"), per_second=True)
        else:
            start = _to_ms(item.get("start_time"))
            end = _to_ms(item.get("end_time"))
        out.append(Subtitle(text=word, start_ms=start, end_ms=end))
    return out


def _to_ms(value: Any, *, per_second: bool = False) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return int(number * 1000) if per_second else int(number)


def _reason(payload: Mapping[str, Any]) -> str:
    for key in ("message", "error", "status_code", "Message"):
        value = payload.get(key)
        if value:
            return str(value)
    return "（上游未给原因）"


def _pronunciation_tones(pronunciation: Any) -> list[str]:
    """术语纠音表 → `原词/(pin1) 音节` 形式。

    接受 `{"梯度下降": "ti1 du4 xia4 jiang4"}` 或直接一串成品字符串。
    与 ASR 热词表**共用同一份课程术语表**：同一份数据，两处收益（P2-A20）。
    """
    if not pronunciation:
        return []
    if isinstance(pronunciation, str):
        return [pronunciation]
    if isinstance(pronunciation, Mapping):
        out = []
        for word, reading in pronunciation.items():
            if not word:
                continue
            text = str(reading or "").strip()
            if not text:
                continue
            syllables = text if "(" in text else " ".join(f"({p})" for p in text.split())
            out.append(f"{word}/{syllables}")
        return out
    if isinstance(pronunciation, (list, tuple)):
        out = []
        for item in pronunciation:
            out.extend(_pronunciation_tones({item[0]: item[1]} if isinstance(item, (list, tuple)) and len(item) == 2 else item))
        return out
    return []


def _dumps(data: Mapping[str, Any]) -> str:
    """`additions` 是 JSON **字符串**而不是对象（A4 表末行特别强调）。"""
    return json.dumps(data, ensure_ascii=False)


__all__ = ["DEFAULT_TIMEOUT", "VolcTTS"]
