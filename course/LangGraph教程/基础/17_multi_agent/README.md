# 17 - 多 Agent 协作（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量，跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` 是等价的脚本版本，本手册不修改它。

## 学习目标

为什么需要多 Agent：单个 Agent 处理复杂任务时，上下文过载、专业性不足、维护困难。

本模块三种模式：

```
模式 1: Supervisor    ── 协调者分配任务，循环直到完成
模式 2: Chain         ── A → B → C 线性接力
模式 3: Dynamic Dispatch ── 分类后路由到专业 Agent
```

## 0. 准备工作

```bash
pip install -U langchain langchain-groq langgraph python-dotenv
```

---

## 单元格 1：初始化模型 + 工具

```python
import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()

model = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0,
    max_tokens=500,
)

print("模型就绪")
```

```python
from langchain_core.tools import tool

@tool
def search_web(query: str) -> str:
    """搜索网络获取最新信息"""
    mock = {
        "人工智能": "人工智能(AI)是计算机科学分支，致力于创建智能系统。包括机器学习、深度学习、NLP。",
        "机器学习": "机器学习是AI子领域，通过算法让计算机从数据中学习。常见方法：监督、无监督、强化学习。",
    }
    for k, v in mock.items():
        if k in query:
            return v
    return f"找到关于'{query}'的相关信息：这是一个重要的技术领域。"

@tool
def check_grammar(text: str) -> str:
    """检查文本的语法和表达"""
    return f"语法检查完成。文本长度：{len(text)}字符。建议：表达清晰，结构合理。"

print("工具就绪")
```

---

## 单元格 2：模式一——Supervisor 监督者模式

核心思想：一个 Supervisor 决定由谁执行，执行完回到 Supervisor，循环直到完成。

```python
from typing import TypedDict, Annotated, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

class TeamState(TypedDict):
    task: str
    messages: Annotated[list, add_messages]
    research_result: str
    draft: str
    final_content: str
    next_agent: str

# Supervisor：决定下一步
def supervisor(state: TeamState) -> dict:
    if not state.get("research_result"):
        return {"next_agent": "researcher"}
    elif not state.get("draft"):
        return {"next_agent": "writer"}
    elif not state.get("final_content"):
        return {"next_agent": "editor"}
    return {"next_agent": "complete"}

# 研究员 Agent
def researcher(state: TeamState) -> dict:
    search_result = search_web.invoke({"query": state["task"]})
    messages = [
        SystemMessage(content="你是研究员，请根据搜索结果整理关键信息要点。"),
        HumanMessage(content=f"任务：{state['task']}\n搜索结果：{search_result}")
    ]
    response = model.invoke(messages)
    return {
        "research_result": response.content,
        "messages": [AIMessage(content=f"[研究员] {response.content}")]
    }

# 作家 Agent
def writer(state: TeamState) -> dict:
    messages = [
        SystemMessage(content="你是作家，请根据研究资料撰写一篇结构清晰的短文。"),
        HumanMessage(content=f"主题：{state['task']}\n研究资料：{state['research_result']}")
    ]
    response = model.invoke(messages)
    return {
        "draft": response.content,
        "messages": [AIMessage(content=f"[作家] {response.content}")]
    }

# 编辑 Agent
def editor(state: TeamState) -> dict:
    grammar = check_grammar.invoke({"text": state["draft"]})
    messages = [
        SystemMessage(content="你是编辑，请审核并优化文章。"),
        HumanMessage(content=f"初稿：{state['draft']}\n语法检查：{grammar}")
    ]
    response = model.invoke(messages)
    return {
        "final_content": response.content,
        "messages": [AIMessage(content=f"[编辑] {response.content}")]
    }

def route_to_agent(state: TeamState) -> Literal["researcher", "writer", "editor", "complete"]:
    return state["next_agent"]

# 构建图
graph = StateGraph(TeamState)
graph.add_node("supervisor", supervisor)
graph.add_node("researcher", researcher)
graph.add_node("writer", writer)
graph.add_node("editor", editor)

graph.add_edge(START, "supervisor")
graph.add_conditional_edges("supervisor", route_to_agent, {
    "researcher": "researcher",
    "writer": "writer",
    "editor": "editor",
    "complete": END
})
graph.add_edge("researcher", "supervisor")
graph.add_edge("writer", "supervisor")
graph.add_edge("editor", "supervisor")

app = graph.compile()
result = app.invoke({"task": "写一篇关于人工智能发展的简短介绍", "messages": []})

print("=" * 50)
print("最终内容：")
print(result["final_content"])
```

执行流程：supervisor → researcher → supervisor → writer → supervisor → editor → supervisor → complete。

---

## 单元格 3：模式二——协作链（线性接力）

A 的输出直接喂给 B，B 喂给 C，无循环：

```python
class ReviewState(TypedDict):
    code: str
    messages: Annotated[list, add_messages]
    security_review: str
    performance_review: str
    final_report: str

def security_reviewer(state: ReviewState) -> dict:
    messages = [
        SystemMessage(content="你是安全专家，请审查代码安全性。简洁回复。"),
        HumanMessage(content=f"代码：\n{state['code']}")
    ]
    response = model.invoke(messages)
    return {"security_review": response.content}

def performance_reviewer(state: ReviewState) -> dict:
    messages = [
        SystemMessage(content="你是性能专家，请分析代码性能。简洁回复。"),
        HumanMessage(content=f"代码：\n{state['code']}")
    ]
    response = model.invoke(messages)
    return {"performance_review": response.content}

def report_generator(state: ReviewState) -> dict:
    messages = [
        SystemMessage(content="请汇总审查结果生成报告。"),
        HumanMessage(content=f"安全：{state['security_review']}\n性能：{state['performance_review']}")
    ]
    response = model.invoke(messages)
    return {"final_report": response.content}

# 线性图：START → 安全 → 性能 → 报告 → END
chain = StateGraph(ReviewState)
chain.add_node("security", security_reviewer)
chain.add_node("performance", performance_reviewer)
chain.add_node("report", report_generator)

chain.add_edge(START, "security")
chain.add_edge("security", "performance")
chain.add_edge("performance", "report")
chain.add_edge("report", END)

chain_app = chain.compile()

result = chain_app.invoke({
    "code": "def get_data(uid):\n    q = f\"SELECT * FROM users WHERE id = {uid}\"\n    return db.execute(q)",
    "messages": []
})
print("审查报告：")
print(result["final_report"])
```

---

## 单元格 4：模式三——动态分发（分类路由）

先分类，再路由到专业 Agent：

```python
class SupportState(TypedDict):
    query: str
    category: str
    messages: Annotated[list, add_messages]
    response: str

def classifier(state: SupportState) -> dict:
    messages = [
        SystemMessage(content="分析用户问题，返回分类：billing（账单）、technical（技术）、general（其他）。只返回分类名称。"),
        HumanMessage(content=state["query"])
    ]
    response = model.invoke(messages)
    category = response.content.strip().lower()
    if category not in ["billing", "technical", "general"]:
        category = "general"
    return {"category": category}

def billing_agent(state: SupportState) -> dict:
    messages = [
        SystemMessage(content="你是账单客服，擅长处理付款、退款、账单问题。用中文回复。"),
        HumanMessage(content=state["query"])
    ]
    response = model.invoke(messages)
    return {"response": f"[账单客服] {response.content}"}

def technical_agent(state: SupportState) -> dict:
    messages = [
        SystemMessage(content="你是技术支持，擅长解决技术问题和使用指导。用中文回复。"),
        HumanMessage(content=state["query"])
    ]
    response = model.invoke(messages)
    return {"response": f"[技术支持] {response.content}"}

def general_agent(state: SupportState) -> dict:
    messages = [
        SystemMessage(content="你是友好的客服代表。用中文回复。"),
        HumanMessage(content=state["query"])
    ]
    response = model.invoke(messages)
    return {"response": f"[客服] {response.content}"}

def route_to_specialist(state: SupportState) -> Literal["billing", "technical", "general"]:
    return state["category"]

dispatch = StateGraph(SupportState)
dispatch.add_node("classifier", classifier)
dispatch.add_node("billing", billing_agent)
dispatch.add_node("technical", technical_agent)
dispatch.add_node("general", general_agent)

dispatch.add_edge(START, "classifier")
dispatch.add_conditional_edges("classifier", route_to_specialist, {
    "billing": "billing", "technical": "technical", "general": "general"
})
for n in ["billing", "technical", "general"]:
    dispatch.add_edge(n, END)

dispatch_app = dispatch.compile()

for q in ["我想申请退款", "软件一直显示加载中", "你们公司在哪里？"]:
    print(f"\n问题: {q}")
    r = dispatch_app.invoke({"query": q, "messages": []})
    print(f"回复: {r['response']}")
```

---

## 核心要点

| 模式 | 适用场景 | 图结构 |
|------|---------|--------|
| Supervisor | 任务需要多轮协调 | 循环：supervisor ↔ workers |
| Chain | 任务可分解为固定步骤 | 线性：A → B → C |
| Dynamic Dispatch | 输入类型不确定 | 树状：分类 → 路由 → 专家 |

1. Supervisor 用条件边 + 回到 supervisor 的普通边实现循环
2. Chain 就是最简单的线性图
3. Dynamic Dispatch 先分类再条件路由

## FAQ

### Q1: Agent 数量有上限吗？

技术上没有，但超过 5-6 个 Agent 时，管理复杂度和 token 消耗会急剧上升。

### Q2: 怎么防止无限循环？

设置最大迭代次数：在状态里加 `iteration: int`，每次循环 +1，超限强制结束。

## 下一步

**18_conditional_routing** —— 条件路由深入：评分路由、重试机制、决策树
