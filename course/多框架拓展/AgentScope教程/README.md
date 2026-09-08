# AgentScope 2.0 教程

> 阿里通义实验室开源的**生产级多智能体框架**，以「看得見、管得住、信得过」为核心设计理念。本教程按官方 building blocks 顺序拆分知识点，每篇独立成档、代码均可按步骤运行。

## 环境要求

- **Python 3.11 及以上**（官方硬性要求）
- 任意一家模型厂商的 API Key（DashScope / OpenAI / Anthropic / Gemini / DeepSeek / Moonshot / xAI / Ollama 均可）
- 安装：`pip install agentscope`（完整依赖 `pip install agentscope[full]`）

## 2.0 关键变化（相对 1.0 是 Breaking Change）

| 维度 | 1.0（已废弃） | 2.0（本教程） |
|------|--------------|--------------|
| 初始化 | `agentscope.init(model_configs=...)` | 不再需要，直接传 `model=` 对象 |
| 消息 | `from agentscope.message import Msg` | `from agentscope.message import UserMsg` |
| 对话智能体 | `DialogAgent(name=, model_config_name=)` | `Agent(name=, model=DashScopeChatModel(...))` |
| 模型配置 | `model_config.json` + `config_name` | `DashScopeChatModel(credential=DashScopeCredential(api_key=...), model=...)` |
| 记忆 | `Memory` 类 | `AgenticMemoryMiddleware` / ReMe / Mem0 中间件 |
| 运行 | 同步 `agent(msg)` | 异步 `await agent.reply(msg)` / `async for ... agent.reply_stream(msg)` |
| 多智能体 | `MsgHub` / `SequentialPipeline`（旧签名） | `pipeline.SequentialPipeline` + Agent Team |

> ⚠️ 本教程**全部基于 2.0**，请勿将 1.0 旧代码混入。若 `import agentscope; print(agentscope.__version__)` 输出 `1.x`，请升级：`pip install -U agentscope`。

## 教程顺序（官方 building blocks 心智模型）

| # | 文件 | 知识点 |
|---|------|--------|
| 0 | `README.md` | 总览 / 学习路径 / 2.0 关键变化 |
| 1 | `01-安装与环境配置.md` | 安装、验证版本、API Key 环境变量 |
| 2 | `02-快速开始.md` | 最简 Agent（`launch_console`）+ 最简脚本（`reply`/`reply_stream`） |
| 3 | `03-模型Model.md` | `DashScopeChatModel` / `Credential`、多提供商配对、参数 |
| 4 | `04-消息与事件系统.md` | `UserMsg`、`reply` / `reply_stream`、`EventType` |
| 5 | `05-智能体Agent.md` | `Agent` 类、`ContextConfig`、核心方法 |
| 6 | `06-工具与Toolkit.md` | `@tool` 自定义、内置 `Bash/Read/Write/Edit/Grep/Glob`、`Toolkit` |
| 7 | `07-ReAct循环与工具调用.md` | `Agent` 内置 ReAct、顺序/并发工具执行、中断恢复 |
| 8 | `08-记忆Memory.md` | `AgenticMemoryMiddleware`、ReMe / Mem0 后端 |
| 9 | `09-权限与人工协同.md` | 权限系统、HITL 确认、bypass 模式 |
| 10 | `10-中间件Middleware.md` | 可组合钩子（reply/reasoning/acting/model…） |
| 11 | `11-工作区与沙箱Workspace.md` | `LocalWorkspace`、`Docker` / `E2B` 隔离执行 |
| 12 | `12-多智能体协作AgentTeam.md` | `SequentialPipeline`、leader-worker、team tools |
| 13 | `13-检索增强RAG.md` | RAG 中间件、内存 Qdrant、静态 / agentic 模式 |
| 14 | `14-MCP与SkillHub.md` | `MCPClient`、`Http/Stdio` 配置、Skill Hub |
| 15 | `15-流式输出与可观测.md` | 事件总线、`Studio`、`console` 调试 |
| 16 | `16-AgentService与部署.md` | FastAPI 服务、Web UI、Channels、Runtime/Knative |

## 配套知识

- 模型架构基础：《[Transformer 架构技术原理文档](../Transformer架构技术原理文档.md)》《[MoE 混合专家架构技术文档](../MoE混合专家架构技术原理文档.md)》
- 应用编排对比：《[Langchain教程](../Langchain教程/README.md)》
- 生产可观测：《[Langfuse 可观测性平台技术文档](../Langfuse可观测性平台技术文档.md)》

> 官方资源：[docs.agentscope.io](https://docs.agentscope.io/) · [GitHub](https://github.com/agentscope-ai/agentscope)
