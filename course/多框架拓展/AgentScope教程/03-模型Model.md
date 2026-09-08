# 03 - 模型 Model

本篇目标：掌握 2.0 的模型抽象——如何用 `ChatModel` + `Credential` 接入各家厂商，以及常用参数。

## 3.1 核心概念

AgentScope 2.0 把模型抽象为对象，统一支持 **LLM / Embedding / TTS**，覆盖主流厂商：

> OpenAI · Anthropic · Gemini · DashScope · DeepSeek · Moonshot · xAI · Ollama

命名约定：`{Provider}ChatModel` + `{Provider}Credential` 一一配对。

## 3.2 前置准备

```bash
pip install agentscope[full]   # 各厂商依赖已含在 full 中
export DASHSCOPE_API_KEY="sk-你的密钥"
```

## 3.3 DashScope 完整示例（推荐起点）

```python
import os

from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.model import DashScopeChatModel


def build_agent() -> Agent:
    return Agent(
        name="Friday",
        system_prompt="You are a helpful assistant.",
        model=DashScopeChatModel(
            credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
            model="qwen-plus",          # 模型名，如 qwen-max / qwen3.6-plus
            # stream=True,              # 是否流式（默认按 reply_stream 自动处理）
            # temperature=0.7,           # 采样温度
            # top_p=0.9,
            # max_tokens=2048,
        ),
    )
```

## 3.4 多提供商配对表

只需替换 `Credential` 与 `ChatModel` 两个类，其余代码不变：

| 厂商 | Credential | ChatModel | 环境变量 |
|------|-----------|----------|----------|
| 阿里云 DashScope | `DashScopeCredential` | `DashScopeChatModel` | `DASHSCOPE_API_KEY` |
| OpenAI | `OpenAICredential` | `OpenAIChatModel` | `OPENAI_API_KEY` |
| Anthropic | `AnthropicCredential` | `AnthropicChatModel` | `ANTHROPIC_API_KEY` |
| Google Gemini | `GeminiCredential` | `GeminiChatModel` | `GEMINI_API_KEY` |
| DeepSeek | `DeepSeekCredential` | `DeepSeekChatModel` | `DEEPSEEK_API_KEY` |
| Moonshot | `MoonshotCredential` | `MoonshotChatModel` | `MOONSHOT_API_KEY` |
| xAI | `XAICredential` | `XAIChatModel` | `XAI_API_KEY` |
| Ollama（本地） | 无需 Credential | `OllamaChatModel` | —（`base_url` 指向本地） |

**OpenAI 示例**

```python
import os
from agentscope.credential import OpenAICredential
from agentscope.model import OpenAIChatModel

model = OpenAIChatModel(
    credential=OpenAICredential(api_key=os.environ["OPENAI_API_KEY"]),
    model="gpt-4o",
)
```

**Ollama 本地示例**

```python
from agentscope.model import OllamaChatModel

model = OllamaChatModel(
    model="llama3:8b",
    base_url="http://localhost:11434",   # 本地 Ollama 服务
)
```

> 注：`Credential` / `ChatModel` 的精确类名以官方文档 [docs.agentscope.io](https://docs.agentscope.io/) 为准；若某厂商类名与你预期略有差异，遵循 `{Provider}Credential` / `{Provider}ChatModel` 约定即可。

## 3.5 常用参数

`ChatModel` 通用构造参数（以 DashScope 为例，其他厂商同名）：

| 参数 | 说明 | 默认 |
|------|------|------|
| `model` / `model_name` | 模型标识 | 必填 |
| `credential` | 凭证对象（封装 api_key） | 必填之一 |
| `api_key` | 也可直接传（等价简写） | — |
| `stream` | 是否流式输出 | `True` |
| `temperature` | 采样温度（0~2） | 厂商默认 |
| `top_p` | 核采样 | 厂商默认 |
| `max_tokens` | 最大生成 token | 厂商默认 |
| `base_url` | 自定义 API 端点（私有化/代理） | 厂商默认 |

简写形式（直接传 `api_key`，无需 `credential` 包裹）：

```python
from agentscope.model import DashScopeChatModel

model = DashScopeChatModel(
    model_name="qwen-max",
    api_key=os.environ["DASHSCOPE_API_KEY"],
    stream=True,
)
```

## 3.6 Embedding 与 TTS

除对话模型外，2.0 还统一抽象了 Embedding（用于 RAG，见 [13-检索增强RAG.md](13-检索增强RAG.md)）与 TTS（语音）。命名同样遵循 `{Provider}Embedding` / `{Provider}TTS` 约定：

```python
from agentscope.model import DashScopeEmbedding

emb = DashScopeEmbedding(
    credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
    model="text-embedding-v3",
)
```

## 关键 API 速查

| API | 说明 |
|-----|------|
| `DashScopeChatModel(credential=, model=, temperature=...)` | DashScope 对话模型 |
| `OpenAIChatModel(credential=, model=)` | OpenAI 对话模型 |
| `OllamaChatModel(model=, base_url=)` | 本地 Ollama |
| `DashScopeCredential(api_key=)` | 凭证封装 |

## 2.0 注意事项

- **不再用** 1.0 的 `model_config.json` + `agentscope.init(model_configs=...)` + `model_config_name=`。2.0 直接把模型对象传给 `Agent(model=...)`。
- 模型参数同时支持 `model=` 与 `model_name=`；`credential=` 与直接 `api_key=` 等价。
- 密钥走环境变量，勿硬编码进代码仓库。

## 下一步

→ [04-消息与事件系统.md](04-消息与事件系统.md)：理解 `UserMsg` 与流式事件 `EventType`。
