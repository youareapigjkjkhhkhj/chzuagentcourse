# 16 - LangGraph 基础（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量（如 `model`），跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` 是等价的脚本版本，本手册不修改它。

## 学习目标

LangGraph = 用图（Graph）构建多步骤 AI 工作流。

| LangChain | LangGraph |
|-----------|-----------|
| `model → prompt → parser` 流水线 | 节点（Node）+ 边（Edge）的状态图 |
| 顺序或简单分支 | 条件路由、循环、多 Agent |
| 中间件控制 | 完全控制每个处理单元 |

核心概念三件套：**State**（状态）→ **Node**（节点）→ **Edge**（边）

## 0. 准备工作

```bash
pip install -U langchain langchain-groq langgraph python-dotenv
```

把仓库根目录的 `.env.example` 复制为 `.env`，填入 `GROQ_API_KEY=gsk_xxx`。

---

## 单元格 1：初始化模型

```python
import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()

model = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0,
    max_tokens=300,
)

print("模型就绪")
```

---

## 单元格 2：第一个图——State + Node + Edge

```python
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

class SimpleState(TypedDict):
    input_text: str
    processed_text: str

def preprocess(state: SimpleState) -> dict:
    """节点函数：接收状态，返回要更新的字段"""
    text = state["input_text"].strip().lower()
    return {"processed_text": text}

# 1. 创建 StateGraph
graph = StateGraph(SimpleState)

# 2. 添加节点
graph.add_node("preprocess", preprocess)

# 3. 添加边：START → preprocess → END
graph.add_edge(START, "preprocess")
graph.add_edge("preprocess", END)

# 4. 编译
app = graph.compile()

result = app.invoke({"input_text": "  Hello World  "})
print(result)
# {'input_text': '  Hello World  ', 'processed_text': 'hello world'}
```

状态更新是**合并式**的：只返回要更新的字段，其他字段保留。

---

## 单元格 3：多节点顺序图

```python
from langchain_core.messages import HumanMessage, SystemMessage

class ThreeStepState(TypedDict):
    input_text: str
    llm_response: str
    final_output: str

def step1_input(state: ThreeStepState) -> dict:
    """步骤1：预处理"""
    return {"input_text": state["input_text"].strip()}

def step2_llm(state: ThreeStepState) -> dict:
    """步骤2：调用 LLM"""
    messages = [
        SystemMessage(content="你是一个简洁的助手，用一句话回答。"),
        HumanMessage(content=state["input_text"])
    ]
    response = model.invoke(messages)
    return {"llm_response": response.content}

def step3_format(state: ThreeStepState) -> dict:
    """步骤3：格式化输出"""
    return {"final_output": f"[回复] {state['llm_response']}"}

graph = StateGraph(ThreeStepState)
graph.add_node("input", step1_input)
graph.add_node("llm", step2_llm)
graph.add_node("format", step3_format)

graph.add_edge(START, "input")
graph.add_edge("input", "llm")
graph.add_edge("llm", "format")
graph.add_edge("format", END)

app = graph.compile()

result = app.invoke({"input_text": "  什么是 LangGraph？  "})
print(result["final_output"])
```

---

## 单元格 4：add_messages 注解——消息自动追加

```python
from typing import Annotated
from langgraph.graph.message import add_messages

class ConversationState(TypedDict):
    messages: Annotated[list, add_messages]  # 关键：add_messages 注解

def chat_node(state: ConversationState) -> dict:
    messages = state["messages"]
    # 注入系统提示（如果是第一轮）
    if not messages or not hasattr(messages[0], 'type') or messages[0].type != "system":
        messages = [SystemMessage(content="你是一个友好的助手。")] + messages
    response = model.invoke(messages)
    return {"messages": [response]}  # add_messages 会自动追加到列表

graph = StateGraph(ConversationState)
graph.add_node("chat", chat_node)
graph.add_edge(START, "chat")
graph.add_edge("chat", END)

app = graph.compile()

# 模拟多轮对话
result1 = app.invoke({"messages": [HumanMessage(content="你好！我叫小明。")]})
result2 = app.invoke({"messages": [HumanMessage(content="你还记得我的名字吗？")]})

print("第1轮:", result1["messages"][-1].content)
print("第2轮:", result2["messages"][-1].content)
print("消息数:", len(result2["messages"]))  # 4 条（user, ai, user, ai）
```

`add_messages` 把每次返回的新消息**追加**到列表，不是替换。

---

## 单元格 5：MemorySaver——多轮对话持久化

```python
from langgraph.checkpoint.memory import MemorySaver

memory = MemorySaver()
app = graph.compile(checkpointer=memory)

# 使用 thread_id 隔离不同会话
config_a = {"configurable": {"thread_id": "user_alice"}}
config_b = {"configurable": {"thread_id": "user_bob"}}

# Alice 的对话
r1 = app.invoke(
    {"messages": [HumanMessage(content="我是 Alice，我喜欢 Python。")]},
    config=config_a
)
r2 = app.invoke(
    {"messages": [HumanMessage(content="我喜欢什么语言？")]},
    config=config_a
)
print("Alice:", r2["messages"][-1].content)

# Bob 的对话（独立线程）
r3 = app.invoke(
    {"messages": [HumanMessage(content="我是 Bob，我喜欢 Java。")]},
    config=config_b
)
print("Bob:", r3["messages"][-1].content)
```

`thread_id` 是会话隔离的钥匙——同一个 thread_id 共享历史，不同 thread_id 完全独立。

---

## 单元格 6：查看对话历史

```python
state = app.get_state(config_a)
print("Alice 线程的完整历史：")
for msg in state.values["messages"]:
    role = "用户" if msg.type == "human" else "AI"
    print(f"  [{role}] {msg.content[:60]}")
```

---

## 单元格 7：可视化图结构

```python
print("图结构：")
print("  START → input → llm → format → END")
print()
print("状态流：")
print("  input_text → step1 清洗 → step2 LLM → step3 格式化 → final_output")
```

---

## 核心要点

1. **State = TypedDict**，定义状态结构
2. **Node = 函数**，接收 state 返回 `dict`（合并更新）
3. **Edge = 执行顺序**，`graph.add_edge(from, to)`
4. **add_messages** 自动追加消息到列表，不是替换
5. **MemorySaver + thread_id** 实现多轮对话持久化
6. 编译后的图是不可变的，需修改要重新 `compile`

## FAQ

### Q1: 状态更新为什么是合并式？

设计哲学：节点只关心自己负责的字段，不用把整个 state 返回。类似 `dict.update()`。

### Q2: add_messages 和普通 list 的区别？

`add_messages` 是 LangGraph 专用注解，实现消息的智能合并（去重、追加）。普通 list 会替换整个列表。

### Q3: 什么时候用 LangGraph 而不是 LangChain 流水线？

简单链式调用用 LangChain；需要条件分支、循环、多 Agent 协作、复杂状态管理时用 LangGraph。

## 下一步

**17_multi_agent** —— 多 Agent 协作：Supervisor 模式、协作链、动态分发
