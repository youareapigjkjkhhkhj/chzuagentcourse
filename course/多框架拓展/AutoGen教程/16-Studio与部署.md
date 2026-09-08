# 16 - Studio 与部署

本篇目标：用 **AutoGen Studio** 零代码原型多智能体工作流，并掌握容器化部署与生产化建议。

## 16.1 AutoGen Studio（无代码 GUI）

AutoGen Studio 是一个可视化原型工具：拖拽组建 Agent 团队、配置模型与工具、直接在浏览器中运行与调试。

```bash
# 安装
pip install -U "autogenstudio"

# 启动（默认 http://localhost:8080）
autogenstudio ui --port 8080 --appdir ./my-app
```

`--appdir` 指定工作目录（团队配置、上传文件、运行记录保存在此）。

典型流程：

1. 打开 `http://localhost:8080`
2. 配置模型（Models）：填服务商、模型名、API Key
3. 创建 Agent（Agents）：写 system_message、绑定工具
4. 组建团队（Teams）：选择 `RoundRobinGroupChat` / `Swarm` / `SelectorGroupChat` 等模式
5. 在 Playground 中运行对话，观察消息流
6. 导出配置（可落到代码版本管理）

官方 Studio 指南：<https://microsoft.github.io/autogen/stable/user-guide/autogenstudio-user-guide/index.html>

## 16.2 代码方式运行（生产推荐）

Studio 适合原型；生产环境建议把配置落成代码：

```python
import asyncio

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import TextMentionTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.ui import Console
from autogen_ext.models.openai import OpenAIChatCompletionClient


async def main() -> None:
    model_client = OpenAIChatCompletionClient(model="gpt-4o")
    team = RoundRobinGroupChat(
        [AssistantAgent("writer", model_client=model_client),
         AssistantAgent("critic", model_client=model_client)],
        termination_condition=TextMentionTermination("APPROVE"),
    )
    await Console(team.run_stream(task="Write a product launch email."))
    await model_client.close()


asyncio.run(main())
```

## 16.3 用 FastAPI 包装成服务

把团队运行暴露成 HTTP 接口（流式可用 SSE）：

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()


@app.post("/run")
async def run(task: str):
    async def event_stream():
        async for message in team.run_stream(task=task):
            yield f"data: {message.model_dump_json()}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

> 多会话场景要给每个会话维护独立的 team 实例（或用 `save_state`/`load_state` 切换）。
> 官方也提供 `FastApiMCP` 集成，可把 AutoGen 团队直接作为 MCP 服务器对外提供（见仓库 `apps/mcp`）。

## 16.4 Docker 部署

官方容器化思路（以官方镜像/自建镜像为准）：

```bash
docker build -t my-autogen-app .
docker run -d \
  --name my-autogen-app \
  -p 8000:8000 \
  -e OPENAI_API_KEY=sk-... \
  my-autogen-app
```

`Dockerfile` 要点：

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`requirements.txt` 示例：

```text
autogen-agentchat==0.7.5
autogen-core==0.7.5
autogen-ext==0.7.5
fastapi
uvicorn[standard]
```

## 16.5 生产化检查清单

| 项 | 建议 |
|----|------|
| 密钥 | 用环境变量 / 密钥管理服务，绝不入库或写死 |
| 客户端生命周期 | 每次运行结束 `await model_client.close()` |
| 超时与预算 | 配 `TimeoutTermination` + `TokenUsageTermination` |
| 并发 | 每个会话独立 team 实例；共享模型客户端时注意线程安全 |
| 状态 | 用 `save_state`/`load_state` 或外部存储实现多轮会话持久化 |
| 可观测 | 接 OpenTelemetry / 集中式日志（见 [15-日志追踪与可观测.md](15-日志追踪与可观测.md)） |
| 工具安全 | MCP/代码执行仅在可信、隔离环境（容器/沙箱）中启用 |
| 人机协同 | 高风险操作保留人工确认（见 [12-人工协同HITL.md](12-人工协同HITL.md)） |

## 16.6 集成到外部应用

AutoGen 可作为能力提供方被集成：

| 方式 | 说明 |
|------|------|
| Web 嵌入 / 弹窗 | Studio 与部分生态组件支持前端嵌入 |
| MCP 服务 | 通过 `FastApiMCP` 把团队暴露为 MCP 服务器，供 Claude Desktop、Dify、n8n 等调用 |
| HTTP API | 自建 FastAPI 服务（SSE 流式） |
| 消息队列/Celery | 长任务异步化，前端轮询结果 |

## 关键 API 速查

| 命令/API | 说明 |
|----------|------|
| `pip install -U autogenstudio` | 安装 Studio |
| `autogenstudio ui --port 8080 --appdir ./my-app` | 启动 Studio |
| `uvicorn main:app --host 0.0.0.0 --port 8000` | 启动自建服务 |
| `StreamingResponse(..., media_type="text/event-stream")` | SSE 流式接口 |

## 注意事项

- Studio 面向**原型与演示**，生产建议代码化 + 容器化。
- 容器中注意时区、日志落盘、健康检查与优雅退出。
- 若启用代码执行器，务必使用 Docker 隔离执行，禁止在宿主机器直接运行模型生成的代码。

## 教程完结

至此 16 篇覆盖了 AutoGen 0.7 的主干：环境 → 单 Agent → 模型 → 消息 → 工具 → MCP → 记忆/RAG → 团队 → 终止 → Swarm → 人工协同 → 自定义 Agent → 状态 → 可观测 → 部署。

继续深入可转向 **AutoGen Core**（事件驱动 runtime、自定义 runtime 与跨语言协作）：
<https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/index.html>
