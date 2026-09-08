# 07 - Memory Basics：内存管理基础（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量（如 `model`），跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` / `test.py` 是等价的脚本版本，本手册不修改它们。
> - **本模块需要在线模型**：`create_agent` 依赖模型的 function calling 能力。Groq 的 Llama-3.3-70B 支持；离线 pipeline 方式加载的本地小模型不支持，无法运行本模块示例。概念可先阅读理解，代码需配置 `GROQ_API_KEY` 后运行。

## 学习目标

**内存 = Agent 记住对话历史的能力**

默认情况下每次 `agent.invoke()` 都是全新开始。本模块学习：

1. 用 `checkpointer=InMemorySaver()` 给 Agent 添加内存
2. 用 `thread_id` 区分不同会话
3. checkpointer 自动追加历史的原理
4. 内存 + 工具的组合行为

## 0. 准备工作

```bash
pip install -U langchain langchain-groq langgraph python-dotenv
```

把仓库根目录的 `.env.example` 复制为 `.env`，填入 `GROQ_API_KEY=gsk_xxx`。

---

## 单元格 1：初始化模型和工具（在线必需）

```python
import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langchain_core.tools import tool

load_dotenv()

model = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.7,
    max_tokens=300,
)


@tool
def search(query: str) -> str:
    """
    搜索资料并返回结果摘要

    参数:
        query: 搜索关键词
    """
    return f"[模拟] 关于'{query}'的搜索结果"


print("就绪")
```

---

## 单元格 2：反面教材——默认没有内存

```python
no_memory_agent = create_agent(model=model, tools=[])

r1 = no_memory_agent.invoke({
    "messages": [{"role": "user", "content": "我叫张三"}]
})
print("第 1 轮:", r1["messages"][-1].content)

r2 = no_memory_agent.invoke({
    "messages": [{"role": "user", "content": "我叫什么？"}]
})
print("第 2 轮:", r2["messages"][-1].content)   # AI 不知道！
```

原因与 03 模块相同：模型无状态，且这里连手动传历史都没有。

---

## 单元格 3：添加内存——checkpointer + thread_id

两步：创建时加 `checkpointer`，调用时传含 `thread_id` 的 `config`：

```python
from langgraph.checkpoint.memory import InMemorySaver

memory_agent = create_agent(
    model=model,
    tools=[],
    checkpointer=InMemorySaver(),      # 添加内存
)

config = {"configurable": {"thread_id": "conversation_1"}}

r1 = memory_agent.invoke({
    "messages": [{"role": "user", "content": "我叫张三"}]
}, config)
print("第 1 轮:", r1["messages"][-1].content)

r2 = memory_agent.invoke({
    "messages": [{"role": "user", "content": "我叫什么？"}]
}, config)
print("第 2 轮:", r2["messages"][-1].content)   # 记得！
```

注意：现在每次只传**新消息**，不用再手动拼完整历史——checkpointer 代劳了。

---

## 单元格 4：自动追加历史的原理

查看同一个 thread 下的历史是如何增长的：

```python
resp = memory_agent.invoke({
    "messages": [{"role": "user", "content": "我住在杭州"}]
}, config)

print("当前历史条数:", len(resp["messages"]))
for msg in resp["messages"]:
    print(f"[{msg.__class__.__name__}] {msg.content[:40]}")
```

checkpointer 每次调用自动做四件事：

```
1. 按 thread_id 读取之前的历史
2. 追加本次新消息
3. 把完整历史传给模型
4. 保存更新后的历史
```

---

## 单元格 5：多会话隔离

不同 `thread_id` 之间完全独立：

```python
config_alice = {"configurable": {"thread_id": "user_alice"}}
config_bob = {"configurable": {"thread_id": "user_bob"}}

memory_agent.invoke({
    "messages": [{"role": "user", "content": "我叫 Alice"}]
}, config_alice)

memory_agent.invoke({
    "messages": [{"role": "user", "content": "我叫 Bob"}]
}, config_bob)

ra = memory_agent.invoke({
    "messages": [{"role": "user", "content": "我叫什么？"}]
}, config_alice)
rb = memory_agent.invoke({
    "messages": [{"role": "user", "content": "我叫什么？"}]
}, config_bob)

print("Alice 会话:", ra["messages"][-1].content)
print("Bob 会话:", rb["messages"][-1].content)
```

thread_id 选择建议：聊天应用用用户 ID / 会话 ID；多轮任务用任务 ID。

---

## 单元格 6：内存 + 工具

内存也会记住工具调用的结果：

```python
tool_agent = create_agent(
    model=model,
    tools=[search],
    checkpointer=InMemorySaver(),
)

cfg = {"configurable": {"thread_id": "session_1"}}

# 第一轮：使用工具
tool_agent.invoke({
    "messages": [{"role": "user", "content": "帮我搜索 LangChain"}]
}, cfg)

# 第二轮：引用之前的结果，无需重新搜索
resp = tool_agent.invoke({
    "messages": [{"role": "user", "content": "刚才搜索的结果是什么？"}]
}, cfg)
print(resp["messages"][-1].content)
```

---

## 单元格 7：实际应用模板

把上面的模式封装成通用函数：

```python
def handle_user_message(agent, session_id: str, message: str) -> str:
    config = {"configurable": {"thread_id": session_id}}
    response = agent.invoke(
        {"messages": [{"role": "user", "content": message}]},
        config,
    )
    return response["messages"][-1].content


print(handle_user_message(memory_agent, "user_alice", "我用什么语言学习编程比较好？"))
print(handle_user_message(memory_agent, "user_alice", "再重复一遍你刚才的建议"))
```

---

## FAQ

### Q1: Agent 就是不记得，怎么排查？

三个条件缺一不可：

- 创建时加了 `checkpointer=InMemorySaver()`
- 每次 `invoke` 都传了 `config`
- 两次调用的 `thread_id` 完全相同

### Q2: InMemorySaver 会丢数据吗？

会。它只存在进程内存里：同一进程内有效；内核重启、程序退出即丢失；
跨进程无法共享。生产环境用 SQLite 持久化（下一模块）。

### Q3: 内存会无限增长吗？

会。消息越积越多，最终超过模型 token 上限、成本上升。
解决方案见下一模块 08_context_management（修剪、摘要）。

### Q4: 如何清空某个会话？

换一个新的 `thread_id` 即等效于开新会话；或重建 Agent。

## 核心要点

1. 默认无内存：每次 `invoke` 是全新开始
2. 添加内存：`checkpointer=InMemorySaver()`
3. 会话管理：`config={"configurable": {"thread_id": "xxx"}}`
4. 只传新消息即可，历史由 checkpointer 自动维护
5. 不同 thread_id = 不同会话，完全隔离
6. 工具调用结果也会被记住

## 下一步

**08_context_management** —— 历史太长怎么办：修剪与自动摘要
