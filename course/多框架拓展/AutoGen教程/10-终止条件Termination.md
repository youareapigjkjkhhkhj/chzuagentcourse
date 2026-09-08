# 10 - 终止条件 Termination

本篇目标：掌握让团队"停下来"的机制——11 种内置条件、`&`/`|` 组合、以及自定义终止条件。

## 10.1 前置准备

```bash
pip install -U "autogen-agentchat" "autogen-ext[openai]"
```

所有内置条件均从 `autogen_agentchat.conditions` 导入。

## 10.2 核心机制

终止条件是一个**可调用对象**：

- 接收"自上次调用以来的增量消息序列"（`BaseAgentEvent | BaseChatMessage`）
- 应该终止 → 返回 `StopMessage`；否则返回 `None`
- 对群聊团队，每次有 Agent 响应后调用一次
- 每次 `run()` / `run_stream()` 结束后**自动 reset**，因此可反复运行

## 10.3 内置条件速查

| 条件 | 触发时机 |
|------|----------|
| `MaxMessageTermination(max_messages=N)` | 产生 N 条消息后（含 Agent 消息与任务消息） |
| `TextMentionTermination("APPROVE")` | 消息中提到指定文本 |
| `StopMessageTermination()` | 某 Agent 产生 `StopMessage` |
| `TokenUsageTermination(...)` | 达到指定 prompt/completion token（需 Agent 上报 usage） |
| `TimeoutTermination(seconds)` | 超过指定秒数 |
| `ExternalTermination()` | 外部调用 `.set()` 触发（UI 停止按钮） |
| `SourceMatchTermination(sources)` | 指定 Agent 响应后 |
| `FunctionalTermination(fn)` | 自定义函数对最新消息返回 True（**简单自定义首选**） |
| `HandoffTermination(target=)` | 产生移交给指定 target 的 `HandoffMessage`（Swarm） |
| `FunctionCallTermination(function_name=)` | 指定函数被调用后 |
| `TextMessageTermination(source)` | 指定 source 产生 `TextMessage` 时 |

## 10.4 MaxMessageTermination

```python
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.ui import Console

max_msg_termination = MaxMessageTermination(max_messages=3)
round_robin_team = RoundRobinGroupChat([primary_agent, critic_agent], termination_condition=max_msg_termination)

await Console(round_robin_team.run_stream(task="Write a unique, Haiku about the weather in Paris"))

# 达到上限后，不传 task 可从中断处继续
await Console(round_robin_team.run_stream())
```

## 10.5 TextMentionTermination

```python
from autogen_agentchat.conditions import TextMentionTermination

text_termination = TextMentionTermination("APPROVE")
# stop_reason = "Text 'APPROVE' mentioned"
```

常与 Agent 的 system_message 配合（"Respond with APPROVE when ..."）。

## 10.6 组合：OR（|）与 AND（&）

```python
max_msg_termination = MaxMessageTermination(max_messages=10)
text_termination = TextMentionTermination("APPROVE")

# OR：任一满足即停
combined = max_msg_termination | text_termination

# AND：两者同时满足才停
combined_and = max_msg_termination & text_termination

team = RoundRobinGroupChat([primary_agent, critic_agent], termination_condition=combined)
await Console(team.run_stream(task="Write a unique, Haiku about the weather in Paris"))
```

典型用法：`ExternalTermination() | TextMentionTermination("TERMINATE")`（既能手动停，也能自动停）。

## 10.7 自定义终止条件

简单逻辑优先用 `FunctionalTermination`；复杂逻辑可继承 `TerminationCondition`：

```python
from typing import Sequence

from autogen_agentchat.base import TerminatedException, TerminationCondition
from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage, StopMessage, ToolCallExecutionEvent
from autogen_core import Component
from pydantic import BaseModel
from typing_extensions import Self


class FunctionCallTerminationConfig(BaseModel):
    function_name: str


class FunctionCallTermination(TerminationCondition, Component[FunctionCallTerminationConfig]):
    component_config_schema = FunctionCallTerminationConfig
    component_provider_override = "autogen_agentchat.conditions.FunctionCallTermination"

    def __init__(self, function_name: str) -> None:
        self._terminated = False
        self._function_name = function_name

    @property
    def terminated(self) -> bool:
        return self._terminated

    async def __call__(self, messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> StopMessage | None:
        if self._terminated:
            raise TerminatedException("Termination condition has already been reached")
        for message in messages:
            if isinstance(message, ToolCallExecutionEvent):
                for execution in message.content:
                    if execution.name == self._function_name:
                        self._terminated = True
                        return StopMessage(
                            content=f"Function '{self._function_name}' was executed.",
                            source="FunctionCallTermination",
                        )
        return None

    async def reset(self) -> None:
        self._terminated = False

    def _to_config(self) -> FunctionCallTerminationConfig:
        return FunctionCallTerminationConfig(function_name=self._function_name)

    @classmethod
    def _from_config(cls, config: FunctionCallTerminationConfig) -> Self:
        return cls(function_name=config.function_name)
```

继承时需实现：`terminated` 属性、`__call__`、`reset`；如需序列化再实现 `_to_config` / `_from_config`。

## 10.8 停止原因

`TaskResult.stop_reason` 常见取值：

```text
"Text 'APPROVE' mentioned"
"Text message received from 'looped_assistant'"
"External termination requested"
"Handoff to user from flights_refunder detected."
"Maximum number of messages 10 reached, current message count: 11"
```

## 关键 API 速查

| API | 说明 |
|-----|------|
| `from autogen_agentchat.conditions import ...` | 全部内置条件 |
| `cond1 | cond2` / `cond1 & cond2` | OR / AND 组合 |
| `await condition.reset()` | 手动重置（通常自动） |
| `result.stop_reason` | 查看停止原因 |
| `FunctionalTermination(fn)` | 函数式自定义（简单场景） |

## 注意事项

- 终止条件对象**有状态**：触发后需 reset 才能再次使用（框架在 run 结束后自动 reset）。
- AND 组合要求"同时满足"，实际很少用；多数场景用 OR（谁先到算谁）。
- 没有终止条件又未设置 `max_messages` 的团队可能长时间运行——务必配终止条件或用户确认。

## 下一步

→ [11-多智能体模式Swarm.md](11-多智能体模式Swarm.md)：基于交接（Handoff）的智能路由团队。
