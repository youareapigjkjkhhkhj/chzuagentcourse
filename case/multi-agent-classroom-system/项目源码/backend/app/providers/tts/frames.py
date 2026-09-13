"""火山 TTS 2.0 双向流式（`/api/v3/tts/bidirection`）的二进制帧编解码。

**这个文件不许和 ASR 的那个合并。** 两条链路都是「V3 二进制帧」，帧头长得一样，
但 payload 区结构不同：TTS 的服务端帧在 payload 前多一层 `session_id` 长度前缀，
ASR 的响应帧在帧头后多一个 4 字节 `Sequence`。看着像能抽公共基类，抽了就错 ——
验收 P2-A22 专门拿 ASR 的真实响应帧喂给本模块的解析器，要求**必须抛异常**。

帧头与扩展字段的排布以官方样例
（`项目文档/材料/TTS Websocket Bidirection protocols/protocols_.py`）为准，
并已对着真端点逐条跑通（2026-09-13，见 `项目文档/P2-语音能力接入.md` §10.4）。

## 服务端下行

    全量响应（0b1001 / 音频 0b1011）：┌ 帧头 ┬ 事件号(4B) ┬ uint32 sid 长度 + sid ┬ uint32 payload 长度 + payload ┐
    错误帧（0b1111）：                ┌ 帧头 ┬ 错误码(4B) ┬ uint32 payload 长度 + payload ┐

- byte0 固定 `0x11`（版本号 | 头长度，各 4 bit）
- byte1 高 4 bit = Message type，低 4 bit = flags（`0b0100` = 携带事件号）
- byte2 高 4 bit = 序列化（`0b0001` JSON / `0b0000` 裸字节），低 4 bit = 压缩（`0b0001` gzip）
- byte3 保留，固定 `0x00`
- **所有整数字段一律大端**

**音频帧是 `0b1011`（AudioOnlyServer）且带事件号 352**，载荷是裸 mp3 字节。
不是「没有事件号的那种帧」—— 按「事件号为空」判音频会把这些帧全丢掉，
最后「合成成功但没有声音」。错误帧**没有事件号也没有 sid**：帧头之后直接是
4 字节错误码，按全量响应的布局去读，会把错误码当成 sid 长度（`45000000` 就是这么
变成「session_id 长度不合理」的）。

未知事件号只记日志并跳过，**不抛异常**：官方原文说的是「常见事件号」而非穷举，
为几个没见过的号掐断整条合成流不划算。

## 上行（客户端 → 服务端）

    ┌ 帧头 ┬ 事件号(4B) ┬ [uint32 sid 长度 + sid] ┬ uint32 payload 长度 + payload ┐

`session_id` 是**二进制字段**，不是 JSON 载荷里的键：只有连接类事件
（`StartConnection`/`FinishConnection`）不带它，其余事件一律带。
载荷形状是 `{"event": <事件号>, "namespace": "BidirectionalTTS", ...}`。
这两条都被实测钉过 —— 换成「`session_id` 写在 JSON 里、不带长度前缀」的写法，
上游会回一个 `45000000` 的错误帧。
"""

from __future__ import annotations

import gzip
import json
import struct
from dataclasses import dataclass
from typing import Any, Mapping

from app.common.logging import get_logger
from app.providers.base import ProviderError

logger = get_logger(__name__)

# --- 帧头取值 ---

#: byte0：版本号 0b0001 + 头长度 0b0001（4 字节 = 1×4）
HEADER_V1 = 0b0001_0001
HEADER_SIZE = 4

#: byte1 高 4 bit：Message type
MSG_FULL_REQUEST = 0b0001  # 客户端完整请求（上行）
MSG_AUDIO_ONLY = 0b0010  # 纯音频包（上行，本链路用不到）
MSG_FULL_RESPONSE = 0b1001  # 服务端完整响应（下行）
MSG_AUDIO_ONLY_RESPONSE = 0b1011  # 服务端音频帧（下行，音频就是这种）
MSG_ERROR = 0b1111  # 错误帧（下行）

#: byte1 低 4 bit：Message type specific flags
FLAG_NO_SEQ = 0b0000
FLAG_HAS_EVENT = 0b0100  # 该帧携带 4 字节事件号

#: byte2
SER_NONE = 0b0000
SER_JSON = 0b0001
COMP_NONE = 0b0000
COMP_GZIP = 0b0001

#: 下行事件号（官方样例 `EventType` + 真实端点核对）
EV_CONNECTION_STARTED = 50
EV_CONNECTION_FAILED = 51
EV_CONNECTION_FINISHED = 52
EV_SESSION_STARTED = 150
EV_SESSION_FINISHED = 152
EV_SESSION_FAILED = 153
EV_SENTENCE_START = 350
EV_SENTENCE_END = 351
EV_TTS_RESPONSE = 352
EV_TTS_ENDED = 359

#: 上行事件号（官方样例 `EventType`，已对真端点跑通）
UPLINK_EVENTS: Mapping[str, int] = {
    "StartConnection": 1,
    "FinishConnection": 2,
    "StartSession": 100,
    "CancelSession": 101,
    "FinishSession": 102,
    "TaskRequest": 200,
}

#: 不带 `session_id` 字段的上行事件：它们描述的是**连接**，此时还没有会话。
#: 实测确认 —— 给 StartConnection 硬塞一个 sid 长度前缀，上游读到的就是错位的载荷。
CONNECTION_EVENTS = frozenset({1, 2})

#: 下行帧里那段 id 是**连接 id** 的事件（其余事件读出来的是 session_id）。
CONNECT_ID_EVENTS = frozenset({EV_CONNECTION_STARTED, EV_CONNECTION_FAILED, EV_CONNECTION_FINISHED})

#: 一个 session_id 的合理上限。下行帧的 sid 长度前缀是 4 字节无符号数，
#: 喂错协议时会读出天文数字 —— 拿它当第一道闸，比等切片越界更早报错。
MAX_SESSION_ID_BYTES = 256

#: 本解析器认得的 flags。除了「携带事件号」这一位，TTS 下行帧不该有别的位置起来
#: —— 多出来的位说明这不是 TTS 帧（比如 ASR 的响应帧会置 `0b0001`，表示带序号）。
_VALID_FLAGS = {FLAG_NO_SEQ, FLAG_HAS_EVENT}


class TTSCodecError(ProviderError):
    """TTS 帧不合法：版本/标志位/长度对不上。

    单独一个异常类型（而不是和 ASR 共用一个 `CodecError`）是刻意的：
    喂错协议时要能一眼看出是哪一侧的解析器拒的。
    """


@dataclass(frozen=True)
class ServerFrame:
    """一帧服务端下行数据。"""

    msg_type: int
    flags: int
    #: 事件号；错误帧为 `None`（错误帧不带事件号，只有错误码）
    event: int | None = None
    session_id: str = ""
    #: 连接类下行帧（50/51/52）里那段 id 落在这里，会话帧为空
    connect_id: str = ""
    #: 已解压；JSON 事件已反序列化成对象，音频帧是原始字节
    payload: Any = b""
    #: payload 是否为 JSON（解析器按序列化方式给，不靠猜）
    is_json: bool = False
    #: 错误帧里的上游报错文案（`msg_type == MSG_ERROR` 时才有）
    error: str = ""
    #: 错误帧的原始错误码，进日志用（文案有时会被上游留空）
    error_code: int = 0

    @property
    def is_audio(self) -> bool:
        """音频帧：载荷是裸字节，不是 JSON。

        判据是**载荷形态**，不是「有没有事件号」：真机上的音频帧是
        `0b1011` 且带事件号 352，按事件号判会把音频全丢光。
        """
        return isinstance(self.payload, (bytes, bytearray)) and not self.is_json

    @property
    def audio(self) -> bytes:
        """音频字节。不是音频帧时返回空 —— 调用方按 `is_audio` 分支。"""
        return bytes(self.payload) if self.is_audio else b""


def encode_client_frame(
    event: str | int,
    payload: Mapping[str, Any] | bytes | None = None,
    *,
    session_id: str = "",
    event_id: int | None = None,
    serialize: bool = True,
    compress: bool = False,
) -> bytes:
    """拼一帧上行数据。

    `event` 传事件名（`UPLINK_EVENTS` 里的键）或事件号，`payload` 传 JSON 对象或裸字节。
    `session_id` 是**二进制字段**：除连接类事件（`StartConnection`/`FinishConnection`）外
    每个事件都要带，不带上游读到的是错位的载荷（实测会回 `45000000`）。
    """
    if isinstance(event, str):
        if event not in UPLINK_EVENTS:
            raise TTSCodecError(f"未知的上行事件名：{event}", details={"event": event})
        event_no = UPLINK_EVENTS[event]
    else:
        event_no = int(event)

    body = _encode_payload(payload, serialize=serialize, compress=compress)

    flags = FLAG_HAS_EVENT
    ser = SER_JSON if serialize else SER_NONE
    comp = COMP_GZIP if compress else COMP_NONE
    header = bytes([HEADER_V1, (MSG_FULL_REQUEST << 4) | flags, (ser << 4) | comp, 0])

    out = bytearray(header)
    out += struct.pack(">i", event_no)  # 事件号
    if event_no not in CONNECTION_EVENTS:
        if not session_id:
            raise TTSCodecError(
                f"上行事件 {event} 必须带 session_id", details={"event": event_no}
            )
        raw_sid = session_id.encode("utf-8")
        if len(raw_sid) > MAX_SESSION_ID_BYTES:
            raise TTSCodecError(
                f"session_id 太长：{len(raw_sid)} 字节", details={"sidLen": len(raw_sid)}
            )
        out += struct.pack(">I", len(raw_sid))  # sid 长度 + sid（大端）
        out += raw_sid
    out += struct.pack(">I", len(body))  # payload 长度（大端）
    out += body

    # 便于排障：上游 log_id / 会话 id 之外，帧长与事件号是唯一能对上的线索
    logger.debug(
        "TTS 上行帧 event=%s(%d) bytes=%d sid=%s json=%s gzip=%s",
        event,
        event_no,
        len(out),
        session_id[:8] or "-",
        serialize,
        compress,
    )
    _ = event_id  # 事件追踪 id 由调用方写进 payload，这里留参数只为可读性
    return bytes(out)


def parse_server_frame(buf: bytes) -> ServerFrame:
    """解析一帧服务端下行数据。

    结构性不合法（版本号不对 / 长度越界 / id 长度离谱）一律抛 `TTSCodecError`；
    只是「事件号没见过」则原样返回，交给调用方记日志跳过。
    """
    if len(buf) < HEADER_SIZE:
        raise TTSCodecError(f"帧太短：{len(buf)} 字节", details={"bytes": len(buf)})
    if buf[0] != HEADER_V1:
        raise TTSCodecError(f"非法版本号 {buf[0]:#04x}", details={"byte0": buf[0]})

    msg_type = buf[1] >> 4
    flags = buf[1] & 0x0F
    ser = buf[2] >> 4
    comp = buf[2] & 0x0F

    if msg_type not in (MSG_FULL_RESPONSE, MSG_AUDIO_ONLY_RESPONSE, MSG_ERROR):
        raise TTSCodecError(f"非服务端帧：Message type={msg_type:#06b}", details={"msgType": msg_type})
    if flags not in _VALID_FLAGS:
        # ASR 响应帧的「带序号」位就落在这里 —— 喂错协议时这一句先拦下
        raise TTSCodecError(f"TTS 帧不该有这些标志位：{flags:#06b}", details={"flags": flags})

    off = HEADER_SIZE

    # 错误帧排在事件号**之前**，且和事件号互斥：它是「帧头 + 错误码 + 载荷」。
    # 按全量响应的布局去读，错误码会被当成 id 长度（45000000 就是这么变成
    # 「session_id 长度不合理」的）。
    error_code = 0
    if msg_type == MSG_ERROR:
        _need(buf, off, 4, "错误码")
        error_code = struct.unpack_from(">I", buf, off)[0]
        off += 4

    event: int | None = None
    session_id = ""
    connect_id = ""
    if flags & FLAG_HAS_EVENT:
        _need(buf, off, 4, "事件号")
        event = struct.unpack_from(">i", buf, off)[0]
        off += 4

        # 事件号之后固定是一段「长度前缀 + id」，两种叫法共用一个位置：
        # 会话事件是 session_id，连接事件（50/51/52）是 connect_id。
        # 不存在两者同时出现的情况，所以这里读一次就够。
        _need(buf, off, 4, "id 长度")
        id_len = struct.unpack_from(">I", buf, off)[0]
        off += 4
        if id_len > MAX_SESSION_ID_BYTES:
            raise TTSCodecError(f"session_id 长度不合理：{id_len}", details={"sidLen": id_len})
        _need(buf, off, id_len, "session_id")
        ident = buf[off : off + id_len].decode("utf-8", errors="replace")
        off += id_len
        if event in CONNECT_ID_EVENTS:
            connect_id = ident
        else:
            session_id = ident

    _need(buf, off, 4, "payload 长度")
    pay_len = struct.unpack_from(">I", buf, off)[0]
    off += 4
    _need(buf, off, pay_len, "payload")
    payload = buf[off : off + pay_len]

    payload, is_json, error = _decode_payload(
        msg_type, event, ser, comp, payload, error_code=error_code
    )
    return ServerFrame(
        msg_type=msg_type,
        flags=flags,
        event=event,
        session_id=session_id,
        connect_id=connect_id,
        payload=payload,
        is_json=is_json,
        error=error,
        error_code=error_code,
    )


def _decode_payload(
    msg_type: int, event: int | None, ser: int, comp: int, payload: bytes, *, error_code: int = 0
) -> tuple[Any, bool, str]:
    """payload 区解码 → `(载荷, 是不是 JSON, 错误文案)`。

    分四路，判据各是一条**协议事实**而不是猜测：
    - 解压：帧头 byte2 低 4 位声明了 gzip 就必须解（音频帧也可能是 gzip 的）；
    - 错误帧（message type 1111）：载荷多半是 `{"error": ...}`，但**也可能是空的**，
      那时只有错误码可讲 —— 文案里必须留下它，否则用户看到的是一句没有线索的
      「上游报错」；
    - 事件帧（带事件号 + 声明 JSON）：载荷必须是 JSON —— 讲稿、时间戳、用量都在里面；
    - 其余（TTSResponse）：载荷就是音频二进制，原样返回。
    """
    if comp == COMP_GZIP:
        try:
            payload = gzip.decompress(payload)
        except OSError as exc:  # 截断的 gzip 流会走到这里
            raise TTSCodecError(f"gzip 解压失败：{exc}", details={"bytes": len(payload)}) from exc

    if msg_type == MSG_ERROR:
        data = _maybe_json(payload, ser)
        error = ""
        if isinstance(data, Mapping):
            error = str(data.get("error") or data.get("message") or "")
        if not error:
            error = f"上游错误码 {error_code}"
            if payload and data is None:
                # 载荷不是 JSON：原样贴一小段，排障时比「错误码 45000000」有用得多
                error += f"：{payload[:200]!r}"
        return (data if data is not None else payload), isinstance(data, dict), error

    if event == EV_TTS_RESPONSE or msg_type == MSG_AUDIO_ONLY_RESPONSE:
        # 音频帧就是音频帧：载荷是 mp3 字节，不是 JSON。上游实际发的音频帧
        # 序列化位是「裸字节」，但**不靠这一位判** —— 万一它写成了 JSON，
        # 按 JSON 解会把「有声音」错判成「帧坏了」，整段合成就此失败。
        return payload, False, ""

    if event is not None and ser == SER_JSON:
        data = _maybe_json(payload, ser)
        if data is None:
            raise TTSCodecError("事件帧声明了 JSON 序列化，但载荷不是合法 JSON")
        return data, True, ""

    return payload, False, ""


def _encode_payload(payload: Mapping[str, Any] | bytes | None, *, serialize: bool, compress: bool) -> bytes:
    if payload is None:
        body = b"{}" if serialize else b""
    elif isinstance(payload, (bytes, bytearray)):
        body = bytes(payload)
    else:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if compress:
        body = gzip.compress(body)
    return body


def _maybe_json(payload: bytes, ser: int) -> Any:
    if ser != SER_JSON or not payload:
        return None
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _need(buf: bytes, off: int, size: int, what: str) -> None:
    """长度校验。越界就说清缺在哪儿 —— 「帧坏了」这种报错排障时等于没说。"""
    if size < 0 or off + size > len(buf):
        raise TTSCodecError(
            f"帧字段越界：读 {what} 需要 offset {off}+{size}，实际仅 {len(buf)} 字节",
            details={"field": what, "offset": off, "size": size, "length": len(buf)},
        )


__all__ = [
    "EV_SENTENCE_END",
    "EV_SENTENCE_START",
    "EV_SESSION_FAILED",
    "EV_SESSION_FINISHED",
    "EV_SESSION_STARTED",
    "EV_TTS_ENDED",
    "EV_TTS_RESPONSE",
    "MSG_AUDIO_ONLY_RESPONSE",
    "MSG_ERROR",
    "MSG_FULL_RESPONSE",
    "UPLINK_EVENTS",
    "ServerFrame",
    "TTSCodecError",
    "encode_client_frame",
    "parse_server_frame",
]
