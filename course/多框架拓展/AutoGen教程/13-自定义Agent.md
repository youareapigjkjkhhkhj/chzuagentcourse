# 13 - 自定义 Agent

本篇目标：当预设 Agent（如 `AssistantAgent`）不够用时，实现自己的 Agent——理解 `BaseChatAgent` 契约与控制消息流。

## 13.1 前置准备

```bash
pip install -U "autogen-agentchat" "autogen-ext[openai]"
```

## 13.2 何时自定义

官方定位：`AssistantAgent` 是面向**原型与教学**的通用实现。以下场景建议自定义：

- 需要确定性的业务规则（不希望 LLM 自由发挥）
- 需要接入自有系统（工单、数据库、内部 API）
- 需要特殊的状态管理或上下文压缩策略
- 需要精确控制输出的消息类型（如只产出结构化结果）

## 13.3 BaseChatAgent 契约

所有 AgentChat Agent 的基类，需实现/具备：

| 成员 | 类型 | 说明 |
|------|------|------|
| `name` | 属性 | 唯一名称 |
| `description` | 属性 | 描述（被包装成工具时展示） |
| `on_messages(messages, cancellation_token)` | **必须实现** | 接收新消息，返回 `Response(chat_message=..., inner_messages=[...])` |
| `on_reset(cancellation_token)` | **必须实现** | 重置到初始状态（团队 `reset()` 时调用） |
| `produced_message_types` | 属性 | 该 Agent 会产出哪些消息类型（团队据此校验） |
| `run(task)` / `run_stream(task)` | 基类提供 | 对外运行接口（内部调用 `on_messages`） |
| `save_state()` / `load_state()` | 可选 | 状态持久化（见 [14-状态管理与序列化.md](14-状态管理与序列化.md)） |

> 基类已实现 `run`/`run_stream`，自定义时通常只需实现 `on_messages` 与 `on_reset`。

## 13.4 最小骨架

```python
from typing import Sequence

from autogen_agentchat.agents import BaseChatAgent
from autogen_agentchat.base import Response
from autogen_agentchat.messages import BaseChatMessage, TextMessage
from autogen_core import CancellationToken


class EchoAgent(BaseChatAgent):
    """最简单的自定义 Agent：把收到的内容原样返回。"""

    def __init__(self, name: str, description: str = "An agent that echoes input.") -> None:
        super().__init__(name, description)
        self._history: list[BaseChatMessage] = []

    @property
    def produced_message_types(self) -> Sequence[type[BaseChatMessage]]:
        return (TextMessage,)

    async def on_messages(self, messages: Sequence[BaseChatMessage], cancellation_token: CancellationToken) -> Response:
        # 1) 记录历史
        self._history.extend(messages)

        # 2) 取最后一条用户消息
        last = messages[-1]
        content = last.content if isinstance(last.content, str) else str(last.content)

        # 3) 产出回复
        reply = TextMessage(content=f"Echo: {content}", source=self.name)
        self._history.append(reply)
        return Response(chat_message=reply)

    async def on_reset(self, cancellation_token: CancellationToken) -> None:
        self._history.clear()
```

使用方式与内置 Agent 完全一致：

```python
agent = EchoAgent("echo")
result = await agent.run(task="Hello AutoGen")
print(result.messages[-1].content)   # Echo: Hello AutoGen
```

也可直接放进团队：

```python
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import MaxMessageTermination

team = RoundRobinGroupChat(
    [EchoAgent("echo"), AssistantAgent("assistant", model_client=model_client)],
    termination_condition=MaxMessageTermination(max_messages=4),
)
await Console(team.run_stream(task="Start"))
```

## 13.5 返回内部过程消息

`Response` 支持 `inner_messages`，用于把中间过程（思考、工具调用）也暴露给流式消费者：

```python
return Response(
    chat_message=final_message,                       # 最终对外消息
    inner_messages=[thinking_event, tool_call_event], # 过程事件（Console 可见）
)
```

## 13.6 取消支持

长时间运行的 Agent 应周期性检查 `cancellation_token`：

```python
async def on_messages(self, messages, cancellation_token: CancellationToken) -> Response:
    for step in self._plan():
        cancellation_token.raise_for_cancellation_if_requested()   # 或 if cancellation_token.is_cancelled(): ...
        await self._do_step(step)
    ...
```

## 关键 API 速查

| API | 说明 |
|-----|------|
| `BaseChatAgent` | 自定义 Agent 基类（`autogen_agentchat.agents`） |
| `Response(chat_message=, inner_messages=)` | 返回结构（`autogen_agentchat.base`） |
| `on_messages(messages, cancellation_token)` | 核心处理入口 |
| `on_reset(cancellation_token)` | 重置 |
| `produced_message_types` | 声明产出消息类型 |
| `CancellationToken` | 取消令牌（`autogen_core`） |

## 注意事项

- `on_messages` 收到的是**增量新消息**，不是完整历史——历史由 Agent 自己维护（如示例中的 `_history`）。
- 一定要实现 `on_reset`，否则 `team.reset()` 后状态残留。
- 自定义 Agent 也遵循"有状态"约定：`run()` 会改变内部状态。
- 完全脱离 AgentChat 的底层编排（事件驱动、自定义 runtime）请使用 **AutoGen Core**：
  <https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/index.html>

## 下一步

→ [14-状态管理与序列化.md](14-状态管理与序列化.md)：保存/恢复 Agent 与团队状态。
