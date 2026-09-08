# 11 - 多智能体模式 Swarm

本篇目标：用 **Swarm** 实现基于"交接（Handoff）"的多智能体协作——由模型决定把任务交给谁，支持交还人类。

## 11.1 前置准备

```bash
pip install -U "autogen-agentchat" "autogen-ext[openai]"
```

## 11.2 核心机制

- 所有 Agent **共享同一消息上下文**。
- **当前发言者由上下文中最近一条 `HandoffMessage` 决定**（这是与轮叫/选择器模式的本质区别）。
- Agent 通过 `handoffs` 参数声明可交接的目标；底层由模型发起 `transfer_to_<target>` 工具调用产生 `HandoffMessage`。
- 目标可以是其他 Agent 的 `name`，也可以是特殊目标 **`"user"`**（交还人类）。

## 11.3 最小示例：客服 + 退款专家

```python
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import HandoffTermination, TextMentionTermination
from autogen_agentchat.messages import HandoffMessage
from autogen_agentchat.teams import Swarm
from autogen_agentchat.ui import Console
from autogen_ext.models.openai import OpenAIChatCompletionClient


def refund_flight(flight_id: str) -> str:
    """Refund a flight"""
    return f"Flight {flight_id} refunded"


model_client = OpenAIChatCompletionClient(
    model="gpt-4o",
    parallel_tool_calls=False,   # 避免一次生成多个 handoff
)

travel_agent = AssistantAgent(
    "travel_agent",
    model_client=model_client,
    handoffs=["flights_refunder", "user"],
    system_message="""You are a travel agent.
    The flights_refunder is in charge of refunding flights.
    If you need information from the user, you must first send your message, then you can handoff to the user.
    Use TERMINATE when the travel planning is complete.""",
)

flights_refunder = AssistantAgent(
    "flights_refunder",
    model_client=model_client,
    handoffs=["travel_agent", "user"],
    tools=[refund_flight],
    system_message="""You are an agent specialized in refunding flights.
    You only need flight reference numbers to refund a flight.
    You have the ability to refund a flight using the refund_flight tool.
    If you need information from the user, you must first send your message, then you can handoff to the user.
    When the transaction is complete, handoff to the travel agent to finalize.""",
)

termination = HandoffTermination(target="user") | TextMentionTermination("TERMINATE")
team = Swarm([travel_agent, flights_refunder], termination_condition=termination)

task = "I need to refund my flight."


async def run_team_stream() -> None:
    task_result = await Console(team.run_stream(task=task))
    last_message = task_result.messages[-1]

    # 若最后一条是移交给 user，则等待用户输入后继续
    while isinstance(last_message, HandoffMessage) and last_message.target == "user":
        user_message = input("User: ")
        task_result = await Console(
            team.run_stream(task=HandoffMessage(source="user", target=last_message.source, content=user_message))
        )
        last_message = task_result.messages[-1]


# 脚本中：asyncio.run(run_team_stream())
await run_team_stream()
await model_client.close()
```

## 11.4 多专家 + 协调者（股票研究）

```python
async def get_stock_data(symbol: str) -> dict:
    """Get stock market data for a given symbol"""
    return {"price": 180.25, "volume": 1000000, "pe_ratio": 65.4, "market_cap": "700B"}


planner = AssistantAgent(
    "planner",
    model_client=model_client,
    handoffs=["financial_analyst", "news_analyst", "writer"],
    system_message="""You are a research planning coordinator.
    Coordinate market research by delegating to specialized agents:
    - Financial Analyst: For stock data analysis
    - News Analyst: For news gathering and analysis
    - Writer: For compiling final report
    Always send your plan first, then handoff to appropriate agent.
    Always handoff to a single agent at a time.
    Use TERMINATE when research is complete.""",
)

financial_analyst = AssistantAgent(
    "financial_analyst",
    model_client=model_client,
    handoffs=["planner"],
    tools=[get_stock_data],
    system_message="""You are a financial analyst.
    Analyze stock market data using the get_stock_data tool.
    Provide insights on financial metrics.
    Always handoff back to planner when analysis is complete.""",
)

# news_analyst / writer 同理：handoffs=["planner"]

from autogen_agentchat.conditions import TextMentionTermination

research_team = Swarm(
    participants=[planner, financial_analyst, news_analyst, writer],
    termination_condition=TextMentionTermination("TERMINATE"),
)

await Console(research_team.run_stream(task="Conduct market research for TSLA stock"))
await model_client.close()
```

## 11.5 消息流

```text
TextMessage(user)                    # 用户任务
ToolCallRequestEvent(planner)        # 模型发起 transfer_to_financial_analyst
ToolCallExecutionEvent(planner)      # 工具返回 "Transferred to financial_analyst, ..."
HandoffMessage(source=planner, target=financial_analyst)   # 交接生效
...（财务分析师工作）
TextMessage(planner, "TERMINATE")    # 触发终止
```

## 11.6 自定义交接：Handoff

`handoffs=["agent_a"]` 不够用时，可用 `Handoff` 定制交接时的话术与工具描述：

```python
from autogen_agentchat.base import Handoff
```

更高阶的完全自定义见官方 Core API 的 **Handoff Pattern**：
<https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/design-patterns/handoffs.html>

## 关键 API 速查

| API | 说明 |
|-----|------|
| `Swarm(participants=[...], termination_condition=)` | 创建交接型团队 |
| `AssistantAgent(handoffs=["agent", "user"])` | 声明交接目标 |
| `HandoffMessage(source=, target=, content=)` | 手工构造交接（常用于人类回复） |
| `HandoffTermination(target=)` | 移交给指定目标时终止 |
| `parallel_tool_calls=False` | 避免多 handoff 并发 |
| `from autogen_agentchat.base import Handoff` | 自定义交接行为 |

## 注意事项

- **模型必须支持 tool calling**（交接靠工具调用实现）。
- 建议关闭并行工具调用，否则可能一次生成多个 handoff 导致意外。
- 交接目标 `"user"` 会让团队停下等待人类输入，需由外层循环把输入包装成 `HandoffMessage` 传回。
- `HandoffMessage` 的 `models_usage` 通常为 `None`（它由前序工具调用产生）。

## 下一步

→ [12-人工协同HITL.md](12-人工协同HITL.md)：系统化的"人类在环"方案。
