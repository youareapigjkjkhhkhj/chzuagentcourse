# AutoGen 0.7 教程

> 微软开源的**多智能体 AI 应用编程框架**（A programming framework for agentic AI）。本教程按官方 building blocks 顺序拆分知识点，每篇独立成档、代码均可按步骤运行。

## 环境要求

- **Python 3.10 及以上**（官方要求）
- 任意一家模型厂商的 API Key（OpenAI / Azure OpenAI / Gemini / Llama API / Ollama 本地模型等）
- 安装：`pip install -U "autogen-agentchat" "autogen-ext[openai]"`

## v0.4 架构：三层分层

AutoGen v0.4 起重构为分层架构（本教程主线是 **AgentChat 高层 API**）：

| 层 | 包名 | 定位 |
|----|------|------|
| AgentChat | `autogen-agentchat` | 高层：预设 Agent（`AssistantAgent`）、团队模式（`RoundRobinGroupChat`/`Swarm`/…）、终止条件。快速原型首选 |
| Core | `autogen-core` | 底层：事件驱动的 agent runtime、消息路由、模型客户端协议。构建自定义复杂编排 |
| Extensions | `autogen-ext` | 扩展：模型客户端（OpenAI/Azure/Ollama…）、代码执行、MCP、Memory（ChromaDB/Redis/Mem0）、缓存 |

> ⚠️ **从 v0.2 迁移**：Microsoft 已声明自 0.2.34 起 `pyautogen` 不再维护。v0.2 代码需重写：`from autogen import AssistantAgent, UserProxyAgent` → `from autogen_agentchat.agents import AssistantAgent`；同步 `initiate_chat` → 异步 `await team.run(...)`。详见官方 Migration Guide。

## 2.0/0.4 关键变化速查（v0.2 → v0.4/0.7）

| 维度 | v0.2（已停维护） | v0.4 / 0.7（本教程） |
|------|-----------------|---------------------|
| 导入 | `from autogen import AssistantAgent` | `from autogen_agentchat.agents import AssistantAgent` |
| 编排 | `user_proxy.initiate_chat(assistant, message=...)` | `await team.run(task=...)` / `run_stream` |
| 模型 | `llm_config={"config_list": [...]}` | `OpenAIChatCompletionClient(model="gpt-4o")` |
| 团队 | `GroupChat` + `GroupChatManager` | `RoundRobinGroupChat` / `Swarm` / `SelectorGroupChat` |
| 工具 | 由另一 Agent（UserProxy）执行 | **同一 Agent 内部直接执行**（`run()` 内完成调用） |
| 终��� | `is_termination_msg` 函数 | `TextMentionTermination` / `MaxMessageTermination` 等条件对象，支持 `&` `|` 组合 |
| 运行 | 同步 | 全异步（`asyncio`） |

## 教程顺序（官方 building blocks 心智模型）

| # | 文件 | 知识点 |
|---|------|--------|
| 0 | `README.md` | 总览 / 学习路径 / 版本变化 |
| 1 | `01-安装与环境配置.md` | 安装、验证版本、API Key 环境变量 |
| 2 | `02-快速开始.md` | 最简 Agent（`run`）+ 流式（`run_stream` + `Console`） |
| 3 | `03-模型客户端Models.md` | `OpenAIChatCompletionClient` / Azure / Ollama / `model_info` / 缓存 |
| 4 | `04-消息与消息类型.md` | `TextMessage`、`ToolCallRequestEvent`、`HandoffMessage`、`TaskResult` |
| 5 | `05-智能体Agent.md` | `AssistantAgent`、`run`/`run_stream`、多模态输入 |
| 6 | `06-工具Tools.md` | 函数工具、并行/串行调用、`reflect_on_tool_use`、`max_tool_iterations` |
| 7 | `07-MCP与外部工具.md` | `McpWorkbench`、`StdioServerParams`（Playwright 网页浏览） |
| 8 | `08-记忆Memory与RAG.md` | `ListMemory`、`ChromaDBVectorMemory`、文档索引与检索注入 |
| 9 | `09-团队Teams.md` | `RoundRobinGroupChat`、reset/resume、外部停止与取消 |
| 10 | `10-终止条件Termination.md` | 11 种内置条件、`&`/`|` 组合、自定义终止条件 |
| 11 | `11-多智能体模式Swarm.md` | `HandoffMessage` 交接、`handoffs` 参数、人机交接 |
| 12 | `12-人工协同HITL.md` | 移交给 `user`、`UserProxyAgent`、外部终止（停止按钮） |
| 13 | `13-自定义Agent.md` | `BaseChatAgent` 契约、实现 `on_messages` |
| 14 | `14-状态管理与序列化.md` | 团队状态延续、`reset()`、组件序列化 |
| 15 | `15-日志追踪与可观测.md` | logging 配置、OpenTelemetry 追踪 |
| 16 | `16-Studio与部署.md` | AutoGen Studio 无代码原型、Docker、生产建议 |

## 配套知识

- 多智能体框架对比：《[AgentScope教程](../AgentScope教程/README.md)》
- 应用编排基础：《[Langchain教程](../Langchain教程/README.md)》
- 生产可观测：《[Langfuse可观测性平台技术文档](../Langfuse可观测性平台技术文档.md)》

## 官方资源

- 文档：<https://microsoft.github.io/autogen/stable/>
- GitHub：<https://github.com/microsoft/autogen>
- AgentChat 用户指南：<https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/index.html>

> 本教程基于 **AutoGen 0.7.x**（`autogen-agentchat` / `autogen-core` / `autogen-ext` 同版本号发布）。升级：`pip install -U "autogen-agentchat" "autogen-ext[openai]"`。
