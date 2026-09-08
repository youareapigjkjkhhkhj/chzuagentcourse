# 06 - Agent Loop：Agent 执行循环（Jupyter 版）

> **本手册为 Jupyter Notebook 学习设计。**
>
> - 所有代码块按 `【单元格 N】` 编号，**请从上到下按顺序运行**（Shift+Enter）。后面的单元格会用到前面定义的变量（如 `agent`、`response`），跳跃执行会报 `NameError`。
> - 如果重启了内核（Kernel → Restart），请回到【单元格 1】重新依次往下执行。
> - 同目录下的 `main.py` / `test.py` 是等价的脚本版本，本手册不修改它们。
> - **本模块需要在线模型**：与 05 模块相同，Agent 循环依赖模型的 function calling 能力。Groq 的 Llama-3.3-70B 支持；离线 pipeline 方式加载的本地小模型不支持，无法运行本模块示例。

## 学习目标

**Agent 执行循环 = 自动化的"思考 → 行动 → 观察"过程**

```
用户问题 → AI 思考 → 调用工具 → 观察结果 → 继续思考 → 最终答案
```

1. 看懂 `response["messages"]` 里的完整消息流转
2. 提取最终答案、统计工具使用情况
3. 多步骤任务的执行过程
4. 流式输出 `stream()` 与调试技巧

## 0. 准备工作

```bash
pip install -U langchain langchain-groq python-dotenv
```

把仓库根目录的 `.env.example` 复制为 `.env`，填入 `GROQ_API_KEY=gsk_xxx`。

---

## 单元格 1：初始化模型 + 工具 + Agent（一次到位）

本模块所有单元格都基于这里的 `agent`：

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
    max_tokens=500,
)


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
def get_weather(city: str) -> str:
    """
    获取指定城市的天气信息

    参数:
        city: 城市名称，如"北京"、"上海"

    返回:
        天气信息字符串
    """
    return f"{city}：晴天，温度 15°C"


agent = create_agent(model=model, tools=[calculator, get_weather])

print("Agent 就绪")
```

---

## 单元格 2：看懂执行循环——完整消息历史

问一个需要工具的问题，然后逐条查看消息：

```python
question = "25 乘以 8 等于多少？"
response = agent.invoke({"messages": [{"role": "user", "content": question}]})

for i, msg in enumerate(response["messages"], 1):
    print(f"\n--- 消息 {i}: {msg.__class__.__name__} ---")
    if msg.content:
        print(f"内容: {msg.content}")
    if getattr(msg, "tool_calls", None):
        for tc in msg.tool_calls:
            print(f"工具调用: {tc['name']}, 参数: {tc['args']}")
```

消息流转过程：

```
HumanMessage          用户问题
AIMessage(tool_calls) AI 决定调用工具
ToolMessage           工具执行结果
AIMessage             基于结果生成最终答案   ← 最后一条
```

这个循环由 Agent 自动完成，所有步骤都记录在 messages 里。

---

## 单元格 3：提取结果的三种常用姿势

```python
# 1. 最终答案：最后一条消息
final_answer = response["messages"][-1].content
print("最终答案:", final_answer)

# 2. 是否使用了工具
has_tool_calls = any(
    getattr(msg, "tool_calls", None) for msg in response["messages"]
)
print("用了工具吗:", has_tool_calls)

# 3. 用了哪些工具
used_tools = [
    tc["name"]
    for msg in response["messages"]
    if getattr(msg, "tool_calls", None)
    for tc in msg.tool_calls
]
print("使用的工具:", used_tools)
```

---

## 单元格 4：多步骤任务

Agent 可以连续调用多次工具，前一步的结果作为下一步的输入：

```python
resp = agent.invoke({
    "messages": [{"role": "user", "content": "先算 10 加 20，然后把结果乘以 3"}]
})

tool_calls_count = sum(
    len(msg.tool_calls)
    for msg in resp["messages"]
    if getattr(msg, "tool_calls", None)
)

print(f"工具调用次数: {tool_calls_count}")   # 可能是 2 次：add → multiply
print(f"最终答案: {resp['messages'][-1].content}")
```

每次调用的结果会影响下一步，直到 AI 认为可以给出最终答案。

> 判断循环结束的标志：出现**不含 tool_calls 的 AIMessage**。

---

## 单元格 5：流式输出 stream()

实时观察每一步，适合长时间任务和进度展示：

```python
step = 0
for chunk in agent.stream({
    "messages": [{"role": "user", "content": "100 除以 5 等于多少？"}]
}):
    step += 1
    print(f"\n步骤 {step}:")
    if "messages" in chunk:
        latest = chunk["messages"][-1]
        print(f"  类型: {latest.__class__.__name__}")
        if getattr(latest, "tool_calls", None):
            print(f"  工具调用: {latest.tool_calls[0]['name']}")
        elif latest.content:
            print(f"  内容: {latest.content[:50]}")
            
#若看不到输出使用
step = 0

for chunk in agent.stream({
    "messages": [
        {
            "role": "user",
            "content": "100 除以 5 等于多少？"
        }
    ]
}):

    step += 1
    print(f"\n========== 步骤 {step} ==========")

    for key, value in chunk.items():

        print("节点:", key)

        if "messages" in value:

            msg = value["messages"][-1]

            print(
                "消息类型:",
                msg.__class__.__name__
            )

            if msg.content:
                print(
                    "内容:",
                    msg.content
                )

            if getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    print(
                        "工具调用:",
                        tc["name"],
                        tc["args"]
                    )
```

| 方法 | 返回 | 用途 |
|-----|------|------|
| `invoke()` | 完整结果 | 等待完成后一次性获取 |
| `stream()` | 生成器 | 实时获取中间步骤 |

只显示最终答案的写法：

```python
for chunk in agent.stream({
    "messages": [{"role": "user", "content": "北京天气如何？"}]
}):
    if "messages" in chunk:
        latest = chunk["messages"][-1]
        if latest.content and not getattr(latest, "tool_calls", None):
            print("最终回答:", latest.content)
```

---

## 单元格 6：调试技巧——详细打印每条消息

排查"Agent 到底干了什么"的万能方法：

```python
def debug_messages(response):
    for i, msg in enumerate(response["messages"], 1):
        print(f"\n[{i}] {msg.__class__.__name__}")
        if hasattr(msg, "name") and msg.name:
            print(f"    工具名: {msg.name}")
        if msg.content:
            print(f"    内容: {msg.content[:100]}")
        if getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                print(f"    调用: {tc['name']}({tc['args']})")


debug_messages(resp)
```

生产环境的错误处理模板：

```python
try:
    r = agent.invoke({"messages": [{"role": "user", "content": "5 加 3"}]})
    answer = r["messages"][-1].content
    print("答案:", answer)
except Exception as e:
    print(f"Agent 执行错误: {e}")
```

---

## 单元格 7（预览）：限制循环步数

防止 Agent 无限循环调用工具（高级用法，后续模块详学）：

```python
config = {"recursion_limit": 5}   # 最多 5 步

r = agent.invoke(
    {"messages": [{"role": "user", "content": "计算 (10 + 20) * 3"}]},
    config=config,
)
print(r["messages"][-1].content)
```

---

## FAQ

### Q1: 如何知道 Agent 何时完成？

当出现不含 `tool_calls` 的 AIMessage 时循环结束——它就是最终答案。

### Q2: Agent 可以无限调用工具吗？

默认没有硬性限制，但可能因超时、token 上限或模型自行停止而结束。
生产环境建议用 `recursion_limit` 兜底。

### Q3: ToolMessage 是谁生成的？

Agent 框架自动执行工具并把结果包装成 ToolMessage 放回历史，
你不需要手动执行（对比 04 模块单元格 8 的手动版本）。

---

## 手册与 main.py 对照表

| 手册单元格 | main.py 中的示例 |
|------------|------------------|
| 单元格 1 | 环境配置 + 导入 tools/ |
| 单元格 2 | 示例 1（理解执行循环） |
| 单元格 4 | 示例 3（多步骤执行） |
| 单元格 5 | 示例 2、4（流式输出、中间状态） |
| 单元格 6 | 示例 6（最佳实践） |

## 核心要点总结

1. **执行循环**：问题 → 工具调用 → 结果 → 答案，全自动完成
2. **messages 历史**：记录完整过程，最后一条即最终答案
3. **流式输出**：`stream()` 实时显示每个步骤
4. **消息类型**：HumanMessage、AIMessage（含/不含 tool_calls）、ToolMessage
5. **调试**：遍历打印 messages 是最有效的排查手段

## 阶段一完成！

已学习：

- 01：环境搭建和模型调用（在线 / 离线）
- 02：提示词模板
- 03：消息类型和对话历史管理
- 04：自定义工具
- 05：Simple Agent
- 06：Agent 执行循环

下一阶段（进阶）：内存管理、上下文工程、Checkpointing、中间件、结构化输出、RAG。
