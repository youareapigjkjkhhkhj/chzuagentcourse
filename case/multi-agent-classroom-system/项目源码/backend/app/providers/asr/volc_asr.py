"""火山引擎流式语音识别（`bigmodel_async`）。

它是两条链路的共同基础：实时语音不可用时的降级路径（ASR + LLM + TTS），
以及学生「按住说话」。

=== 与 TTS 的关键差别 ===

1. **二进制私有帧，但 payload 结构不同。** ASR 的 payload 里没有 TTS 那段
   `4 字节 session_id 长度 + session_id` —— 只有 `4 字节 payload 长度 + payload`。
   两边的 codec 看起来像，但一对就对不上，**不要合并**（见 `frames.py` 的说明）。

2. 音频按 200ms 切包上行（**不是实时语音的 20ms** —— 两者不通用，P2-A16），
   末包带负包标志位表示「说完了」，否则服务端一直等下文的音频。

3. 中间结果会**反复回来**，而且是**可回改的全文**：`同学们。` 的下一帧可能就是
   `同学们好。`。本适配器对外发的是**累计文本**（与 `MockASR` 口径一致），
   每帧整段替换、前端覆盖显示 —— 拼接会让「边说边上屏」出现重复字。

4. **信封的形状文档和实拍对不上**，解析必须两种都兼容：实拍的响应是
   `{"audio_info": ..., "result": {"text": ..., "utterances": [...]}}`（`result`
   直接在顶层，没有 `payload_msg` 那一层），而文档给的示例是包着的。见
   `_result_payload()` —— 这条踩过一次「识别明明成功却返回空文本」。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Iterable, Iterator, Mapping

from app.common.errors import ValidationError
from app.common.logging import get_logger
from app.providers.asr import frames
from app.providers.base import (
    ASRProvider,
    ASRResult,
    ASRSegment,
    ProviderError,
    Secret,
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

logger = get_logger("app.providers.asr")

#: 单次识别的默认上限（秒）。学生一次提问通常 3~10s，30s 足够宽裕；
#: 超了就说明上游或网络卡住了，别让按住说话的那只手一直等着。
DEFAULT_TIMEOUT = 30.0

#: 4xx 停、5xx 重连（§5.3-C7）。这份表只做分流，文案给用户看的是「怎么回事」。
_RETRYABLE_PREFIX = "55"
#: 空音频这类「用户的问题，不是系统的故障」：提示重说，不要重试。
_EMPTY_AUDIO_CODES = frozenset({45000002})


class VolcASR(ASRProvider):
    """火山流式 ASR（bigmodel_async）。"""

    def __init__(
        self,
        name: str = "volc_asr",
        *,
        api_key: str = "",
        endpoint: str = "",
        resource_id: str = "",
        packet_ms: int | None = None,
        hotwords: Iterable[str] | None = None,
        connect: Connector | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        **options: Any,
    ) -> None:
        super().__init__(name, **options)
        self.endpoint = endpoint
        self.resource_id = resource_id
        #: 包长缺省值就在 **本模块**（`frames.PACKET_MS`）：调用方不填时，
        #: 默认值不该由配置层再抄一遍 —— 抄一份就有一个会和这里不一致的副本。
        self.packet_ms = int(packet_ms or frames.PACKET_MS)
        self._secret = Secret(api_key)
        self._connect: Connector = connect or default_connector
        self.timeout = float(timeout)
        #: 课程术语热词（与 TTS 纠音共用同一份术语表，P2-A20）。
        #: 直传热词限 100 tokens，调用方按此裁剪。
        self.hotwords = list(hotwords or [])
        self._conn: WsTransport | None = None
        self._lock = threading.Lock()

    # --- 配置齐备性 ---

    def missing_config(self) -> list[str]:
        missing = []
        if not self._secret:
            missing.append("API Key")
        if not self.endpoint:
            missing.append("接入地址")
        return missing

    @property
    def configured(self) -> bool:
        return not self.missing_config()

    @property
    def packet_bytes(self) -> int:
        """当前 `packet_ms` 对应的每包字节数（16k / 16bit / mono）。"""
        return frames.SAMPLE_RATE * 2 * self.packet_ms // 1000

    # --- 识别 ---

    def transcribe(
        self,
        audio: bytes,
        *,
        fmt: str = "wav",
        sample_rate: int = 16000,
        **options: Any,
    ) -> ASRResult:
        """整段识别：把一段音频切包推完，返回终稿。

        按住说话的**离线兜底**走这条路（已经录完一整段的情况），
        边说边上屏请用 `stream()`。
        """
        pcm = _to_pcm(audio, fmt)
        segments = list(self.stream(_packets(pcm, self.packet_bytes), sample_rate=sample_rate, **options))
        final = segments[-1] if segments else ASRSegment(text="", final=True)
        return ASRResult(
            text=final.text,
            segments=tuple(segments),
            duration_ms=int(len(pcm) / (frames.SAMPLE_RATE * 2) * 1000),
            provider=self.name,
        )

    def stream(
        self,
        chunks: Iterable[bytes],
        *,
        fmt: str = "pcm",
        sample_rate: int = 16000,
        **options: Any,
    ) -> Iterator[ASRSegment]:
        """边收音频边出中间结果。

        `chunks` 是浏览器推上来的音频块（大小随意），这里按 200ms 重量分包 ——
        上游对发包节奏有要求，块大小不能由前端说了算。
        """
        if not self.configured:
            raise not_configured(self)
        _check_audio_params(fmt, sample_rate)

        # 热词可以由本次调用覆盖（临时词优先于课程术语表）
        hotwords = list(options.get("hotwords") or self.hotwords)
        with self._lock:
            yield from self._stream_locked(chunks, hotwords=hotwords, options=options)

    # --- 一次识别 ---

    def _stream_locked(
        self, chunks: Iterable[bytes], *, hotwords: list[str], options: Mapping[str, Any]
    ) -> Iterator[ASRSegment]:
        conn = self._ensure_conn()
        sequence = frames.FIRST_SEQUENCE
        buffer = bytearray()
        text = ""
        last: ASRSegment | None = None
        try:
            conn.send(frames.build_full_client_request(self._request_params(hotwords)))
            for chunk in chunks:
                buffer += chunk or b""
                # 攒够一包就发：上游按 100~200ms 的节奏等包，发早了发晚了都会被判「等包超时」
                while len(buffer) >= self.packet_bytes:
                    packet, buffer = bytes(buffer[: self.packet_bytes]), buffer[self.packet_bytes :]
                    sequence += 1
                    conn.send(frames.build_audio_request(packet, sequence=sequence))
                    for segment in self._drain(conn, text):
                        text, last = segment.text, segment
                        yield segment

            # 末包：带上剩下的不足一包的尾巴，并置负包标志位告诉服务端「说完了」
            sequence += 1
            conn.send(frames.build_audio_request(bytes(buffer), sequence=sequence, last=True))
            for segment in self._drain(conn, text, final=True):
                text, last = segment.text, segment
                yield segment
        finally:
            # 一次识别一条连接：ASR 的会话状态与音频强绑定，
            # 复用一条连接去跑下一段语音，等于把上一段的上下文带过去。
            self._drop_conn()

        if last is None:
            logger.debug("火山 ASR 没有产生任何识别结果（可能是空音频）")

    def _drain(self, conn: WsTransport, previous: str, *, final: bool = False) -> Iterator[ASRSegment]:
        """把已经到达的响应收干净，产出累计文本。

        `final=True` 时等到非超时为止（末包之后服务端一定会给结果）；
        否则只**顺手**收一下有没有中间结果 —— 收不到就接着推音频，
        绝不为了等中间结果把发包节奏拖慢。
        """
        deadline = time.monotonic() + self.timeout
        while True:
            timeout = 0.01 if not final else max(0.0, deadline - time.monotonic())
            if final and timeout <= 0:
                raise TransportTimeout(f"等待火山 ASR 最终结果超时（{self.timeout:g}s）")
            try:
                raw = conn.receive(timeout=timeout)
            except TransportTimeout:
                if final:
                    raise
                return None
            except TransportClosed:
                if final:
                    # 末包之后上游主动关连接是**正常收尾**：实拍的关闭理由就是
                    # 「finish last sequence」。这时候它可能压根没发
                    # `is_last_package`（静音输入就是这样），把关闭当失败会把
                    # 一次正常识别报成错误。
                    logger.debug("ASR 末包后上游关闭连接，按正常收尾处理")
                    return None
                raise
            segment = self._segment(raw, previous)
            if segment is None:
                continue
            previous = segment.text
            yield segment
            if segment.final:
                return None

    def _segment(self, raw: bytes | str, previous: str) -> ASRSegment | None:
        """一帧响应 → 一个累计文本片段。返回 None 表示这帧没有识别内容。"""
        if isinstance(raw, str):
            logger.warning("火山 ASR 收到文本帧，已忽略：%s", raw[:120])
            return None
        frame = frames.parse_server_frame(raw)

        if frame.is_error or frame.code not in (0, 20000000):
            raise _upstream_error(frame)

        inner = _result_payload(frame.data or {})
        text = _merge_text(previous, _result_text(inner))
        start_ms, end_ms = _times(inner)
        if not text and not frame.is_last:
            return None
        return ASRSegment(text=text, start_ms=start_ms, end_ms=end_ms, final=frame.is_last)

    # --- 连接与参数 ---

    def _ensure_conn(self) -> WsTransport:
        if self._conn is not None:
            return self._conn
        if not self.endpoint:
            raise not_configured(self, "接入地址")
        self._conn = wrap(self._connect(self.endpoint, headers=self._headers(), timeout=self.timeout))
        return self._conn

    def _drop_conn(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            conn.close()

    def _headers(self) -> dict[str, str]:
        """鉴权头。**唯一读取 Key 明文的地方。**

        只发 3 个头（较新的官方文档 + 新版控制台口径）。若实测握手失败，
        再加 `X-Api-Sequence` / `X-Api-Connect-Id` —— 三个头写在一处，
        改动成本极低（§5.3-C2 的 ⚠️）。
        """
        headers = {
            "X-Api-Key": self._secret.reveal(),
            "X-Api-Request-Id": uuid.uuid4().hex,
        }
        if self.resource_id:
            headers["X-Api-Resource-Id"] = self.resource_id
        return headers

    def _request_params(self, hotwords: list[str]) -> dict[str, Any]:
        """首包的 JSON 参数（§5.3-C5 的本项目子集）。"""
        params: dict[str, Any] = {
            "user": {"uid": "eduagentx"},
            "audio": {
                "format": "pcm",
                "rate": frames.SAMPLE_RATE,
                "bits": frames.BITS,
                "channel": frames.CHANNELS,
                "language": "zh-CN",
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                # 语义顺滑：删掉「嗯、那个」一类停顿词，课堂提问的文本更干净
                "enable_ddc": True,
                "show_utterances": True,
                # `full`（文档默认值）= 每帧回**到目前为止的整段转写**。
                # 别改成 `single`：那个「不返回之前分句的结果」的语义配上上游
                # **会回改已出字**的行为（实拍：`同学们。` 的下一帧是 `同学们好。`），
                # 累计逻辑就得去猜「这帧是新句子还是同一句的修订」，猜错就出现
                # 「同学们。同学们好。」这种重字（真机踩过）。
                "result_type": "full",
                "end_window_size": 800,
            },
        }
        if hotwords:
            # 直传热词优先于热词表；双向流式限 100 tokens
            params["request"]["corpus"] = {
                "context": _dumps({"hotwords": [{"word": w} for w in hotwords if w][:100]})
            }
        return params


# --- 响应解析小工具（只服务于本适配器）---


def _result_payload(frame_data: Mapping[str, Any]) -> Mapping[str, Any]:
    """响应信封 → 装着识别结果的那个对象。

    两种形状都得吃，因为文档和实拍**不一致**（§5.3-C6 的 ⚠️）：

    - 实拍（`bigmodel_async`）：`{"audio_info": {...}, "result": {"text": ...,
      "utterances": [...]}}` —— **没有 `payload_msg` 这一层**，`result` 就挂在
      顶层，旁边是 `audio_info`。
    - 文档另一版：`{"payload_msg": {"result": ...}}`。

    只认其中一种的后果不是报错而是**静默返回空文本**：帧解析得好好的，
    业务码是 0，就是取不到字。真机踩过（识别全程正常，返回的却是空串）。
    """
    inner = frame_data.get("payload_msg")
    if isinstance(inner, Mapping):
        frame_data = inner
    result = frame_data.get("result")
    if isinstance(result, Mapping):
        return result
    return frame_data


def _result_text(inner: Mapping[str, Any]) -> str:
    """取本次响应里的识别文本。

    `result` 是对象还是数组，两份官方文档给的示例不一致 —— 两种都兼容，
    不假设其一（§5.3-C6 的 ⚠️）。数组时取所有元素的 `text`（增量模式下通常只有一个）。
    """
    result = inner.get("result")
    if result is None:
        result = inner
    if isinstance(result, str):
        return result
    if isinstance(result, Mapping):
        return str(result.get("text") or "")
    if isinstance(result, list):
        return "".join(str(item.get("text") or "") for item in result if isinstance(item, Mapping))
    return ""


def _merge_text(previous: str, piece: str) -> str:
    """这一帧的文本 → 我们往外发的累计文本：**新的直接覆盖旧的**。

    首包参数里 `result_type=full`，所以每帧给的已经是「到目前为止的整段转写」——
    它本身就满足 P2-A14「单调增长不回退」的要求，我们不需要再拼。

    实拍证明上游还会**回头改已经出过的字**：`同学们。` 的下一帧是 `同学们好。`
    （补字，标点跟着往后挪）。所以这里一旦去「拼接/取最长重叠」，就会拼出
    「同学们。同学们好。」——用户看到的是重字，而不是「上游改了」。同理，
    比旧文本短的那一帧也不能丢：那是修订，不是回退。

    空帧（上游偶尔只发心跳）保留已有的，别把屏幕擦空。
    """
    return piece or previous


def _times(inner: Mapping[str, Any]) -> tuple[int, int]:
    """分句时间戳（毫秒）。取最后一个分句的 end_time 当作「说到哪儿了」。"""
    start = end = 0
    utterances = inner.get("utterances")
    if isinstance(utterances, Mapping):  # 又是一处对象/数组不一致
        utterances = [utterances]
    if isinstance(utterances, list):
        for item in utterances:
            if not isinstance(item, Mapping):
                continue
            try:
                start = int(item.get("start_time") or start)
                end = int(item.get("end_time") or end)
            except (TypeError, ValueError):
                continue
    return start, end


def _packets(pcm: bytes, size: int) -> Iterator[bytes]:
    """整段音频 → 定长包（不足一包的尾巴也照发，由末包标志位收尾）。"""
    for offset in range(0, len(pcm), size):
        yield pcm[offset : offset + size]


def _to_pcm(audio: bytes, fmt: str) -> bytes:
    """把整段音频转成本适配器唯一的输入格式：裸 PCM 16k/16bit/mono。

    wav 只剥 44 字节头（标准 RIFF 头长度），这是「浏览器录完直接传上来」
    最常见的形式。其它容器（mp3/ogg）不在这里解码 —— 上游虽然收，但那意味着
    我们要在 provider 里塞一个解码库，不值得。
    """
    if fmt in ("pcm", "raw"):
        return audio
    if fmt == "wav":
        if audio[:4] == b"RIFF" and len(audio) > 44:
            return audio[44:]
        return audio
    raise ValidationError(f"火山 ASR 只接受 pcm / wav，收到 {fmt!r}", details={"fmt": fmt})


def _check_audio_params(fmt: str, sample_rate: int) -> None:
    """上游只支持 16k / 16bit / mono（§5.3-C4）—— 不满足就明确报错，别让它猜。"""
    if fmt not in ("pcm", "raw"):
        raise ValidationError(f"流式识别只接受 pcm，收到 {fmt!r}", details={"fmt": fmt})
    if int(sample_rate) != frames.SAMPLE_RATE:
        raise ValidationError(
            f"火山 ASR 只支持 {frames.SAMPLE_RATE} Hz，收到 {sample_rate} Hz",
            details={"sampleRate": sample_rate},
        )


def _upstream_error(frame: frames.ServerFrame) -> ProviderError:
    """上游报错 → 我们这边的异常。4xx 停、5xx 重连（§5.3-C7）。"""
    code = frame.code
    reason = frame.error or (frame.payload or b"")[:200].decode("utf-8", errors="replace")
    if code in _EMPTY_AUDIO_CODES:
        return ProviderError("没有听清，请再说一次", details={"provider": "volc_asr", "code": code})
    retryable = code == -1 or str(code).startswith(_RETRYABLE_PREFIX)
    prefix = "上游暂时不可用" if retryable else "识别失败"
    return ProviderError(
        f"{prefix}（错误码 {code}）：{reason or '（上游未给原因）'}",
        details={"provider": "volc_asr", "code": code, "retryable": retryable},
    )


def _dumps(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


__all__ = ["DEFAULT_TIMEOUT", "VolcASR"]
