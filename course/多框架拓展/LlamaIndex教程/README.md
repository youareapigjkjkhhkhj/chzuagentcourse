# LlamaIndex 0.14 教程

> 面向**自有数据构建 LLM 智能体**的数据编排框架（The leading framework for building LLM-powered agents over your data）。本教程按官方「上下文增强（Context Augmentation）」心智模型拆分知识点，每篇独立成档、代码均可按步骤运行。

## 环境要求

- **Python 3.10 及以上、4.0 以下**（官方包要求）
- 任意 LLM 与 Embedding 提供方：OpenAI（默认）、Azure、Gemini、Anthropic，或本地 Ollama / HuggingFace
- 安装：`pip install llama-index`（starter bundle）

## 0.14 版本与生态

| 项 | 说明 |
|----|------|
| 当前版本 | **0.14.24**（2026-08 发布） |
| 命名空间包 | `llama-index-core`（核心）+ 数百个集成包（`llama-index-llms-*`、`llama-index-embeddings-*`、`llama-index-readers-*`、`llama-index-vector-stores-*`） |
| 工作方式 | 在 `llama_index.core` 下统一 API，按需安装集成包 |
| Python / TS | 官方同时提供 [LlamaIndex.TS](https://ts.llamaindex.ai/) |
| 文档站 | <https://developers.llamaindex.ai/python/framework/> |

> `llama-index` 是 **starter bundle**（伞包），会拉取 `llama-index-core` + `llama-index-llms-openai` + `llama-index-embeddings-openai` + `llama-index-readers-file`。生产建议**按需安装并锁版本**。

## 五大构建块（官方定义）

| 构建块 | 作用 |
|--------|------|
| **Data connectors** | 从原生来源与格式接入数据（API、PDF、SQL 等） |
| **Data indexes** | 把数据结构化为便于 LLM 消费的中间表示 |
| **Engines** | 自然语言访问数据：**Query engines**（问答/RAG）、**Chat engines**（多轮对话） |
| **Agents** | 由工具增强的 LLM 知识工作者（从简单函数到 API 集成） |
| **Workflows** | 事件驱动系统，把上述一切组合起来（比图式编排更灵活） |

外加 **Observability / Evaluation** 集成，形成"实验—评估—监控"闭环。

## 教程顺序（官方 RAG 五阶段 + 智能体编排）

| # | 文件 | 知识点 |
|---|------|--------|
| 0 | `README.md` | 总览 / 学习路径 / 生态 |
| 1 | `01-安装与环境配置.md` | 安装、锁版本、API Key、本地模型 |
| 2 | `02-快速开始.md` | 5 行 starter、远程 API 与本地模型两条路线 |
| 3 | `03-核心概念与上下文增强.md` | Agentic 应用特征、RAG 五阶段、Document/Node |
| 4 | `04-数据加载与连接器.md` | `SimpleDirectoryReader`、LlamaHub 连接器 |
| 5 | `05-文档节点与切分.md` | Node/Document、文本切分、元数据与节点解析 |
| 6 | `06-模型配置Settings.md` | 全局 LLM / Embedding 配置、本地模型 |
| 7 | `07-索引Index.md` | `VectorStoreIndex` 及各类索引结构与选择 |
| 8 | `08-存储与持久化.md` | `StorageContext`、持久化与重载、向量数据库 |
| 9 | `09-检索器Retriever.md` | `as_retriever`、top-k、混合检索、路由与递归检索 |
| 10 | `10-节点后处理与重排.md` | Postprocessor、Rerank、元数据过滤 |
| 11 | `11-响应合成与提示词.md` | Response Synthesizer、`response_mode`、自定义提示词 |
| 12 | `12-查询引擎QueryEngine.md` | `as_query_engine`、子问题/多步查询、结构化数据 |
| 13 | `13-聊天引擎ChatEngine.md` | `as_chat_engine`、`chat_mode`、流式与记忆 |
| 14 | `14-结构化数据提取.md` | Pydantic 抽取器、Schema 抽取、LlamaExtract |
| 15 | `15-Agents智能体.md` | `FunctionAgent`、`ReActAgent`、`CodeActAgent`、多智能体 |
| 16 | `16-Workflows工作流.md` | 事件驱动、`@step`、事件、`Context`、流式与人工协同 |
| 17 | `17-评估与部署.md` | Evaluation、LlamaCloud/LlamaParse、`llama_deploy` |

## 配套知识

- 多智能体框架对比：《[AgentScope教程](../AgentScope教程/README.md)》《[AutoGen教程](../AutoGen教程/README.md)》
- 应用编排基础：《[Langchain教程](../Langchain教程/README.md)》
- 相关项目实战：《[医疗智能问答系统](../医疗智能问答系统/项目文档/00-README.md)》（FAISS + RAG）、《[研究报告生成器](../研究报告生成器/项目文档/00-README.md)》（本地混合检索）

## 官方资源

- 文档：<https://developers.llamaindex.ai/python/framework/>
- GitHub：<https://github.com/run-llama/llama_index>
- LlamaHub（连接器/工具市场）：<https://llamahub.ai>
- LlamaCloud（LlamaParse / LlamaExtract / 托管索引检索）：<https://docs.cloud.llamaindex.ai/>
- 脚手架：`create-llama`（`npx create-llama@latest`）

> 本教程基于 **LlamaIndex 0.14.x**。升级：`pip install -U llama-index`；生产环境建议锁定版本。
