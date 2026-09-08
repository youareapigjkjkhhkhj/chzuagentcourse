# 01 - Hello LangChain：第一个 LLM 调用（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量（如 `model`），跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` 是等价的脚本版本，本手册不修改它，两者内容互相对应（见文末对照表）。
> - **在线 / 离线二选一**：单元格 1 分为在线版（1A）和离线版（1B），按自己的环境运行其中一个即可。两者定义出的 `model` 用法完全相同，后续所有单元格不用做任何改动。

## 学习目标

1. `init_chat_model` —— 统一的模型初始化接口
2. `invoke` —— 三种输入格式与返回值结构
3. Messages —— SystemMessage / HumanMessage / AIMessage
4. 模型参数 —— temperature、max_tokens
5. 同一套代码在在线 API 和本地模型之间无缝切换

## 两种运行方案对比（二选一即可）

| | 在线方案（Groq API） | 离线方案（本地 Qwen2.5-0.5B） |
|---|---|---|
| 联网需求 | 调用时需要联网 | 仅首次下载模型时需要 |
| 费用 | 免费（有速率限制） | 完全免费 |
| 模型效果 | Llama 3.3 70B，效果好 | 0.5B 小模型，够用于学语法 |
| 速度 | 很快 | CPU 上较慢（每次回复数秒到数十秒） |
| 额外安装 | `langchain-groq` | `torch`、`transformers` 等 |

---

## 0. 准备工作

### 0.1 安装依赖

```bash
# 在线方案
pip install -U langchain langchain-groq python-dotenv

# 离线方案（额外需要）
pip install -U torch transformers accelerate langchain-huggingface
```

### 0.2 配置 API Key（仅在线方案需要）

把仓库根目录的 `.env.example` 复制一份，重命名为 `.env`，填入你的真实 Key：

```bash
GROQ_API_KEY=gsk_xxxxxxxxxxxx
```

获取地址：<https://console.groq.com/keys>（免费，无需信用卡）。

> 没有 Key？直接跳过这一步，走离线方案即可。
> 使用 NextChat / OneAPI 等中转服务的，见文末「使用自定义端点」。

---

## 单元格 1：初始化模型（在线版 / 离线版 二选一）

**这是整个 Notebook 的地基，必须最先运行。** 下面两个版本任选其一运行即可，它们定义出的 `model` 对象用法完全相同。

### 单元格 1A：在线版（Groq + Llama 3.3 70B）

```python
import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()  # 读取仓库根目录的 .env 文件

model = init_chat_model(
    "groq:llama-3.3-70b-versatile",       # 格式："提供商:模型名"
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.7,
    max_tokens=200,
)

print("模型就绪：Groq llama-3.3-70b-versatile")
```

`init_chat_model` 常用参数：

| 参数 | 说明 |
|------|------|
| `"provider:model_name"` | 必需。如 `"groq:llama-3.3-70b-versatile"`、`"openai:gpt-4o-mini"` |
| `api_key` | 不传时会自动读取环境变量（如 `GROQ_API_KEY`） |
| `temperature` | 0.0（确定）~ 2.0（随机），默认 1.0 |
| `max_tokens` | 限制输出长度 |

### 单元格 1B：离线版（本地 Qwen2.5-0.5B，同 本地示例.txt）

```python
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
from langchain_huggingface import ChatHuggingFace, HuggingFacePipeline

model_id = "Qwen/Qwen2.5-0.5B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(model_id)
hf_model = AutoModelForCausalLM.from_pretrained(
    model_id,
    torch_dtype=torch.float32,   # CPU 用 float32；有 GPU 可改 bfloat16
    device_map="cpu",            # 有 GPU 改成 "auto"
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

# 包装成 LangChain 聊天模型，之后用法与在线 model 完全相同
model = ChatHuggingFace(llm=HuggingFacePipeline(pipeline=pipe))

print("模型就绪：Qwen2.5-0.5B-Instruct（本地）")

model = init_chat_model(
    "ollama:qwen3:8b",   # 格式 ollama:<你的ollama模型名>，例如 llama3.1:8b、qwen2.5:7b
    base_url="http://localhost:11434",
    api_key="dummy",     # ollama不需要key，必须传一个占位字符串，不能None
    temperature=0.7,
    max_tokens=200,
)
```

**要点：**
- 无论选哪个版本，得到的都是一个带 `.invoke()` 方法的 `model` 对象——这正是 LangChain 统一接口的价值。
- 离线首次运行会把约 1GB 的模型下载到本地缓存 `~/.cache/huggingface`（这一步需要联网），之后不再联网。
- 想换离线模型：修改 `model_id`（如 `"Qwen/Qwen2.5-1.5B-Instruct"`，约 3GB，效果更好），重新运行本单元格即可。

---

## 单元格 2：字符串输入——最简单的调用

`invoke` 共支持 3 种输入格式，第 1 种是纯字符串：

```python
response = model.invoke("什么是机器学习？用一句话解释")

print(type(response).__name__)   # AIMessage
print(response.content)          # 回复文本
```

| 优点 | 缺点 |
|------|------|
| 一行搞定，适合快速测试 | 无法设置系统提示，无法携带对话历史 |

---

## 单元格 3：字典列表输入（推荐）

三种角色的分工：

| role | 作用 | 示例 |
|------|------|------|
| `system` | 设定 AI 的行为和规则 | "你是一个专业的 Python 导师" |
| `user` | 用户输入 | "什么是装饰器？" |
| `assistant` | AI 的历史回复（多轮对话用） | "装饰器是一种设计模式..." |

```python
messages = [
    {"role": "system", "content": "你是一个简洁的 Python 导师，回答不超过 100 字。"},
    {"role": "user", "content": "什么是 Python 列表推导式？"},
]

response = model.invoke(messages)
print(response.content)
```

### 核心规则：多轮对话必须传入完整历史！

模型本身**没有记忆**。想让第二轮对话记得第一轮，就必须把之前的所有消息一起传入：

```python
# 把上一轮的回复追加进历史，再提出新问题
messages.append({"role": "assistant", "content": response.content})
messages.append({"role": "user", "content": "给我一个简单的代码例子"})

response2 = model.invoke(messages)   # 注意：重新传入整个 messages
print(response2.content)
```

> 常见错误：`model.invoke("我刚才问了什么？")` —— 不带历史，AI 必然"失忆"。

---

## 单元格 4：消息对象写法

字典格式的"类型安全版"，两者可以混用：

| 消息类 | 等价的字典写法 |
|--------|----------------|
| `SystemMessage` | `{"role": "system", ...}` |
| `HumanMessage` | `{"role": "user", ...}` |
| `AIMessage` | `{"role": "assistant", ...}` |

```python
from langchain_core.messages import SystemMessage, HumanMessage

msgs = [
    SystemMessage(content="你是一个数学老师"),
    HumanMessage(content="什么是斐波那契数列？"),
]

resp = model.invoke(msgs)
print(resp.content)

# 追加历史时，AIMessage 对象可以直接放回列表
msgs.append(resp)
msgs.append(HumanMessage(content="前 10 项是什么？"))

print(model.invoke(msgs).content)
```

什么时候用哪种？

- 字典格式：简洁、易序列化成 JSON，日常首选
- 消息对象：IDE 补全友好、类型明确，大型项目使用

---

## 单元格 5：输出随机性实验

同一个问题问两次，观察两次输出是否一样：

```python
question = "写一句关于春天的句子"

for i in range(2):
    print(f"第{i+1}次:", model.invoke(question).content)
```

因为单元格 1 中 `temperature=0.7`（采样生成），两次结果通常不一样。

temperature 控制输出随机性：`0.0` 最确定，`2.0` 最随机。想直观对比不同温度的效果（在线用户直接运行）：

```python
model_precise = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"), temperature=0.0, max_tokens=100,
)
model_creative = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"), temperature=1.5, max_tokens=100,
)

for name, m in [("temperature=0.0", model_precise),
                ("temperature=1.5", model_creative)]:
    print(f"\n----- {name} -----")
    for i in range(2):
        print(f"第{i+1}次:", m.invoke(question).content)
```

> 离线用户请跳过上面这段：离线温度在单元格 1B 的 `pipeline(temperature=...)` 中设置，
> 改完后重新运行单元格 1B 即可（不必加载多份模型占内存）。

经验取值：

- `0.0 - 0.3`：数据提取、分类、代码生成（要稳定）
- `0.5 - 0.7`：日常聊天、问答（要平衡）
- `0.8 - 1.5`：写作、头脑风暴（要创意）

---

## 单元格 6：解析返回值 AIMessage

```python
response = model.invoke("用一句话解释什么是递归")

print("内容     :", response.content)
print("消息类型 :", type(response).__name__)
print("消息 ID  :", response.id)

# Token 用量（不同后端的字段位置略有差异，这里做兼容处理）
usage = getattr(response, "usage_metadata", None)           # 新版统一字段
if not usage:
    usage = response.response_metadata.get("token_usage")   # Groq/OpenAI 风格
print("Token 用量:", usage)
```

在线（Groq）模式的典型元数据结构：

```python
{
    'model_name': 'llama-3.3-70b-versatile',
    'finish_reason': 'stop',      # stop=正常结束, length=达到 max_tokens 被截断
    'model_provider': 'groq',
    'token_usage': {
        'prompt_tokens': ...,     # 输入消耗
        'completion_tokens': ..., # 输出消耗
        'total_tokens': ...
    }
}
```

---

## 单元格 7：错误处理

```python
try:
    resp = model.invoke("Hello!")
    print(resp.content)
except ValueError as e:
    print(f"配置错误（如缺少 API Key）: {e}")
except ConnectionError as e:
    print(f"网络错误: {e}")
except Exception as e:
    print(f"{type(e).__name__}: {e}")
```

离线模式常见问题：

- 首次运行卡住 / 下载失败 → 需要联网下载模型，检查网络后重跑单元格 1B
- 内存不足（OOM）→ 换更小的模型，见下一格

---

## 单元格 8（可选）：切换模型对比

```python
# 在线：只改字符串就能换厂商/模型
for name in ["groq:llama-3.3-70b-versatile", "groq:gemma2-9b-it"]:
    try:
        m = init_chat_model(name, api_key=os.getenv("GROQ_API_KEY"))
        print(f"\n[{name}]")
        print(m.invoke("用一句话解释什么是机器学习").content)
    except Exception as e:
        print(f"{name} 调用失败: {e}")
```

> 离线用户请跳过本单元格：换模型的方法是修改单元格 1B 的 `model_id` 后重新运行（见该节要点）。

---

## 使用自定义端点（OpenAI 兼容代理，可选）

如果你用的是 NextChat / OneAPI / 各类中转站等 OpenAI 兼容服务，先在 `.env` 中添加：

```bash
NEXTCHAT_API_KEY=sk-xxx
NEXTCHAT_API_BASE=https://xxx/v1
```

然后用下面的代码替换单元格 1A 即可：

```python
from langchain_openai import ChatOpenAI

model = ChatOpenAI(
    model="kimi-k2-turbo-preview",              # 服务商提供的模型名
    api_key=os.getenv("NEXTCHAT_API_KEY"),
    base_url=os.getenv("NEXTCHAT_API_BASE"),
    temperature=0.7,
    max_tokens=200,
)
```

其余单元格不用做任何改动。

---

## FAQ

### Q1: `init_chat_model` 和 `ChatGroq` 有什么区别？

`init_chat_model` 是 LangChain 1.0 的统一入口，改字符串即可切换厂商；`ChatGroq`、`ChatOpenAI` 是具体厂商的实现类（离线包装、自定义 base_url 等场景仍会用到它们）。

```python
# 具体实现类（旧方式，仍然可用）
from langchain_groq import ChatGroq
model = ChatGroq(model="llama-3.3-70b-versatile")

# 统一接口（推荐）
from langchain.chat_models import init_chat_model
model = init_chat_model("groq:llama-3.3-70b-versatile")
```

### Q2: 为什么对话"没有记忆"？

模型是无状态的。多轮对话必须把完整历史传入 `invoke`，参见单元格 3。

### Q3: `invoke` 和 `stream` 的区别？

`invoke` 等待完整结果；`stream` 逐段实时返回：

```python
for chunk in model.stream("写一首关于编程的五言绝句"):
    print(chunk.content, end="", flush=True)
```

### Q4: Jupyter 里运行顺序乱了 / 报 NameError 怎么办？

菜单 Kernel → Restart Kernel，然后从单元格 1 开始按顺序重跑。

### Q5: 离线模型答非所问、质量差？

0.5B 小模型能力有限，属正常现象。本模块的目标是掌握**调用语法**，不是追求模型效果；想要高质量回复请配置 `GROQ_API_KEY` 使用在线方案。

---

## 手册与 main.py 对照表

| 手册单元格 | main.py 中的示例 |
|------------|------------------|
| 单元格 1A / 1B | 环境配置部分 |
| 单元格 2 | `example_1_simple_invoke` |
| 单元格 3 | `example_3_dict_messages` |
| 单元格 4 | `example_2_messages` |
| 单元格 5 | `example_4_model_parameters` |
| 单元格 6 | `example_5_response_structure` |
| 单元格 7 | `example_6_error_handling` |
| 单元格 8 | `example_8_multiple_models` |

## 下一步学习

1. **02_prompt_templates** —— 提示词模板，告别手工拼字符串
2. **03_messages** —— 深入理解消息类型与对话管理
3. **04_custom_tools** —— 创建自定义工具
4. **05_simple_agent** —— 用 `create_agent` 构建第一个 Agent

## 小结

完成本模块后，你应该能够：

- 用 `init_chat_model`（在线）或 `ChatHuggingFace`（离线）得到统一的 `model` 对象
- 用 `invoke` 以三种格式调用模型：字符串 / 字典列表 / 消息对象
- 记住核心规则：多轮对话必须传入完整历史
- 通过 temperature 控制输出的确定性与创造性
- 解析 `AIMessage` 的 content 与 token 用量
- 在线 / 离线两套环境共用同一份业务代码

**恭喜迈出 LangChain 1.0 学习的第一步！**
