# 09 - 团队 Teams

本篇目标：把多个 Agent 组成团队——以 `RoundRobinGroupChat` 为主，掌握运行、观测、重置、恢复、停止与取消。

## 9.1 前置准备

```bash
pip install -U "autogen-agentchat" "autogen-ext[openai]"
```

## 9.2 团队类型总览

| 团队 | 调度方式 | 适用 |
|------|----------|------|
| `RoundRobinGroupChat` | **轮叫**：按参与者顺序轮流发言，每人广播给全队 | 审稿/写作循环、固定流程 |
| `SelectorGroupChat` | 每条消息后用模型**选择下一个发言者** | 需要 LLM 动态决策发言顺序 |
| `Swarm` | 由最近的 `HandoffMessage` 决定下一个发言者（工具化交接） | 客服、专家路由（见 [11-多智能体模式Swarm.md](11-多智能体模式Swarm.md)） |
| `MagenticOneGroupChat` | 通用多智能体系统（Web/文件类开放任务） | 复杂开放式任务 |
| `GraphFlow` | 有向图编排的工作流 | 需要确定性 DAG 流程 |

> 本页以 `RoundRobinGroupChat` 为主；其余类型见对应章节与官方 Advanced 指南。

## 9.3 创建团队

```python
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import TextMentionTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_ext.models.openai import OpenAIChatCompletionClient

model_client = OpenAIChatCompletionClient(
    model="gpt-4o-2024-08-06",
    # api_key="sk-...",
)

primary_agent = AssistantAgent(
    "primary",
    model_client=model_client,
    system_message="You are a helpful AI assistant.",
)

critic_agent = AssistantAgent(
    "critic",
    model_client=model_client,
    system_message="Provide constructive feedback. Respond with 'APPROVE' to when your feedbacks are addressed.",
)

text_termination = TextMentionTermination("APPROVE")

team = RoundRobinGroupChat([primary_agent, critic_agent], termination_condition=text_termination)
```

机制：每个 Agent 在自己回合**向所有其他 Agent 广播**响应，全队共享一致上下文。

## 9.4 运行

```python
# 非流式
result = await team.run(task="Write a short poem about the fall season.")
print(result.messages, result.stop_reason)

# 流式
from autogen_agentchat.base import TaskResult
async for message in team.run_stream(task="Write a short poem about the fall season."):
    if isinstance(message, TaskResult):
        print("Stop Reason:", message.stop_reason)
    else:
        print(message)

# 流式 + Console（推荐）
from autogen_agentchat.ui import Console
await Console(team.run_stream(task="Write a short poem about the fall season."))
```

`Console` 结束时输出摘要：消息数、Finish reason、token 消耗、耗时。

## 9.5 重置 reset()

```python
await team.reset()   # 清空团队状态，并调用每个 Agent 的 on_reset()
```

- **不相关**的新任务前建议 reset。
- **相关**的后续任务可直接继续（见 9.6）。

## 9.6 恢复 Resume

```python
# 继续上次任务（不传 task）
await Console(team.run_stream())

# 带新任务但保留上文
await Console(team.run_stream(task="将这首诗用中文唐诗风格写一遍。"))
```

`RoundRobinGroupChat` 会从**上次最后发言者的下一个**继续轮叫。

## 9.7 外部停止 ExternalTermination（优雅停止）

适合 UI 的"停止"按钮：当前 Agent 会**先完成本回合**再停止，保证状态一致。

```python
from autogen_agentchat.conditions import ExternalTermination

external_termination = ExternalTermination()
team = RoundRobinGroupChat(
    [primary_agent, critic_agent],
    termination_condition=external_termination | text_termination,   # 用 | 组合
)

run = asyncio.create_task(Console(team.run_stream(task="Write a short poem about the fall season.")))
await asyncio.sleep(0.1)
external_termination.set()      # 请求停止
await run
# stop_reason='External termination requested'
```

## 9.8 立即取消 CancellationToken（硬中断）

```python
from autogen_core import CancellationToken

cancellation_token = CancellationToken()
run = asyncio.create_task(
    team.run(task="Translate the poem to Spanish.", cancellation_token=cancellation_token)
)
cancellation_token.cancel()

try:
    result = await run
except asyncio.CancelledError:
    print("Task was cancelled.")
```

| 方式 | 行为 |
|------|------|
| `ExternalTermination.set()` | 优雅：当前 Agent 完成回合后停止 |
| `CancellationToken.cancel()` | 立即中断，抛 `asyncio.CancelledError` |

## 9.9 单代理团队（工具循环）

v0.6.2+ 可用 `max_tool_iterations` 直接实现；早期写法是把单 Agent 放进团队，用 `TextMessageTermination` 控制循环：

```python
from autogen_agentchat.conditions import TextMessageTermination
from autogen_agentchat.teams import RoundRobinGroupChat

model_client = OpenAIChatCompletionClient(model="gpt-4o", parallel_tool_calls=False)

def increment_number(number: int) -> int:
    """Increment a number by 1."""
    return number + 1

looped_assistant = AssistantAgent(
    "looped_assistant",
    model_client=model_client,
    tools=[increment_number],
    system_message="You are a helpful AI assistant, use the tool to increment the number.",
)

team = RoundRobinGroupChat(
    [looped_assistant],
    termination_condition=TextMessageTermination("looped_assistant"),
)

async for message in team.run_stream(task="Increment the number 5 to 10."):
    print(type(message).__name__, message)

await model_client.close()
```

## 关键 API 速查

| API | 说明 |
|-----|------|
| `RoundRobinGroupChat([agents], termination_condition=)` | 创建轮叫团队 |
| `await team.run(task=)` / `team.run_stream(task=)` | 运行（流式末项为 TaskResult） |
| `await Console(team.run_stream(...))` | 格式化输出 |
| `await team.reset()` | 重置团队与成员 |
| `team.run_stream()` 无 task | 从中断处恢复 |
| `ExternalTermination().set()` | 优雅停止 |
| `CancellationToken().cancel()` | 硬中断 |

## 注意事项

- 团队与成员都是**有状态**的：不 reset 就带上下文继续，这是特性而非 bug。
- 终止条件在每次 `run()/run_stream()` 结束后会**自动重置**，所以能反复运行。
- 多个终止条件用 `|`（或）与 `&`（与）组合。

## 下一步

→ [10-终止条件Termination.md](10-终止条件Termination.md)：11 种内置条件与自定义终止。
