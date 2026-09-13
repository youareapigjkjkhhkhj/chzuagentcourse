"""语音三件套的协议行为（P2-A8/A11/A12/A13/A17/A18/A19/A20）。

**没有火山 Key 也能跑完**：三个适配器都收一个 `connect=` 连接工厂，
这里塞一个假上游（`FakeUpstream`）进去，真协议代码一行不改。

假上游按脚本回话，脚本里的每条消息都是**手写的 JSON / 手搭的字节**，
不用被测适配器的编码器去造 —— 否则「写错了」和「读错了」会一起过。
字节布局的穷举断言在 test_voice_codecs.py，这里管的是**行为**：
什么时候发什么、什么时候重连、什么时候该说人话。
"""

from __future__ import annotations

import base64
import gzip
import json
import struct
from collections import deque
from typing import Any, Iterable

import pytest

from app.common.errors import RateLimitError
from app.providers.asr import frames as asr_frames
from app.providers.asr.volc_asr import VolcASR
from app.providers.base import ProviderError, ProviderNotConfiguredError
from app.providers.transport import TransportClosed, TransportTimeout
from app.providers.tts import frames as tts_frames
from app.providers.tts.volc_realtime import (
    MODE_KEEP_ALIVE,
    VolcRealtime,
)
from app.providers.tts.volc_realtime import (
    PACKET_BYTES as REALTIME_PACKET_BYTES,
)
from app.providers.tts.volc_tts import VolcTTS

pytestmark = pytest.mark.unit

VOICE_TTS = "zh_male_m191_uranus_bigtts"
VOICE_REALTIME = "zh_male_yunzhou_jupiter_bigtts"


# --- 假上游 ---


class FakeConn:
    """一条假连接：send 记下来，receive 按脚本回话，没脚本了就超时。"""

    def __init__(self, pending: Iterable[Any] = (), *, hold_until_audio: int = 0) -> None:
        self.sent: list[bytes | str] = []
        self.pending: deque[Any] = deque(pending)
        #: 「上游要收到 N 个音频包才开始回话」。默认 0：一收就回。
        #: 用它模拟「服务端在末包之后才出最终结果」的真实节奏。
        self.hold_until_audio = int(hold_until_audio)
        self.audio_sent = 0
        self.closed = False
        self.close_count = 0

    def send(self, data: bytes | str) -> None:
        if self.closed:
            raise TransportClosed("连接已关闭")
        self.sent.append(data)
        if isinstance(data, bytes) and len(data) > 8 and data[1] >> 4 == 0b0010:
            self.audio_sent += 1

    def receive(self, timeout: float | None = None) -> bytes | str:
        if self.closed:
            raise TransportClosed("连接已关闭")
        if self.audio_sent < self.hold_until_audio or not self.pending:
            raise TransportTimeout("没有新消息")
        item = self.pending.popleft()
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self, reason: str | None = None) -> None:
        self.closed = True
        self.close_count += 1

    # --- 断言辅助 ---

    def json_sent(self, kind: str) -> list[dict]:
        """所有已发出的 JSON 消息里，`type` 等于 kind 的那些（实时语音用）。"""
        out = []
        for item in self.sent:
            if not isinstance(item, str):
                continue
            data = json.loads(item)
            if data.get("type") == kind:
                out.append(data)
        return out

    @property
    def binary(self) -> list[bytes]:
        return [item for item in self.sent if isinstance(item, bytes)]


class FakeUpstream:
    """连接工厂：第 n 次连接回第 n 条脚本。用完的脚本按顺序取，取完就没有了。"""

    def __init__(self, *scripts: Iterable[Any], hold_until_audio: int = 0) -> None:
        self.scripts = list(scripts)
        self.conns: list[FakeConn] = []
        self.urls: list[str] = []
        self.headers: list[Any] = []
        self.hold_until_audio = hold_until_audio

    def __call__(self, url: str, **options: Any) -> FakeConn:
        pending = self.scripts.pop(0) if self.scripts else []
        conn = FakeConn(pending, hold_until_audio=self.hold_until_audio)
        self.conns.append(conn)
        self.urls.append(url)
        self.headers.append(options.get("headers"))
        return conn

    @property
    def last(self) -> FakeConn:
        return self.conns[-1]

    @property
    def opens(self) -> int:
        return len(self.conns)


def _body(frame: bytes, offset: int) -> bytes:
    size = struct.unpack_from(">I", frame, offset)[0]
    body = frame[offset + 4 : offset + 4 + size]
    return gzip.decompress(body) if frame[2] & 0x0F == 0b0001 else body


def tts_uplink(conn: FakeConn) -> list[tuple[int, str, Any]]:
    """TTS 上行帧 → [(事件号, session_id, payload)]。

    布局（实测口径）：头 4 + 事件号 4 + [sid 长度 4 + sid] + 载荷长度 4 + 载荷。
    只有连接类事件（StartConnection / FinishConnection）没有 sid 那一段。
    """
    out = []
    for frame in conn.binary:
        event = struct.unpack_from(">i", frame, 4)[0]
        offset, sid = 8, ""
        if event not in (1, 2):  # 连接类事件
            (sid_len,) = struct.unpack_from(">I", frame, offset)
            offset += 4
            sid = frame[offset : offset + sid_len].decode("utf-8")
            offset += sid_len
        out.append((event, sid, json.loads(_body(frame, offset) or b"{}")))
    return out


def asr_uplink(conn: FakeConn) -> list[tuple[int, Any]]:
    """ASR 上行帧 → [(序号, payload)]。

    序号在不在，只看 flags 最低位；payload 是 JSON 还是裸 PCM，只看序列化位 ——
    两者互相独立，本函数如实反映这一点（音频段多出来的 4 字节就在这儿露馅）。
    """
    out = []
    for frame in conn.binary:
        has_sequence = bool(frame[1] & 0x0F & 0b0001)
        offset = 8 if has_sequence else 4
        sequence = struct.unpack_from(">i", frame, 4)[0] if has_sequence else 0
        body = _body(frame, offset)
        out.append((sequence, json.loads(body) if frame[2] >> 4 == 0b0001 else body))
    return out


# --- 手搭的服务端帧（与 test_voice_codecs.py 同源，此处只保留用得到的形状）---


def tts_frame(
    payload: Any, *, event: int | None = None, error: bool = False, raw: bool = False
) -> bytes:
    """服务端下行帧：头 + [事件号 + sid 长度 + sid] + payload 长度 + payload。

    - `raw=True`：音频帧 —— 真机上是 `0b1011` + 事件号 352 + 裸 mp3 字节；
    - `error=True`：错误帧 —— `0b1111`，帧头之后直接是错误码，**没有事件号也没有 sid**。
    """
    flags = 0b0100 if event is not None else 0b0000
    msg_type = 0b1111 if error else (0b1011 if raw else 0b1001)
    ser = 0b0000 if raw else 0b0001
    head = bytes([0x11, (msg_type << 4) | flags, (ser << 4) | 0b0000, 0])
    out = bytearray(head)
    if error:
        out += struct.pack(">I", 55000002)  # 错误码
    elif flags & 0b0100:
        out += struct.pack(">i", event or 0)
        sid = b"sess-1"
        out += struct.pack(">I", len(sid)) + sid
    body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
    out += struct.pack(">I", len(body)) + body
    return bytes(out)


def tts_audio(mp3: bytes) -> bytes:
    """一帧真机形状的音频：`0b1011` + 事件号 352 + 裸字节。"""
    return tts_frame(mp3, event=tts_frames.EV_TTS_RESPONSE, raw=True)


def tts_greeting() -> list[bytes]:
    """新建连接的回执：`StartConnection` → 50，`StartSession` → 150。

    客户端在**发会话之前**要等到这两帧（实测口径）：`_ensure_conn` 等 50，
    `_start_session` 等 150。所以每条连接的脚本都得先把它们排上。
    """
    return [
        tts_frame({}, event=tts_frames.EV_CONNECTION_STARTED),
        tts_frame({}, event=tts_frames.EV_SESSION_STARTED),
    ]


def asr_frame(
    code: int, *, result: Any = None, last: bool = False, wrapped: bool = False
) -> bytes:
    """服务端响应帧。

    默认按**实拍**的信封拼：`{"audio_info": ..., "result": {"text": ...}}` ——
    `result` 直接挂在顶层，没有 `payload_msg` 那一层。`wrapped=True` 拼文档里
    那一版（`{"payload_msg": {"result": ...}}`），两种都得吃（§5.3-C6）。
    """
    envelope: dict[str, Any] = {"code": code}
    if result is not None:
        if wrapped:
            envelope["payload_msg"] = {"result": result}
        else:
            envelope["audio_info"] = {"duration": 1400}
            envelope["result"] = result
    if last:
        envelope["is_last_package"] = True
    head = bytes([0x11, (0b1001 << 4) | 0b0001, 0x10, 0])
    body = json.dumps(envelope, ensure_ascii=False).encode()
    return head + struct.pack(">iI", 1, len(body)) + body


def audio_payload(size: int, seed: int = 7) -> bytes:
    return bytes((seed + i) % 256 for i in range(size))


# ============ VolcTTS ============


def tts_provider(upstream: FakeUpstream, **kw: Any) -> VolcTTS:
    options = {
        "api_key": "k-test",
        "endpoint": "wss://example.invalid/tts",
        "resource_id": "seed-tts-2.0",
        "speaker": VOICE_TTS,
        "connect": upstream,
    }
    options.update(kw)
    return VolcTTS(**options)


def end_script(mp3: bytes | None = None) -> list[Any]:
    """一条连接的完整脚本：握手回执 → 音频 → 句子文本 → 会话结束。

    给那些只想看**上行发了什么**的用例：没有音频帧的话，`_run_once` 会如实报
    「没有返回音频」—— 那是另一条用例的事。
    """
    return [
        *tts_greeting(),
        tts_audio(audio_payload(16) if mp3 is None else mp3),
        tts_frame({"text": "你好。"}, event=tts_frames.EV_SENTENCE_END),
        tts_frame({}, event=tts_frames.EV_SESSION_FINISHED),
    ]


class TestVolcTTS:
    def test_synthesize_collects_audio_subtitles_and_usage(self):
        """一次合成：音频、字级时间戳、上游计量三样都要落到 TTSResult 上。"""
        mp3 = audio_payload(48)
        upstream = FakeUpstream(
            [
                *tts_greeting(),
                tts_frame(
                    {
                        "EventType": "TTSSentenceStart",
                        "words": [{"word": "梯度", "startTime": 0.0, "endTime": 0.24}],
                    },
                    event=tts_frames.EV_SENTENCE_START,
                ),
                tts_audio(mp3),
                tts_frame(
                    {"EventType": "TTSSentenceEnd", "usage": {"text_words": 12}},
                    event=tts_frames.EV_SENTENCE_END,
                ),
                tts_frame({}, event=tts_frames.EV_SESSION_FINISHED),
            ]
        )

        result = tts_provider(upstream).synthesize("梯度下降是什么？")

        assert result.audio == mp3
        assert result.fmt == "mp3"
        assert [s.text for s in result.subtitles] == ["梯度"]
        assert result.subtitles[0].end_ms == 240  # startTime/endTime 的单位是**秒**
        assert result.duration_ms == 240  # 有时戳就用时戳，不按码率估
        assert result.usage["text_words"] == 12  # P2-A11 的用量来源
        assert result.provider == "volc_tts"

    def test_uplink_order_and_task_text(self):
        """上行顺序：StartConnection → StartSession → TaskRequest → FinishSession。

        `FinishSession` 紧跟在 `TaskRequest` 后面不是「收尾」，是**出音频的条件**：
        末段音频和句子文本都是上游收到它之后才吐的（实测）。
        """
        upstream = FakeUpstream(end_script())
        tts_provider(upstream).synthesize("卷积")

        frames = tts_uplink(upstream.last)
        assert [event for event, _sid, _body in frames] == [
            tts_frames.UPLINK_EVENTS["StartConnection"],
            tts_frames.UPLINK_EVENTS["StartSession"],
            tts_frames.UPLINK_EVENTS["TaskRequest"],
            tts_frames.UPLINK_EVENTS["FinishSession"],
        ]
        assert frames[2][2]["req_params"]["text"] == "卷积"
        assert frames[2][1] == frames[1][1], "同一个会话：TaskRequest 要带 StartSession 那个 sid"
        assert frames[2][1], "sid 不能是空的"
        assert frames[0][1] == "", "连接级事件没有 sid"
        assert not upstream.last.closed, "只关会话、不关连接：下一个 beat 还要复用"

    def test_req_params_carry_markdown_and_pronunciation(self):
        """A19 关 Markdown 过滤；A20 课程术语进纠音表；additions 是 JSON **字符串**。"""
        upstream = FakeUpstream(end_script())
        tts_provider(upstream).synthesize(
            "**重点**：梯度下降", pronunciation={"梯度下降": "ti1 du4 xia4 jiang4"}
        )

        params = tts_uplink(upstream.last)[1][2]["req_params"]
        assert isinstance(params["additions"], str), "additions 必须是 JSON 字符串"
        additions = json.loads(params["additions"])
        assert additions["disable_markdown_filter"] is True
        assert additions["pronunciation_dict"]["tone"] == ["梯度下降/(ti1) (du4) (xia4) (jiang4)"]
        assert params["speaker"] == VOICE_TTS
        # 字幕开关在 audio_params 里，不是 req_params 的兄弟：放错层级上游
        # 不报错、静默忽略，字级时间戳就永远拿不到（实测踩过）
        assert params["audio_params"]["enable_subtitle"] is True
        assert "enable_subtitle" not in params

    @pytest.mark.parametrize(("speed", "expected"), [(2.0, 100), (1.0, 0), (0.5, -50), (3.0, 100)])
    def test_speed_maps_to_upstream_speech_rate(self, speed: float, expected: int):
        """倍速 → `[-50, 100]` 的语速，越界要夹住而不是原样发。"""
        upstream = FakeUpstream(end_script())
        tts_provider(upstream).synthesize("你好", speed=speed)

        params = tts_uplink(upstream.last)[1][2]["req_params"]
        assert params["audio_params"]["speech_rate"] == expected

    def test_version_is_resource_id_so_cache_key_changes_with_model(self):
        """上游换一代模型，缓存键就得换 —— 它取自 resource_id。"""
        provider = tts_provider(FakeUpstream())
        assert provider.version == "seed-tts-2.0"
        assert provider.describe()["version"] == "seed-tts-2.0"

    def test_unknown_event_number_is_skipped_not_fatal(self):
        """规范只给「常见事件号」：没见过的号要跳过，不能掐断整条合成流。"""
        mp3 = audio_payload(16)
        upstream = FakeUpstream(
            [
                *tts_greeting(),
                tts_frame({"EventType": "SomethingNew"}, event=999),
                tts_audio(mp3),
                tts_frame({}, event=tts_frames.EV_SESSION_FINISHED),
            ]
        )
        assert tts_provider(upstream).synthesize("你好").audio == mp3

    def test_error_frame_raises_and_drops_the_connection(self):
        """上游报错 → 抛 ProviderError；这条连接状态已不可知，必须丢掉。"""
        upstream = FakeUpstream(
            [*tts_greeting(), tts_frame({"error": "invalid speaker"}, error=True)]
        )
        provider = tts_provider(upstream)

        with pytest.raises(ProviderError) as excinfo:
            provider.synthesize("你好")
        assert "invalid speaker" in str(excinfo.value)

        # 下一次合成应当重开一条连接，而不是复用那条「可能还有半截音频」的
        upstream.scripts.append(end_script())
        provider.synthesize("再来一次")
        assert upstream.opens == 2

    def test_connection_drop_is_retried_once(self):
        """连接断了重连再试一次 —— 合成是幂等的，重试是安全的。"""
        upstream = FakeUpstream([TransportClosed("对端关闭")], end_script())
        result = tts_provider(upstream).synthesize("你好")
        assert result.audio
        assert upstream.opens == 2

    def test_empty_text_and_missing_config_are_distinct_errors(self):
        with pytest.raises(ProviderNotConfiguredError) as excinfo:
            tts_provider(FakeUpstream(), api_key="").synthesize("你好")
        assert excinfo.value.code == 40201
        assert "API Key" in str(excinfo.value)

        with pytest.raises(ProviderError):
            tts_provider(FakeUpstream()).synthesize("   ")

    def test_list_voices_only_reports_configured_ones(self):
        provider = tts_provider(FakeUpstream(), voices={"沈老师": VOICE_TTS, "顾老师": ""})
        assert [v.id for v in provider.list_voices()] == [VOICE_TTS]


# ============ VolcASR ============


def asr_provider(upstream: FakeUpstream, **kw: Any) -> VolcASR:
    options = {
        "api_key": "k-test",
        "endpoint": "wss://example.invalid/asr",
        "connect": upstream,
    }
    options.update(kw)
    return VolcASR(**options)


class TestVolcASR:
    def test_stream_sends_full_request_then_audio_packets(self):
        """首包是 JSON 参数包（带序号），之后每 6400 字节一包裸 PCM（不是 20ms/640B）。"""
        pcm = audio_payload(asr_frames.PACKET_BYTES * 2)
        upstream = FakeUpstream(
            [asr_frame(0, result={"text": "这是字节跳动，"}, last=True)],
            hold_until_audio=3,
        )

        segments = list(asr_provider(upstream).stream([pcm]))
        frames = asr_uplink(upstream.last)

        # 首包 1 号，音频包依次递增（序号在 flags 最低位置 1 时才存在）；
        # 末包取负 —— 上游收到正数的末包会判 sequence mismatch（实拍）
        assert [sequence for sequence, _ in frames] == [1, 2, 3, -4]
        assert frames[0][1]["audio"]["rate"] == 16000
        assert frames[1][1] == pcm[: asr_frames.PACKET_BYTES]  # 音频包 payload 是裸 PCM
        assert segments[-1].text == "这是字节跳动，"
        assert segments[-1].final

    def test_last_packet_carries_the_tail_and_the_stop_flag(self):
        """说完了：尾巴（不足一包的部分）也要发出去，并带负包标志位。"""
        pcm = audio_payload(asr_frames.PACKET_BYTES + 320)
        upstream = FakeUpstream(
            [asr_frame(0, result={"text": "你好"}, last=True)],
            hold_until_audio=2,
        )
        list(asr_provider(upstream).stream([pcm]))

        last = upstream.last.binary[-1]
        assert last[1] & asr_frames.FLAG_NEG_SEQUENCE, "末包必须置负包标志位（判停靠它）"
        sequence, tail = asr_uplink(upstream.last)[-1]
        assert sequence < 0, "末包的序号写负数，写正数上游当场掐连接（实拍）"
        assert len(tail) == 320  # 尾包 = 余数

    def test_transcribe_strips_wav_header(self):
        wav = b"RIFF" + b"\x00" * 35 + b"\x04" + b"WAVE" + audio_payload(1000)  # 共 44 字节头
        upstream = FakeUpstream([asr_frame(0, result={"text": "卷积"}, last=True)])

        result = asr_provider(upstream).transcribe(wav)

        assert result.text == "卷积"
        assert result.provider == "volc_asr"
        assert len(asr_uplink(upstream.last)[-1][1]) == 1000  # 44 字节 wav 头已剥掉

    def test_stream_emits_the_running_transcript_verbatim(self):
        """累计文本 = 上游每帧的全文，**整段替换**（P2-A14）。

        第三条是重复下发，不许变成四个字；第二条是**回改**（实拍里
        `同学们。` → `同学们好。` 就是这种），必须替换而不是拼上去。
        """
        upstream = FakeUpstream(
            [
                asr_frame(0, result={"text": "同学们。"}),
                asr_frame(0, result={"text": "同学们好。"}),
                asr_frame(0, result={"text": "同学们好。"}, last=True),
            ],
            hold_until_audio=3,
        )
        segments = list(asr_provider(upstream).stream([audio_payload(asr_frames.PACKET_BYTES * 2)]))

        texts = [s.text for s in segments]
        assert texts == ["同学们。", "同学们好。", "同学们好。"]
        assert segments[-1].final

    def test_stream_keeps_the_previous_text_when_a_frame_carries_none(self):
        """空帧是心跳，不是「撤回」—— 别把屏幕上已有的字擦掉。"""
        upstream = FakeUpstream(
            [
                asr_frame(0, result={"text": "卷积"}),
                asr_frame(0, result={"text": ""}),
                asr_frame(0, result={"text": "卷积"}, last=True),
            ],
            hold_until_audio=3,
        )
        segments = list(asr_provider(upstream).stream([audio_payload(asr_frames.PACKET_BYTES * 2)]))

        assert [s.text for s in segments] == ["卷积", "卷积", "卷积"]

    def test_documented_envelope_with_payload_msg_is_also_accepted(self):
        """文档那版信封（多一层 `payload_msg`）也得吃：只认一种的表现是**静默空文本**。"""
        upstream = FakeUpstream(
            [asr_frame(0, result={"text": "卷积"}, last=True, wrapped=True)]
        )

        segments = list(asr_provider(upstream).stream([audio_payload(64)]))

        assert segments[-1].text == "卷积"

    @pytest.mark.parametrize(
        ("previous", "piece", "expected"),
        [
            ("同学们。", "同学们好。", "同学们好。"),  # 回改：替换，不许拼成两句
            ("梯度", "梯度下降", "梯度下降"),  # 尾部继续长
            ("梯度", "梯度", "梯度"),  # 重复下发：不许变长
            ("同学们。", "", "同学们。"),  # 空帧：保留已有的
        ],
    )
    def test_merge_text_rules(self, previous: str, piece: str, expected: str):
        """`result_type=full` 下上游给的就是全文，所以规则只有一条：新的覆盖旧的。"""
        from app.providers.asr.volc_asr import _merge_text

        assert _merge_text(previous, piece) == expected

    def test_hotwords_go_into_the_first_packet(self):
        """A20：课程术语表同时喂给 ASR 热词与 TTS 纠音。"""
        upstream = FakeUpstream([asr_frame(0, result={"text": "x"}, last=True)])
        list(asr_provider(upstream, hotwords=["梯度下降"]).stream([audio_payload(100)]))

        first = asr_uplink(upstream.last)[0][1]
        context = json.loads(first["request"]["corpus"]["context"])
        assert context == {"hotwords": [{"word": "梯度下降"}]}

    def test_empty_audio_tells_the_student_to_say_it_again(self):
        """45000002 是「没听清」，不是系统故障 —— 文案要能直接给学生看。"""
        upstream = FakeUpstream([asr_frame(45000002)])

        with pytest.raises(ProviderError) as excinfo:
            list(asr_provider(upstream).stream([audio_payload(64)]))
        assert "没有听清" in str(excinfo.value)

    def test_5xx_is_marked_retryable(self):
        upstream = FakeUpstream([asr_frame(55000001)])
        with pytest.raises(ProviderError) as excinfo:
            list(asr_provider(upstream).stream([audio_payload(64)]))
        assert excinfo.value.details["retryable"] is True

    def test_connection_is_not_reused_across_recognitions(self):
        """一次识别一条连接：复用会把上一段的会话上下文带过去。"""
        upstream = FakeUpstream(
            [asr_frame(0, result={"text": "一"}, last=True)],
            [asr_frame(0, result={"text": "二"}, last=True)],
        )
        provider = asr_provider(upstream)

        assert provider.transcribe(audio_payload(100)).text == "一"
        assert provider.transcribe(audio_payload(100)).text == "二"
        assert upstream.opens == 2
        assert upstream.conns[0].closed

    def test_packet_size_follows_configuration(self):
        provider = asr_provider(FakeUpstream(), packet_ms=100)
        assert provider.packet_bytes == 3200

    def test_wrong_sample_rate_is_refused_before_touching_the_network(self):
        from app.common.errors import ValidationError

        upstream = FakeUpstream()
        with pytest.raises(ValidationError):
            list(asr_provider(upstream).stream([b"\x00" * 8], sample_rate=48000))
        assert upstream.opens == 0


# ============ VolcRealtime ============


def realtime_provider(upstream: FakeUpstream, **kw: Any) -> VolcRealtime:
    options = {
        "api_key": "k-test",
        "endpoint": "wss://example.invalid/rt",
        "model": "1.2.6.1",
        "speaker": VOICE_REALTIME,
        "connect": upstream,
        "qpm_limit": 0,  # 频率闸门在下面单独测，别的影响别的用例
    }
    options.update(kw)
    return VolcRealtime(**options)


def created(session_id: str = "dlg-1") -> str:
    return json.dumps({"type": "session.created", "session": {"id": session_id}})


class TestVolcRealtime:
    def test_session_create_shape(self):
        """§5.3-B2：输入 16k pcm、输出 **pcm_s16le** 24k、三个 extra 都不许为空。"""
        upstream = FakeUpstream([created()])
        session = realtime_provider(upstream).start_session(
            voice=VOICE_REALTIME, instructions="你是沈老师", hotwords=["梯度下降"]
        )
        session.start()

        body = upstream.last.json_sent("session.create")[0]
        assert body["event_id"]  # 每条上行都带追踪 ID
        assert body["session"]["model"] == "1.2.6.1"
        assert body["session"]["instructions"] == "你是沈老师"
        assert body["session"]["audio"]["input"]["format"] == {"type": "pcm", "rate": 16000}
        output = body["session"]["audio"]["output"]
        assert output["format"] == {"type": "pcm_s16le", "rate": 24000}
        assert output["voice"] == VOICE_REALTIME

        extension = body["extension"]
        for kind in ("asr", "tts", "dialog"):
            assert isinstance(extension[kind]["extra"], dict), f"{kind}.extra 置空会报 42000020"
        assert extension["dialog"]["extra"]["input_mod"] == "push_to_talk"  # A18
        assert extension["asr"]["extra"]["context"]["hotwords"] == [{"word": "梯度下降"}]
        assert session.dialog_id == "dlg-1"

    def test_keep_alive_mode_is_configurable(self):
        """模式 2 的常开麦：换掉 input_mod 即可，不改上行事件。"""
        upstream = FakeUpstream([created()])
        session = realtime_provider(upstream).start_session(mode=MODE_KEEP_ALIVE)
        session.start()
        body = upstream.last.json_sent("session.create")[0]
        assert body["extension"]["dialog"]["extra"]["input_mod"] == "keep_alive"

        session.keep_alive(muted=True)
        session.keep_alive(muted=False)
        assert [e["type"] for e in upstream.last.json_sent("input_audio_mute.commit")] == [
            "input_audio_mute.commit"
        ]
        assert [e["type"] for e in upstream.last.json_sent("input_audio_unmute.commit")] == [
            "input_audio_unmute.commit"
        ]

    def test_audio_is_repacked_into_640_byte_base64_frames(self, monkeypatch):
        """A16：实时语音按 20ms / 640 字节上行，块大小由前端定不了。"""
        sleeps: list[float] = []
        monkeypatch.setattr("app.providers.tts.volc_realtime.time.sleep", sleeps.append)

        upstream = FakeUpstream([created()])
        session = realtime_provider(upstream).start_session()
        session.start()
        session.send_audio(audio_payload(REALTIME_PACKET_BYTES * 3))

        appends = upstream.last.json_sent("input_audio_buffer.append")
        assert len(appends) == 3
        for event in appends:
            assert len(base64.b64decode(event["audio"])) == REALTIME_PACKET_BYTES
        assert sleeps == [pytest.approx(0.02, abs=0.02)] * 2  # 二、三包按真实节奏等

    def test_commit_flushes_the_tail_before_saying_done(self):
        """松开按键：先补发不足一包的尾巴，再 commit —— 少了尾巴就丢字。"""
        upstream = FakeUpstream([created()])
        session = realtime_provider(upstream).start_session()
        session.start()
        session.send_audio(audio_payload(300))
        assert upstream.last.json_sent("input_audio_buffer.append") == []  # 攒着，不满一包不发

        session.commit_audio()
        kinds = [json.loads(item)["type"] for item in upstream.last.sent if isinstance(item, str)]
        assert kinds[-2:] == ["input_audio_buffer.append", "input_audio_buffer.commit"]
        tail = upstream.last.json_sent("input_audio_buffer.append")[0]
        assert len(base64.b64decode(tail["audio"])) == 300

    def test_downlink_events_are_translated(self):
        """下游事件翻译成语义事件：学生说的、模型说的、音频、用量各归各位。

        字段名按**实拍**写：增量事件用 `delta`（文本和音频都是），只有
        `.completed` / `.done` 才给 `text`。写反的表现是「事件照来、内容全空」。
        """
        pcm = audio_payload(32)
        upstream = FakeUpstream(
            [
                created(),
                json.dumps({"type": "conversation.item.input_audio_transcription.started"}),
                json.dumps({"type": "conversation.item.input_audio_transcription.delta", "delta": "梯度"}),
                json.dumps(
                    {"type": "conversation.item.input_audio_transcription.completed", "text": "梯度是什么"}
                ),
                json.dumps({"type": "response.output_text.delta", "delta": "我先说"}),
                json.dumps(
                    {
                        "type": "response.output_audio.delta",
                        "delta": base64.b64encode(pcm).decode(),
                    }
                ),
                json.dumps({"type": "response.output_audio.done", "status_code": "OK"}),
                json.dumps({"type": "response.done", "usage": {"input_text_tokens": 3}}),
            ]
        )
        session = realtime_provider(upstream).start_session()
        session.start()

        events = list(session.receive(timeout=0.2))
        assert [e.type for e in events] == [
            "barge_in",  # A8：学生一开口就打断播报
            "asr",
            "asr",
            "reply",
            "audio",
            "done",
            "usage",
        ]
        assert events[2].final and events[2].text == "梯度是什么"
        assert events[4].audio == pcm  # Base64 已解开
        assert events[6].raw["input_text_tokens"] == 3

    def test_unintelligible_is_a_student_side_message(self):
        upstream = FakeUpstream(
            [
                created(),
                json.dumps(
                    {
                        "type": "conversation.item.input_audio_transcription.failed",
                        "error": {"code": "audio_unintelligible"},
                    }
                ),
            ]
        )
        session = realtime_provider(upstream).start_session()
        session.start()

        events = list(session.receive(timeout=0.2))
        assert [e.type for e in events] == ["error"]
        assert "没有听清" in events[0].text

    def test_unknown_events_are_skipped(self):
        upstream = FakeUpstream([created(), json.dumps({"type": "response.something.new"})])
        session = realtime_provider(upstream).start_session()
        session.start()
        assert list(session.receive(timeout=0.1)) == []

    def test_released_session_is_rebuilt_without_the_user_noticing(self):
        """A17：10 分钟空闲被释放（45000003）是常规路径 —— 自动重建，前端无感。"""
        upstream = FakeUpstream(
            [
                created("dlg-1"),
                json.dumps({"type": "error", "error": {"code": 45000003, "message": "Abnormal silence"}}),
                created("dlg-2"),
            ]
        )
        session = realtime_provider(upstream).start_session()
        session.start()

        events = list(session.receive(timeout=0.2))
        assert [e.type for e in events] == ["reconnected"]
        assert len(upstream.last.json_sent("session.create")) == 2  # 重发了一次建会话
        assert upstream.opens == 1  # 连接没断，不用重连
        assert session.dialog_id == "dlg-2"

    def test_broken_transport_reconnects_and_recreates(self):
        upstream = FakeUpstream(
            [created("dlg-1"), TransportClosed("对端关闭")],
            [created("dlg-2")],
        )
        session = realtime_provider(upstream).start_session()
        session.start()

        list(session.receive(timeout=0.2))
        assert upstream.opens == 2
        assert session.dialog_id == "dlg-2"

    def test_close_waits_for_the_closed_ack(self):
        """A13：`session.close` 要等到 `session.closed` 再断连，否则上游报 55000001。"""
        upstream = FakeUpstream([created(), json.dumps({"type": "session.closed"})])
        session = realtime_provider(upstream).start_session()
        session.start()

        session.close()

        assert [e["type"] for e in upstream.last.json_sent("session.close")] == ["session.close"]
        assert upstream.last.closed
        session.close()  # 幂等
        assert upstream.last.close_count == 1

    def test_close_tolerates_a_missing_ack(self):
        """没等到回执也不能把「关不掉」升级成异常 —— 收尾失败不该盖住别的事。"""
        upstream = FakeUpstream([created()])
        session = realtime_provider(upstream).start_session()
        session.start()
        session.timeout = 0.05

        session.close()
        assert upstream.last.closed

    def test_barge_in_cancels_the_current_response(self):
        upstream = FakeUpstream([created()])
        session = realtime_provider(upstream).start_session()
        session.start()
        session.barge_in()
        assert upstream.last.json_sent("response.cancel")

    def test_text_mode_lets_ai_speak_a_given_line(self):
        upstream = FakeUpstream([created()])
        session = realtime_provider(upstream).start_session()
        session.start()
        session.send_text("我们来看这道题")
        kinds = [json.loads(item)["type"] for item in upstream.last.sent if isinstance(item, str)]
        assert kinds[-2:] == ["speech_text_buffer.append", "speech_text_buffer.commit"]

    def test_missing_config_raises_40201(self):
        provider = realtime_provider(FakeUpstream(), api_key="")
        with pytest.raises(ProviderNotConfiguredError):
            provider.start_session()

    def test_qpm_guard_blocks_before_the_upstream_does(self):
        """上游按分钟限流，撞上去就是 429：先在我们这边拦住，文案才说得清。"""
        upstream = FakeUpstream([created()], [created()])
        provider = realtime_provider(upstream, qpm_limit=1)

        provider.start_session()
        with pytest.raises(RateLimitError):
            provider.start_session()
        assert upstream.opens == 0  # 拦在建连之前

    def test_list_voices_comes_from_the_realtime_pool(self):
        provider = realtime_provider(
            FakeUpstream(), voices={"沈老师": VOICE_REALTIME, "顾老师": ""}
        )
        assert [v.id for v in provider.list_voices()] == [VOICE_REALTIME]
