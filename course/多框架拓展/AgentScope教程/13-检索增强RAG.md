# 13 - 检索增强 RAG

本篇目标：给智能体接上「知识库」。2.0 把文档解析、切片、向量化、检索整条链路封装好，支持**库模式手动拼接**与**中间件自动注入**两种方式。

## 13.1 前置准备

```bash
pip install agentscope[full]   # 含 Embedding 与默认内存向量库依赖
export DASHSCOPE_API_KEY="sk-你的密钥"
```

## 13.2 核心概念

RAG（Retrieval-Augmented Generation）让智能体在回答前先从知识库检索相关片段，注入上下文后生成，缓解「幻觉」与「知识过时」。

2.0 的 RAG 支持两种姿势：

| 模式 | 行为 | 适用 |
|------|------|------|
| **静态模式** | 检索结果**自动注入**上下文（中间件驱动） | 固定知识库问答 |
| **Agentic 模式** | 智能体**自己决定何时检索** | 复杂多步、需判断的任务 |

默认使用**内存版向量库（Qdrant）**，零外部依赖，开箱即用。

## 13.3 嵌入模型（已支持）

RAG 依赖 Embedding，2.0 统一抽象（见 [03-模型Model.md](03-模型Model.md)）：

```python
from agentscope.model import DashScopeEmbedding

emb = DashScopeEmbedding(
    credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
    model="text-embedding-v3",
)
```

## 13.4 使用方式（官方示例）

AgentScope 2.0 的 RAG 既可「库模式手动拼接向量检索」，也可「中间件自动注入」。具体 API 见官方示例 `examples/rag/`（默认内存 Qdrant，零外部依赖）。

**静态模式（示意）**：RAG 中间件把检索结果自动拼进 system prompt 上下文——

```python
from agentscope.agent import Agent
from agentscope.middleware import RAGMiddleware  # 中间件类名以官方 examples/rag 为准

agent = Agent(
    name="KBAssistant",
    system_prompt="基于知识库回答用户问题。",
    model=DashScopeChatModel(...),
    # 中间件自动注入检索片段
    middlewares=[RAGMiddleware(index=your_qdrant_index)],
)
```

**Agentic 模式（示意）**：智能体通过工具主动检索——

```python
# 把检索能力作为工具暴露给 Agent，由模型决定调用时机
toolkit = Toolkit(tools=[retrieve_tool])
```

> RAG 中间件 / 索引构建的**确切类名与构造参数**以官方 `examples/rag/` 与文档为准；上文为结构示意，核心机制（静态自动注入 vs Agentic 主动检索、默认内存 Qdrant）已确认。

## 13.5 分布式 RAG 服务

2.0 还提供**分布式、多租户、多会话的 RAG Service**（详见 [16-代理Service与部署.md](16-代理Service与部署.md)）：blob 存储 + index worker + 多租户检索，适合生产级知识库场景。

## 关键 API 速查

| API/概念 | 说明 |
|----------|------|
| `DashScopeEmbedding(...)` | 嵌入模型 |
| RAG 中间件（自动注入） | 静态模式 |
| 检索工具（Agent 自决） | Agentic 模式 |
| 内存 Qdrant（默认） | 零依赖向量库 |

## 2.0 注意事项

- RAG 中间件的精确 API 以官方 `examples/rag/` 为准，勿凭记忆拼类名。
- 生产级用**分布式 RAG Service**，开发验证用默认内存 Qdrant 即可。
- Embedding 与 ChatModel 来自同一 `agentscope.model` 抽象，命名一致。

## 下一步

→ [14-MCP与SkillHub.md](14-MCP与SkillHub.md)：用 MCP 协议接入上千个现成外部工具。
