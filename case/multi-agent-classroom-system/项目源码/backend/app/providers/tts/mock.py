"""离线语音合成 / 离线实时语音（AGENTS.md §23）。

Mock 产出的是**结构合法**的 WAV（静音），不是随手拼的字节：
浏览器能真的把它播出来，前端不必为「Mock 模式」写特例分支，
离线演示时听到的是静音而不是报错。

注意 realtime 的 Mock 也放在本模块：AGENTS.md §14.2 的目录约定里
没有 realtime/ 独立目录，而实时语音按约定归在 tts/ 下（见 volc_realtime.py）。
"""

from __future__ import annotations

import struct
from typing import Any, Iterable, Iterator

from app.providers.base import (
    ASRSegment,
    RealtimeProvider,
    TTSProvider,
    TTSResult,
    Voice,
)

#: 中文讲解语速的经验值：一个字约 220ms（speed=1.0）。
MS_PER_CHAR = 220

#: Mock 音频封顶时长 —— 离线用例不该产出长音频。
MAX_MOCK_MS = 5000

DEFAULT_MOCK_VOICES: tuple[Voice, ...] = (
    Voice(
        id="mock-voice-teacher",
        name="离线音色·讲解",
        gender="female",
        style="沉稳",
        provider="mock",
    ),
    Voice(
        id="mock-voice-humanities",
        name="离线音色·人文",
        gender="male",
        style="温和",
        provider="mock",
    ),
    Voice(
        id="mock-voice-science",
        name="离线音色·理科",
        gender="male",
        style="清晰",
        provider="mock",
    ),
)


def estimate_duration_ms(text: str, speed: float = 1.0) -> int:
    """按字数估时长。真实服务商会返回精确值，Mock 只能估。"""
    rate = speed if speed and speed > 0 else 1.0
    return int(min(len(text or "") * MS_PER_CHAR / rate, MAX_MOCK_MS))


def silence_wav(duration_ms: int, sample_rate: int = 24000) -> bytes:
    """生成一段合法的单声道 16bit 静音 WAV。"""
    frames = max(int(sample_rate * duration_ms / 1000), 0)
    payload = b"\x00\x00" * frames
    byte_rate = sample_rate * 2
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(payload),
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        1,  # 单声道
        sample_rate,
        byte_rate,
        2,  # block align
        16,  # bits per sample
        b"data",
        len(payload),
    )
    return header + payload


class MockTTS(TTSProvider):
    """确定性离线合成。"""

    def __init__(
        self,
        name: str = "mock",
        *,
        voices: Iterable[Voice] | None = None,
        **options: Any,
    ) -> None:
        super().__init__(
            name,
            configured=True,
            default_voice=DEFAULT_MOCK_VOICES[0].id,
            audio_format="wav",
            sample_rate=24000,
            **options,
        )
        self._voices = list(voices) if voices is not None else list(DEFAULT_MOCK_VOICES)
        #: 最近若干次合成请求，供测试断言「传给 TTS 的文本被怎么处理过」
        self.calls: list[dict] = []

    def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float | None = None,
        **options: Any,
    ) -> TTSResult:
        chosen = voice or self.default_voice
        rate = float(speed) if speed else 1.0
        duration = estimate_duration_ms(text, rate)
        self.calls.append({"text": text, "voice": chosen, "speed": rate})
        return TTSResult(
            audio=silence_wav(duration, self.sample_rate),
            fmt=self.audio_format,
            duration_ms=duration,
            provider=self.name,
            # 字幕按整段给一条 —— 真实 TTS 会按句切分，Mock 不假装能做到
            subtitles=(),
        )

    def stream(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float | None = None,
        **options: Any,
    ) -> Iterator[bytes]:
        """按句切块吐出，模拟「边合成边出流」的形状。"""
        result = self.synthesize(text, voice=voice, speed=speed, **options)
        audio = result.audio
        # 44 字节是 WAV 头，按整块切会让每块都不是合法音频，所以
        # 这里只切一次：Mock 的职责是给出「多块」的形状，不是模拟流式编码
        chunk_size = max(len(audio) // 2, 1)
        for start in range(0, len(audio), chunk_size):
            yield audio[start : start + chunk_size]

    def list_voices(self) -> list[Voice]:
        return list(self._voices)

    def describe(self) -> dict:
        info = super().describe()
        info["offline"] = True
        return info


class MockRealtime(RealtimeProvider):
    """离线全双工会话。

    P0 只提供「能建立起来」的会话对象；真正的双工收发在 P2。
    """

    def __init__(self, name: str = "mock", **options: Any) -> None:
        super().__init__(name, configured=True, **options)
        #: 已建立的会话书（测试可断言「有没有被建起来、建了几次」）
        self.sessions: list["MockRealtimeSession"] = []

    def start_session(self, **options: Any) -> "MockRealtimeSession":
        session = MockRealtimeSession(**options)
        self.sessions.append(session)
        return session

    def list_voices(self) -> list[Voice]:
        return [
            Voice(
                id="mock-realtime-voice",
                name="离线实时音色",
                gender="female",
                style="自然",
                provider=self.name,
            )
        ]

    def describe(self) -> dict:
        info = super().describe()
        info["offline"] = True
        return info


class MockRealtimeSession:
    """只记录收发内容，不做任何音频编解码。"""

    def __init__(self, **options: Any) -> None:
        self.options = dict(options)
        self.sent: list[Any] = []
        self.closed = False

    def send_audio(self, chunk: bytes) -> None:
        self.sent.append(chunk)

    def send_text(self, text: str) -> None:
        self.sent.append(text)

    def receive(self) -> Iterator[ASRSegment]:
        return iter(())

    def close(self) -> None:
        self.closed = True


__all__ = [
    "DEFAULT_MOCK_VOICES",
    "MAX_MOCK_MS",
    "MS_PER_CHAR",
    "MockRealtime",
    "MockRealtimeSession",
    "MockTTS",
    "estimate_duration_ms",
    "silence_wav",
]
