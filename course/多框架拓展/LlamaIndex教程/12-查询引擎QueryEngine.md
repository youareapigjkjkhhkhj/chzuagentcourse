# 12 - 查询引擎 QueryEngine

本篇目标：掌握端到端问答接口 Query Engine 的进阶用法——子问题分解、多步查询、路由，以及对结构化数据（SQL / Pandas）的查询。

## 12.1 前置准备

```bash
pip install llama-index
```

## 12.2 什么是 Query Engine（官方定义）

> A query engine is an end-to-end flow that allows you to ask questions over your data. It takes in a natural language query, and returns a response, along with reference context retrieved and passed to the LLM.

它的内部 = Retriever（可选多个）+ Node Postprocessors + Response Synthesizer。

## 12.3 基础用法

```python
query_engine = index.as_query_engine(
    similarity_top_k=5,
    response_mode="compact",
)
response = query_engine.query("文档讲了什么？")
print(response)
print(response.source_nodes)
```

同步 `query()` 与异步 `aquery()`：

```python
response = await query_engine.aquery("文档讲了什么？")
```

## 12.4 手工组装（低层 API）

```python
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core import get_response_synthesizer
from llama_index.core.postprocessor import SimilarityPostprocessor

retriever = index.as_retriever(similarity_top_k=10)
synthesizer = get_response_synthesizer(response_mode="compact")

query_engine = RetrieverQueryEngine(
    retriever=retriever,
    response_synthesizer=synthesizer,
    node_postprocessors=[SimilarityPostprocessor(similarity_cutoff=0.7)],
)
```

## 12.5 子问题查询引擎（Sub-Question）

把复杂问题拆成多个子问题，分别在不同数据源上回答后汇总：

```python
from llama_index.core.tools import QueryEngineTool, ToolMetadata
from llama_index.core.query_engine import SubQuestionQueryEngine

# 为两个索引各建一个工具
tool_a = QueryEngineTool(
    query_engine=index_a.as_query_engine(),
    metadata=ToolMetadata(name="product_docs", description="产品功能与规格说明"),
)
tool_b = QueryEngineTool(
    query_engine=index_b.as_query_engine(),
    metadata=ToolMetadata(name="pricing_docs", description="定价与套餐政策"),
)

sub_engine = SubQuestionQueryEngine.from_defaults(
    query_engine_tools=[tool_a, tool_b],
    use_async=True,
)

response = sub_engine.query("企业版套餐包含哪些功能，价格是多少？")
```

## 12.6 多步查询（Multi-Step）

逐步拆解并迭代求解：

```python
from llama_index.core.query_engine import MultiStepQueryEngine

step_engine = MultiStepQueryEngine(
    query_engine=index.as_query_engine(similarity_top_k=3),
    query_transform=...,    # 步骤分解器
    num_steps=3,
)
```

## 12.7 路由器查询引擎

```python
from llama_index.core.query_engine import RouterQueryEngine
from llama_index.core.selectors import LLMSingleSelector

router_engine = RouterQueryEngine(
    selector=LLMSingleSelector.from_defaults(),
    query_engine_tools=[tool_a, tool_b],
)

print(router_engine.query("价格是多少？"))
```

## 12.8 结构化数据：Text-to-SQL

让 LLM 直接查关系数据库：

```bash
pip install llama-index-core sqlalchemy
```

```python
from sqlalchemy import create_engine
from llama_index.core import SQLDatabase
from llama_index.core.query_engine import NLSQLTableQueryEngine

engine = create_engine("postgresql+psycopg2://user:pwd@localhost:5432/mydb")
sql_database = SQLDatabase(engine, include_tables=["orders", "customers"])

query_engine = NLSQLTableQueryEngine(
    sql_database=sql_database,
    tables=["orders", "customers"],
)

response = query_engine.query("2025 年第三季度销售额最高的前 5 个客户是谁？")
print(response)

# 查看生成的 SQL（调试用）
print(response.metadata.get("sql_query"))
```

> 官方说明：结构化查询（SQL / Pandas）可以与非结构化文档 RAG **并存于同一个编排层**，不必外挂两套系统。

## 12.9 结构化数据：Text-to-Pandas

```python
import pandas as pd
from llama_index.core.query_engine import PandasQueryEngine

df = pd.read_csv("sales.csv")
query_engine = PandasQueryEngine(df=df, verbose=True)

response = query_engine.query("各区域销售额的平均值是多少？")
```

## 12.10 把 Query Engine 变成 Agent 的工具

Query Engine 天然就是 Agent 的一个工具（见 [15-Agents智能体.md](15-Agents智能体.md)）：

```python
from llama_index.core.tools import QueryEngineTool, ToolMetadata

rag_tool = QueryEngineTool(
    query_engine=index.as_query_engine(similarity_top_k=3),
    metadata=ToolMetadata(
        name="company_kb",
        description="回答公司制度、产品与流程相关问题",
    ),
)
```

## 关键 API 速查

| API | 说明 |
|-----|------|
| `index.as_query_engine(similarity_top_k=, response_mode=)` | 基础查询引擎 |
| `RetrieverQueryEngine(retriever=, response_synthesizer=, node_postprocessors=)` | 手工组装 |
| `SubQuestionQueryEngine.from_defaults(query_engine_tools=)` | 子问题分解 |
| `MultiStepQueryEngine(...)` | 多步查询 |
| `RouterQueryEngine(selector=, query_engine_tools=)` | 路由 |
| `NLSQLTableQueryEngine(sql_database=, tables=)` | Text-to-SQL |
| `PandasQueryEngine(df=)` | Text-to-Pandas |
| `QueryEngineTool(query_engine=, metadata=)` | 包装成工具 |

## 注意事项

- Text-to-SQL 会执行生成的 SQL——生产务必用**只读账号**并加超时/行数限制。
- 子问题/多步查询会放大 LLM 调用次数，注意成本与延迟。
- 路由器的效果强依赖 `description` 写得是否准确。
- 调试时优先看 `response.source_nodes` 与生成的 SQL，再调提示词。

## 下一步

→ [13-聊天引擎ChatEngine.md](13-聊天引擎ChatEngine.md)：从单轮问答走向多轮对话。
