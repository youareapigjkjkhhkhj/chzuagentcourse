# 项目二：多智能体客服系统（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量，跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` 是等价的脚本版本，本手册不修改它。

## 项目目标

构建多 Agent 协作的智能客服：意图分类 → 专业路由 → 工具调用 → 质量检查 → 人工升级。

## 0. 准备工作

```bash
pip install -U langchain langchain-groq langgraph python-dotenv
```

---

## 单元格 1：初始化模型

```python
import os
import json
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

---

## 单元格 2：模拟数据库 + 工具

```python
MOCK_ORDERS = {
    "ORD001": {"status": "已发货", "product": "智能手表 Pro", "price": 1299, "tracking": "SF1234567890"},
    "ORD002": {"status": "处理中", "product": "无线耳机 Max", "price": 899, "tracking": None},
    "ORD003": {"status": "已完成", "product": "便携充电宝", "price": 199, "tracking": "YT9876543210"},
}

MOCK_PRODUCTS = {
    "智能手表 Pro": {"price": 1299, "features": ["心率监测", "GPS", "防水50米", "7天续航"], "rating": 4.8},
    "无线耳机 Max": {"price": 899, "features": ["主动降噪", "40小时续航", "蓝牙5.3"], "rating": 4.6},
    "便携充电宝": {"price": 199, "features": ["20000mAh", "快充", "双USB"], "rating": 4.5},
}

from langchain_core.tools import tool

@tool
def query_order(order_id: str) -> str:
    """查询订单状态"""
    order = MOCK_ORDERS.get(order_id)
    if not order:
        return f"未找到订单 {order_id}"
    return json.dumps(order, ensure_ascii=False)

@tool
def search_product(product_name: str) -> str:
    """搜索产品信息"""
    product = MOCK_PRODUCTS.get(product_name)
    if not product:
        return f"未找到产品 {product_name}"
    return json.dumps(product, ensure_ascii=False)

@tool
def process_refund(order_id: str) -> str:
    """处理退款"""
    order = MOCK_ORDERS.get(order_id)
    if not order:
        return f"未找到订单 {order_id}"
    if order["status"] == "已完成":
        return f"订单 {order_id} 已完成，可申请退款，退款金额 ¥{order['price']}"
    return f"订单 {order_id} 状态为 {order['status']}，暂不能退款"

print("工具就绪")
```

---

## 单元格 3：意图分类器

```python
from typing import TypedDict, Literal, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

class CustomerState(TypedDict):
    messages: Annotated[list, add_messages]
    query: str
    category: str
    response: str
    escalate: bool

def classifier(state: CustomerState) -> dict:
    messages = [
        SystemMessage(content="""分析用户问题，返回分类：
- technical: 技术问题、故障、使用方法
- billing: 账单、付款、退款
- product: 产品功能、价格、推荐
- general: 其他
只返回分类名称。"""),
        HumanMessage(content=state["query"])
    ]
    response = model.invoke(messages)
    category = response.content.strip().lower()
    if category not in ["technical", "billing", "product", "general"]:
        category = "general"
    return {"category": category}

print("分类器就绪")
```

---

## 单元格 4：专业 Agent

```python
def tech_support(state: CustomerState) -> dict:
    msgs = [
        SystemMessage(content="你是技术支持工程师。用专业但友好的语气回答技术问题。用中文。"),
        HumanMessage(content=state["query"])
    ]
    response = model.invoke(msgs)
    return {"response": f"[技术支持] {response.content}"}

def billing_agent(state: CustomerState) -> dict:
    msgs = [
        SystemMessage(content="你是账单客服。处理付款、退款、账单问题。用中文。"),
        HumanMessage(content=state["query"])
    ]
    response = model.invoke(msgs)
    return {"response": f"[账单客服] {response.content}"}

def product_agent(state: CustomerState) -> dict:
    # 先搜索产品信息
    product_info = search_product.invoke({"product_name": state["query"]})
    msgs = [
        SystemMessage(content="你是产品顾问。根据产品信息回答用户问题。用中文。"),
        HumanMessage(content=f"用户问题：{state['query']}\n产品信息：{product_info}")
    ]
    response = model.invoke(msgs)
    return {"response": f"[产品顾问] {response.content}"}

def general_agent(state: CustomerState) -> dict:
    msgs = [
        SystemMessage(content="你是友好的客服代表。热情回复用户。用中文。"),
        HumanMessage(content=state["query"])
    ]
    response = model.invoke(msgs)
    return {"response": f"[客服] {response.content}"}

print("Agent 就绪")
```

---

## 单元格 5：质量检查 + 人工升级

```python
def quality_check(state: CustomerState) -> dict:
    response = state["response"]
    # 简单质量检查：响应是否足够长
    escalate = len(response) < 30
    return {"escalate": escalate}

def route_to_agent(state: CustomerState) -> Literal["tech", "billing", "product", "general", "escalate"]:
    if state.get("escalate"):
        return "escalate"
    return state["category"]

def escalate_to_human(state: CustomerState) -> dict:
    return {"response": "已为您转接人工客服，请稍候。"}
```

---

## 单元格 6：构建客服系统图

```python
graph = StateGraph(CustomerState)

graph.add_node("classifier", classifier)
graph.add_node("tech", tech_support)
graph.add_node("billing", billing_agent)
graph.add_node("product", product_agent)
graph.add_node("general", general_agent)
graph.add_node("quality", quality_check)
graph.add_node("escalate", escalate_to_human)

graph.add_edge(START, "classifier")
graph.add_conditional_edges("classifier", lambda s: s["category"], {
    "tech": "tech", "billing": "billing",
    "product": "product", "general": "general"
})
for n in ["tech", "billing", "product", "general"]:
    graph.add_edge(n, "quality")
graph.add_conditional_edges("quality", route_to_agent, {
    "tech": "tech", "billing": "billing", "product": "product",
    "general": "general", "escalate": "escalate"
})
graph.add_edge("escalate", END)

app = graph.compile()
print("客服系统就绪")
```

---

## 单元格 7：测试完整流程

```python
test_queries = [
    "我的订单 ORD001 到哪了？",
    "智能手表 Pro 有什么功能？",
    "软件打开后一直显示加载中，怎么解决？",
    "你们公司在哪里？"
]

for q in test_queries:
    print(f"\n{'='*50}")
    print(f"用户: {q}")
    r = app.invoke({"messages": [], "query": q, "category": "", "response": "", "escalate": False})
    print(f"客服: {r['response']}")
```

---

## 核心要点

1. **意图分类** → 条件路由到专业 Agent
2. **工具集成**：Agent 可调用工具查询订单/产品信息
3. **质量检查**：响应太短时自动升级人工
4. **完整流程**：分类 → 处理 → 检查 → 升级/返回

## 进阶优化方向

- 添加更多专业 Agent（物流、投诉）
- 集成真实业务系统
- 实现 Agent 间协作
- 添加用户画像分析

## 下一步

**03_research_assistant** —— 智能研究助手
