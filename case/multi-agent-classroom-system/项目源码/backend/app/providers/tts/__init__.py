"""语音合成适配器。

- volc_tts.py      —— 大模型 TTS 2.0（双向流式，二进制私有帧）      P2 实现
- volc_realtime.py —— 端到端实时语音（全双工，纯 JSON 文本帧）      P2 实现
- mock.py          —— 离线替身（含实时语音的 Mock）
"""

from app.providers.tts.mock import MockRealtime, MockTTS
from app.providers.tts.volc_realtime import VolcRealtime
from app.providers.tts.volc_tts import VolcTTS

__all__ = ["MockRealtime", "MockTTS", "VolcRealtime", "VolcTTS"]
