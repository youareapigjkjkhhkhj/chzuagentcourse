# 14 - MCP 与 Skill Hub

本篇目标：用 **MCP（Model Context Protocol）** 接入社区上千个现成工具/服务，并用 **Skill Hub** 一键安装技能，让智能体能力「即插即用」。

## 14.1 前置准备

```bash
pip install agentscope[full]
export DASHSCOPE_API_KEY="sk-你的密钥"
```

## 14.2 MCP 是什么

MCP 是开放协议，让智能体通过统一接口连接外部工具服务器（文件系统、搜索、数据库、第三方 API…）。AgentScope 2.0 内置 `MCPClient`，支持 HTTP 与 stdio 两种传输。

## 14.3 HTTP 方式接入 MCP

```python
import os

from agentscope.agent import Agent
from agentscope.credential import DashScopeCredential
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit
from agentscope.mcp import MCPClient, HttpMCPConfig


agent = Agent(
    name="my_agent",
    system_prompt="你是一个AI助手。",
    model=DashScopeChatModel(
        credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
        model="qwen-max",
    ),
    toolkit=Toolkit(
        tools=[],
        mcps=[
            MCPClient(
                name="amap",                       # 高德地图 MCP
                is_stateful=False,
                mcp_config=HttpMCPConfig(
                    url=f"https://mcp.amap.com/mcp?key={os.environ['AMAP_API_KEY']}",
                ),
            ),
        ],
    ),
)
```

## 14.4 stdio 方式接入 MCP（本地进程）

```python
from agentscope.mcp import MCPClient, StdioMCPConfig

mcp_clients = [
    MCPClient(
        name="file_system",
        mcp_config=StdioMCPConfig(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "./workspace"],
        ),
        is_stateful=True,
    ),
]

# 加入 Agent 的 toolkit.mcps
agent = Agent(
    name="my_agent",
    system_prompt="你是一个AI助手。",
    model=DashScopeChatModel(...),
    toolkit=Toolkit(tools=[], mcps=mcp_clients),
)
```

> 配置好后加入工作区的 `default_mcps`，智能体就能通过 MCP 协议操作对应资源——社区生态里上千个现成 MCP 服务都能这样接。

## 14.5 Skill Hub（技能中心）

2.0 支持 **Skill Hub**：浏览中心、安装到本地库、再加入工作区。2026-08 起，官方已将 **GitHub MCP Registry** 与 **ClawHub** 作为内置中心。

```python
from agentscope.tool import Toolkit

toolkit = Toolkit(
    tools=[Bash(), Read(), Write(), Edit()],
    mcps=[...],
    skills_or_loaders=["./skills"],   # 本地技能目录，或指向 Hub 安装的技能
)
```

工作流：
1. 在 Hub（GitHub MCP Registry / ClawHub）浏览技能
2. 安装到你的 library
3. 加入 workspace / toolkit，智能体即可调用

## 14.6 MCP 与 Toolkit 的组合

`Toolkit` 可同时承载三类来源，智能体无感调用：

| 来源 | 配置项 |
|------|--------|
| 内置/自定义 Python 工具 | `tools=[Bash(), current_time, ...]` |
| MCP 服务器 | `mcps=[MCPClient(...)]` |
| Skill | `skills_or_loaders=["./skills"]` |

## 关键 API 速查

| API | 说明 |
|-----|------|
| `MCPClient(name, mcp_config, is_stateful=)` | 创建一个 MCP 客户端 |
| `HttpMCPConfig(url=)` | HTTP 传输配置 |
| `StdioMCPConfig(command=, args=)` | 本地进程 stdio 配置 |
| `Toolkit(mcps=, skills_or_loaders=)` | 把 MCP/Skill 装入工具集 |

## 2.0 注意事项

- `mcp_config` 必须匹配传输类型：`HttpMCPConfig`（远程）或 `StdioMCPConfig`（本地进程）。
- MCP 首次运行（如 `npx ...`）需联网下载，确保网络通畅且 `npx` 可用。
- 自定义工具与 MCP 工具可共存于同一个 `Toolkit`，无需分开管理。

## 下一步

→ [15-流式输出与可观测.md](15-流式输出与可观测.md)：用事件总线与 Studio 看清智能体每一步。
