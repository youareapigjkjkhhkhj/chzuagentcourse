# 03 - 模型客户端 Models

本篇目标：掌握 `ChatCompletionClient` 协议与各家实现——OpenAI、Azure OpenAI、Ollama 本地模型、Gemini/其他 OpenAI 兼容服务，以及缓存与能力声明。

## 3.1 分层关系

- `autogen-core` 定义**模型客户端协议**（`ChatCompletionClient`）
- `autogen-ext` 提供**各家实现**
- AgentChat 直接使用这些客户端

所有客户端统一接口：`await client.create([UserMessage(...)])` 调用，`await client.close()` 关闭。

```python
from autogen_core.models import UserMessage

result = await client.create([UserMessage(content="What is the capital of France?", source="user")])
print(result)
await client.close()
```

返回结构（`CreateResult`）：

```text
CreateResult(finish_reason='stop', content='The capital of France is Paris.',
             usage=RequestUsage(prompt_tokens=15, completion_tokens=7),
             cached=False, logprobs=None)
```

## 3.2 OpenAI

```bash
pip install "autogen-ext[openai]"
```

```python
from autogen_core.models import UserMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient

client = OpenAIChatCompletionClient(
    model="gpt-4o-2024-08-06",
    # api_key="sk-...",   # 已设 OPENAI_API_KEY 可省略
)

result = await client.create([UserMessage(content="What is the capital of France?", source="user")])
print(result)
await client.close()
```

## 3.3 Azure OpenAI

```bash
pip install "autogen-ext[openai,azure]"
```

支持两种认证：**API Key** 与 **AAD Token**（后者需分配 *Cognitive Services OpenAI User* 角色）。

```python
from autogen_core.models import UserMessage
from autogen_ext.auth.azure import AzureTokenProvider
from autogen_ext.models.openai import AzureOpenAIChatCompletionClient
from azure.identity import DefaultAzureCredential

token_provider = AzureTokenProvider(
    DefaultAzureCredential(),
    "https://cognitiveservices.azure.com/.default",
)

client = AzureOpenAIChatCompletionClient(
    azure_deployment="{your-azure-deployment}",
    model="{model-name, such as gpt-4o}",
    api_version="2024-06-01",
    azure_endpoint="https://{your-custom-endpoint}.openai.azure.com/",
    azure_ad_token_provider=token_provider,   # AAD 认证
    # api_key="sk-...",                       # 或密钥认证（二选一）
)

result = await client.create([UserMessage(content="What is the capital of France?", source="user")])
print(result)
await client.close()
```

## 3.4 Ollama 本地模型

```bash
pip install -U "autogen-ext[ollama]"
# 另需本地启动 Ollama 服务（默认 11434 端口）
```

```python
from autogen_core.models import UserMessage
from autogen_ext.models.ollama import OllamaChatCompletionClient

client = OllamaChatCompletionClient(model="llama3.2")   # 默认连 localhost:11434

response = await client.create([UserMessage(content="What is the capital of France?", source="user")])
print(response)
await client.close()
```

> 官方提示：小型本地模型在复杂任务上表现通常不如云端大模型。

## 3.5 其他 OpenAI 兼容服务

`OpenAIChatCompletionClient` 可直接指向任何 OpenAI 兼容端点（Gemini、Llama API、vLLM、自建代理等）：

```python
from autogen_ext.models.openai import OpenAIChatCompletionClient

# 例：自建 / 代理服务
client = OpenAIChatCompletionClient(
    model="gpt-4o-mini",
    base_url="https://your-openai-compatible-endpoint/v1",
    api_key="sk-...",
)
```

> 官方说明：OpenAI 兼容端点属于"可用但未官方测试"的用法，遇到问题优先查对应服务商文档。

## 3.6 声明模型能力：`model_info`

框架需要知道模型是否支持**视觉、函数调用、JSON 输出、结构化输出**。用 `ModelInfo` 显式声明：

```python
from autogen_core.models import ModelInfo, UserMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient

client = OpenAIChatCompletionClient(
    model="gemini-2.0-flash-lite",
    model_info=ModelInfo(
        vision=True,
        function_calling=True,
        json_output=True,
        family="unknown",
        structured_output=True,   # 支持结构化输出
    ),
    # api_key="GEMINI_API_KEY",
)

response = await client.create([UserMessage(content="What is the capital of France?", source="user")])
await client.close()
```

| 字段 | 含义 |
|------|------|
| `vision` | 支持图片输入 |
| `function_calling` | 支持工具/函数调用 |
| `json_output` | 支持 JSON 模式输出 |
| `structured_output` | 支持结构化输出（Pydantic 模型约束） |
| `family` | 模型系列（未知填 `"unknown"`） |

部分客户端（如 Azure AI Foundry 的 `AzureAIChatCompletionClient`）用**字典**形式传入同样的键。

## 3.7 多模态（图片）输入

```python
from pathlib import Path

from autogen_core import Image
from autogen_core.models import UserMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient

client = OpenAIChatCompletionClient(model="gpt-4o")
image = Image.from_file(Path("test.png"))

response = await client.create(
    [UserMessage(content=["What is in this image", image], source="user")]
)
print(response)
await client.close()
```

## 3.8 响应缓存

`ChatCompletionCache` 是**缓存包装器**，可包裹任意客户端，避免重复请求：

```python
from autogen_ext.models.cache import ChatCompletionCache

# 完整路径：autogen_ext.models.cache.ChatCompletionCache
# 具体参数以官方 API Reference 为准
```

命中缓存时，`CreateResult.cached` 字段会变为 `True`。

## 关键 API 速查

| API | 导入 | 说明 |
|-----|------|------|
| `OpenAIChatCompletionClient` | `autogen_ext.models.openai` | OpenAI / 兼容端点 |
| `AzureOpenAIChatCompletionClient` | `autogen_ext.models.openai` | Azure OpenAI |
| `OllamaChatCompletionClient` | `autogen_ext.models.ollama` | 本地 Ollama |
| `AzureAIChatCompletionClient` | `autogen_ext.models.azure` | Azure AI Foundry |
| `ChatCompletionCache` | `autogen_ext.models.cache` | 缓存包装器 |
| `ModelInfo` | `autogen_core.models` | 模型能力声明 |
| `UserMessage` / `CreateResult` / `RequestUsage` | `autogen_core.models` | 消息与结果 |
| `Image` | `autogen_core` | 图片输入（`Image.from_file`） |

## 注意事项

- 每个客户端都要 `await client.close()`。
- 切换服务商通常只改 `model_client` 一处，Agent/团队代码不动。
- 用兼容端点时务必用 `model_info` 声明真实能力，否则框架可能误判（例如按"不支持函数调用"处理导致工具失效）。

## 下一步

→ [04-消息与消息类型.md](04-消息与消息类型.md)：读懂 `TaskResult.messages` 里的每一类消息。
