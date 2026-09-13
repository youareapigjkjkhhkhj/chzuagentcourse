"""火山流式语音识别（`/api/v3/sauc/bigmodel_async`）的二进制帧编解码。

**这个文件不许和 TTS 的那个合并。** 两条链路都是「V3 二进制帧」、帧头长得一样，
但布局不同：ASR 的响应帧在帧头后多一个 4 字节 `Sequence`（序号），
而 TTS 的服务端帧是「可选事件号 + `session_id` 长度前缀 + payload」。
验收 P2-A22 专门拿 TTS 的真实帧喂给本模块的解析器，要求**必须抛异常**。

## 帧结构（§5.3-C3 + 2026-09-13 实拍）

    响应帧：┌ 4 字节帧头 ┬ [可选 Sequence(4B)] ┬ uint32 payload 长度 ┬ payload ┐
    错误帧：┌ 4 字节帧头 ┬ 错误码(4B) ┬ uint32 payload 长度 ┬ payload ┐

- byte0 高 4 bit = 协议版本 `0b0001`，低 4 bit = 头长度 `0b0001`（即 4 字节）
- byte1 高 4 bit = Message type，低 4 bit = specific flags
- byte2 高 4 bit = 序列化方式，低 4 bit = 压缩方式
- byte3 保留，固定 `0x00`
- **所有整数字段一律大端**

错误帧的排布和 TTS 那边**一样**（都是「错误码 + 载荷」，没有序号），这不是巧合：
两条链路共用同一套 V3 帧壳。实拍的错误帧长这样 ——
`45000000` 是错误码，`0x85` 才是载荷长度：

    11 f0 10 00 | 00 00 00 ...(45000000) | 00 00 00 85 | {"error":"..."}   （共 145 字节）

Message type：`0b0001` 首包（full client request，含 JSON 参数）｜`0b0010` 音频包
（audio only request）｜`0b1001` 服务端完整响应｜`0b1111` 错误。
flags：`0b0000` 无序号｜`0b0001` 序号为正｜`0b0010` 最后一包（负包，无序号）｜
`0b0011` 序号为负（最后一包）。

**Sequence 只在 flags 最低位置 1 时存在** —— 官方示例的 `parse_response` 就是这么判的，
本模块照此实现（`has_sequence`）。这也是与 TTS 帧的分水岭：TTS 下行帧压根没有这一位。

## 与实时语音的分包不通用（P2-A16）

实时语音要求 20ms / 640 字节，ASR 要求 100~200ms（16k/16bit/mono 下 200ms = 6400 字节）。
分包常量在本 Provider 内，**service 层不得出现任何分包常量** —— 两套分片逻辑各写各的。
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

HEADER_V1 = 0b0001_0001
HEADER_SIZE = 4

MSG_FULL_REQUEST = 0b0001  # 客户端首包，payload 是 JSON 参数
MSG_AUDIO_ONLY = 0b0010  # 客户端音频包
MSG_FULL_RESPONSE = 0b1001  # 服务端响应
MSG_ERROR = 0b1111  # 服务端错误帧

FLAG_NO_SEQUENCE = 0b0000
FLAG_POS_SEQUENCE = 0b0001  # 带序号
FLAG_NEG_SEQUENCE = 0b0010  # 最后一包，不带序号
FLAG_NEG_WITH_SEQUENCE = 0b0011  # 最后一包，带序号

SER_NONE = 0b0000
SER_JSON = 0b0001
COMP_NONE = 0b0000
COMP_GZIP = 0b0001

#: 服务端响应可能出现的那几种 flags。**注意这里没有 `0b0100`**（TTS 的「携带事件号」）——
#: 喂 TTS 的帧进来，第一步就卡在这条上。
#:
#: `0b0000`（不带序号）是**必须收**的：实拍的响应里，「会话已建立」那一帧就是它
#: （载荷只有 `{"result":{"additions":{"log_id":...}}}`）。把它当非法帧拒掉，
#: 表现是「上游明明回话了，我们却说这不是 ASR 帧」（实测踩过）。
_VALID_RESPONSE_FLAGS = {
    FLAG_NO_SEQUENCE,
    FLAG_POS_SEQUENCE,
    FLAG_NEG_SEQUENCE,
    FLAG_NEG_WITH_SEQUENCE,
}

#: 首包序列号固定从 1 开始（官方示例如此），后续音频包依次 +1。
FIRST_SEQUENCE = 1

#: 音频参数：ASR 只支持 16k / 16bit / mono（§5.3-C4）。
SAMPLE_RATE = 16000
BITS = 16
CHANNELS = 1
#: 建议分包时长（ms）与对应字节数。**只在本文件里出现**，别的地方要用请从这里取。
PACKET_MS = 200
PACKET_BYTES = SAMPLE_RATE * (BITS // 8) * CHANNELS * PACKET_MS // 1000  # 6400


class ASRCodecError(ProviderError):
    """ASR 帧不合法：版本/标志位/长度对不上。

    与 `TTSCodecError` 分开定义是刻意的 —— 互相喂错帧时要能看出是哪一侧拒的。
    """


@dataclass(frozen=True)
class ServerFrame:
    """一帧服务端响应。"""

    msg_type: int
    flags: int
    sequence: int | None
    #: 已解压的原始 payload
    payload: bytes = b""
    #: 反序列化后的 JSON（外层的 code / payload_msg 信封）；不是 JSON 时为 None
    data: Mapping[str, Any] | None = None
    error: str = ""
    #: 错误帧的原始错误码（`msg_type == MSG_ERROR` 时才有），进日志用
    error_code: int = 0

    @property
    def is_last(self) -> bool:
        """服务端说「识别结果已全部返回」。"""
        if self.data is not None and "is_last_package" in self.data:
            return bool(self.data.get("is_last_package"))
        return self.flags in (FLAG_NEG_SEQUENCE, FLAG_NEG_WITH_SEQUENCE)

    @property
    def is_error(self) -> bool:
        return self.msg_type == MSG_ERROR

    @property
    def code(self) -> int:
        """上游业务码：0 = 成功。

        错误帧的码有**两个可能的出处**：payload 里 JSON 的 `code`，和帧头后面
        那 4 字节。实拍的错误帧 payload 只有 `{"error":"..."}`，一个数字都没有
        —— 这时候必须回落到那 4 字节，否则报出来的错误码是 0，拿它去查文档
        什么也查不到（能查的是 `45000001` 这一串）。
        """
        if self.data is not None:
            value = self.data.get("code")
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return -1
        if self.is_error:
            return self.error_code or -1
        return 0


def build_full_client_request(
    params: Mapping[str, Any],
    *,
    sequence: int = FIRST_SEQUENCE,
    compress: bool = True,
) -> bytes:
    """首包：JSON 参数（`user` / `audio` / `request`）。"""
    body = json.dumps(params, ensure_ascii=False).encode("utf-8")
    comp = COMP_GZIP if compress else COMP_NONE
    if compress:
        body = gzip.compress(body)
    header = bytes(
        [
            HEADER_V1,
            (MSG_FULL_REQUEST << 4) | FLAG_POS_SEQUENCE,
            (SER_JSON << 4) | comp,
            0,
        ]
    )
    return header + struct.pack(">i", sequence) + struct.pack(">I", len(body)) + body


def build_audio_request(
    chunk: bytes,
    *,
    sequence: int | None = None,
    last: bool = False,
    compress: bool = False,
) -> bytes:
    """音频包。「最后一包」用负包标志位 —— 服务端据此判停并出最终结果（§5.3-C8）。

    `sequence` 给了就用「带序号」的两种标志位，没给就用不带序号的那种。
    默认不压缩：音频已经是裸 PCM，gzip 一遍只赚 CPU 开销。

    ⚠️ **末包的序号必须写成负数**，取当前计数取负（full client request 算第 1 个，
    之后依次 +1）。协议表里 `0b0011` 那一行写的是「sequence number 且**需要为负数**
    （最后一包/负包）」，序号本身是几就写几的相反数 —— 上游收到正数会当场回
    `autoAssignedSequence (-7) mismatch sequence in request (7)` 并掐断连接（实测）。
    取负放在构造器里而不是调用方：这是个「忘了就必错、且错得很难懂」的约定，
    留在离字节最近的地方，调用方只管数数。
    """
    if last:
        flags = FLAG_NEG_WITH_SEQUENCE if sequence is not None else FLAG_NEG_SEQUENCE
    else:
        flags = FLAG_POS_SEQUENCE if sequence is not None else FLAG_NO_SEQUENCE

    body = gzip.compress(chunk) if compress else chunk
    header = bytes(
        [
            HEADER_V1,
            (MSG_AUDIO_ONLY << 4) | flags,
            (SER_NONE << 4) | (COMP_GZIP if compress else COMP_NONE),
            0,
        ]
    )
    out = bytearray(header)
    if sequence is not None:
        value = -abs(int(sequence)) if last else int(sequence)
        out += struct.pack(">i", value)
    out += struct.pack(">I", len(body))
    out += body
    return bytes(out)


def parse_server_frame(buf: bytes) -> ServerFrame:
    """解析一帧服务端响应。

    结构性不合法一律抛 `ASRCodecError`。业务码（`code != 0`）不在这里抛 ——
    4xx 停、5xx 重连是 Provider 的策略，编解码层只负责把字节读对。
    """
    msg_type, flags, ser, comp = _split_header(buf)

    if msg_type not in (MSG_FULL_RESPONSE, MSG_ERROR):
        raise ASRCodecError(f"非服务端帧：Message type={msg_type:#06b}", details={"msgType": msg_type})
    if flags not in _VALID_RESPONSE_FLAGS:
        # TTS 的响应帧（无序号 / 携带事件号）会落到这里 —— 喂错协议时先拦这道
        raise ASRCodecError(f"ASR 响应帧不该有这些标志位：{flags:#06b}", details={"flags": flags})

    error_code, sequence, off = _read_leading_fields(buf, msg_type, flags)
    payload = _read_payload(buf, off, comp)

    data: Mapping[str, Any] | None = None
    error = ""
    if ser == SER_JSON and payload:
        try:
            parsed = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, Mapping):
            data = parsed
            if msg_type == MSG_ERROR:
                error = str(parsed.get("error") or parsed.get("message") or "")

    if msg_type == MSG_ERROR and not error:
        # 上游有时只给一个码。码必须留下来 —— 排障时它是唯一的线索。
        detail = payload[:200].decode("utf-8", errors="replace")
        error = f"上游错误码 {error_code}：{detail}" if detail else f"上游错误码 {error_code}"

    return ServerFrame(
        msg_type=msg_type,
        flags=flags,
        sequence=sequence,
        payload=payload,
        data=data,
        error=error,
        error_code=error_code,
    )


def _split_header(buf: bytes) -> tuple[int, int, int, int]:
    """帧头四字节 → (message type, flags, 序列化方式, 压缩方式)。"""
    if len(buf) < HEADER_SIZE:
        raise ASRCodecError(f"帧太短：{len(buf)} 字节", details={"bytes": len(buf)})
    if buf[0] != HEADER_V1:
        raise ASRCodecError(f"非法版本号 {buf[0]:#04x}", details={"byte0": buf[0]})
    return buf[1] >> 4, buf[1] & 0x0F, buf[2] >> 4, buf[2] & 0x0F


def _read_leading_fields(buf: bytes, msg_type: int, flags: int) -> tuple[int, int | None, int]:
    """帧头之后、载荷长度之前的那两个可选字段 → (错误码, 序号, 新偏移)。

    错误帧排在序号**之前**，而且和它互斥：「帧头 + 错误码 + 载荷长度 + 载荷」。
    按响应帧的布局去读，错误码会被当成序号，后面整段错位 —— 上游明明说了
    「sequence mismatch」，我们读出来的却是一句看不懂的解析错误（实测）。
    """
    off = HEADER_SIZE
    error_code = 0
    if msg_type == MSG_ERROR:
        _need(buf, off, 4, "错误码")
        error_code = struct.unpack_from(">I", buf, off)[0]
        off += 4

    sequence: int | None = None
    if flags & FLAG_POS_SEQUENCE:
        _need(buf, off, 4, "序号")
        sequence = struct.unpack_from(">i", buf, off)[0]
        off += 4
    return error_code, sequence, off


def _read_payload(buf: bytes, off: int, comp: int) -> bytes:
    """读载荷（按需解压）。压缩方式就是帧头低 4 bit 那一格。"""
    _need(buf, off, 4, "payload 长度")
    pay_len = struct.unpack_from(">I", buf, off)[0]
    off += 4
    _need(buf, off, pay_len, "payload")
    payload = buf[off : off + pay_len]

    if comp == COMP_GZIP:
        try:
            return gzip.decompress(payload)
        except OSError as exc:
            raise ASRCodecError(f"gzip 解压失败：{exc}", details={"bytes": len(payload)}) from exc
    return payload


def _need(buf: bytes, off: int, size: int, what: str) -> None:
    if size < 0 or off + size > len(buf):
        raise ASRCodecError(
            f"帧字段越界：读 {what} 需要 offset {off}+{size}，实际仅 {len(buf)} 字节",
            details={"field": what, "offset": off, "size": size, "length": len(buf)},
        )


__all__ = [
    "FIRST_SEQUENCE",
    "PACKET_BYTES",
    "PACKET_MS",
    "SAMPLE_RATE",
    "ASRCodecError",
    "ServerFrame",
    "build_audio_request",
    "build_full_client_request",
    "parse_server_frame",
]
