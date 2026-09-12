"""Provider 层（P0 §6）：所有厂商能力的唯一入口。

业务代码的写法：

    from app.services.provider_registry import get_registry
    result = get_registry().current_llm().chat(messages)

绝不要写：

    from openai import OpenAI          # 厂商 SDK 只允许出现在 app/providers/ 里
    import websockets

这条界线由 tests/unit/test_provider_layering.py 守着。

具体适配器（Mock / OpenAI 兼容 / 火山语音）请从各自的子包导入，
本模块只暴露抽象层与注册表 —— 免得 import 抽象基类顺手把 openai SDK 拖进来。
"""

from app.providers.base import (
    ASRProvider,
    ASRResult,
    ASRSegment,
    BaseProvider,
    LLMProvider,
    LLMResult,
    ProbeResult,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderTimeoutError,
    RealtimeProvider,
    Secret,
    Subtitle,
    TTSProvider,
    TTSResult,
    Voice,
)
from app.providers.registry import KINDS, MOCK_NAME, ProviderRegistry

__all__ = [
    "KINDS",
    "MOCK_NAME",
    "ASRProvider",
    "ASRResult",
    "ASRSegment",
    "BaseProvider",
    "LLMProvider",
    "LLMResult",
    "ProbeResult",
    "ProviderError",
    "ProviderNotConfiguredError",
    "ProviderRegistry",
    "ProviderTimeoutError",
    "RealtimeProvider",
    "Secret",
    "Subtitle",
    "TTSProvider",
    "TTSResult",
    "Voice",
]
