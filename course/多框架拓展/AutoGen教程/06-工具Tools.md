# 06 - 工具 Tools

本篇目标：让 Agent 调用外部能力——自定义函数工具、把 Agent 包装成工具、控制工具调用的轮次与并行。

## 6.1 前置准备

```bash
pip install -U "autogen-agentchat" "autogen-ext[openai]"
```

## 6.2 定义一个函数工具

三条硬规则：**`async def`** + **类型注解** + **docstring**（框架据此生成 JSON Schema 交给模型）。

```python
async def get_weather(city: str) -> str:
    """Get the weather for a given city."""
    return f"The weather in {city} is 73 degrees and Sunny."

agent = AssistantAgent(
    name="weather_agent",
    model_client=model_client,
    tools=[get_weather],
)
```

模型看到的是：函数名 `get_weather`、参数 `city: str`、描述 `Get the weather for a given city.`

## 6.3 工具调用的执行位置（v0.4 重大变化）

> **v0.4 起，工具由发起调用的 Agent 自己执行**，在同一个 `run()` 内完成；不再像 v0.2 那样交给 `UserProxyAgent` 执行。默认情况下，Agent 会把工具调用结果作为最终响应返回。

开启 `reflect_on_tool_use=True`，Agent 会在拿到结果后**再生成一段自然语言总结**：

```python
agent = AssistantAgent(
    name="weather_agent",
    model_client=model_client,
    tools=[get_weather],
    reflect_on_tool_use=True,
)
```

消息流对比：

```text
# reflect_on_tool_use=False（默认）
TextMessage(user) → ToolCallRequestEvent → ToolCallExecutionEvent

# reflect_on_tool_use=True
TextMessage(user) → ToolCallRequestEvent → ToolCallExecutionEvent → ToolCallSummaryMessage
```

## 6.4 同步工具也可以

```python
def increment_number(number: int) -> int:
    """Increment a number by 1."""
    return number + 1

agent = AssistantAgent("assistant", model_client=model_client, tools=[increment_number])
```

## 6.5 多轮工具调用

v0.6.2 起可直接用 `max_tool_iterations` 让 Agent 连续多轮调用工具（不必再套单 Agent 团队）：

```python
agent = AssistantAgent(
    name="looped_assistant",
    model_client=model_client,
    tools=[increment_number],
    system_message="You are a helpful AI assistant, use the tool to increment the number.",
    max_tool_iterations=10,
)
```

早期写法是把单 Agent 放进 `RoundRobinGroupChat`，用 `TextMessageTermination` 控制循环（见 [09-团队Teams.md](09-团队Teams.md) 的单代理团队示例）。

## 6.6 并行工具调用

并行开关在**模型客户端**层：

```python
model_client = OpenAIChatCompletionClient(
    model="gpt-4o",
    parallel_tool_calls=False,   # 关闭并行（Swarm 交接场景建议关闭）
)
```

> Swarm 中并行调用可能一次性产生多个 handoff，官方建议关闭。

## 6.7 把 Agent 包装成工具（AgentTool）

用 `AgentTool` 把一个 Agent 变成上层 Agent 的"工具"，实现**层级编排**：

```python
import asyncio

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.tools import AgentTool
from autogen_agentchat.ui import Console
from autogen_ext.models.openai import OpenAIChatCompletionClient


async def main() -> None:
    model_client = OpenAIChatCompletionClient(model="gpt-4.1")

    math_agent = AssistantAgent(
        "math_expert",
        model_client=model_client,
        system_message="You are a math expert.",
        description="A math expert assistant.",
        model_client_stream=True,
    )
    math_agent_tool = AgentTool(math_agent, return_value_as_last_message=True)

    chemistry_agent = AssistantAgent(
        "chemistry_expert",
        model_client=model_client,
        system_message="You are a chemistry expert.",
        description="A chemistry expert assistant.",
        model_client_stream=True,
    )
    chemistry_agent_tool = AgentTool(chemistry_agent, return_value_as_last_message=True)

    agent = AssistantAgent(
        "assistant",
        system_message="You are a general assistant. Use expert tools when needed.",
        model_client=model_client,
        model_client_stream=True,
        tools=[math_agent_tool, chemistry_agent_tool],
        max_tool_iterations=10,
    )

    await Console(agent.run_stream(task="What is the integral of x^2?"))
    await Console(agent.run_stream(task="What is the molecular weight of water?"))
    await model_client.close()


asyncio.run(main())
```

要点：
- 被包装的 Agent 需要 `description`（编排 Agent 靠它决定调谁）。
- `return_value_as_last_message=True` 让子 Agent 的最终回复作为工具返回值。

## 6.8 内置工具（Extensions）

`autogen_ext` 提供常用工具能力，例如：

| 能力 | 位置（示例） |
|------|-------------|
| 代码执行 | 本地 / Docker 代码执行器（`autogen_ext.code_executors`） |
| 网页浏览 | `MultimodalWebSurfer`（`autogen_ext.agents.web_surfer`） |
| 文件问答 | `FileSurfer`（`autogen_ext.agents.file_surfer`） |
| 外部 MCP 工具 | `McpWorkbench`（见 [07-MCP与外部工具.md](07-MCP与外部工具.md)） |

> 具体类与参数以官方 Extensions 指南为准：<https://microsoft.github.io/autogen/stable/user-guide/extensions-user-guide/index.html>

## 关键 API 速查

| API | 说明 |
|-----|------|
| `tools=[func]` | 注册函数工具（async + 注解 + docstring） |
| `reflect_on_tool_use=True` | 工具结果后生成总结 |
| `max_tool_iterations=N` | 单轮最多 N 次工具调用（v0.6.2+） |
| `parallel_tool_calls=False` | 模型客户端层关闭并行调用 |
| `AgentTool(agent, return_value_as_last_message=True)` | Agent 变工具（`autogen_agentchat.tools`） |

## 注意事项

- 工具的 docstring 就是给模型看的"说明书"，写得越准确，调用越可靠。
- 工具返回值建议是**字符串或可序列化结构**，便于进入模型上下文。
- 工具执行失败会返回 `is_error=True` 的 `FunctionExecutionResult`，Agent 可据此重试或换策略。

## 下一步

→ [07-MCP与外部工具.md](07-MCP与外部工具.md)：接入 MCP 服务器（如 Playwright 网页浏览）。
