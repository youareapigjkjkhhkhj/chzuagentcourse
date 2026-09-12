"""离线语音识别（AGENTS.md §23）。

Mock 不做真实识别 —— 它返回固定文本，用来把「学生举手提问 → 识别 → 送进 LLM」
这条链路在没有网络时跑通。识别质量不是它要证明的事。
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator

from app.providers.base import ASRProvider, ASRResult, ASRSegment

#: 默认的假识别结果：一句典型的课堂提问。
DEFAULT_TRANSCRIPT = "老师，光合作用为什么需要光？"


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
        self.calls.append({"bytes": len(audio or b""), "fmt": fmt, "sampleRate": sample_rate})
        return ASRResult(
            text=self.transcript,
            segments=(ASRSegment(text=self.transcript, start_ms=0, end_ms=0, final=True),),
            duration_ms=0,
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


__all__ = ["DEFAULT_TRANSCRIPT", "MockASR"]
