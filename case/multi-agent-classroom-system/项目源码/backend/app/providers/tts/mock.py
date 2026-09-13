"""离线语音合成 / 离线实时语音（AGENTS.md §23）。

Mock 产出的是**结构合法**的 WAV（静音），不是随手拼的字节：
浏览器能真的把它播出来，前端不必为「Mock 模式」写特例分支，
离线演示时听到的是静音而不是报错。

注意 realtime 的 Mock 也放在本模块：AGENTS.md §14.2 的目录约定里
没有 realtime/ 独立目录，而实时语音按约定归在 tts/ 下（见 volc_realtime.py）。
"""

from __future__ import annotations

import struct
from collections import deque
from typing import Any, Iterable, Iterator

from app.providers.base import (
    RealtimeEvent,
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
        self.calls.append(
            {"text": text, "voice": chosen, "speed": rate, "tone": str(options.get("tone") or "")}
        )
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


#: 离线会话里「学生说的那句话」。与 MockASR 的假识别结果是同一类东西：
#: 固定文本，用来把「说话 → 识别 → 回答 → 出声」这条链路在没有网络时跑通。
DEFAULT_SPEECH = "老师，为什么学习率要衰减？"

#: 离线教师的回答。分两句发，模拟「逐句返回，供字幕用」（§4.2 的 reply）。
DEFAULT_REPLIES = (
    "好问题。学习率太大时，参数会在最优点附近来回跳，甚至越走越远。",
    "所以在训练后期把它调小，模型才能稳稳地收敛到谷底。",
)

#: 会话下行音频的规格：24k / 单声道 / 16bit，与火山实时语音的输出一致
#: （`pcm_s16le` —— `pcm` 是 32bit，浏览器播不了）。
REALTIME_SAMPLE_RATE = 24000
#: 每片音频的长度（毫秒）。真实会话是 20ms 一片，Mock 用 100ms：
#: 它要证明的是「音频按片到达、前端按 seq 顺序播」，不是模拟码流节奏。
REALTIME_CHUNK_MS = 100


class MockRealtime(RealtimeProvider):
    """离线全双工会话。"""

    def __init__(self, name: str = "mock", **options: Any) -> None:
        super().__init__(name, configured=True, **options)
        #: 已建立的会话（测试可断言「有没有被建起来、建了几次」）
        self.sessions: list[MockRealtimeSession] = []

    def start_session(self, **options: Any) -> MockRealtimeSession:
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
    """离线全双工会话：**接口与 `VolcRealtimeSession` 对齐**，内部只记收发。

    为什么非得对齐：WS 的语义层（`services/voice/realtime.py`）对两种会话
    一视同仁 —— 它调 `start()` / `send_audio()` / `commit_audio()` /
    `barge_in()` / `receive()`。Mock 少一个方法，那条链路就只能在真凭据下测，
    而 AGENTS.md §23 要求「无网络、无密钥也必须能跑通全流程」。

    一轮对话的脚本：收到音频并 `commit_audio()`（或直接 `send_text()`）后，
    依次吐 `asr` → `reply`（逐句）→ `audio`（分片）→ `done` → `usage`。
    音频是**结构合法的 PCM 静音**，前端拿去就能播，不必为 Mock 写特例分支。
    """

    def __init__(self, **options: Any) -> None:
        self.options = dict(options)
        self.voice = str(options.get("voice") or "")
        self.instructions = str(options.get("instructions") or "")
        self.hotwords = [str(item) for item in options.get("hotwords") or []]
        self.mode = str(options.get("mode") or "")
        self.sent: list[Any] = []
        self.closed = False
        #: 已经吐出去的事件（测试可断言「哪些话真的传下去了」）
        self.events: list[RealtimeEvent] = []
        self.barge_ins = 0
        self.started = False
        self._queue: deque[RealtimeEvent] = deque()
        self._audio = bytearray()
        self._turns = 0

    # --- 生命周期 ---

    @property
    def dialog_id(self) -> str:
        return f"mock-dialog-{id(self) % 10000:04d}"

    @property
    def alive(self) -> bool:
        return self.started and not self.closed

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True
        self._queue.clear()

    # --- 上行 ---

    def send_audio(self, chunk: bytes) -> None:
        self.sent.append(chunk)
        self._audio += chunk

    def send_text(self, text: str) -> None:
        self.sent.append(text)
        self._script(asr="")

    def commit_audio(self) -> None:
        """松开按键：把这一轮的话变成「识别 + 回答」。"""
        self._script(asr=DEFAULT_SPEECH)
        self._audio.clear()

    @property
    def audio_bytes(self) -> int:
        """这一轮累计收到多少上行音频。断言「音频真的传到了」用它。"""
        return len(self._audio)

    def send_context(self, pairs: Any) -> None:
        self.sent.append(list(pairs))

    def barge_in(self) -> None:
        self.barge_ins += 1
        # 打断之后这一轮的音频不再往下吐（真实会话里服务端会停下这一轮）
        self._audio.clear()

    def keep_alive(self, muted: bool = True) -> None:
        self.sent.append("mute" if muted else "unmute")

    # --- 下行 ---

    def receive(self, timeout: float | None = None) -> Iterator[RealtimeEvent]:
        """把排好的事件一次给完，给完就空转。

        **不模拟节奏**（不等 `timeout`、不按 20ms 分片发）：它要证明的是
        「事件按正确的顺序、正确的形状到达」，节奏是真实适配器的事 ——
        在 Mock 里加 sleep 只会让每次测试多花几秒，还会让「慢」这件事
        在离线测试里被掩盖过去。
        """
        while self._queue:
            event = self._queue.popleft()
            self.events.append(event)
            yield event

    # --- 内部 ---

    def _script(self, *, asr: str) -> None:
        """排一轮：识别稿（可选）→ 回答逐句 → 音频分片 → done → usage。"""
        if self.closed:
            return
        self._turns += 1
        if asr:
            self._queue.append(RealtimeEvent(type="asr", text=asr, final=False))
            self._queue.append(RealtimeEvent(type="asr", text=asr, final=True))
        for index, sentence in enumerate(DEFAULT_REPLIES):
            final = index == len(DEFAULT_REPLIES) - 1
            self._queue.append(RealtimeEvent(type="reply", text=sentence, final=final))
        for _ in range(len(DEFAULT_REPLIES)):
            self._queue.append(RealtimeEvent(type="audio", audio=self._chunk()))
        self._queue.append(RealtimeEvent(type="done", raw={"turn": self._turns}))
        self._queue.append(
            RealtimeEvent(
                type="usage",
                raw={"durationMs": REALTIME_CHUNK_MS * len(DEFAULT_REPLIES), "provider": "mock"},
            )
        )

    def _chunk(self) -> bytes:
        frames = REALTIME_SAMPLE_RATE * REALTIME_CHUNK_MS // 1000
        return b"\x00\x00" * frames


__all__ = [
    "DEFAULT_MOCK_VOICES",
    "DEFAULT_REPLIES",
    "DEFAULT_SPEECH",
    "MAX_MOCK_MS",
    "MS_PER_CHAR",
    "REALTIME_CHUNK_MS",
    "REALTIME_SAMPLE_RATE",
    "MockRealtime",
    "MockRealtimeSession",
    "MockTTS",
    "estimate_duration_ms",
    "silence_wav",
]
