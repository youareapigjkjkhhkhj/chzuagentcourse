# 05 - 智能体 Agent

本篇目标：深入 `Agent`——2.0 的核心抽象。它把**模型、工具、权限、人机协同、上下文管理、中间件、事件系统**整合进一个统一接口，本质是一个「无状态的推理-行动循环引擎」。

## 5.1 前置准备

```bash
pip install agentscope
export DASHSCOPE_API_KEY="sk-你的密钥"
```

## 5.2 Agent 是什么

`Agent` 不是一个「聊天机器人外壳」，而是一个**推理-行动（ReAct）循环引擎**：

- 接收输入消息 / 事件 → 调用工具完成任务
- 管理上下文（自动压缩、工具结果卸载）
- 在生命周期关键节点运行**中间件**
- 自动编排工具的**并发 / 顺序**执行（依据工具属性）

## 5.3 最小配置

```python
from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.model import DashScopeChatModel


def build_agent(api_key: str) -> Agent:
    return Agent(
        name="my_agent",
        system_prompt="你是一个有帮助的助手。",
        model=DashScopeChatModel(
            credential=DashScopeCredential(api_key=api_key),
            model="qwen-max",
        ),
    )
```

## 5.4 上下文管理 ContextConfig

长对话会撑爆上下文窗口。2.0 内置**自动压缩**与**工具结果卸载**，用 `ContextConfig` 精细控制。

```python
from agentscope.agent import Agent, ContextConfig
from agentscope.credential import DashScopeCredential
from agentscope.model import DashScopeChatModel

agent = Agent(
    name="my_agent",
    system_prompt="你是一个有帮助的助手。",
    model=DashScopeChatModel(
        credential=DashScopeCredential(api_key="YOUR_API_KEY"),
        model="qwen-max",
    ),
    context_config=ContextConfig(
        trigger_ratio=0.7,     # 上下文使用到 70% 时触发压缩
        reserve_ratio=0.2,     # 压缩后保留最近 20% 的内容
        tool_result_limit=1000,  # 单个工具结果超过 1000 token 时截断
    ),
)
```

| 参数 | 含义 |
|------|------|
| `trigger_ratio` | 上下文占用达到该比例时触发压缩（0~1） |
| `reserve_ratio` | 压缩后保留的最近内容比例 |
| `tool_result_limit` | 工具返回结果的最大 token 数，超出截断（防上下文溢出） |

## 5.5 核心方法

| 方法 | 说明 |
|------|------|
| `await agent.reply(inputs)` | 运行推理-行动循环，返回最终消息 |
| `async for e in agent.reply_stream(inputs)` | 流式产出事件（见 [04-消息与事件系统.md](04-消息与事件系统.md)） |
| `agent.observe(msgs)` | 把消息加入上下文，**不**触发推理 |
| `agent.compress_context(config)` | 手动触发上下文压缩 |

```python
# 注入上下文（不推理）
agent.observe([UserMsg(name="user", content="我正在做 AgentScope 教程。")])

# 运行并拿到回复
reply = await agent.reply(UserMsg(name="user", content="我们讲到哪了？"))

# 手动压缩（通常自动触发，无需手动）
agent.compress_context(ContextConfig(trigger_ratio=0.8))
```

## 5.6 带工具与中间件的完整 Agent

```python
import os

from agentscope.agent import Agent, ContextConfig
from agentscope.credential import DashScopeCredential
from agentscope.message import UserMsg
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit, Bash, Read, Write, Edit
from agentscope.middleware import AgenticMemoryMiddleware
from agentscope.workspace import LocalWorkspace


async def main() -> None:
    async with LocalWorkspace(workdir="./workspace") as ws:
        agent = Agent(
            name="Friday",
            system_prompt="You are a helpful assistant named Friday.",
            model=DashScopeChatModel(
                credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
                model="qwen-plus",
            ),
            toolkit=Toolkit(tools=await ws.list_tools()),
            context_config=ContextConfig(trigger_ratio=0.7, reserve_ratio=0.2),
            middlewares=[AgenticMemoryMiddleware(workdir=ws.workdir, backend=ws.get_backend())],
        )
        reply = await agent.reply(UserMsg(name="user", content="把对话总结成 note.md"))
        print(reply.content)


import asyncio
asyncio.run(main())
```

> `LocalWorkspace` / `AgenticMemoryMiddleware` 详见 [08-记忆Memory.md](08-记忆Memory.md) 与 [11-工作区与沙箱Workspace.md](11-工作区与沙箱Workspace.md)。

## 关键 API 速查

| API | 说明 |
|-----|------|
| `Agent(name, system_prompt, model, toolkit=, context_config=, middlewares=)` | 创建智能体 |
| `ContextConfig(trigger_ratio, reserve_ratio, tool_result_limit)` | 上下文压缩配置 |
| `agent.reply` / `reply_stream` / `observe` / `compress_context` | 核心方法 |

## 2.0 注意事项

- `Agent` 取代 1.0 的 `DialogAgent` / `UserAgent`；不要再 `from agentscope.agents import DialogAgent`。
- 上下文压缩**默认开启且自动触发**，`ContextConfig` 只是调参，无需手动调 `compress_context`。
- 多轮上下文自动维护，无需在 `system_prompt` 里手动拼历史。

## 下一步

→ [06-工具与Toolkit.md](06-工具与Toolkit.md)：让智能体真正「动手」——自定义工具与内置工具全家桶。
