"""文本模型适配器。

- openai_compatible.py —— 覆盖 DeepSeek / OpenAI / Qwen / Kimi / 方舟 / 自建
- mock.py             —— 离线替身
"""

from app.providers.llm.mock import MockLLM
from app.providers.llm.openai_compatible import OpenAICompatibleLLM

__all__ = ["MockLLM", "OpenAICompatibleLLM"]
