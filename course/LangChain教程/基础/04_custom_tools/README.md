# 04 - Custom Tools：自定义工具（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量（如 `model`、`get_weather`），跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` 和 `tools/` 目录是等价的脚本版本，本手册不修改它们（见文末对照表）。
> - **在线 / 离线说明**：
>   - 工具的**定义与直接调用是纯 Python 代码**，在线离线都能运行；
>   - 【单元格 7】"绑定到模型让 AI 自动选择工具"需要模型支持 **function calling**——本地 pipeline 方式加载的小模型不支持，该单元格需使用在线方案。

## 学习目标

1. `@tool` 装饰器 —— 把 Python 函数变成 AI 可用的工具
2. docstring、类型注解为什么重要
3. 单参数 / 多参数 / 可选参数工具
4. 直接调用工具 vs 绑定到模型

## 0. 准备工作

```bash
# 在线方案
pip install -U langchain langchain-groq python-dotenv

# 离线方案（额外需要，仅能运行到单元格 6）
pip install -U torch transformers accelerate langchain-huggingface
```

在线用户：把仓库根目录的 `.env.example` 复制为 `.env`，填入 `GROQ_API_KEY=gsk_xxx`。

---

## 单元格 1：初始化模型（在线版 / 离线版 二选一）

**必须最先运行。**

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

import os
from dotenv import load_dotenv 
from langchain.chat_models import init_chat_model
load_dotenv() 
model = init_chat_model(
    "ollama:orieg/gemma3-tools:27b-ft",   # 格式 ollama:<你的ollama模型名>，例如 llama3.1:8b、qwen2.5:7b
    base_url=os.getenv("OLLAMA_BASE_URL"),
    api_key="dummy",     # ollama不需要key，必须传一个占位字符串，不能None
    temperature=0.7,
    max_tokens=200,
)
```

> 离线首次运行会下载约 1GB 模型到 `~/.cache/huggingface`（需联网），之后不再联网。

---

## 单元格 2：第一个工具

`@tool` 装饰器 + docstring + 类型注解，三样缺一不可：

```python
from langchain_core.tools import tool

@tool
def get_weather(city: str) -> str:
    """
    获取指定城市的天气信息

    参数:
        city: 城市名称，如"北京"、"上海"

    返回:
        天气信息字符串
    """
    # 实际项目中这里会调用天气 API；教程里返回模拟数据
    return f"{city}：晴天，温度 15°C"
```

创建后可以查看工具的元信息：

```python
print("名称:", get_weather.name)
print("描述:", get_weather.description)
print("参数:", get_weather.args)
```

| 必需项 | 说明 |
|-------|------|
| `@tool` 装饰器 | 声明这是一个工具 |
| **docstring** | AI 靠它理解工具用途，非常重要 |
| 类型注解 | AI 靠它生成正确的参数 |
| 返回 `str` | 字符串最容易被 AI 理解 |

---

## 单元格 3：直接调用工具（测试用）

工具本质还是函数，可以不经过 AI 直接调用——这是测试工具的标准方式：

```python
result = get_weather.invoke({"city": "北京"})
print(result)
```

参数用字典传入（键 = 参数名）。这一步与模型无关，离线也能跑。

---

## 单元格 4：docstring 的好坏对比

AI 完全依赖 docstring 决定"什么时候用这个工具、怎么传参"：

```python
@tool
def vague_tool(x: str) -> str:
    """做一些事情"""
    return "ok"


@tool
def search_products(query: str) -> str:
    """
    在产品数据库中按关键词搜索产品

    参数:
        query: 搜索关键词，如"笔记本电脑"、"手机"

    返回:
        产品列表的 JSON 字符串
    """
    return f"[模拟] 与'{query}'相关的产品列表"
```

对比两者暴露给 AI 的描述：

```python
print("模糊版描述:", vague_tool.description)
print("清晰版描述:", search_products.description)
```

`"""做一些事情"""` 这种描述会让 AI 不知道何时该用它。

---

## 单元格 5：多参数与可选参数

多参数工具：

```python
@tool
def calculator(operation: str, a: float, b: float) -> str:
    """
    执行基本的数学计算

    参数:
        operation: 运算类型，"add"/"subtract"/"multiply"/"divide"
        a: 第一个数字
        b: 第二个数字
    """
    ops = {
        "add": a + b,
        "subtract": a - b,
        "multiply": a * b,
        "divide": a / b if b != 0 else None,
    }
    result = ops.get(operation)
    return f"{a} {operation} {b} = {result}"
```

可选参数用 `Optional[type]` 并给默认值：

```python
from typing import Optional

@tool
def web_search(query: str, num_results: Optional[int] = 3) -> str:
    """
    搜索网页并返回结果摘要

    参数:
        query: 搜索关键词
        num_results: 返回结果数量，默认 3
    """
    return f"[模拟] 关于'{query}'的前 {num_results} 条搜索结果"
```

直接测试：

```python
print(calculator.invoke({"operation": "multiply", "a": 15, "b": 23}))
print(web_search.invoke({"query": "LangChain 教程"}))                    # 不传可选参数
print(web_search.invoke({"query": "LangChain 教程", "num_results": 5})) # 传可选参数
```

---

## 单元格 6：错误处理

工具内部要自己兜住异常，永远返回字符串（哪怕报错也要返回错误说明，
否则 Agent 循环可能被中断）：

```python
@tool
def divide(a: float, b: float) -> str:
    """
    除法计算

    参数:
        a: 被除数
        b: 除数
    """
    try:
        if b == 0:
            return "错误：除数不能为零"
        return f"{a} / {b} = {a / b}"
    except Exception as e:
        return f"计算错误：{e}"


print(divide.invoke({"a": 100, "b": 5}))
print(divide.invoke({"a": 100, "b": 0}))   # 边界情况
```

其他最佳实践：

- 功能单一：一个工具只做一件事，不要写 `do_everything(action, data)` 这种万能函数
- 描述明确：多个工具的功能描述要有区分度，避免 AI 混淆

---

## 单元格 7：绑定到模型，让 AI 决定是否调用（需在线）

> 本单元格需要支持 function calling 的模型。离线小模型不支持，请切换在线方案后再运行。

```python
model_with_tools = model.bind_tools([get_weather, calculator])

# 问一个需要工具的问题
response = model_with_tools.invoke("北京天气如何？")

if response.tool_calls:
    print("AI 想调用工具:")
    for tc in response.tool_calls:
        print(f"  工具: {tc['name']}, 参数: {tc['args']}")
else:
    print("AI 直接回答:", response.content)
```

再对比一个不需要工具的问题——AI 会直接回答而不产生 tool_calls：

```python
response2 = model_with_tools.invoke("用一句话介绍你自己")
print("tool_calls:", response2.tool_calls)
print("回答:", response2.content)
```

关键理解：`bind_tools` 只是把工具清单告诉 AI，由 **AI 自己决定**调不调、调哪个、传什么参数；
真正的执行发生在 Agent 循环里（下一模块）。

为什么输出为空呢？

简单来说，因为此时 AI 处于“向程序下达指令”的状态，而不是“向用户输出回答”的状态。

### 想象一下这样一个场景：

- **用户** = 客户
- **AI** **大模型** = 老板
- **Tool 工具** = 秘书（懂怎么查天气）

当客户（用户）问老板（AI）：“北京今天天气如何？” 老板意识到自己脑子里没有今天的数据，于是他转头对秘书（程序工具）下达指令：“去查一下北京的天气”。 在这个瞬间，老板是对秘书说话的（输出了 `tool_calls`），他暂时没有对客户说话（所以 `content` 是空的）。

只有等秘书把天气结果拿回来给老板后，老板才会转过头对客户说（也就是生成最终的 `content`）：“北京今天是晴天，50度。”

---

## 单元格 8（进阶）：手动执行 AI 选择的工具

把单元格 7 的 tool_calls 手动执行一遍，就能看清 Agent 内部发生的事：

```python
response = model_with_tools.invoke("计算 25 乘以 8")

for tc in response.tool_calls:
    # 根据 AI 给出的名字和参数，找到对应工具执行
    tool_map = {"get_weather": get_weather, "calculator": calculator}
    selected_tool = tool_map[tc["name"]]
    result = selected_tool.invoke(tc["args"])
    print(f"AI 选择: {tc['name']}, 参数: {tc['args']}")
    print(f"执行结果: {result}")
```

这就是 Agent 自动化的"思考 → 调用 → 观察"循环的最小雏形。

---

## FAQ

### Q1: AI 就是不调用我的工具？

按顺序检查：docstring 是否说清了用途和场景；问题是否明确需要该工具；参数类型注解是否完整。

### Q2: 工具可以返回字典吗？

技术上可行，但推荐返回字符串（如用 `json.dumps(..., ensure_ascii=False)` 转一下），对 AI 最友好。

### Q3: 工具数量有上限吗？

建议 2~5 个。太多会互相干扰，导致 AI 选错工具。

---

## 项目结构与对照表

```
04_custom_tools/
├── main.py                # 6 个示例
├── README.md              # 本文件
└── tools/
    ├── weather.py         # 天气工具
    ├── calculator.py      # 计算器工具
    └── web_search.py      # 搜索工具
```

| 手册单元格 | 对应文件 |
|------------|----------|
| 单元格 1A / 1B | 环境配置部分 |
| 单元格 2、3 | `tools/weather.py` |
| 单元格 5 | `tools/calculator.py`、`tools/web_search.py` |
| 单元格 7、8 | main.py 中 bind_tools 相关示例 |

## 下一步学习

**05_simple_agent** —— 用 `create_agent` 让 AI 自动完成"选工具 → 执行 → 回答"的全过程
