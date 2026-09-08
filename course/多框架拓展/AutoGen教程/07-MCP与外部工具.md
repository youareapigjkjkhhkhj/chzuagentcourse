# 07 - MCP 与外部工具

本篇目标：通过 **MCP（Model Context Protocol）** 把外部工具服务器接入 Agent，让 Agent 具备网页浏览等真实世界能力。

## 7.1 前置准备

```bash
pip install -U "autogen-agentchat" "autogen-ext[openai]"
# 本例用 Playwright MCP 服务器（需 Node.js）
npm install -g @playwright/mcp@latest
```

> ⚠️ 官方警告：**只连接可信的 MCP 服务器**——它们可能在本地执行命令或暴露敏感信息。

## 7.2 核心概念

| 概念 | 说明 |
|------|------|
| MCP | Model Context Protocol，工具服务器与客户端之间的标准协议 |
| `StdioServerParams` | 以**标准输入输出**启动本地 MCP 服务器进程的配置 |
| `SseServerParams` | 通过 **SSE/HTTP** 连接远程 MCP 服务器的配置 |
| `McpWorkbench` | AutoGen 侧的 MCP 工作台，把服务器暴露的工具交给 Agent |

## 7.3 完整示例：网页浏览助手

让 Agent 通过 Playwright MCP 服务器浏览网页并回答问题：

```python
import asyncio

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.ui import Console
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.tools.mcp import McpWorkbench, StdioServerParams


async def main() -> None:
    model_client = OpenAIChatCompletionClient(model="gpt-4.1")

    server_params = StdioServerParams(
        command="npx",
        args=["@playwright/mcp@latest", "--headless"],
    )

    async with McpWorkbench(server_params) as mcp:
        agent = AssistantAgent(
            "web_browsing_assistant",
            model_client=model_client,
            workbench=mcp,          # 多个 MCP 服务器可放列表
            model_client_stream=True,
            max_tool_iterations=10,
        )
        await Console(
            agent.run_stream(task="Find out how many contributors for the microsoft/autogen repository")
        )

    await model_client.close()


asyncio.run(main())
```

要点：
- `McpWorkbench` 用 `async with` 管理服务器进程生命周期（退出时自动关闭）。
- `workbench=mcp` 挂载；**多个服务器传列表**：`workbench=[mcp1, mcp2]`。
- `max_tool_iterations=10` 允许多轮网页操作（打开页面 → 滚动 → 提取）。

## 7.4 远程 MCP 服务器（SSE）

```python
from autogen_ext.tools.mcp import McpWorkbench, SseServerParams

server_params = SseServerParams(url="https://your-mcp-server/sse")
# 之后同样用 async with McpWorkbench(server_params) as mcp: ...
```

## 7.5 服务端：把 AutoGen 暴露为 MCP 服务

AutoGen 应用本身也能作为 MCP 服务器被其他客户端（Claude Desktop、Dify、n8n 等）调用，见 `apps/mcp` 与 `FastApiMCP` 集成（[16-Studio与部署.md](16-Studio与部署.md)）。

## 关键 API 速查

| API | 说明 |
|-----|------|
| `StdioServerParams(command=, args=)` | 本地进程型 MCP 服务器配置 |
| `SseServerParams(url=)` | 远程 SSE MCP 服务器配置 |
| `McpWorkbench(server_params)` | MCP 工作台（`async with` 使用） |
| `AssistantAgent(..., workbench=mcp)` | 挂载 MCP 工具 |
| `max_tool_iterations=N` | 允许多轮工具调用 |

## 注意事项

- **只连接可信 MCP 服务器**：它们具备本地命令执行能力。
- MCP 服务器进程随 `async with` 退出而关闭；不要在退出后再调用工具。
- 首次使用 Playwright MCP 需要下载浏览器内核（按 Playwright 官方指引执行安装）。
- 网页类任务耗时较长，建议配合流式输出与较大的 `max_tool_iterations`。

## 下一步

→ [08-记忆Memory与RAG.md](08-记忆Memory与RAG.md)：给 Agent 加长期记忆与文档检索能力。
