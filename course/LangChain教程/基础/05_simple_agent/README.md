# 05 - Simple Agent：简单 Agent（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量（如 `agent`），跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` 是等价的脚本版本，本手册不修改它（见文末对照表）。
> - **本模块需要在线模型**：`create_agent` 依赖模型的 function calling 能力。Groq 的 Llama-3.3-70B 支持；离线 pipeline 方式加载的本地小模型**不支持**工具调用，无法运行本模块示例。离线学习者可先阅读理解概念，代码需配置 `GROQ_API_KEY` 后运行。

## 学习目标

1. **Agent = 模型 + 工具 + 自动决策**
2. `create_agent` —— LangChain 1.0 统一 API
3. Agent 如何自动选择工具
4. 多轮对话与 system_prompt 定制

Agent 的关键能力：理解问题 → 判断是否需要工具 → 选择工具并传参 → 基于结果回答。

## 0. 准备工作

```bash
pip install -U langchain langchain-groq python-dotenv
```

把仓库根目录的 `.env.example` 复制为 `.env`，填入 `GROQ_API_KEY=gsk_xxx`
（获取地址：<https://console.groq.com/keys>）。

---

## 单元格 1：初始化模型（在线必需）

```python
import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model

load_dotenv()

model = init_chat_model(
    "groq:llama-3.3-70b-versatile",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0.7,
    max_tokens=500,
)

print("模型就绪：Groq llama-3.3-70b-versatile")
```

---

## 单元格 2：准备工具

定义三个功能清晰的工具（内容来自 04 模块）：

```python
from typing import Optional
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
    return f"{city}：晴天，温度 15°C"


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


@tool
def web_search(query: str, num_results: Optional[int] = 3) -> str:
    """
    搜索网页并返回结果摘要

    参数:
        query: 搜索关键词
        num_results: 返回结果数量，默认 3
    """
    return f"[模拟] 关于'{query}'的前 {num_results} 条搜索结果"


print("工具就绪:", [t.name for t in [get_weather, calculator, web_search]])
```

AI 会根据每个工具的 **docstring** 决定用哪个——描述越清晰，选择越准确。

---

## 单元格 3：创建第一个 Agent

```python
from langchain.agents import create_agent

agent = create_agent(
    model=model,
    tools=[get_weather],          # 只给一个工具
)

response = agent.invoke({
    "messages": [{"role": "user", "content": "北京今天天气怎么样？"}]
})

print("Agent 回复:", response["messages"][-1].content)
```

再问一个不需要工具的问题——Agent 会直接回答：

```python
response = agent.invoke({
    "messages": [{"role": "user", "content": "你好，用一句话介绍你自己"}]
})

print("Agent 回复:", response["messages"][-1].content)
```

| 参数 | 说明 | 必需 |
|-----|------|------|
| `model` | 语言模型 | 必需 |
| `tools` | 工具列表 | 可选 |
| `system_prompt` | 系统提示，定义 Agent 行为 | 可选 |

---

## 单元格 4：多工具 Agent——自动选择

给 Agent 配多个工具，观察它按问题自动选：

```python
multi_agent = create_agent(
    model=model,
    tools=[get_weather, calculator, web_search],
)

tests = [
    "上海的天气怎么样？",     # 应选 get_weather
    "15 乘以 23 等于多少？",   # 应选 calculator
]

for q in tests:
    resp = multi_agent.invoke({"messages": [{"role": "user", "content": q}]})
    print(f"问: {q}")
    print(f"答: {resp['messages'][-1].content}\n")
```

选择依据：问题内容 + 每个工具的描述 → 匹配度最高的工具。

---

## 单元格 5：查看响应结构

`invoke` 返回字典，`messages` 记录了完整执行过程：

```python
resp = multi_agent.invoke({"messages": [{"role": "user", "content": "10 加 5"}]})

for msg in resp["messages"]:
    print(f"[{msg.__class__.__name__}] {msg.content[:60]}")
```

典型结构：

```
HumanMessage   用户问题
AIMessage      AI 决定调用工具（含 tool_calls）
ToolMessage    工具执行结果
AIMessage      最终回答  ← 通常取这个
```

取最终答案的标准写法：

```python
final_answer = resp["messages"][-1].content
```

---

## 单元格 6：多轮对话——传入历史

和普通模型一样，Agent 的记忆也靠传入历史消息：

```python
# 第一轮
r1 = multi_agent.invoke({
    "messages": [{"role": "user", "content": "10 + 5"}]
})
print("第一轮:", r1["messages"][-1].content)

# 第二轮：把上一轮的全部消息带上，再追加新问题
r2 = multi_agent.invoke({
    "messages": r1["messages"] + [{"role": "user", "content": "再乘以 3"}]
})
print("第二轮:", r2["messages"][-1].content)
```

"再乘以 3"能算对，正是因为历史里包含了上一轮的结果。

---

## 单元格 7：system_prompt 定制行为

```python
weather_agent = create_agent(
    model=model,
    tools=[get_weather],
    system_prompt="""你是天气助手。

工作流程：
1. 理解用户查询的城市
2. 使用 get_weather 工具获取数据
3. 简洁清晰地回答，包含天气状况和温度
""",
)

resp = weather_agent.invoke({
    "messages": [{"role": "user", "content": "深圳天气如何？"}]
})
print(resp["messages"][-1].content)
```

---

## 单元格 8：流式输出预览

`stream()` 实时返回中间步骤（下一模块详细讲解）：

```python
for chunk in weather_agent.stream({
    "messages": [{"role": "user", "content": "北京天气如何？"}]
}):
    if "messages" in chunk:
        latest = chunk["messages"][-1]
        # 只打印最终答案（不含 tool_calls 的 AIMessage）
        if latest.content and not getattr(latest, "tool_calls", None):
            print("最终回答:", latest.content)
```

---

## FAQ

### Q1: Agent 不调用工具？

- 工具 docstring 太模糊 → 写清用途、参数、场景
- 问题表述不明确 → 让问题明确指向工具能力
- 换更强的模型试试

### Q2: Agent 选错工具？

- 工具描述要有明确区分度
- 只给必要的工具（2~5 个最佳）
- 在 system_prompt 中说明各工具的使用场景

### Q3: Agent 和 bind_tools 有什么区别？

`bind_tools` 只让模型"说出"想调用的工具，执行要自己写；
`create_agent` 把"决定 → 执行 → 观察 → 再决定"的循环全部自动化。

---

## 手册与 main.py 对照表

| 手册单元格 | main.py 中的示例 |
|------------|------------------|
| 单元格 1 | 环境配置部分 |
| 单元格 2 | 导入 tools/ 目录的工具 |
| 单元格 3 | 示例 1（第一个 Agent） |
| 单元格 4 | 示例 2（多工具 Agent） |
| 单元格 6 | 多轮对话示例 |
| 单元格 7 | system_prompt 示例 |
| 单元格 8 | 流式输出示例 |

## 下一步学习

**06_agent_loop** —— 深入理解 Agent 执行循环的底层机制：消息流转、流式输出、调试技巧
