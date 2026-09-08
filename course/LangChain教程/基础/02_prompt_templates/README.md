# 02 - Prompt Templates：提示词模板（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量（如 `model`），跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` 是等价的脚本版本，本手册不修改它，两者内容互相对应（见文末对照表）。
> - **在线 / 离线二选一**：单元格 1 分为在线版（1A）和离线版（1B），运行其中一个即可。两者定义出的 `model` 用法完全相同，后续所有单元格不用做任何改动。

## 学习目标

1. 为什么需要提示词模板——字符串拼接的问题
2. `PromptTemplate` —— 简单文本模板
3. `ChatPromptTemplate` —— 聊天消息模板（推荐）
4. 部分变量（partial）、模板组合、可复用模板库
5. LCEL 链式调用预览：`chain = prompt | model`

## 0. 准备工作

```bash
# 在线方案
pip install -U langchain langchain-groq python-dotenv

# 离线方案（额外需要）
pip install -U torch transformers accelerate langchain-huggingface
```

在线用户：把仓库根目录的 `.env.example` 复制为 `.env`，填入 `GROQ_API_KEY=gsk_xxx`。
没有 Key 直接走离线方案。模型初始化的参数详解见 01 模块手册。

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

## 单元格 2：字符串拼接的问题 vs 模板

先看不推荐的做法：

```python
user_name = "张三"
topic = "Python"

prompt = f"你好 {user_name}，我来帮你学习 {topic}"
print(prompt)
```

f-string 的问题：模板和数据混在一起、难以复用、难以维护、容易拼错格式。

模板的做法——模板与数据分离：

```python
from langchain_core.prompts import PromptTemplate

template = PromptTemplate.from_template(
    "你好 {user_name}，我来帮你学习 {topic}"
)

print("自动识别的变量:", template.input_variables)

prompt = template.format(user_name="张三", topic="Python")
print(prompt)
```

模板的优势：可复用（一个模板多次填充）、可维护（改模板不用改逻辑）、可组合。

---

## 单元格 3：PromptTemplate 实战调用模型

```python
translator = PromptTemplate.from_template(
    "将以下{source_lang}文本翻译成{target_lang}，只输出译文：\n{text}"
)

prompt = translator.format(
    source_lang="英语",
    target_lang="中文",
    text="Hello, how are you?",
)
print(prompt)

response = model.invoke(prompt)   # 格式化结果就是字符串，直接 invoke
print(response.content)
```

两种取值方式：`format()` 返回字符串；`invoke()` 返回 PromptValue 对象：

```python
pv = translator.invoke({
    "source_lang": "英语",
    "target_lang": "中文",
    "text": "Good morning",
})

print(type(pv).__name__)   # StringPromptValue
print(pv.text)             # .text 拿到字符串
```

---

## 单元格 4：ChatPromptTemplate（推荐）

| 特性 | PromptTemplate | ChatPromptTemplate |
|------|----------------|--------------------|
| 输出格式 | 纯文本字符串 | 消息列表 |
| 角色支持 | 无 | system / user / assistant |
| 适用场景 | 简单提示 | 聊天、对话、多轮交互 |

元组格式 `(角色, 文本)` 是最常用的写法：

```python
from langchain_core.prompts import ChatPromptTemplate

chat_template = ChatPromptTemplate.from_messages([
    ("system", "你是一个友好的{role}，擅长{skill}"),
    ("user", "{question}"),
])

messages = chat_template.format_messages(
    role="编程导师",
    skill="用简单语言解释复杂概念",
    question="什么是递归？",
)

for msg in messages:
    print(f"[{msg.type}] {msg.content}")

response = model.invoke(messages)   # 消息列表直接传给模型
print(response.content)
```

同样支持 `invoke()` 方式，得到 ChatPromptValue，用 `.to_messages()` 转成消息列表：

```python
pv = chat_template.invoke({
    "role": "编程导师",
    "skill": "耐心",
    "question": "什么是循环？",
})
messages = pv.to_messages()
```

---

## 单元格 5：多轮对话模板

把历史对话也写进模板，一次性构造完整上下文：

```python
conversation_template = ChatPromptTemplate.from_messages([
    ("system", "你是一个{role}"),
    ("user", "{question1}"),
    ("assistant", "{answer1}"),
    ("user", "{question2}"),
])

messages = conversation_template.format_messages(
    role="Python 专家",
    question1="什么是列表？",
    answer1="列表是 Python 的有序可变集合。",
    question2="它和元组有什么区别？",   # 基于上文提问
)

response = model.invoke(messages)
print(response.content)
```

---

## 单元格 6：部分变量（partial）

固定不变的变量预先填充，只留每次变化的部分：

```python
translator = ChatPromptTemplate.from_messages([
    ("system", "你是专业翻译，精通{source}和{target}"),
    ("user", "翻译：{text}"),
])

en_to_zh = translator.partial(source="英语", target="中文")
zh_to_en = translator.partial(source="中文", target="英语")

print("en_to_zh 剩余变量:", en_to_zh.input_variables)

resp = model.invoke(en_to_zh.format_messages(text="Knowledge is power."))
print(resp.content)
```

适用场景：某些变量在所有调用中都相同（部门名、语言方向、输出风格等）。

---

## 单元格 7：模板组合

方式 1：字符串拼接公共片段：

```python
role_part = "你是一个{domain}专家。"
style_part = "回答风格：{style}。"
constraint_part = "限制：{constraint}字以内。"

structured = ChatPromptTemplate.from_messages([
    ("system", role_part + style_part + constraint_part),
    ("user", "{question}"),
])

resp = model.invoke(structured.format_messages(
    domain="机器学习", style="技术性强、简洁", constraint="100",
    question="什么是梯度下降？",
))
print(resp.content)
```

方式 2：`+` 运算符组合两个模板：

```python
t1 = ChatPromptTemplate.from_messages([("system", "你是助手")])
t2 = ChatPromptTemplate.from_messages([("user", "{input}")])

combined = t1 + t2
print(combined.format_messages(input="你好"))
```

---

## 单元格 8：可复用模板库

项目里建议把常用模板集中管理：

```python
class PromptLibrary:
    """可复用的提示词模板库"""

    TRANSLATOR = ChatPromptTemplate.from_messages([
        ("system", "你是专业翻译，精通{source_lang}和{target_lang}"),
        ("user", "翻译以下文本：\n{text}"),
    ])

    SUMMARIZER = ChatPromptTemplate.from_messages([
        ("system", "你是内容摘要专家"),
        ("user", "将以下内容总结为{num}个要点：\n{content}"),
    ])

    TUTOR = ChatPromptTemplate.from_messages([
        ("system", "你是{subject}导师，学生水平：{level}"),
        ("user", "{question}"),
    ])

resp = model.invoke(PromptLibrary.TUTOR.format_messages(
    subject="Python", level="零基础", question="什么是变量？",
))
print(resp.content)
```

---

## 单元格 9：LCEL 链式调用预览

用管道符 `|` 把"模板 → 模型"串成链，之后直接对链 invoke，不再手动 format：

```python
prompt = ChatPromptTemplate.from_messages([
    ("system", "你是{role}"),
    ("user", "{input}"),
])

chain = prompt | model          # 数据流向：输入 → prompt → model → 输出

response = chain.invoke({
    "role": "Python 导师",
    "input": "什么是装饰器？",
})

print(response.content)
```

链的优势：简洁（一行完成多步）、可读（清晰的数据流）、可组合（继续接输出解析器等组件）。后续模块会大量使用。

---

## FAQ

### Q1: PromptTemplate 和 ChatPromptTemplate 怎么选？

简单单次提示用 `PromptTemplate`；涉及 system 角色、多轮对话一律用 `ChatPromptTemplate`（推荐默认）。

### Q2: 模板里怎么写多行长文本？

用三引号字符串，`{variable}` 占位符照常使用：

```python
template = PromptTemplate.from_template("""
你是一个{role}。

请完成以下任务：
1. {task1}
2. {task2}
""")
```

### Q3: 变量可以传数字吗？

可以，非字符串会被自动转成字符串：`template.format(count=5)`。

### Q4: 忘记传某个变量会怎样？

抛出错误提示缺少变量。可用 `partial()` 预填或检查 `input_variables` 排查。

---

## 手册与 main.py 对照表

| 手册单元格 | main.py 中的示例 |
|------------|------------------|
| 单元格 1A / 1B | 环境配置部分 |
| 单元格 2 | 示例 1（为什么需要模板） |
| 单元格 3 | 示例 2（PromptTemplate） |
| 单元格 4 | 示例 3（ChatPromptTemplate） |
| 单元格 5 | 示例 4（多轮对话模板） |
| 单元格 6 | 示例 6（部分变量） |
| 单元格 7 | 示例 7（模板组合） |
| 单元格 8 | 示例 8（模板库） |
| 单元格 9 | 示例 9（LCEL 链式调用） |

## 下一步学习

1. **03_messages** —— 深入理解消息类型和对话管理
2. **04_custom_tools** —— 创建自定义工具
3. **05_simple_agent** —— 使用 `create_agent` 构建第一个 Agent

## 小结

完成本模块后，你应该能够：

- 说明模板相比 f-string 拼接的优势
- 用 `PromptTemplate` / `ChatPromptTemplate` 创建并复用模板
- 用 `partial()` 预填固定变量
- 组合模板片段、搭建自己的模板库
- 用 `|` 把模板和模型串成 LCEL 链
