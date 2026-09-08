# 11 - 工作区与沙箱 Workspace

本篇目标：把智能体的「动手」行为隔离进**安全沙箱**——文件读写、代码执行都在隔离环境中进行，避免误伤宿主机。

## 11.1 前置准备

```bash
pip install agentscope[full]   # 沙箱后端依赖含在 full
export DASHSCOPE_API_KEY="sk-你的密钥"
```

## 11.2 什么是 Workspace

`Workspace` 是智能体**工具与代码执行**的隔离环境。内置工具（`Bash`/`Read`/`Write`/`Edit` 等）天然绑定工作区，落盘到 `workdir`，而非随意写系统路径。

```python
from agentscope.workspace import LocalWorkspace

async with LocalWorkspace(workdir="./workspace") as ws:
    # ws 是隔离工作区，工具只在此目录内操作
    toolkit = Toolkit(tools=await ws.list_tools())  # 从工作区加载工具
```

## 11.3 LocalWorkspace（本地隔离）

最简单的沙箱：在当前机器上用 `./workspace` 目录做隔离边界。

```python
import os
import asyncio

from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.message import UserMsg
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit
from agentscope.workspace import LocalWorkspace


async def main() -> None:
    async with LocalWorkspace(workdir="./workspace") as ws:
        agent = Agent(
            name="Friday",
            system_prompt="You are a coding assistant. Operate within the workspace.",
            model=DashScopeChatModel(
                credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
                model="qwen-plus",
            ),
            toolkit=Toolkit(tools=await ws.list_tools()),
        )
        reply = await agent.reply(
            UserMsg(name="user", content="在 workspace 里创建 hello.txt，写『Hi』")
        )
        print(reply.content)


asyncio.run(main())
```

## 11.4 可切换的沙箱后端

2.0 支持多种隔离后端，按需选择隔离强度：

| 后端 | 隔离强度 | 适用 |
|------|----------|------|
| `LocalWorkspace` | 目录级隔离（进程内） | 本地开发、单机 |
| `Docker` / `Apple Container` / `Bubblewrap` | 容器/命名空间级 | 中等隔离 |
| `E2B` | 远程微虚拟机 | 强隔离、云托管 |
| `OpenSandbox` | 平台沙箱 | 企业/云 |
| `Daytona` | 开发环境沙箱 | 云端工作区 |
| `K8s` | 集群 Pod 级 | 生产分布式 |

> 各后端的构造参数（如 `DockerWorkspace(image=...)`）以官方文档与示例为准；切换只需替换 `Workspace` 类，上层 `Agent` / `Toolkit` 代码不变。

## 11.5 与权限、记忆的配合

工作区是安全底座，常与另外两项组合：

- **权限系统**（[09-权限与人工协同.md](09-权限与人工协同.md)）：即便确认过，危险操作仍限制在沙箱内
- **记忆**（[08-记忆Memory.md](08-记忆Memory.md)）：`ws.workdir` 同时是记忆落盘目录

## 关键 API 速查

| API | 说明 |
|-----|------|
| `LocalWorkspace(workdir=)` | 本地隔离工作区（异步上下文管理器） |
| `await ws.list_tools()` | 从工作区加载工具集 |
| 其他后端（Docker/E2B/K8s…） | 替换 `Workspace` 类即可 |

## 2.0 注意事项

- 生产环境**务必**用容器/VM 级沙箱（Docker/E2B/K8s），不要直接 `Bash()` 裸跑在宿主机。
- `workdir` 既管工具落盘，也管记忆文件；换目录会「失忆」（见 08 篇）。
- 沙箱后端依赖含在 `agentscope[full]`，按需安装对应 extra。

## 下一步

→ [12-多智能体协作AgentTeam.md](12-多智能体协作AgentTeam.md)：让多个智能体协同完成任务。
