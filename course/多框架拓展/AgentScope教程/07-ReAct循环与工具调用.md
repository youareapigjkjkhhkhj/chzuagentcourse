# 07 - ReAct 循环与工具调用

本篇目标：理解 2.0 的「推理-行动」循环如何让智能体**自动调用工具**完成任务，以及框架如何编排工具执行、支持中断恢复。

## 7.1 前置准备

```bash
pip install agentscope[full]
export DASHSCOPE_API_KEY="sk-你的密钥"
```

## 7.2 Agent 内置 ReAct 循环

`Agent` 本身就是一个 **ReAct（Reasoning + Acting）引擎**：你只需把工具交给 `toolkit`，智能体会自己决定「何时调用、调用哪个、调用几次」。**无需手写 while 循环**。

```python
import os
import asyncio

from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.message import UserMsg
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit, Bash, Read, Write, Edit


async def main() -> None:
    agent = Agent(
        name="Friday",
        system_prompt="You are a helpful coding assistant. Use tools to get things done.",
        model=DashScopeChatModel(
            credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
            model="qwen-plus",
        ),
        toolkit=Toolkit(tools=[Bash(), Read(), Write(), Edit()]),
    )

    # 智能体内部循环：推理 → 调 Write → 观察结果 → 继续推理 → 给出回复
    reply = await agent.reply(
        UserMsg(name="user", content="在当前目录创建一个 note.md，写一句『AgentScope 2.0 学习笔记』")
    )
    print(reply.content)


asyncio.run(main())
```

运行后，终端会先弹**工具调用确认**（见 [09-权限与人工协同.md](09-权限与人工协同.md)），确认后文件落盘。

## 7.3 顺序 / 并发工具执行（自动编排）

AgentScope 2.0 会**根据工具属性智能编排**：互相独立的工具**并发**执行，有依赖的**顺序**执行。你不用手动标注，框架自动判断。

```python
# 例如「查北京天气」和「查上海天气」两个独立工具调用会被并发触发，
# 而「先读文件再基于内容写总结」则是顺序执行。
```

## 7.4 中断与恢复

- **交互式**：`launch_console` 内置 `Ctrl+C` 中断；中断后上下文保留，可重新开始。
- **任务级**：复杂任务在 Agent Team 中可中断、修订计划、再恢复（见 [12-多智能体协作AgentTeam.md](12-多智能体协作AgentTeam.md)）。
- **后台任务**：长耗时工具可转入后台执行，完成后唤醒智能体恢复对话（见官方示例 `examples/`）。

## 7.5 显式 ReActAgent（可选）

除默认的 `Agent` 外，2.0 也提供 `ReActAgent` 类，语义等价、适合需要显式指定 ReAct 行为的场景：

```python
from agentscope.agent import ReActAgent
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit, execute_python_code, execute_shell_command

toolkit = Toolkit()
toolkit.register_tool_function(execute_python_code)
toolkit.register_tool_function(execute_shell_command)

agent = ReActAgent(
    name="Friday",
    sys_prompt="You're a helpful assistant named Friday.",
    model=DashScopeChatModel(
        model_name="qwen-max",
        api_key=os.environ["DASHSCOPE_API_KEY"],
        stream=True,
    ),
    toolkit=toolkit,
)
```

> 注：`ReActAgent` 的 `sys_prompt`（带 `s`）与 `Agent` 的 `system_prompt` 命名略有差异，具体以官方源码为准；日常开发推荐直接用 `Agent`，它已内置 ReAct 循环。

## 关键 API 速查

| 概念 | 说明 |
|------|------|
| `Agent(toolkit=...)` | 内置 ReAct，自动调工具 |
| `toolkit=Toolkit(tools=[...])` | 注入工具集 |
| 并发 / 顺序执行 | 框架按工具属性自动编排 |
| `Ctrl+C` / 后台任务 | 中断与恢复机制 |

## 2.0 注意事项

- **不要手写** `while True: ... 解析 tool_call` 的循环——2.0 的 `Agent` 已内置，手写反而失去中断/并发/压缩能力。
- 工具调用默认**需人工确认**（安全设计），批量无人值守时切 `bypass` 模式（见 09 篇）。
- 模型「不调用工具」通常是因为：① toolkit 没注册；② system_prompt 没要求用工具。两处都确认即可。

## 下一步

→ [08-记忆Memory.md](08-记忆Memory.md)：让智能体「记得住」——跨会话长期记忆。
