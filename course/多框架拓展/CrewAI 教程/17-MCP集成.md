# 17 - MCP 集成

本篇目标：掌握 CrewAI 的 **MCP（Model Context Protocol）集成**——如何将外部 MCP 服务器作为 Agent 工具，支持多种传输协议。

## 17.1 什么是 MCP？

**MCP（Model Context Protocol）** 是一种开放协议，让 AI 应用可以连接到外部工具和数据源。CrewAI 支持将 MCP 服务器作为 Agent 的工具使用。

MCP 服务器提供工具、资源和上下文，Agent 可以像使用本地工具一样调用它们。

## 17.2 支持的传输协议

| 协议 | 说明 | 适用场景 |
|------|------|----------|
| **stdio** | 标准输入/输出 | 本地进程间通信 |
| **SSE** | Server-Sent Events | HTTP 事件流 |
| **Streamable HTTP** | 流式 HTTP | 远程服务器通信 |

## 17.3 快速开始

### 创建 MCP 服务器实例

#### stdio（本地进程）

```python
from crewai.tools import MCPServerStdio

import asyncio

# 本地 MCP 服务器（如 npx 启动的服务器）
mcp_server = MCPServerStdio(
    command="npx",
    args=["-y", "@modelcontextprotocol/server-github"],
    env={"GITHUB_PERSONAL_ACCESS_TOKEN": "your_token"},
)

# 等待服务器就绪
asyncio.run(mcp_server._start())
```

#### SSE（Server-Sent Events）

```python
from crewai.tools import MCPSSEConnection

sse_connection = MCPSSEConnection(
    sse_url="http://localhost:8000/sse",
    session_id="your_session_id",  # 可选
)

# 转换为例 MCP 服务器
```

#### Streamable HTTP

```python
from crewai.tools import MCPHTTPServer

mcp_http_server = MCPHTTPServer(
    url="http://localhost:8000/mcp",
)
```

## 17.4 将 MCP 工具挂载到 Agent

```python
from crewai import Agent, Task, Crew
from crewai.tools import MCPServerStdio

import asyncio

async def main():
    # 创建 MCP 服务器
    mcp_server = MCPServerStdio(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem"],
        args=["/tmp"],
    )
    
    await mcp_server._start()

    # 创建 Agent，使用 MCP 服务器提供的工具
    agent = Agent(
        role="文件管理器",
        goal="使用文件系统工具管理文件",
        backstory="精通文件操作的助手",
        tools=mcp_server.get_tools(),  # 获取 MCP 服务器暴露的所有工具
    )

    task = Task(
        description="列出 /tmp 目录中的文件",
        expected_output="文件列表",
        agent=agent,
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
    )

    result = await crew.kickoff_async()
    print(result)

asyncio.run(main())
```

## 17.5 多 MCP 服务器

同时连接多个 MCP 服务器，Agent 获得更丰富的工具集：

```python
from crewai.tools import MCPServerStdio
import asyncio

async def main():
    # 服务器 1：GitHub
    github_server = MCPServerStdio(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": "token1"},
    )
    
    # 服务器 2：Filesystem
    fs_server = MCPServerStdio(
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem"],
        args=["/projects"],
    )
    
    await github_server._start()
    await fs_server._start()
    
    # 合并所有工具
    all_tools = github_server.get_tools() + fs_server.get_tools()
    
    agent = Agent(
        role="全能助理",
        goal="管理项目文件并查看 GitHub 信息",
        backstory="精通 GitHub 和文件系统的助手",
        tools=all_tools,
    )
    # ... 继续创建任务和 Crew

asyncio.run(main())
```

## 17.6 DSL 集成（JSONC 配置）

在 `crew.jsonc` 中通过 DSL 集成 MCP：

```jsonc
{
  "agents": ["agent1"],
  "tasks": [
    {
      "name": "task1",
      "description": "...",
      "agent": "agent1"
    }
  ],
  "mcp_servers": {
    "github": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"
      }
    },
    "database": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

## 17.7 MCP 安全考虑

连接 MCP 服务器时注意：

1. **只连接可信服务器**：MCP 服务器拥有执行工具的能力，确保来自可信来源
2. **最小权限原则**：为 MCP 工具配置尽量少的权限
3. **密钥保护**：不要在代码中硬编码密钥，使用环境变量
4. **运行环境**：确保 MCP 服务器的运行环境与数据安全策略一致
5. **网络隔离**：远程 MCP 服务器确保使用 HTTPS 和认证

## 17.8 MCP 使用场景示例

| 场景 | MCP 服务器 |
|------|------------|
| GitHub 操作 | `server-github` |
| 文件系统 | `server-filesystem` |
| 数据库查询 | 自定义数据库 MCP |
| 网络搜索 | 搜索类 MCP（如 Brave Search MCP） |
| 浏览器自动化 | Playwright MCP |
| 数据库操作 | SQLite / Postgres MCP |

## 关键 API 速查

| API | 用途 |
|-----|------|
| `MCPServerStdio(command=, args=)` | stdio 协议服务器 |
| `MCPSSEConnection(sse_url=)` | SSE 协议连接 |
| `MCPHTTPServer(url=)` | Streamable HTTP 服务器 |
| `server.get_tools()` | 获取 MCP 服务器工具 |
| `asyncio.run(main())` | 异步运行 |
| DSL `mcp_servers` | JSONC 配置 MCP |

## 下一步

教程已完成！回顾 [README.md](README.md) 查看全部章节。
