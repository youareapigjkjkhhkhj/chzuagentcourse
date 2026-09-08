# 10 - Middleware Basics：中间件基础（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量（如 `model`），跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` / `test.py` 是等价的脚本版本，本手册不修改它们。
> - **在线 / 离线说明**：中间件类本身是纯 Python 定义；但【单元格 2】起的运行示例需要创建 Agent 并调用模型（function calling），因此需在线模型。

## 学习目标

**Middleware（中间件）= Agent 执行过程中的钩子函数**

1. 编写自定义中间件：`before_model` / `after_model`
2. 理解三种返回值：None / dict / jump_to
3. 多个中间件的执行顺序（洋葱模型）
4. 了解内置中间件

## 0. 准备工作

```bash
pip install -U langchain langchain-groq langgraph python-dotenv
```

把仓库根目录的 `.env.example` 复制为 `.env`，填入 `GROQ_API_KEY=gsk_xxx`。

---

## 单元格 1：初始化模型（在线必需）

```python
import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langgraph.checkpoint.memory import InMemorySaver

load_dotenv()

model = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.7,
    max_tokens=200,
)

print("就绪")
```

---

## 单元格 2：第一个中间件——日志

继承 `AgentMiddleware`，实现钩子方法：

```python
class LoggingMiddleware(AgentMiddleware):
    def before_model(self, state, runtime):
        """模型调用前执行"""
        print(f"[before] 当前消息数: {len(state.get('messages', []))}")
        return None   # 不修改状态，继续正常流程

    def after_model(self, state, runtime):
        """模型响应后执行"""
        last = state.get('messages', [])[-1]
        print(f"[after] 响应类型: {last.__class__.__name__}")
        return None


log_agent = create_agent(
    model=model,
    tools=[],
    middleware=[LoggingMiddleware()],
)

log_agent.invoke({"messages": [{"role": "user", "content": "你好"}]})
# 运行时能看到 [before]/[after] 日志穿插在对话中
```

---

## 单元格 3：返回值的三种用法

| 返回值 | 效果 |
|-------|------|
| `None` | 不修改状态，继续正常流程 |
| `dict` | 更新状态（如 `{"messages": [...]}` 或自定义字段） |
| `{"jump_to": "..."}` | 控制流程跳转（`"__end__"` 结束 / `"tools"` 跳到工具节点） |

计数中间件——通过返回 dict 更新自定义状态：

```python
class CallCounterMiddleware(AgentMiddleware):
    def after_model(self, state, runtime):
        count = state.get("model_call_count", 0)
        print(f"[计数] 第 {count + 1} 次模型调用")
        return {"model_call_count": count + 1}


counter_agent = create_agent(
    model=model,
    tools=[],
    middleware=[CallCounterMiddleware()],
    checkpointer=InMemorySaver(),   # 自定义状态字段需要 checkpointer 保存
)

cfg = {"configurable": {"thread_id": "counter_demo"}}
counter_agent.invoke({"messages": [{"role": "user", "content": "问题一"}]}, cfg)
counter_agent.invoke({"messages": [{"role": "user", "content": "问题二"}]}, cfg)
```

限流中间件——通过 jump_to 控制流程：

```python
class MaxCallsMiddleware(AgentMiddleware):
    def __init__(self, max_calls=3):
        super().__init__()
        self.max_calls = max_calls

    def before_model(self, state, runtime):
        if state.get("call_count", 0) >= self.max_calls:
            return {"jump_to": "__end__"}   # 达到上限，跳过模型直接结束
        return None

    def after_model(self, state, runtime):
        return {"call_count": state.get("call_count", 0) + 1}
```

---

## 单元格 4：消息修剪中间件

把 08 模块的修剪逻辑做成通用中间件：

```python
class MessageTrimmerMiddleware(AgentMiddleware):
    def __init__(self, max_messages=6):
        super().__init__()
        self.max_messages = max_messages

    def before_model(self, state, runtime):
        messages = state.get('messages', [])
        if len(messages) > self.max_messages:
            return {"messages": messages[-self.max_messages:]}
        return None


trim_agent = create_agent(
    model=model,
    tools=[],
    middleware=[MessageTrimmerMiddleware(max_messages=6)],
    checkpointer=InMemorySaver(),
)

cfg = {"configurable": {"thread_id": "trim_demo"}}
for q in ["问题1", "问题2", "问题3", "问题4"]:
    r = trim_agent.invoke({"messages": [{"role": "user", "content": q}]}, cfg)
    print(f"{q} -> 传给模型前消息数被限制在 {6 + 1} 条以内")
```

---

## 单元格 5：多中间件的执行顺序（洋葱模型）

```python
agent = create_agent(
    model=model,
    middleware=[M1(), M2(), M3()]   # 按列表顺序
)
```

```
1. M1.before_model   ↓ 正序
2. M2.before_model   ↓
3. M3.before_model   ↓

   [模型调用]

4. M3.after_model    ↑ 逆序
5. M2.after_model    ↑
6. M1.after_model    ↑
```

组合验证——日志和计数一起用：

```python
combo_agent = create_agent(
    model=model,
    tools=[],
    middleware=[LoggingMiddleware(), CallCounterMiddleware()],
    checkpointer=InMemorySaver(),
)

combo_agent.invoke({
    "messages": [{"role": "user", "content": "测试顺序"}]
}, {"configurable": {"thread_id": "order_demo"}})
```

顺序很重要：先修剪 → 再摘要 → 最后记日志是常见排列。

---

## 单元格 6：内置中间件一览

```python
from langchain.agents.middleware import SummarizationMiddleware

# 1. 自动摘要（08 模块已学）
SummarizationMiddleware(
    model="groq:llama-3.3-70b-versatile",
    max_tokens_before_summary=1000,
)
```

```python
from langchain.agents.middleware import HumanInTheLoopMiddleware

# 2. 人工审核：调用指定工具前暂停等待人工确认
HumanInTheLoopMiddleware(interrupt_on={"send_email": True})
```

```python
from langchain.agents.middleware import PIIMiddleware

# 3. 敏感信息处理：邮箱脱敏、电话拦截
PIIMiddleware("email", strategy="redact")
PIIMiddleware("phone_number", strategy="block")
```

这些内置中间件按需加入 `middleware=[]` 列表即可。

---

## FAQ

### Q1: 中间件能拦截工具调用吗？

`before_model` / `after_model` 只在模型节点执行。要拦截工具调用需使用 `wrap_tool_call` 钩子（高级特性）。

### Q2: 修改状态为什么有时要 checkpointer？

返回 `{"messages": [...]}` 不需要（messages 自动管理）；返回自定义字段（如 `call_count`）需要 checkpointer 来保存。

### Q3: 能在中间件里调用另一个模型吗？

可以（如在 after_model 里做输出校验），注意会额外增加延迟和成本。

## 核心要点

1. 中间件 = Agent 生命周期钩子，继承 `AgentMiddleware`
2. `before_model` 正序执行；`after_model` 逆序执行（洋葱模型）
3. 三种返回值：None / dict（更新状态）/ `{"jump_to": ...}`（控制流程）
4. 自定义状态字段需要配合 checkpointer
5. 内置中间件：Summarization、HumanInTheLoop、PII

## 下一步

**11_structured_output** —— 用 Pydantic 让 LLM 输出结构化对象
