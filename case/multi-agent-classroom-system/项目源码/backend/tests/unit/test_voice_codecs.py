"""语音两条链路的字节级编解码（P2-A15 / P2-A21 / P2-A22）。

这些用例是**手搭字节**、再喂给解析器的 —— 不用被测模块的编码器去造输入，
否则「编码器写错了」和「解析器读错了」会一起错、一起过。规格来源是
`项目文档/技术实现方案.md` §5.3-A7（TTS）与 §5.3-C3（ASR），下面每条断言
旁边都标了对着规格的哪一句。

这个文件同时替 P2-A22 站岗：**TTS 与 ASR 的两套编解码器不许通用**。
"""

from __future__ import annotations

import gzip
import json
import re
import struct
from pathlib import Path
from typing import ClassVar

import pytest

from app.providers.asr import frames as asr
from app.providers.tts import frames as tts

pytestmark = pytest.mark.unit


# --- 手搭帧（独立于被测编码器，只用 struct 按规格拼） ---


def tts_server_frame(
    *,
    event: int | None,
    session_id: str = "sess-1",
    payload: bytes = b"",
    msg_type: int = 0b1001,
    ser: int = 0b0001,
    comp: int = 0b0000,
    flags: int | None = None,
    error_code: int = 0,
) -> bytes:
    """TTS 服务端下行帧。

    正常帧：头 + [事件号 + id 长度前缀 + id] + payload 长度 + payload
    错误帧：头 + 错误码 + payload 长度 + payload（**没有事件号也没有 id**）
    """
    if flags is None:
        flags = 0b0100 if event is not None else 0b0000
    head = bytes([0x11, (msg_type << 4) | flags, (ser << 4) | comp, 0])
    out = bytearray(head)
    if msg_type == 0b1111:
        out += struct.pack(">I", error_code)
    elif flags & 0b0100:
        out += struct.pack(">i", event if event is not None else 0)
        sid = session_id.encode("utf-8")
        out += struct.pack(">I", len(sid)) + sid
    body = gzip.compress(payload) if comp == 0b0001 else payload
    out += struct.pack(">I", len(body)) + body
    return bytes(out)


def asr_server_frame(
    *,
    sequence: int = 3,
    payload: bytes = b"{}",
    flags: int = 0b0001,
    msg_type: int = 0b1001,
    ser: int = 0b0001,
    comp: int = 0b0000,
    error_code: int = 0,
) -> bytes:
    """ASR 服务端下行帧。

    正常帧：头 + [序号] + payload 长度 + payload
    错误帧：头 + 错误码 + payload 长度 + payload（**没有序号**，实拍如此）
    """
    head = bytes([0x11, (msg_type << 4) | flags, (ser << 4) | comp, 0])
    out = bytearray(head)
    if msg_type == 0b1111:
        out += struct.pack(">I", error_code)
    elif flags & 0b0001:
        out += struct.pack(">i", sequence)
    body = gzip.compress(payload) if comp == 0b0001 else payload
    out += struct.pack(">I", len(body)) + body
    return bytes(out)


# --- P2-A21 TTS 帧 ---


class TestTTSFrames:
    def test_uplink_header_says_client_full_request_with_event(self):
        """上行帧头：byte0=0x11；byte1 高位 message type、低位 flags；byte2 拆序列化与压缩。"""
        frame = tts.encode_client_frame(
            "TaskRequest", {"text": "你好"}, session_id="s", compress=True
        )

        assert frame[0] == 0x11  # 版本号 | 头长度
        assert frame[1] >> 4 == 0b0001  # Message type：客户端完整请求
        assert frame[1] & 0x0F == 0b0100  # flags：携带事件号
        assert frame[2] >> 4 == 0b0001  # 序列化：JSON
        assert frame[2] & 0x0F == 0b0001  # 压缩：gzip
        assert frame[3] == 0x00  # 保留位

    def test_uplink_event_id_is_followed_by_a_length_prefixed_binary_sid(self):
        """事件号之后是 `uint32 sid 长度 + sid`，再是载荷长度 —— 全是裸字节，不是 JSON 字段。

        实测口径（2026-09-13）：把 `session_id` 写进 JSON 里发出去，上游回
        `45000000` 错误帧，一个字都合成不出来。
        """
        frame = tts.encode_client_frame("StartSession", {"event": 100}, session_id="abc")

        event, sid_len = struct.unpack_from(">iI", frame, 4)
        assert event == tts.UPLINK_EVENTS["StartSession"]
        assert sid_len == 3
        assert frame[12:15] == b"abc"
        (size,) = struct.unpack_from(">I", frame, 15)
        assert size == len(frame) - 19  # 头 4 + 事件 4 + 长度 4 + sid 3 + 长度 4
        assert json.loads(frame[19:])["event"] == 100

        gz = tts.encode_client_frame("TaskRequest", {"event": 200}, session_id="abc", compress=True)
        (size_gz,) = struct.unpack_from(">I", gz, 15)
        assert size_gz == len(gz) - 19
        assert json.loads(gzip.decompress(gz[19:]))["event"] == 200

    def test_connection_events_carry_no_session_id(self):
        """`StartConnection` 是连接级事件，此时还没有会话 —— 多写一段 sid 就是错位。"""
        frame = tts.encode_client_frame("StartConnection", {})

        event, next_field = struct.unpack_from(">iI", frame, 4)
        assert event == 1
        assert next_field == len(b"{}"), "连接事件：事件号之后直接是载荷长度"

    def test_non_connection_events_without_a_session_id_are_refused(self):
        """少写 sid 比写错 sid 更难查（上游只会说一句「格式不对」），本地先拦。"""
        with pytest.raises(tts.TTSCodecError):
            tts.encode_client_frame("TaskRequest", {"event": 200})

    def test_unknown_uplink_event_name_is_refused(self):
        with pytest.raises(tts.TTSCodecError):
            tts.encode_client_frame("NoSuchEvent", {})

    @pytest.mark.parametrize("event", [tts.EV_SENTENCE_START, tts.EV_SENTENCE_END])
    def test_event_frames_parse_to_350_and_351(self, event: int):
        """带事件号的帧能解析出 350 / 351，payload 是 JSON。"""
        body = json.dumps({"text": "梯度下降"}, ensure_ascii=False).encode("utf-8")
        got = tts.parse_server_frame(tts_server_frame(event=event, payload=body))

        assert got.event == event
        assert got.session_id == "sess-1"
        assert got.payload == {"text": "梯度下降"}
        assert got.is_json
        assert not got.is_audio

    def test_audio_frame_is_1011_and_carries_event_352(self):
        """真机上的音频帧：message type `0b1011` + 事件号 352 + 裸 mp3 字节。

        按「没有事件号的那种帧」判音频会把这些帧全丢掉 —— 表现是
        「合成成功、字节为 0、一点声音都没有」。
        """
        audio = bytes(range(32))
        got = tts.parse_server_frame(
            tts_server_frame(event=tts.EV_TTS_RESPONSE, payload=audio, msg_type=0b1011, ser=0b0000)
        )

        assert got.event == tts.EV_TTS_RESPONSE
        assert got.is_audio
        assert got.audio == audio
        assert got.session_id == "sess-1"
        assert not got.is_json

    def test_gzip_frame_is_decompressed_before_use(self):
        body = json.dumps({"text": "卷积"}, ensure_ascii=False).encode("utf-8")
        raw = tts_server_frame(event=tts.EV_SENTENCE_START, payload=body, comp=0b0001)
        assert raw[2] & 0x0F == 0b0001  # 帧头如实声明了 gzip

        got = tts.parse_server_frame(raw)
        assert got.payload == {"text": "卷积"}

    def test_gzipped_audio_frame_also_works(self):
        audio = b"\x00\x01" * 40
        got = tts.parse_server_frame(tts_server_frame(event=None, payload=audio, comp=0b0001))
        assert got.audio == audio

    def test_unknown_event_number_is_not_fatal(self):
        """官方给的是「常见事件号」而非穷举 —— 没见过的号只跳过，不许掐断合成流。"""
        got = tts.parse_server_frame(
            tts_server_frame(event=999, payload=b'{"x":1}')
        )
        assert got.event == 999
        assert got.payload == {"x": 1}

    def test_error_frame_exposes_upstream_message(self):
        """错误帧的布局是「头 + 错误码 + 载荷」—— 没有事件号，也没有 id。

        按全量响应的布局读它，4 字节错误码会被当成 id 长度：`45000000` 就是这么
        变成「session_id 长度不合理」的，用户看到的是 500，上游说的原因一个字都到不了。
        """
        got = tts.parse_server_frame(
            tts_server_frame(
                event=None,
                payload=b'{"error":"invalid speaker"}',
                msg_type=0b1111,
                flags=0b0000,
                error_code=55000002,
            )
        )
        assert got.msg_type == tts.MSG_ERROR
        assert "invalid speaker" in got.error
        assert got.error_code == 55000002

    def test_error_frame_without_a_message_still_names_the_code(self):
        """上游有时只回一个码，载荷是空的 —— 文案里必须留下码，否则无从查起。"""
        got = tts.parse_server_frame(
            tts_server_frame(event=None, payload=b"", msg_type=0b1111, flags=0b0000, error_code=45000000)
        )
        assert "45000000" in got.error

    @pytest.mark.parametrize(
        ("buf", "why"),
        [
            (b"\x11\x90", "帧太短"),
            (b"\x21\x90\x10\x00" + b"\x00" * 16, "版本号不对"),
            (
                # 帧头说「不带事件号」，字节流里却写了事件号：解析器只能按头走，
                # 把那 4 个字节当 session_id 长度读 → 350 > 256 上限 → 抛
                b"\x11\x90\x10\x00" + struct.pack(">iI", 350, 6) + b"sess-1" + struct.pack(">I", 0),
                "带事件号却没置标志位",
            ),
        ],
    )
    def test_malformed_frames_raise(self, buf: bytes, why: str):
        """结构性不合法必须抛 —— 但不能靠猜：长度越界就报越界。"""
        with pytest.raises(tts.TTSCodecError):
            tts.parse_server_frame(buf)

    def test_truncated_payload_raises(self):
        full = tts_server_frame(event=350, payload=b'{"text":"x"}')
        with pytest.raises(tts.TTSCodecError):
            tts.parse_server_frame(full[:-4])

    def test_absurd_session_id_length_raises(self):
        head = bytes([0x11, 0x90, 0x10, 0x00])
        buf = head + struct.pack(">iI", 350, 0xFFFFFF) + b"\x00" * 8
        with pytest.raises(tts.TTSCodecError):
            tts.parse_server_frame(buf)


# --- P2-A15 ASR 帧 ---


class TestASRFrames:
    PARAMS: ClassVar[dict] = {
        "user": {"uid": "u1"},
        "audio": {"format": "pcm", "rate": 16000, "bits": 16, "channel": 1},
        "request": {"model_name": "bigmodel"},
    }

    def test_full_client_request_header_and_big_endian_fields(self):
        """首包：message type 0b0001、flags 0b0001（序号为正）、JSON + gzip、大端。"""
        frame = asr.build_full_client_request(self.PARAMS)

        assert frame[0] == 0x11  # 版本号 0b0001 | 头长度 0b0001
        assert frame[1] >> 4 == 0b0001
        assert frame[1] & 0x0F == 0b0001
        assert frame[2] >> 4 == 0b0001  # JSON
        assert frame[2] & 0x0F == 0b0001  # gzip
        assert frame[3] == 0x00

        sequence, size = struct.unpack_from(">iI", frame, 4)
        assert sequence == asr.FIRST_SEQUENCE
        assert size == len(frame) - 12
        assert json.loads(gzip.decompress(frame[12:])) == self.PARAMS

    def test_audio_packet_has_no_sequence_and_raw_payload(self):
        """音频包：message type 0b0010、flags 0b0000（无序号）、不序列化不压缩。"""
        pcm = b"\x01\x02" * asr.PACKET_BYTES
        frame = asr.build_audio_request(pcm)

        assert frame[1] >> 4 == 0b0010
        assert frame[1] & 0x0F == asr.FLAG_NO_SEQUENCE
        assert frame[2] == 0x00
        size = struct.unpack_from(">I", frame, 4)[0]  # 无序号 → 头后直接是长度
        assert size == len(pcm)
        assert frame[8:] == pcm

    def test_last_packet_uses_negative_flag(self):
        """松开按键：flags=0b0010 的负包，服务端据此判停（§5.3-C8）。"""
        frame = asr.build_audio_request(b"\x00" * 16, last=True)

        assert frame[1] >> 4 == 0b0010
        assert frame[1] & 0x0F == asr.FLAG_NEG_SEQUENCE
        assert struct.unpack_from(">I", frame, 4)[0] == 16

    def test_last_packet_with_sequence_uses_neg_with_sequence(self):
        """末包的序号要**取负**：写正数上游当场回 sequence mismatch 并掐连接（实拍）。

        取负在构造器里做，因为这是个「忘了必错、且错得很难懂」的约定。
        """
        frame = asr.build_audio_request(b"\x00" * 16, sequence=7, last=True)
        assert frame[1] & 0x0F == asr.FLAG_NEG_WITH_SEQUENCE
        assert struct.unpack_from(">i", frame, 4)[0] == -7

    def test_sequence_present_iff_flag_bit0(self):
        """序号只在 flags 最低位置 1 时存在 —— 两种包各验一次。"""
        with_seq = asr.build_audio_request(b"abc", sequence=5)
        without = asr.build_audio_request(b"abc")
        assert struct.unpack_from(">I", with_seq, 8)[0] == 3  # 序号占 4 字节，再读长度
        assert struct.unpack_from(">I", without, 4)[0] == 3

    def test_response_envelope_parses(self):
        """响应：序号 + JSON 信封（code / is_last_package / payload_msg）。"""
        envelope = {
            "code": 0,
            "is_last_package": True,
            "payload_msg": {"result": {"text": "这是字节跳动，"}},
        }
        buf = asr_server_frame(
            sequence=3, payload=json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        )
        got = asr.parse_server_frame(buf)

        assert got.sequence == 3
        assert got.code == 0
        assert got.is_last
        assert got.data is not None
        assert got.data["payload_msg"]["result"]["text"] == "这是字节跳动，"

    def test_response_may_be_gzipped(self):
        envelope = {"code": 0, "payload_msg": {"result": {"text": "卷积"}}}
        got = asr.parse_server_frame(
            asr_server_frame(payload=json.dumps(envelope).encode("utf-8"), comp=0b0001)
        )
        assert got.data is not None
        assert got.data["payload_msg"]["result"]["text"] == "卷积"

    def test_negative_flag_without_envelope_also_means_last(self):
        got = asr.parse_server_frame(
            asr_server_frame(flags=asr.FLAG_NEG_WITH_SEQUENCE, payload=b'{"code":0}')
        )
        assert got.is_last

    def test_error_code_is_reported(self):
        """错误帧：帧头后第一段是错误码，不是序号（排布和 TTS 那边一样）。"""
        got = asr.parse_server_frame(
            asr_server_frame(
                msg_type=0b1111,
                flags=0b0000,
                payload=b'{"code":45000002,"message":"empty audio"}',
                error_code=45000002,
            )
        )
        assert got.is_error
        assert got.error_code == 45000002
        assert got.code == 45000002

    def test_error_frame_falls_back_to_frame_code_when_payload_has_none(self):
        """实拍的错误帧 payload 只有 `{"error":"..."}` —— 码得从帧里那 4 字节取。"""
        got = asr.parse_server_frame(
            asr_server_frame(
                msg_type=0b1111, flags=0b0000, payload=b'{"error":"empty audio"}', error_code=45000002
            )
        )
        assert got.code == 45000002
        assert got.error == "empty audio"

    def test_packet_size_matches_200ms_of_16k_mono_16bit(self):
        """200ms × 16000Hz × 2 字节 × 1 声道 = 6400 字节（§5.3-C4）。"""
        assert asr.PACKET_MS == 200
        assert asr.PACKET_BYTES == 6400

    def test_malformed_frames_raise(self):
        with pytest.raises(asr.ASRCodecError):
            asr.parse_server_frame(b"\x11\x90")
        with pytest.raises(asr.ASRCodecError):
            asr.parse_server_frame(b"\x21\x90\x10\x00" + b"\x00" * 8)


# --- P2-A22 两套编解码器不通用 ---


class TestCodecsAreNotInterchangeable:
    def test_real_asr_response_frame_is_refused_by_tts_parser(self):
        asr_frame = asr_server_frame(sequence=1, payload=b'{"code":0,"payload_msg":{}}')
        with pytest.raises(tts.TTSCodecError):
            tts.parse_server_frame(asr_frame)

    def test_real_tts_frame_is_refused_by_asr_parser(self):
        # 音频下行帧的 message type 是 `0b1011`（TTS 专有），ASR 只认 `0b1001`
        audio = tts_server_frame(msg_type=0b1011, event=0, payload=b"\xff\xfb" * 8)
        with pytest.raises(asr.ASRCodecError):
            asr.parse_server_frame(audio)

        event_frame = tts_server_frame(event=tts.EV_SENTENCE_START, payload=b'{"text":"x"}')
        with pytest.raises(asr.ASRCodecError):
            asr.parse_server_frame(event_frame)

    def test_error_types_are_distinct(self):
        """两个异常类不许有继承关系 —— 否则「哪一侧拒的」就看不出来了。"""
        assert tts.TTSCodecError is not asr.ASRCodecError
        assert not issubclass(tts.TTSCodecError, asr.ASRCodecError)
        assert not issubclass(asr.ASRCodecError, tts.TTSCodecError)

    def test_parsers_are_separate_functions(self):
        """防止后续重构「顺手抽公共基类」：两个解析函数必须是不同的对象。"""
        assert tts.parse_server_frame is not asr.parse_server_frame


# --- P2-A16 分包规格不串用 ---


#: 只认独立的标识符与字节数。`VOLC_ASR_PACKET_MS` 这种**配置项名**不算 ——
#: 名字里带 PACKET_MS 的是「去哪儿读配置」，不是「自己规定了包多大」。
_PACKET_CONSTANT = re.compile(r"(?<![A-Za-z0-9_])(?:PACKET_MS|PACKET_BYTES)(?![A-Za-z0-9_])|6400")


def test_packet_constants_live_in_providers_only():
    """service 层不得出现分包常量：实时语音 20ms/640B 与 ASR 200ms/6400B 各写各的。"""
    backend = Path(__file__).resolve().parent.parent.parent
    offenders: list[str] = []
    for path in sorted((backend / "app" / "services").rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _PACKET_CONSTANT.search(line):
                offenders.append(f"{path.name}:{lineno} → {line.strip()}")
    assert not offenders, "分包常量属于 Provider，不该出现在 service 层：\n  " + "\n  ".join(
        offenders
    )


def test_realtime_and_asr_packet_sizes_differ():
    """实时语音 20ms/640 字节、ASR 200ms/6400 字节 —— 数字不同本身就是防串用的证据。"""
    from app.providers.tts import volc_realtime

    assert volc_realtime.PACKET_BYTES == 640
    assert volc_realtime.PACKET_MS == 20
    assert asr.PACKET_BYTES == 6400
    assert asr.PACKET_MS == 200
