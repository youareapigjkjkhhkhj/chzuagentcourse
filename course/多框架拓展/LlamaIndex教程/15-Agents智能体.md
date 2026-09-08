# 15 - Agents 智能体

本篇目标：用 LlamaIndex 构建**会自主调用工具的智能体**——`FunctionAgent`、`ReActAgent`、`CodeActAgent`，以及多智能体编排。

## 15.1 前置准备

```bash
pip install llama-index-core llama-index-llms-openai python-dotenv
```

`.env`：

```env
OPENAI_API_KEY=sk-proj-xxxx
```

## 15.2 Agent 是什么（官方定义）

> An agent is a semi-autonomous piece of software powered by an LLM that is given a task and executes a series of steps towards solving that task. It is given a set of tools... and it selects the best available tool to complete each step.

循环：

1. 收到用户消息
2. LLM 结合历史、工具、最新消息决定下一步动作
3. 可能调用一个或多个工具
4. 解释工具输出，决定下一步
5. 不再调用工具 → 返回最终结果

## 15.3 第一个 Agent（官方示例：FunctionAgent）

```python
from dotenv import load_dotenv

load_dotenv()

from llama_index.llms.openai import OpenAI
from llama_index.core.agent.workflow import FunctionAgent


def multiply(a: float, b: float) -> float:
    """Multiply two numbers and returns the product"""
    return a * b


def add(a: float, b: float) -> float:
    """Add two numbers and returns the sum"""
    return a + b


llm = OpenAI(model="gpt-4o-mini")

workflow = FunctionAgent(
    tools=[multiply, add],
    llm=llm,
    system_prompt="You are an agent that can perform basic mathematical operations using tools.",
)


async def main():
    response = await workflow.run(user_msg="What is 20+(2*4)?")
    print(response)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

输出示例：`The result of (20 + (2 times 4)) is 28.`

要点：
- 普通 Python 函数即可作为工具；Agent 依据**函数名、参数、docstring、类型注解**判断是否使用。
- **docstring 要写清楚**，这是工具选择的依据。
- 代码是异步的：脚本里需 `asyncio.run(main())`。

> 若遇到模型不支持流式，可 `FunctionAgent(..., streaming=False)` 关闭流式。

## 15.4 显式定义 FunctionTool

```python
from llama_index.core.tools import FunctionTool


def search_kb(query: str) -> str:
    """在公司知识库中检索相关文档片段。"""
    return "..."


tool = FunctionTool.from_defaults(
    fn=search_kb,
    name="knowledge_search",
    description="根据问题检索公司知识库；输入应为完整问题句。",
)
```

## 15.5 把 RAG 查询引擎作为工具

```python
from llama_index.core.tools import QueryEngineTool, ToolMetadata

rag_tool = QueryEngineTool(
    query_engine=index.as_query_engine(similarity_top_k=3),
    metadata=ToolMetadata(
        name="company_kb",
        description="回答公司制度、产品说明、流程规范相关问题",
    ),
)

agent = FunctionAgent(
    tools=[rag_tool, multiply, add],
    llm=llm,
    system_prompt="优先使用知识库工具回答制度类问题。",
)
```

官方强调的核心优势：**RAG 管线可以作为众多工具之一**，而不是唯一手段。

## 15.6 其他预置 Agent

| Agent | 策略 | 适用 |
|-------|------|------|
| `FunctionAgent` | 函数调用（tool calling） | 默认首选，模型支持 function calling 时 |
| `ReActAgent` | ReAct 提示（思考-行动-观察） | 模型不支持可靠 function calling 时 |
| `CodeActAgent` | 生成并执行代码完成任务 | 数据处理、计算密集型任务 |

```python
from llama_index.core.agent.workflow import ReActAgent, CodeActAgent

react_agent = ReActAgent(tools=[...], llm=llm)
code_agent = CodeActAgent(tools=[...], llm=llm)
```

## 15.7 多智能体：AgentWorkflow

用 `AgentWorkflow` 管理多个 Agent，支持**交接（handoff）**：

```python
from llama_index.core.agent.workflow import AgentWorkflow, FunctionAgent


def lookup_policy(question: str) -> str:
    """查找公司政策条款"""
    return "..."


def calculate_refund(amount: float, days: int) -> float:
    """按天数计算退款金额"""
    return amount * (1 - 0.01 * days)


policy_agent = FunctionAgent(
    name="PolicyAgent",
    description="负责解读公司政策条款",
    system_prompt="你是政策专家，只回答与政策相关的问题。",
    tools=[lookup_policy],
    llm=llm,
    can_handoff_to=["RefundAgent"],
)

refund_agent = FunctionAgent(
    name="RefundAgent",
    description="负责计算退款金额",
    system_prompt="你是退款计算专家。",
    tools=[calculate_refund],
    llm=llm,
    can_handoff_to=["PolicyAgent"],
)

workflow = AgentWorkflow(
    agents=[policy_agent, refund_agent],
    root_agent=policy_agent.name,
)

response = await workflow.run(user_msg="买了 30 天的商品，能退多少钱？")
print(response)
```

要点：
- 每个 Agent 需 `name` 与 `description`（用于交接判断）
- `can_handoff_to=[...]` 声明可交接的目标
- `root_agent` 指定入口 Agent

## 15.8 状态与记忆

```python
# 在同一 workflow 实例上连续对话，上下文会被保留
await workflow.run(user_msg="我叫小明")
await workflow.run(user_msg="我叫什么？")
```

需要持久化时，可取出/恢复 Agent 的记忆（配合 Workflow 的 Context 能力，见 [16-Workflows工作流.md](16-Workflows工作流.md)）。

## 15.9 流式与调试

```python
handler = workflow.run(user_msg="帮我核对这笔退款")

async for ev in handler.stream_events():
    print(ev)

result = await handler
print(result)
```

## 关键 API 速查

| API | 说明 |
|-----|------|
| `from llama_index.core.agent.workflow import FunctionAgent` | 函数调用型 Agent |
| `FunctionAgent(tools=, llm=, system_prompt=)` | 创建 Agent |
| `await workflow.run(user_msg=...)` | 运行 |
| `FunctionTool.from_defaults(fn=, name=, description=)` | 显式定义工具 |
| `QueryEngineTool(query_engine=, metadata=)` | RAG 工具 |
| `AgentWorkflow(agents=, root_agent=)` | 多智能体编排 |
| `can_handoff_to=[...]` | 交接目标 |
| `streaming=False` | 关闭流式（模型不支持时） |

## 注意事项

- 官方提醒：**Agents 需要能力较强的模型**，小模型可靠性明显下降。
- 工具 docstring 与 `description` 是决定 Agent 行为的关键——写得含糊会选错工具。
- 涉及写操作/资金的工具要加权限校验与人工确认。
- 复杂确定性流程建议用 Workflow 显式编排，而不是完全交给 Agent 自由发挥。

## 下一步

→ [16-Workflows工作流.md](16-Workflows工作流.md)：用事件驱动编排复杂流程。
