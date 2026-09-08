# 16 - Agent Service 与部署

本篇目标：把本地智能体升级为**生产级服务**——多租户、多会话、带 Web UI 与权限控制。这是 AgentScope 2.0 的「上层开箱即用能力」。

## 16.1 前置准备

```bash
git clone -b main https://github.com/agentscope-ai/agentscope.git
cd agentscope
pip install agentscope[full]
export DASHSCOPE_API_KEY="sk-你的密钥"
```

## 16.2 什么是 Agent Service

AgentScope 2.0 自带一个 **batteries-included 智能体服务**：

- **后端**：FastAPI，多租户、多会话隔离
- **前端**：预置 Web UI（`examples/web_ui`）
- 把你的 `Agent` 直接变成可多人使用、带权限的应用

## 16.3 两步启动（后端 + Web UI）

```bash
# 1) 后端：FastAPI，端口 8000
cd agentscope/examples/agent_service
python main.py

# 2) 另开一个终端，启动前端
cd agentscope/examples/web_ui
pnpm install
pnpm dev
```

浏览器打开前端，填入 `http://localhost:8000` 即可进入对话界面。在界面里可创建 Agent、绑定 Environment、发起 Session、查看 Dashboard 事件与运行时信息。

## 16.4 服务层能力一览

| 能力 | 提供什么 |
|------|----------|
| Serving | 多租户、多会话隔离、FastAPI 后端、预置 Web UI |
| Agent Team | Leader-worker 编排、内置 team tools、任务规划 |
| Channels | 连接 IM 平台——飞书（Lark）、Discord、自定义频道、消息路由 |
| RAG Service | Blob 存储 + index worker + 多租户检索 |
| MCP & Skill Hub | 浏览 GitHub MCP Registry / ClawHub，安装进库，加入 workspace |
| Resource Sharing | 组/组织级共享模型、MCP、技能、workspace |
| Persistence | Agent 状态与会话的 SQL & NoSQL 持久化 |
| Scheduling | 定时任务、智能体唤醒、后台任务卸载 |

> 所有能力**可组合**，你可以基于服务层用极少胶水代码拼出自己的应用。

## 16.5 多智能体团队协作（Web UI）

在 Web UI 下达一句话即可创建团队并自动协作：

```text
Create a team to survey what API are supported by these LLM vendors
```

→ Leader 建队 → 拆解「逐厂商调研」子任务 → 多 Worker 并行 → 汇总结构化报告。界面可实时看任务进度与成员状态。

## 16.6 分布式部署（Runtime / Knative）

生产部署用 **AgentScope Runtime**（容器沙箱 + K8s）：

```bash
pip install agentscope-runtime>=1.1.0

# 部署为 Knative Serverless 服务（具体参数以官方文档为准）
agentscope deploy
```

Runtime 提供：基于容器的安全沙箱（代码/文件/浏览器执行）、K8s 部署、会话持久化、中断恢复、负载均衡、高可用。

## 16.7 本地快速体验 vs 生产

| 场景 | 推荐方式 |
|------|----------|
| 学习 / 调试 | `launch_console`（终端）或 `npx @agentscope/studio` |
| 单人应用 | 脚本内 `Agent.reply` / `reply_stream` |
| 多人产品 | `examples/agent_service` + Web UI |
| 企业生产 | Runtime + K8s / Knative，多租户隔离 |

## 关键 API / 命令速查

| 命令 / 组件 | 说明 |
|-------------|------|
| `python examples/agent_service/main.py` | 启动服务后端（:8000） |
| `pnpm dev`（examples/web_ui） | 启动 Web UI |
| `npx @agentscope/studio` | 可视化监控 |
| `pip install agentscope-runtime` + `agentscope deploy` | 分布式部署 |

## 2.0 注意事项

- Agent Service 是**示例应用**（`examples/`），生产前需按官方文档配置认证、持久化与租户边界。
- 服务层与 SDK 共享同一套 `Agent` / `Toolkit` / `Workspace` 抽象，迁移成本低。
- 分布式 RAG Service、Channels、Scheduling 等能力以官方文档最新版为准（2.0 持续迭代中）。

## 收官

至此 16 篇教程覆盖 AgentScope 2.0 全栈：**SDK 构建**（模型/消息/Agent/工具/ReAct/记忆/权限/中间件/Workspace/多智能体/RAG/MCP）→ **可观测**（事件总线/Studio/console）→ **服务与部署**（Agent Service/Runtime）。

回到总目录：[README.md](README.md)。配套对比阅读：[Langchain教程](../Langchain教程/README.md)、[Langfuse 可观测性平台技术文档](../Langfuse可观测性平台技术文档.md)。
