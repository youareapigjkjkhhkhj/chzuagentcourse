"""火山引擎流式语音识别（`bigmodel_async`）。

**P0 只交付骨架**，实现安排在 P2。它是两条链路的共同基础：
实时语音不可用时的降级路径（ASR + LLM + TTS），以及学生「按住说话」。

=== 与 TTS 的关键差别 ===

1. **二进制私有帧，但 payload 结构不同。** ASR 的 payload 里没有 TTS 那段
   `4 字节 session_id 长度 + session_id` —— 只有 `4 字节 payload 长度 + payload`。
   两边的 codec 看起来像，但一对就对不上，**不要合并**（见 volc_tts.py 的说明）。

2. 音频按 `VOLC_ASR_PACKET_MS`（默认 200ms）切包上行，
   末包要带负包序号表示「说完了」，否则服务端一直等下文的音频。

3. 识别结果是**增量**的：同一个片段的中间结果会反复回来，
   只有 `final=True` 的那条才是定稿。前端要做的是覆盖而非追加。
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator

from app.providers.base import ASRProvider, ASRResult, ASRSegment, ProviderError

_NOT_IMPLEMENTED = "火山流式语音识别适配器将在 P2 阶段实现"


class VolcASR(ASRProvider):
    """火山流式 ASR（bigmodel_async）。"""

    # ★ P0 只交付骨架（见模块注释）。置 False 是不让「凭据齐了」被
    #   读成「现在能用」—— 调用会抛 50201，而 50201 看起来像上游故障，
    #   排查方向会一路歪到网络上去。P2 填完实现时删掉这一行。
    implemented = False

    def __init__(
        self,
        name: str = "volc_asr",
        *,
        api_key: str = "",
        endpoint: str = "",
        resource_id: str = "",
        packet_ms: int = 200,
        **options: Any,
    ) -> None:
        super().__init__(name, **options)
        self.endpoint = endpoint
        self.resource_id = resource_id
        self.packet_ms = packet_ms
        self._api_key = api_key

    # --- 配置齐备性 ---

    def missing_config(self) -> list[str]:
        missing = []
        if not self._api_key:
            missing.append("API Key")
        if not self.endpoint:
            missing.append("接入地址")
        return missing

    @property
    def configured(self) -> bool:
        return not self.missing_config()

    def transcribe(
        self,
        audio: bytes,
        *,
        fmt: str = "wav",
        sample_rate: int = 16000,
        **options: Any,
    ) -> ASRResult:
        raise ProviderError(_NOT_IMPLEMENTED)

    def stream(
        self,
        chunks: Iterable[bytes],
        *,
        fmt: str = "pcm",
        sample_rate: int = 16000,
        **options: Any,
    ) -> Iterator[ASRSegment]:
        raise ProviderError(_NOT_IMPLEMENTED)
        yield ASRSegment(text="")  # pragma: no cover - 保持生成器语义


__all__ = ["VolcASR"]
