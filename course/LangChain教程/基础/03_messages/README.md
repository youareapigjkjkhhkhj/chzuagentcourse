# 03 - Messages：消息类型与对话管理（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量（如 `model`、`conversation`），跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` / `test.py` 是等价的脚本版本，本手册不修改它们。
> - **在线 / 离线二选一**：单元格 1 分为在线版（1A）和离线版（1B），运行其中一个即可。两者定义出的 `model` 用法完全相同，后续所有单元格不用做任何改动。

## 学习目标

本模块只讲一个核心难点：**模型没有记忆，多轮对话必须每次传入完整历史。**

1. 三种消息类型与推荐写法
2. 对话历史的正确管理方式
3. 常见错误模式（失忆的原因）
4. 历史过长时的裁剪优化

## 0. 准备工作

```bash
# 在线方案
pip install -U langchain langchain-groq python-dotenv

# 离线方案（额外需要）
pip install -U torch transformers accelerate langchain-huggingface
```

在线用户：把仓库根目录的 `.env.example` 复制为 `.env`，填入 `GROQ_API_KEY=gsk_xxx`。

---

## 单元格 1：初始化模型（在线版 / 离线版 二选一）

**必须最先运行。** 下面两个版本任选其一，定义出的 `model` 用法完全相同。

### 单元格 1A：在线版

```python
import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()

model = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.7,
    max_tokens=200,
)

print("模型就绪：Groq llama-3.3-70b-versatile")
```

### 单元格 1B：离线版

```python
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
from langchain_huggingface import ChatHuggingFace, HuggingFacePipeline

model_id = "Qwen/Qwen2.5-0.5B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(model_id)
hf_model = AutoModelForCausalLM.from_pretrained(
    model_id,
    torch_dtype=torch.float32,
    device_map="cpu",
)
pipe = pipeline(
    "text-generation",
    model=hf_model,
    tokenizer=tokenizer,
    max_new_tokens=128,
    do_sample=True,
    temperature=0.7,
    top_p=0.8,
)

model = ChatHuggingFace(llm=HuggingFacePipeline(pipeline=pipe))

print("模型就绪：Qwen2.5-0.5B-Instruct（本地）")
```

> 离线首次运行会下载约 1GB 模型到 `~/.cache/huggingface`（需联网），之后不再联网。

---

## 单元格 2：三种消息类型

| 角色 | 字典格式 | 对象格式 | 用途 |
|------|---------|---------|------|
| System | `{"role": "system", ...}` | `SystemMessage(...)` | 系统提示 |
| User | `{"role": "user", ...}` | `HumanMessage(...)` | 用户输入 |
| Assistant | `{"role": "assistant", ...}` | `AIMessage(...)` | AI 回复 |

**推荐直接用字典**，简洁且与 OpenAI 格式一致：

```python
messages = [
    {"role": "system", "content": "你是一个简洁的助手，回答不超过 50 字。"},
    {"role": "user", "content": "你好"},
]

response = model.invoke(messages)
print(response.content)
```

---

## 单元格 3：反面教材——不带历史，AI 必然"失忆"

两次**互相独立**的调用，第二次不带任何历史：

```python
r1 = model.invoke("我叫张三")
print("第 1 次:", r1.content)

r2 = model.invoke("我叫什么？")   # 没传历史！
print("第 2 次:", r2.content)     # AI 不知道，因为它只看到当前这一句
```

原因：模型是无状态的。每次 `invoke` 它只能看到你这次传入的内容，
上一次对话对它来说根本不存在。

---

## 单元格 4：正确做法——完整历史 + 保存 AI 回复

三个动作缺一不可：

1. 用户消息加入历史
2. 调用后**把 AI 回复也存回历史**
3. 下次调用传入整个列表

```python
conversation = []

# 第 1 轮
conversation.append({"role": "user", "content": "我叫张三"})
r1 = model.invoke(conversation)
conversation.append({"role": "assistant", "content": r1.content})   # 关键！

# 第 2 轮：带上完整历史
conversation.append({"role": "user", "content": "我叫什么？"})
r2 = model.invoke(conversation)
print(r2.content)   # AI 记得！
```

---

## 单元格 5：查看历史结构

历史就是一个不断增长的列表：

```python
for i, msg in enumerate(conversation):
    print(f"{i}: [{msg['role']}] {msg['content'][:40]}")
```

对话增长规律：

```
第 1 轮：[system?, user] → 保存回复
第 2 轮：[system?, user, assistant, user] → 保存回复
第 3 轮：[system?, user, assistant, user, assistant, user] → ...
每次都传递所有历史！
```

---

## 单元格 6：历史太长怎么办——只保留最近 N 轮

历史越长，token 消耗越大。优化策略：**总是保留 system，只保留最近 N 轮对话**。

先定义工具函数（用假数据测试，不消耗 token）：

```python
def keep_recent_messages(messages, max_pairs=3):
    """
    保留 system 消息 + 最近 N 轮对话（每轮 = user + assistant）
    """
    system_msgs = [m for m in messages if m.get("role") == "system"]
    conversation = [m for m in messages if m.get("role") != "system"]

    recent = conversation[-(max_pairs * 2):]
    return system_msgs + recent


fake_history = [{"role": "system", "content": "你是助手"}]
for i in range(10):
    fake_history.append({"role": "user", "content": f"问题{i}"})
    fake_history.append({"role": "assistant", "content": f"回答{i}"})

trimmed = keep_recent_messages(fake_history, max_pairs=2)
for msg in trimmed:
    print(f"[{msg['role']}] {msg['content']}")
# 只有 system + 最后两轮被保留
```

真实对话中的用法：

```python
optimized = keep_recent_messages(conversation, max_pairs=5)
response = model.invoke(optimized)
print(response.content)
```

---

## 单元格 7：综合练习——三轮对话测记忆

```python
chat = [
    {"role": "system", "content": "你是 Python 导师"},
]

# 第 1 轮
chat.append({"role": "user", "content": "什么是列表？"})
r1 = model.invoke(chat)
chat.append({"role": "assistant", "content": r1.content})
print("AI:", r1.content[:80], "...")

# 第 2 轮（基于上文追问）
chat.append({"role": "user", "content": "它和元组有什么区别？"})
r2 = model.invoke(chat)
chat.append({"role": "assistant", "content": r2.content})
print("AI:", r2.content[:80], "...")

# 第 3 轮（测试记忆）
chat.append({"role": "user", "content": "我第一个问题问的是什么？"})
r3 = model.invoke(chat)
print("AI:", r3.content)   # 应能答出"什么是列表"
```

---

## 常见错误清单

错误 1：忘记保存 AI 回复——下一轮历史里缺了 assistant 消息，AI 看不到自己说过什么。

```python
conversation.append({"role": "user", "content": "问题1"})
r1 = model.invoke(conversation)
# ❌ 少了 conversation.append({"role": "assistant", "content": r1.content})
```

错误 2：每轮重新创建列表——历史直接丢失。

```python
conversation = [{"role": "user", "content": "问题2"}]   # ❌ 上一轮全丢了
```

---

## FAQ

### Q1: 用字典还是消息对象？

日常用字典（简洁、易存 JSON）。需要 IDE 类型提示时用对象；两者可混用。

### Q2: system 消息要重复加吗？

不用。它放在列表开头一次即可，每轮调用时随完整历史一起传入。

### Q3: 为什么不能只传最近一句？

模型无状态。只传最近一句等于每次都开新对话，之前的所有信息全部丢失。

---

## 手册与 main.py 对照表

| 手册单元格 | main.py 中的内容 |
|------------|------------------|
| 单元格 1A / 1B | 环境配置部分 |
| 单元格 2 | 消息类型示例 |
| 单元格 3、4 | 失忆 vs 记住对比 |
| 单元格 6 | `keep_recent_messages` |
| 单元格 7 | 完整三轮对话 |

## 下一步学习

1. **04_custom_tools** —— 创建自定义工具
2. **05_simple_agent** —— 构建第一个 Agent
3. **07_memory_basics** —— 用框架自动管理历史（不必再手动 append）

## 小结

| 要点 | 说明 |
|------|------|
| 格式 | 推荐字典写法 |
| 历史 | 每次必须传递完整历史 |
| 保存 | 必须把 AI 回复存回历史 |
| 优化 | 只保留最近 N 轮，system 永远保留 |
