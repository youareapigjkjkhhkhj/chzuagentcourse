# 12 - 人工协同 HITL

本篇目标：把人类纳入循环——采用移交给 `user`、`UserProxyAgent` 参与团队、以及外部终止（UI 停止按钮）三种主流方式。

## 12.1 前置准备

```bash
pip install -U "autogen-agentchat" "autogen-ext[openai]"
```

## 12.2 方式一：Swarm 移交给 `user`（最常用）

Agent 在需要人类信息时，交接给特殊目标 `"user"`，团队停下等待；外层循环把用户输入包装成 `HandoffMessage` 交还给原 Agent。

```python
from autogen_agentchat.conditions import HandoffTermination, TextMentionTermination
from autogen_agentchat.messages import HandoffMessage
from autogen_agentchat.teams import Swarm
from autogen_agentchat.ui import Console

termination = HandoffTermination(target="user") | TextMentionTermination("TERMINATE")
team = Swarm([travel_agent, flights_refunder], termination_condition=termination)


async def run_team_stream() -> None:
    task_result = await Console(team.run_stream(task="I need to refund my flight."))
    last_message = task_result.messages[-1]

    while isinstance(last_message, HandoffMessage) and last_message.target == "user":
        user_message = input("User: ")
        task_result = await Console(
            team.run_stream(
                task=HandoffMessage(source="user", target=last_message.source, content=user_message)
            )
        )
        last_message = task_result.messages[-1]
```

要点：
- `target=last_message.source` 把控制权**交还给请求输入的那个 Agent**。
- `HandoffTermination(target="user")` 让"移交给人"本身成为停止条件，避免团队空转。

## 12.3 方式二：`UserProxyAgent` 参与团队

`UserProxyAgent` 代表人类用户作为团队成员，轮到它时从外部获取输入：

```python
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.ui import Console

user_proxy = UserProxyAgent("user_proxy")          # 代表人类
assistant = AssistantAgent("assistant", model_client=model_client)

team = RoundRobinGroupChat(
    [assistant, user_proxy],
    termination_condition=...,                      # 配终止条件
)
await Console(team.run_stream(task="..."))
```

> `UserProxyAgent` 的具体参数与输入回调方式以官方 API Reference 为准。

## 12.4 方式三：外部终止（停止按钮）

在 Web/桌面 UI 中给用户一个"停止"按钮，调用 `ExternalTermination.set()`：

```python
from autogen_agentchat.conditions import ExternalTermination, TextMentionTermination

external_termination = ExternalTermination()
team = RoundRobinGroupChat(
    [primary_agent, critic_agent],
    termination_condition=external_termination | TextMentionTermination("APPROVE"),
)

run = asyncio.create_task(Console(team.run_stream(task="...")))
# 用户点击停止
external_termination.set()
await run
```

特性：
- **优雅停止**：当前 Agent 完成本回合后才停，保证状态一致。
- 若需立即中断，用 `CancellationToken.cancel()`（见 [09-团队Teams.md](09-团队Teams.md)）。

## 12.5 在 Agent 提示词中约束"何时求助"

让 Agent 知道可以（且应该）向人类求助，是 HITL 生效的关键：

```python
travel_agent = AssistantAgent(
    "travel_agent",
    model_client=model_client,
    handoffs=["flights_refunder", "user"],
    system_message="""You are a travel agent.
    If you need information from the user, you must first send your message,
    then you can handoff to the user.
    Use TERMINATE when the travel planning is complete.""",
)
```

官方示例反复强调的范式：**先说明你要什么，再 handoff 给用户**——避免用户收到无上下文的提问。

## 12.6 人工审批（敏感操作）

把高风险工具（如退款、发邮件、删除）包装成需要确认的工具，或在工具内部先返回"待确认"并由人类决定是否执行：

```python
async def refund_flight(flight_id: str) -> str:
    """Refund a flight"""
    # 生产环境：在此接入审批流程/幂等校验/审计日志
    return f"Flight {flight_id} refunded"
```

## 关键 API 速查

| API | 说明 |
|-----|------|
| `handoffs=[..., "user"]` | 允许 Agent 移交给人类 |
| `HandoffMessage(source="user", target=..., content=...)` | 人类输入回传 |
| `HandoffTermination(target="user")` | 移交人类即停止 |
| `UserProxyAgent(name)` | 人类代理（团队成员） |
| `ExternalTermination().set()` | 外部请求停止 |
| `CancellationToken().cancel()` | 硬中断 |

## 注意事项

- 移交给 `"user"` 后若不回传，团队会一直停在等待态——UI 必须处理这种状态。
- v0.2 中由 `UserProxyAgent` 执行代码的方式在 v0.4 已改变：工具由发起 Agent 自己执行，`UserProxyAgent` 主要用于**代表人类输入**。
- 人工介入点要在 system_message 中明确写出，否则模型不会主动求助。

## 下一步

→ [13-自定义Agent.md](13-自定义Agent.md)：实现自己的 Agent 逻辑。
