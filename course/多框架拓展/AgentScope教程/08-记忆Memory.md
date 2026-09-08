# 08 - 记忆 Memory

本篇目标：让智能体「记得住」。默认智能体「过目即忘」，2.0 通过**中间件**挂载长期记忆，支持跨会话持久化。

## 8.1 前置准备

```bash
pip install agentscope[full]
export DASHSCOPE_API_KEY="sk-你的密钥"
```

## 8.2 核心概念：Agentic Memory

AgentScope 2.0 的 Agentic Memory 把持久化事实写成**人类可读的 Markdown 文件**，重启后依然记得你；并支持 **ReMe**、**Mem0** 等可切换后端。

- **短期记忆**：当前会话上下文（由 `ContextConfig` 压缩管理，见 [05-智能体Agent.md](05-智能体Agent.md)）
- **长期记忆**：跨会话持久化，写入工作区 `Memory/` 目录

## 8.3 挂载 AgenticMemoryMiddleware

记忆通过**中间件**注入 `Agent`（中间件机制详见 [10-中间件Middleware.md](10-中间件Middleware.md)）。需配合 `LocalWorkspace` 提供落盘目录与后端。

```python
import os
import asyncio

from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.message import UserMsg
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit
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
            # 挂上长期记忆中间件
            middlewares=[
                AgenticMemoryMiddleware(workdir=ws.workdir, backend=ws.get_backend())
            ],
        )

        # 第一步：告诉它一条偏好
        await agent.reply(UserMsg(name="user", content="我偏好简洁的中文回答。"))
        # → 中间件把这条写进 workspace/Memory/MEMORY.md

        # 第二步：重启（新进程）后再问，它仍记得
        # （需在同一 workdir 启动，记忆文件被重新加载）


import asyncio
asyncio.run(main())
```

效果：偏好被记进 `workspace/Memory/MEMORY.md`；重启后问「你还记得我什么？」，智能体能答上来。

## 8.4 可切换后端

`AgenticMemoryMiddleware` 的 `backend` 支持多种记忆后端：

| 后端 | 说明 |
|------|------|
| 工作区文件系统（默认） | Markdown 文件，零依赖、可读 |
| `ReMe` | AgentScope 官方记忆管理套件（持久化 + 检索） |
| `Mem0` | 社区流行记忆后端 |

> 后端的具体实例化方式（如 `ws.get_backend()`）以官方文档与示例 `examples/long_term_memory/agentic_memory/` 为准。

## 8.5 与上下文压缩的区别

| 机制 | 作用域 | 触发 |
|------|--------|------|
| `ContextConfig`（短期） | 单次会话内 | token 超 `trigger_ratio` 自动压缩 |
| `AgenticMemoryMiddleware`（长期） | 跨会话 | 智能体主动「记住」事实，落盘持久化 |

## 关键 API 速查

| API | 说明 |
|-----|------|
| `AgenticMemoryMiddleware(workdir=, backend=)` | 长期记忆中间件 |
| `LocalWorkspace(workdir=)` | 提供记忆落盘目录与后端 |
| `workspace/Memory/MEMORY.md` | 记忆持久化文件 |

## 2.0 注意事项

- 记忆是**中间件**，不是 1.0 的 `Memory` 类；不要再 `from agentscope.memory import Memory`。
- 必须保持 `workdir` 不变，重启后才能加载到旧记忆；换目录等于「失忆」。
- 记忆中间件需 `agentscope[full]`（含 Mem0 等可选后端依赖）。

## 下一步

→ [09-权限与人工协同.md](09-权限与人工协同.md)：给危险工具调用加「闸」——权限与人工确认。
