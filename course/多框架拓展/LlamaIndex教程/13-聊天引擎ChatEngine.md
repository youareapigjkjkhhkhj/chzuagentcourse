# 13 - 聊天引擎 ChatEngine

本篇目标：把索引变成**多轮对话**接口——理解 `chat_mode` 各模式差异、保持上下文记忆、实现流式与重置。

## 13.1 前置准备

```bash
pip install llama-index
```

## 13.2 什么是 Chat Engine（官方定义）

> A chat engine is an end-to-end flow for having a conversation with your data (multiple back-and-forth instead of a single question-and-answer).

与 Query Engine 的区别：**Chat Engine 维护对话历史**，能理解"它是什么意思？"这类依赖上文的追问。

## 13.3 最小用法

```python
chat_engine = index.as_chat_engine()

print(chat_engine.chat("这份文档的核心观点是什么？"))
print(chat_engine.chat("能用一句话总结吗？"))     # 依赖上一轮上下文
```

## 13.4 chat_mode 详解

```python
chat_engine = index.as_chat_engine(chat_mode="condense_plus_context")
```

| 模式 | 行为 | 适用 |
|------|------|------|
| `best` | 自动选择（当前等价于 `condense_plus_context`） | 不确定时的默认 |
| `condense_question` | 先把"追问 + 历史"压缩成一个**独立问题**，再走普通 RAG | 追问多、上下文长 |
| `context` | 直接在检索到的上下文 + 历史上做问答 | 需要严格贴合资料 |
| `condense_plus_context` | **先压缩问题检索，再结合历史与上下文作答**（常用） | 大多数知识库问答 |
| `simple` | 不检索，直接用 LLM 对话 | 无需知识库时 |
| `react` | 以 ReAct 方式决定是否调用检索工具 | 需要多步/工具推理 |

```python
# 严格依据资料、少发挥
strict_chat = index.as_chat_engine(chat_mode="context")

# 追问场景，自动把代词补全
condense_chat = index.as_chat_engine(chat_mode="condense_question")
```

## 13.5 异步调用

```python
response = await chat_engine.achat("总结一下第三章")
```

## 13.6 流式输出

```python
chat_engine = index.as_chat_engine(chat_mode="condense_plus_context", streaming=True)

response = chat_engine.stream_chat("请介绍文档的主要内容")
for token in response.response_gen:
    print(token, end="", flush=True)
```

## 13.7 历史与重置

Chat Engine 内部维护 `chat_history`：

```python
chat_engine = index.as_chat_engine()

chat_engine.chat("我叫小明")
chat_engine.chat("我叫什么？")       # 能答上来

chat_engine.reset()                  # 清空历史，开启新会话
chat_engine.chat("我叫什么？")       # 已遗忘
```

直接查看/接管历史：

```python
for msg in chat_engine.chat_history:
    print(msg.role, "|", msg.content[:60])
```

## 13.8 自定义系统提示与上下文提示

```python
from llama_index.core import PromptTemplate

custom_prompt = PromptTemplate(
    "你是一个严谨的企业知识库助手。\n"
    "以下是相关资料：\n{context_str}\n"
    "请依据资料用简体中文回答；资料未覆盖的内容请说明不确定。\n"
    "用户问题：{query_str}"
)

chat_engine = index.as_chat_engine(
    chat_mode="context",
    system_prompt="你是企业知识库助手，回答必须基于资料。",
    context_template=custom_prompt,
)
```

> 不同 `chat_mode` 可用的模板参数略有差异（如 `condense_question` 用 `condense_prompt`），以官方 API 文档为准。

## 13.9 低层构造

```python
from llama_index.core.chat_engine import CondensePlusContextChatEngine

chat_engine = CondensePlusContextChatEngine.from_defaults(
    retriever=index.as_retriever(similarity_top_k=5),
    llm=Settings.llm,
    node_postprocessors=[],
)
```

## 13.10 与 Agent 的边界

| 场景 | 选择 |
|------|------|
| 基于知识库的多轮问答 | **Chat Engine** |
| 需要调用多个工具、自主决定步骤 | **Agent**（[15](15-Agents智能体.md)） |
| 需要确定性多步流程编排 | **Workflow**（[16](16-Workflows工作流.md)） |

官方建议：即使是聊天机器人或 Agent，底层通常也依赖 RAG 技术——Chat Engine 与 Agent 可以组合（把 RAG 查询引擎作为 Agent 的一个工具）。

## 关键 API 速查

| API | 说明 |
|-----|------|
| `index.as_chat_engine(chat_mode=)` | 创建聊天引擎 |
| `chat_engine.chat(msg)` / `achat(msg)` | 同步/异步对话 |
| `chat_engine.stream_chat(msg)` → `response.response_gen` | 流式 |
| `chat_engine.reset()` | 清空历史 |
| `chat_engine.chat_history` | 查看历史 |
| `CondensePlusContextChatEngine.from_defaults(...)` | 低层构造 |

## 注意事项

- 多轮对话会累积 token——长会话要定期 `reset()` 或裁剪历史。
- 资料严格性要求高时，用 `context` 模式并在提示词中禁止编造。
- 流式输出依赖模型与 LLM 集成支持；不支持时退回非流式。
- 每个用户会话应持有**独立的 chat_engine 实例**，避免串话。

## 下一步

→ [14-结构化数据提取.md](14-结构化数据提取.md)：从文档里抽出结构化字段。
