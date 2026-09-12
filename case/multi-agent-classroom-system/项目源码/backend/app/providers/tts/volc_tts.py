"""火山引擎大模型语音合成（双向流式，二进制私有帧）。

**P0 只交付骨架**：身份、配置读取、错误形态先定下来，协议实现在 P2。
这样做的价值是把「契约」与「实现」分开 —— P0 的验收不依赖任何语音密钥。

=== 实现这一版之前必须记住的坑（来自接口文档，别重新踩）===

1. **帧编码是私有的，和 ASR 不通用。** 别把两边的编解码器合并成一个：
   TTS 的 payload 在音频数据前多一段 `4 字节 session_id 长度 + session_id`，
   ASR 没有这一段。共用一个 codec 会写出「两个都对不上」的实现。

   帧结构：4 字节 header + 可选扩展字段 + 4 字节 payload 长度 + payload。

   header 逐字节：
     字节0  版本号(4bit) + 版本号(4bit)      固定 0b0001_0001 (v1)
     字节1  Message type(4bit) + flags(4bit)  0b1001=全量服务响应；
                                              flags 的 0b0100 表示「含事件号」
     字节2  序列化方式(4bit) + 压缩方式(4bit) 0b0001=JSON；0b0000=无压缩 / 0b0001=gzip
     字节3  保留位                            固定 0x00

   所有整数字段**大端**。
   含事件号时，header 后是 4 字节事件号，常见值：
     350 TTSSentenceStart（合成开始）/ TTSResponse（音频数据）/
     351 TTSSentenceEnd（合成结束）。

2. **音色池不通用。** 本适配器的音色必须来自 TTS 2.0 池（`_uranus_bigtts` 一族，
   90+ 个）；实时语音那边是另一个池（`_jupiter_bigtts`，中文只有 4 个）。
   拿错池子的 ID 会直接 `ClientError:InvalidSpeaker`。音色 ID 一律走
   `VOLC_TTS_SPEAKER` / `VOLC_TTS_VOICE_*` 配置，代码里不写字面量。

3. **必须打开 `disable_markdown_filter`。** 否则讲稿里的 `**重点**`
   会被读成「星星重点星星」。讲稿是 Markdown 生成的，这条不是可选项。
"""

from __future__ import annotations

from typing import Any, Iterator

from app.providers.base import ProviderError, TTSProvider, TTSResult, Voice

#: 骨架阶段的统一文案：说清「现在还不能用」以及「什么时候能用」。
_NOT_IMPLEMENTED = "火山语音合成适配器将在 P2 阶段实现"


class VolcTTS(TTSProvider):
    """火山大模型 TTS 2.0（双向流式 WebSocket）。"""

    # ★ P0 只交付骨架：凭据可以填、卡片可以显示「已配置」，但这个能力
    #   现在**用不了**。置 False 让自检、能力清单、/api/health 一起说真话，
    #   而不是等用户点了播放才吃 50201。P2 把 synthesize() 写完时删掉这一行。
    implemented = False

    def __init__(
        self,
        name: str = "volc_tts",
        *,
        api_key: str = "",
        endpoint: str = "",
        resource_id: str = "",
        speaker: str = "",
        audio_format: str = "mp3",
        sample_rate: int = 24000,
        speech_rate: int = 0,
        enable_subtitle: bool = True,
        **options: Any,
    ) -> None:
        super().__init__(
            name,
            default_voice=speaker,
            audio_format=audio_format,
            sample_rate=sample_rate,
            **options,
        )
        self.endpoint = endpoint
        self.resource_id = resource_id
        self.speech_rate = speech_rate
        self.enable_subtitle = enable_subtitle
        self._api_key = api_key

    # --- 配置齐备性 ---

    def missing_config(self) -> list[str]:
        missing = []
        if not self._api_key:
            missing.append("API Key")
        if not self.endpoint:
            missing.append("接入地址")
        if not self.default_voice:
            missing.append("音色 ID")
        return missing

    @property
    def configured(self) -> bool:
        return not self.missing_config()

    def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float | None = None,
        **options: Any,
    ) -> TTSResult:
        raise ProviderError(_NOT_IMPLEMENTED)

    def stream(
        self,
        text: str,
        *,
        voice: str | None = None,
        speed: float | None = None,
        **options: Any,
    ) -> Iterator[bytes]:
        raise ProviderError(_NOT_IMPLEMENTED)
        yield b""  # pragma: no cover - 让本方法保持生成器语义

    def list_voices(self) -> list[Voice]:
        # 下拉列表来自 TTS 2.0 音色池。P2 接上游拉取，先返回空而不是造假数据。
        return []


__all__ = ["VolcTTS"]
