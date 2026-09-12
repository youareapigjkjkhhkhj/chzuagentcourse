"""语音识别适配器。

- volc_asr.py —— 流式 ASR（bigmodel_async，二进制私有帧）  P2 实现
- mock.py     —— 离线替身
"""

from app.providers.asr.mock import MockASR
from app.providers.asr.volc_asr import VolcASR

__all__ = ["MockASR", "VolcASR"]
