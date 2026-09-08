# 05 - 智能体 Agent

本篇目标：掌握 AgentChat 的核心 Agent——`AssistantAgent` 的参数、运行方法与有状态特性，以及各类预设 Agent 的定位。

## 5.1 前置准备

```bash
pip install -U "autogen-agentchat" "autogen-ext[openai]"
export OPENAI_API_KEY="sk-你的密钥"
```

## 5.2 所有 Agent 的共同契约

AgentChat 的预设 Agent 都继承自 `BaseChatAgent`，共享：

| 成员 | 说明 |
|------|------|
| `name` | Agent 唯一名称（团队中用于路由/`source` 标识） |
| `description` | 文本描述（被包装成工具时展示给编排者） |
| `run(task)` | 用**新消息**（不是完整历史）运行，返回 `TaskResult` |
| `run_stream(task)` | 同上，流式产出消息 + 末项 `TaskResult` |

> 关键设计：**Agent 是有状态的**。`run()` 应传入"增量"的新消息，框架负责维护历史。

## 5.3 AssistantAgent

`AssistantAgent` 是内置的"使用语言模型 + 能调用工具"的 Agent。官方定位：它是面向**原型与教学**的通用 Agent；深入理解后应实现自己的 Agent（见 [13-自定义Agent.md](13-自定义Agent.md)）。

```python
from autogen_agentchat.agents import AssistantAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient

model_client = OpenAIChatCompletionClient(model="gpt-4.1-nano")

agent = AssistantAgent(
    name="assistant",
    model_client=model_client,
    tools=[web_search],
    system_message="Use tools to solve tasks.",
)
```

## 5.4 常用参数

| 参数 | 说明 |
|------|------|
| `name` | 名称（团队内唯一） |
| `model_client` | 模型客户端实例 |
| `tools` | 工具列表（异步函数 / 工具对象 / `AgentTool`） |
| `system_message` | 系统提示词 |
| `description` | 描述（供编排者/交接场景理解该 Agent 能做什么） |
| `reflect_on_tool_use` | 拿到工具结果后**再反思生成自然语言总结** |
| `model_client_stream` | 开启逐 token 流式 |
| `memory` | 挂载记忆/RAG（列表，见 [08-记忆Memory与RAG.md](08-记忆Memory与RAG.md)） |
| `handoffs` | 可交接的目标（Swarm 模式，见 [11-多智能体模式Swarm.md](11-多智能体模式Swarm.md)） |
| `max_tool_iterations` | 单轮运行内最多进行多少轮工具调用（v0.6.2+） |
| `parallel_tool_calls` | 是否允许并行工具调用（模型客户端层参数） |

## 5.5 运行与结果

```python
# 非流式
result = await agent.run(task="Find information on AutoGen")
print(result.messages)

# 流式（推荐配 Console）
from autogen_agentchat.ui import Console
await Console(agent.run_stream(task="Find information on AutoGen"))
```

拿到最终文本：

```python
final = result.messages[-1]
print(final.content)
```

## 5.6 有状态与继续对话

```python
# 第一次
await agent.run(task="我叫小明，在做 AutoGen 教程。")

# 第二次：只传增量，Agent 记得上文
result = await agent.run(task="我叫什么？")
print(result.messages[-1].content)
```

不传 `task` 调用 `run()`，会让 Agent 基于当前状态继续生成。

## 5.7 多模态输入

```python
from autogen_agentchat.messages import MultiModalMessage
from autogen_core import Image
import requests, PIL
from io import BytesIO

pil_image = PIL.Image.open(BytesIO(requests.get("https://picsum.photos/300/200").content))
img = Image(pil_image)

result = await agent.run(
    task=MultiModalMessage(content=["Can you describe the content of this image?", img], source="user")
)
```

## 5.8 其他预设 Agent（生态）

AgentChat 还提供面向不同场景的预设 Agent（均在 `autogen_agentchat.agents`）：

| Agent | 用途 |
|-------|------|
| `UserProxyAgent` | 代表人类用户，在团队中接收用户输入（人机协同，见 [12-人工协同HITL.md](12-人工协同HITL.md)） |
| `CodeExecutorAgent` | 执行代码（常配本地/Docker 代码执行器） |
| `SocietyOfMindAgent` | 把内部团队"包装"成单个 Agent 对外呈现 |
| `MessageFilterAgent` | 过滤/变换其包装 Agent 的消息 |
| `MultimodalWebSurfer` | 多模态网页浏览（位于 `autogen_ext.agents.web_surfer`） |
| `FileSurfer` | 文件浏览与问答（`autogen_ext.agents.file_surfer`） |
| `VideoSurfer` | 视频理解（`autogen_ext.agents.video_surfer`） |

> 具体导入路径与参数以官方 API Reference 为准：<https://microsoft.github.io/autogen/stable/reference/python/autogen_agentchat.html>

## 关键 API 速查

| API | 说明 |
|-----|------|
| `AssistantAgent(name, model_client=, tools=, system_message=)` | 创建助手 Agent |
| `await agent.run(task=)` / `agent.run_stream(task=)` | 运行（增量消息） |
| `result.messages[-1].content` | 取最终回复文本 |
| `reflect_on_tool_use=True` | 工具结果后二次总结 |
| `memory=[...]` | 挂载记忆 |
| `handoffs=[...]` | 声明交接目标 |

## 注意事项

- `AssistantAgent` 是"kitchen sink"（大而全）实现，官方建议理解其设计后按需自行实现 Agent。
- **v0.2 → v0.4 差异**：工具在同一 Agent 内直接执行；不再由 `UserProxyAgent` 代跑代码。
- 每个 Agent 都持有自己的模型客户端引用；关闭时统一 `await model_client.close()`。

## 下一步

→ [06-工具Tools.md](06-工具Tools.md)：让 Agent 真正"动手"——自定义工具与执行控制。
