"""火山引擎端到端实时语音大模型（全双工对话）。

**P0 只交付骨架**，实现安排在 P2。

=== 与 TTS / ASR 的关键差别（决定它为什么必须单独一个适配器）===

1. **帧编码完全不同。** 端到端实时语音走的是**纯 JSON 文本帧 + Base64 音频**
   （`{"type": "audio", "data": "<base64>"}` 这一形状），
   不共用 volc_tts.py / volc_asr.py 的二进制私有帧编解码器。
   三套 codec 互为「看起来很像但一对就对不上」的陷阱，不要试图合并。

2. **音色池是独立的。** 本适配器的音色只能来自实时语音池
   （`_jupiter_bigtts`，中文仅 4 个），与 TTS 2.0 池（`_uranus_bigtts`）
   完全不通用。用错池子 → `ClientError:InvalidSpeaker`。

3. **10 分钟空闲会被服务端断连（错误码 45000003）。** 断连是**常规路径**，
   不是异常分支：课堂里学生沉默几分钟太正常了。所以重连必须做成
   一条正常代码路径（复用会话、补上下文），而不是包在 except 里的补丁。
   `FinishSession` 的语义说明连接本身是可复用的，重建成本很低。
"""

from __future__ import annotations

from typing import Any, Iterator

from app.providers.base import ASRSegment, ProviderError, RealtimeProvider, Voice

_NOT_IMPLEMENTED = "实时语音会话将在 P2 阶段实现"


class VolcRealtime(RealtimeProvider):
    """豆包端到端实时语音（全双工）。"""

    # ★ P0 只交付骨架。实时语音是「AI 同学能插话」的前提，把它显示成
    #   已就绪会让人以为课堂已经能对话了。P2 填完实现时删掉这一行。
    implemented = False

    def __init__(
        self,
        name: str = "volc_realtime",
        *,
        api_key: str = "",
        endpoint: str = "",
        model: str = "",
        speaker: str = "",
        qpm_limit: int = 60,
        **options: Any,
    ) -> None:
        super().__init__(name, **options)
        self.endpoint = endpoint
        self.model = model
        self.speaker = speaker
        #: 每分钟请求上限，超了要在客户端先排队，别等服务端拒绝
        self.qpm_limit = qpm_limit
        self._api_key = api_key

    # --- 配置齐备性 ---

    def missing_config(self) -> list[str]:
        missing = []
        if not self._api_key:
            missing.append("API Key")
        if not self.endpoint:
            missing.append("接入地址")
        if not self.speaker:
            missing.append("音色 ID")
        return missing

    @property
    def configured(self) -> bool:
        return not self.missing_config()

    def start_session(self, **options: Any) -> Any:
        raise ProviderError(_NOT_IMPLEMENTED)

    def list_voices(self) -> list[Voice]:
        # 实时语音池只有 4 个中文音色，P2 从上游拉；先返回空。
        return []


class VolcRealtimeSession:
    """P2 填充：负责收发 JSON 帧、Base64 音频编解码、以及空闲重连。"""

    def __init__(self, **options: Any) -> None:
        self.options = dict(options)

    def send_audio(self, chunk: bytes) -> None:
        raise ProviderError(_NOT_IMPLEMENTED)

    def send_text(self, text: str) -> None:
        raise ProviderError(_NOT_IMPLEMENTED)

    def receive(self) -> Iterator[ASRSegment]:
        raise ProviderError(_NOT_IMPLEMENTED)

    def close(self) -> None:
        raise ProviderError(_NOT_IMPLEMENTED)


__all__ = ["VolcRealtime", "VolcRealtimeSession"]
