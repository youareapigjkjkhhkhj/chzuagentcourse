# 10 - 中间件 Middleware

本篇目标：理解 2.0 的「可组合钩子」机制——**非侵入式**地修改智能体运行时行为（如记忆注入、上下文压缩、权限检查）。

## 10.1 前置准备

```bash
pip install agentscope[full]
export DASHSCOPE_API_KEY="sk-你的密钥"
```

## 10.2 什么是中间件

中间件是挂在 `Agent` 生命周期**关键节点**上的可组合钩子，让你不改智能体核心代码就能扩展能力。2.0 在以下节点提供钩子：

| 钩子节点 | 作用 |
|----------|------|
| `reply` | 回复前后拦截/改写 |
| `reasoning` | 推理阶段 |
| `acting` | 工具行动前后 |
| `model calling` | 模型调用前后（如日志、限流） |
| `permission checking` | 权限校验（见 [09-权限与人工协同.md](09-权限与人工协同.md)） |
| `context compression` | 上下文压缩（见 [05-智能体Agent.md](05-智能体Agent.md)） |
| `system prompt` | 系统提示注入（如注入 RAG 检索结果） |

## 10.3 注入中间件

所有中间件通过 `Agent(middlewares=[...])` 传入，已是确定保真 API：

```python
from agentscope.agent import Agent
from agentscope.middleware import AgenticMemoryMiddleware
from agentscope.workspace import LocalWorkspace

async with LocalWorkspace(workdir="./workspace") as ws:
    agent = Agent(
        name="Friday",
        system_prompt="You are a helpful assistant.",
        model=DashScopeChatModel(...),
        toolkit=Toolkit(tools=await ws.list_tools()),
        middlewares=[
            AgenticMemoryMiddleware(workdir=ws.workdir, backend=ws.get_backend()),
            # 可叠加更多：上下文压缩中间件、权限中间件、RAG 中间件…
        ],
    )
```

## 10.4 内置现成中间件

| 中间件 | 作用 | 见篇 |
|--------|------|------|
| `AgenticMemoryMiddleware` | 长期记忆持久化 | [08-记忆Memory.md](08-记忆Memory.md) |
| 上下文压缩中间件 | 自动压缩（由 `ContextConfig` 驱动） | [05-智能体Agent.md](05-智能体Agent.md) |
| 权限中间件 | 工具调用前确认/bypass | [09-权限与人工协同.md](09-权限与人工协同.md) |
| RAG 中间件 | 自动注入检索结果 | [13-检索增强RAG.md](13-检索增强RAG.md) |

## 10.5 自定义中间件（示意）

自定义中间件需继承 `agentscope.middleware` 中的基类并实现对应钩子方法。以下为**结构示意**（确切基类与方法名以官方文档为准）：

```python
from agentscope.middleware import Middleware  # 基类名称以官方文档为准


class LoggingMiddleware(Middleware):
    """在每次模型调用前后打日志（示意）"""

    async def on_model_call(self, payload):
        print("[before model call]", payload.model)
        return payload

    async def on_reply(self, reply):
        print("[after reply]", reply.content[:50])
        return reply
```

> 自定义中间件的精确基类与钩子签名请查阅官方 `agentscope.middleware` 模块文档；内置 `AgenticMemoryMiddleware` 等可直接使用，已在前述篇目验证。

## 关键 API 速查

| API | 说明 |
|-----|------|
| `Agent(middlewares=[...])` | 注入中间件列表 |
| `AgenticMemoryMiddleware(...)` | 现成记忆中间件 |
| `Middleware` 子类 | 自定义钩子（以官方基类为准） |

## 2.0 注意事项

- 中间件是「非侵入」扩展点；优先用现成中间件，避免手写循环内逻辑（会丢失压缩/权限/流式能力）。
- 多个中间件按列表顺序串联执行。
- 自定义中间件务必参考官方 `agentscope.middleware` 文档，基类方法名不要臆测。

## 下一步

→ [11-工作区与沙箱Workspace.md](11-工作区与沙箱Workspace.md)：把工具执行隔离进安全沙箱。
