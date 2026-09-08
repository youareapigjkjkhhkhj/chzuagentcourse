# 18 - 条件路由（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量，跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` 是等价的脚本版本，本手册不修改它。

## 学习目标

1. `add_conditional_edges` 实现动态分支
2. 路由函数的写法（`Literal` 类型标注）
3. 循环控制：重试机制
4. 多层条件路由：决策树

## 0. 准备工作

```bash
pip install -U langchain langchain-groq langgraph python-dotenv
```

---

## 单元格 1：初始化模型

```python
import os
import random
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

## 单元格 2：评分路由——根据分数走不同流程

```python
from typing import TypedDict, Literal
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage, SystemMessage

class ScoreState(TypedDict):
    content: str
    score: int
    feedback: str
    result: str

def evaluate(state: ScoreState) -> dict:
    messages = [
        SystemMessage(content="评估以下内容并给出1-100的分数。只返回数字。"),
        HumanMessage(content=state["content"])
    ]
    response = model.invoke(messages)
    try:
        score = max(0, min(100, int(response.content.strip())))
    except:
        score = 70
    return {"score": score}

def route_by_score(state: ScoreState) -> Literal["excellent", "good", "improve", "reject"]:
    score = state["score"]
    if score >= 90:   return "excellent"
    elif score >= 70: return "good"
    elif score >= 50: return "improve"
    else:             return "reject"

def handle_excellent(state: ScoreState) -> dict:
    return {"feedback": "恭喜！内容非常出色！", "result": "APPROVED_WITH_HONORS"}

def handle_good(state: ScoreState) -> dict:
    return {"feedback": "内容合格，已通过审核。", "result": "APPROVED"}

def handle_improve(state: ScoreState) -> dict:
    messages = [
        SystemMessage(content="请为以下内容提供简洁的改进建议（50字以内）。"),
        HumanMessage(content=state["content"])
    ]
    response = model.invoke(messages)
    return {"feedback": f"建议改进：{response.content}", "result": "NEEDS_IMPROVEMENT"}

def handle_reject(state: ScoreState) -> dict:
    return {"feedback": "内容不符合要求，请重新撰写。", "result": "REJECTED"}

graph = StateGraph(ScoreState)
graph.add_node("evaluate", evaluate)
graph.add_node("excellent", handle_excellent)
graph.add_node("good", handle_good)
graph.add_node("improve", handle_improve)
graph.add_node("reject", handle_reject)

graph.add_edge(START, "evaluate")
graph.add_conditional_edges("evaluate", route_by_score, {
    "excellent": "excellent", "good": "good",
    "improve": "improve", "reject": "reject"
})
for n in ["excellent", "good", "improve", "reject"]:
    graph.add_edge(n, END)

app = graph.compile()

for content in [
    "Python 是一门优秀的编程语言，语法简洁，生态丰富，广泛应用于 Web、数据科学、AI。",
    "Python 是编程语言，很好用。",
    "编程"
]:
    print(f"\n内容: {content[:30]}...")
    r = app.invoke({"content": content})
    print(f"  结果: {r['result']} | 反馈: {r['feedback']}")
```

---

## 单元格 3：重试机制——失败时循环回到执行节点

```python
class RetryState(TypedDict):
    task: str
    retry_count: int
    max_retries: int
    success: bool
    result: str

def execute_task(state: RetryState) -> dict:
    retry_count = state.get("retry_count", 0)
    # 模拟 50% 失败率
    success = random.random() > 0.5
    if success:
        return {"success": True, "result": f"任务 '{state['task']}' 执行成功！", "retry_count": retry_count + 1}
    else:
        return {"success": False, "result": "模拟错误", "retry_count": retry_count + 1}

def should_retry(state: RetryState) -> Literal["retry", "fallback", "success"]:
    if state["success"]:
        return "success"
    if state["retry_count"] < state["max_retries"]:
        return "retry"        # 回到 execute_task
    return "fallback"         # 超限，走备用

def fallback_handler(state: RetryState) -> dict:
    return {"result": f"⚠️ 备用方案完成（原任务失败 {state['retry_count']} 次）"}

graph = StateGraph(RetryState)
graph.add_node("execute", execute_task)
graph.add_node("fallback", fallback_handler)

graph.add_edge(START, "execute")
graph.add_conditional_edges("execute", should_retry, {
    "retry": "execute",        # 循环回到自己
    "fallback": "fallback",
    "success": END
})
graph.add_edge("fallback", END)

retry_app = graph.compile()

for i in range(3):
    print(f"\n--- 测试 {i+1} ---")
    r = retry_app.invoke({"task": "发送邮件", "retry_count": 0, "max_retries": 3, "success": False})
    print(f"结果: {r['result']}")
```

关键：`"retry": "execute"` 形成了**自循环**，配合 `retry_count` 控制循环次数。

---

## 单元格 4：决策树——多层条件路由

贷款审批：信用分 → 抵押物 → 收入比，层层路由。

```python
class LoanState(TypedDict):
    applicant_name: str
    credit_score: int
    income: int
    loan_amount: int
    has_collateral: bool
    decision: str
    reason: str

def initial_check(state: LoanState) -> dict:
    print(f"  [检查] {state['applicant_name']}: 信用{state['credit_score']} 收入¥{state['income']}")
    return {}

def route_initial(state: LoanState) -> Literal["auto_reject", "credit_review", "income_review"]:
    if state["credit_score"] < 550:  return "auto_reject"
    if state["credit_score"] >= 750: return "income_review"
    return "credit_review"

def auto_reject(state: LoanState) -> dict:
    return {"decision": "REJECTED", "reason": "信用分低于最低要求"}

def credit_review(state: LoanState) -> dict:
    return {}

def route_credit(state: LoanState) -> Literal["income_review", "manual_review"]:
    return "income_review" if state["has_collateral"] else "manual_review"

def income_review(state: LoanState) -> dict:
    return {}

def route_income(state: LoanState) -> Literal["approve", "partial_approve", "manual_review"]:
    ratio = state["loan_amount"] / (state["income"] * 12)
    if ratio <= 3:   return "approve"
    elif ratio <= 5: return "partial_approve"
    else:            return "manual_review"

def approve(state: LoanState) -> dict:
    return {"decision": "APPROVED", "reason": "符合所有审批条件"}

def partial_approve(state: LoanState) -> dict:
    amt = state["income"] * 12 * 3
    return {"decision": "PARTIALLY_APPROVED", "reason": f"批准 ¥{amt}（原申请 ¥{state['loan_amount']}）"}

def manual_review(state: LoanState) -> dict:
    return {"decision": "PENDING_REVIEW", "reason": "需信贷专员进一步审核"}

graph = StateGraph(LoanState)
graph.add_node("check", initial_check)
graph.add_node("auto_reject", auto_reject)
graph.add_node("credit_review", credit_review)
graph.add_node("income_review", income_review)
graph.add_node("approve", approve)
graph.add_node("partial_approve", partial_approve)
graph.add_node("manual_review", manual_review)

graph.add_edge(START, "check")
graph.add_conditional_edges("check", route_initial, {
    "auto_reject": "auto_reject", "credit_review": "credit_review", "income_review": "income_review"
})
graph.add_conditional_edges("credit_review", route_credit, {
    "income_review": "income_review", "manual_review": "manual_review"
})
graph.add_conditional_edges("income_review", route_income, {
    "approve": "approve", "partial_approve": "partial_approve", "manual_review": "manual_review"
})
for n in ["auto_reject", "approve", "partial_approve", "manual_review"]:
    graph.add_edge(n, END)

loan_app = graph.compile()

cases = [
    {"applicant_name": "张三", "credit_score": 800, "income": 20000, "loan_amount": 500000, "has_collateral": True},
    {"applicant_name": "李四", "credit_score": 650, "income": 10000, "loan_amount": 200000, "has_collateral": True},
    {"applicant_name": "王五", "credit_score": 500, "income": 8000, "loan_amount": 100000, "has_collateral": False},
    {"applicant_name": "赵六", "credit_score": 720, "income": 15000, "loan_amount": 1000000, "has_collateral": False},
]

for case in cases:
    r = loan_app.invoke(case)
    print(f"\n{case['applicant_name']}: {r['decision']} → {r['reason']}")
```

决策树结构：`check → [auto_reject | credit_review → [income_review | manual_review] | income_review → [approve | partial_approve | manual_review]]`

---

## 核心要点

1. **路由函数**必须用 `Literal` 标注返回值，映射必须覆盖所有可能
2. **循环**通过 `add_conditional_edges("node", func, {"retry": "node"})` 实现
3. **多层路由**：多个 `add_conditional_edges` 形成决策树
4. 路由函数应是**纯函数**，无副作用

## FAQ

### Q1: 路由函数可以返回任意字符串吗？

不能。返回值必须是映射中定义的 key，否则 LangGraph 会报错。

### Q2: 条件边和普通边的性能差别？

无差别。条件边只是在运行时多了一次函数调用来决定下一步。

## 下一步

**19_image_input** —— 图像输入：视觉模型、Base64 编码、OCR、图表分析
