"""离线语音识别（AGENTS.md §23）。

Mock 不做真实识别 —— 它返回固定文本，用来把「学生举手提问 → 识别 → 送进 LLM」
这条链路在没有网络时跑通。识别质量不是它要证明的事。
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator

from app.providers.base import ASRProvider, ASRResult, ASRSegment

#: 默认的假识别结果：一句典型的课堂提问。
DEFAULT_TRANSCRIPT = "老师，光合作用为什么需要光？"

#: 16bit 单声道的采样字节数。时长按它估出来。
BYTES_PER_FRAME = 2


def estimate_duration_ms(audio: bytes, sample_rate: int = 16000) -> int:
    """按字节数估这段音频有多长。

    **不为精确**（真上游会回传精确时长）—— 为的是让「识别多久 → 记一笔账」
    这条链路在没有网络、没有凭据时也能走通。返回 0 的话，下游的用量看板
    在离线演示里永远显示 0 秒，而那条路恰恰是要演示给人看的东西。
    """
    rate = sample_rate if sample_rate and sample_rate > 0 else 16000
    return int(len(audio or b"") / BYTES_PER_FRAME * 1000 / rate)


class MockASR(ASRProvider):
    """确定性离线识别。"""

    def __init__(
        self,
        name: str = "mock",
        *,
        transcript: str = DEFAULT_TRANSCRIPT,
        **options: Any,
    ) -> None:
        super().__init__(name, configured=True, **options)
        self.transcript = transcript
        #: 最近若干次请求（音频字节数 / 格式），供测试断言「音频确实传下来了」
        self.calls: list[dict] = []

    def transcribe(
        self,
        audio: bytes,
        *,
        fmt: str = "wav",
        sample_rate: int = 16000,
        **options: Any,
    ) -> ASRResult:
        duration = estimate_duration_ms(audio, sample_rate)
        self.calls.append({"bytes": len(audio or b""), "fmt": fmt, "sampleRate": sample_rate})
        return ASRResult(
            text=self.transcript,
            segments=(
                ASRSegment(text=self.transcript, start_ms=0, end_ms=duration, final=True),
            ),
            duration_ms=duration,
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
        """先给一个中间结果，再给终稿 —— 中间结果的存在是前端「边听边显示」的前提。"""
        total = sum(len(chunk) for chunk in chunks)
        self.calls.append({"bytes": total, "fmt": fmt, "sampleRate": sample_rate})
        head = self.transcript[: max(len(self.transcript) // 2, 1)]
        yield ASRSegment(text=head, start_ms=0, end_ms=0, final=False)
        yield ASRSegment(text=self.transcript, start_ms=0, end_ms=0, final=True)

    def describe(self) -> dict:
        info = super().describe()
        info["offline"] = True
        return info


__all__ = ["BYTES_PER_FRAME", "DEFAULT_TRANSCRIPT", "MockASR", "estimate_duration_ms"]
