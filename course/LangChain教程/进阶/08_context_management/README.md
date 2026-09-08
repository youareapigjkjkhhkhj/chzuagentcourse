# 08 - Context Management：上下文管理（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量，跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` 是等价的脚本版本，本手册不修改它。
> - **在线 / 离线说明**：【单元格 4】的 `SummarizationMiddleware` 需要在线模型（Agent + function calling）；【单元格 3】的 `trim_messages` 是纯本地函数，用假消息演示，不消耗 token。

## 学习目标

**问题**：对话历史无限增长 → 超 token 上限、成本高、响应慢

1. 用 `trim_messages` 手动修剪历史
2. 用 `SummarizationMiddleware` 自动摘要旧消息（推荐）
3. 根据场景选择策略

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
from langgraph.checkpoint.memory import InMemorySaver

load_dotenv()

model = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.7,
    max_tokens=200,
)

base_agent = create_agent(
    model=model,
    tools=[],
    checkpointer=InMemorySaver(),
)

config = {"configurable": {"thread_id": "growth_demo"}}

print("就绪")
```

---

## 单元格 2：问题演示——历史无限增长

多轮对话后观察消息条数：

```python
questions = [
    "我叫张三",
    "我喜欢用 Python 写代码",
    "我在杭州工作",
    "最近在学 LangChain",
]

for q in questions:
    resp = base_agent.invoke(
        {"messages": [{"role": "user", "content": q}]},
        config,
    )
    print(f"提问: {q}  ->  历史条数: {len(resp['messages'])}")
```

条数只增不减。对话继续下去，迟早逼近模型上下文上限，
且每次调用都要为全部历史付费。

---

## 单元格 3：trim_messages——手动修剪（纯本地）

用假消息测试修剪逻辑，不消耗任何 token：

```python
from langchain_core.messages import HumanMessage, trim_messages

# 构造 20 条假消息
fake_history = [HumanMessage(content=f"消息 {i}") for i in range(20)]

trimmed = trim_messages(
    fake_history,
    max_tokens=5,          # 配合下面的计数器 = 最多保留 5 "条"
    strategy="last",       # 保留最后的
    token_counter=len,     # 用消息条数当计数器（演示用）
)

print(f"修剪前: {len(fake_history)} 条 -> 修剪后: {len(trimmed)} 条")
```

生产中通常换成真实的 token 计数器（如 `model.get_num_tokens_from_messages`）。
适用场景：只需要最近几轮、不在乎旧信息的简单应用。

---

## 单元格 4：SummarizationMiddleware——自动摘要（推荐，需在线）

超过阈值时自动把旧消息压缩成一段摘要，最近消息保持原样：

```python
from langchain.agents.middleware import SummarizationMiddleware

summary_agent = create_agent(
    model=model,
    tools=[],
    checkpointer=InMemorySaver(),
    middleware=[
        SummarizationMiddleware(
            model="groq:llama-3.3-70b-versatile",   # 生成摘要用的模型（可用更便宜的）
            max_tokens_before_summary=500,           # 历史超过 500 tokens 触发摘要
        )
    ],
)

config_s = {"configurable": {"thread_id": "summary_demo"}}

# 多聊几轮，历史变长后会自动触发摘要
for q in ["我叫张三", "我是Python工程师", "帮我记住：项目代号是凤凰"]:
    r = summary_agent.invoke(
        {"messages": [{"role": "user", "content": q}]},
        config_s,
    )
    print(f"提问: {q}")

r = summary_agent.invoke({
    "messages": [{"role": "user", "content": "我的名字和项目代号是什么？"}]
}, config_s)
print(r["messages"][-1].content)   # 摘要保留了关键信息
```

工作原理：

```
对话历史: [消息1, 消息2, ..., 消息20]   超过阈值
    ↓ 触发 SummarizationMiddleware
旧消息 → 摘要："用户叫张三，Python工程师，项目代号凤凰..."
新历史: [摘要, 最近几条消息]
```

| 参数 | 说明 | 默认值 |
|-----|------|--------|
| `model` | 生成摘要的模型（可用便宜模型） | 必需 |
| `max_tokens_before_summary` | 触发摘要的 token 阈值 | 1000 |

阈值选择经验：上下文窗口 4k 设 3000；8k 设 6000；16k 设 12000（留余量给系统提示和工具）。

---

## 单元格 5：策略对比与选型

| 策略 | 优点 | 缺点 | 适用 |
|-----|------|------|------|
| 不处理 | 完整历史 | 超 token、成本高 | 短对话 |
| **SummarizationMiddleware** | 自动化、保留关键信息 | 摘要有额外成本 | 长对话（推荐） |
| trim_messages | 简单、精确可控 | 丢失旧信息 | 只要最近 N 轮 |

场景配置参考：

```python
# 客服机器人：历史较长，阈值放宽
SummarizationMiddleware(model="groq:llama-3.3-70b-versatile",
                        max_tokens_before_summary=800)

# 监控建议：频繁触发摘要 -> 提高阈值；从不触发 -> 降低阈值
```

---

## FAQ

### Q1: 摘要会丢失信息吗？

会有细节损失，但姓名、关键事实等重要信息通常能保留，最近的消息完整不变，多数场景足够。

### Q2: 摘要成本高吗？

只在超过阈值时触发一次，且可用便宜模型做摘要；相比每轮都传全量历史，通常更省。

### Q3: 能自定义摘要提示词吗？

内置中间件用默认提示词。需要自定义时可以实现自己的中间件（下一模块学习）。

## 核心要点

1. 默认行为：对话历史无限增长
2. 推荐方案：`middleware=[SummarizationMiddleware(...)]`
3. 手动方案：`trim_messages(messages, max_tokens=..., strategy="last")`
4. 阈值按模型上下文窗口留余量设置

## 下一步

**09_checkpointing** —— 内存持久化到 SQLite，程序重启也不丢
