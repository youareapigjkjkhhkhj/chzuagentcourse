# 09 - 检索器 Retriever

本篇目标：掌握 RAG 五阶段中 **Querying** 的第一环——检索器：如何控制召回数量、做混合检索、路由与递归检索。

## 9.1 前置准备

```bash
pip install llama-index
```

## 9.2 检索器的角色（官方定义）

> A retriever defines how to efficiently retrieve relevant context from an index when given a query. **你的检索策略是召回相关性与效率的关键。**

索引负责"组织数据"，检索器负责"怎么取"。

## 9.3 最基础：as_retriever

```python
retriever = index.as_retriever(similarity_top_k=5)
nodes = retriever.retrieve("文档中关于定价的部分")

for node_with_score in nodes:
    print(round(node_with_score.score, 3), "|", node_with_score.node.text[:80])
```

`retrieve()` 返回 `NodeWithScore` 列表，含 `node` 与 `score`。

| 参数 | 说明 |
|------|------|
| `similarity_top_k` | 召回条数（默认通常为 2，建议显式设置） |
| `filters` | 元数据过滤（见 9.6） |

## 9.4 直接构造检索器

```python
from llama_index.core.retrievers import VectorIndexRetriever

retriever = VectorIndexRetriever(
    index=index,
    similarity_top_k=5,
)
```

## 9.5 混合检索（关键词 + 向量）

纯向量检索对专有名词、编号、精确术语不敏感。BM25 关键词检索可补足：

```bash
pip install llama-index-retrievers-bm25
```

```python
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.core.retrievers import QueryFusionRetriever

vector_retriever = index.as_retriever(similarity_top_k=5)
bm25_retriever = BM25Retriever.from_defaults(docstore=index.docstore, similarity_top_k=5)

# 融合两种检索结果（RRF 倒数排名融合）
fusion_retriever = QueryFusionRetriever(
    [vector_retriever, bm25_retriever],
    similarity_top_k=5,
    num_queries=1,          # >1 时会生成多个查询变体
    mode="reciprocal_rerank",
    use_async=True,
)

nodes = fusion_retriever.retrieve("2025 年 Q3 的产品定价策略")
```

> 部分向量库（Qdrant、Weaviate、PGVector 等）原生支持 hybrid 模式，可直接在 vector store 层开启。

## 9.6 元数据过滤

```python
from llama_index.core.vector_stores import MetadataFilters, MetadataFilter, FilterOperator

filters = MetadataFilters(
    filters=[
        MetadataFilter(key="department", value="finance", operator=FilterOperator.EQ),
        MetadataFilter(key="year", value=2024, operator=FilterOperator.GTE),
    ]
)

retriever = index.as_retriever(filters=filters, similarity_top_k=5)
```

常见操作符：`EQ`、`NE`、`GT`、`GTE`、`LT`、`LTE`、`IN`、`NIN`、`CONTAINS`、`TEXT_MATCH`。

> 过滤能力取决于底层向量库——`SimpleVectorStore` 支持基础精确匹配，生产建议用 Qdrant / PGVector 等。

## 9.7 路由器 Router（官方定义）

> A router determines which retriever will be used to retrieve relevant context. `RouterRetriever` 依据候选检索器的元数据与查询，选择一个或多个执行。

```python
from llama_index.core.retrievers import RouterRetriever
from llama_index.core.selectors import LLMSingleSelector
from llama_index.core.tools import RetrieverTool

# 假设有两个索引：财务文档 / 技术文档
finance_tool = RetrieverTool.from_defaults(
    retriever=finance_index.as_retriever(similarity_top_k=3),
    description="用于回答财务、预算、成本相关问题",
)
tech_tool = RetrieverTool.from_defaults(
    retriever=tech_index.as_retriever(similarity_top_k=3),
    description="用于回答技术架构、接口、部署相关问题",
)

retriever = RouterRetriever(
    selector=LLMSingleSelector.from_defaults(),
    retriever_tools=[finance_tool, tech_tool],
)

nodes = retriever.retrieve("我们的技术栈是什么？")
```

## 9.8 递归检索与自动合并

长文档常用"小 chunk 检索、大 chunk 生成"：

```python
from llama_index.core.node_parser import HierarchicalNodeParser
from llama_index.core.retrievers import AutoMergingRetriever

# 1) 建索引时用层次解析器
node_parser = HierarchicalNodeParser.from_defaults()
nodes = node_parser.get_nodes_from_documents(documents)
index = VectorStoreIndex(nodes, storage_context=storage_context)

# 2) 检索时用自动合并检索器
base_retriever = index.as_retriever(similarity_top_k=6)
retriever = AutoMergingRetriever(base_retriever, storage_context, verbose=True)

nodes = retriever.retrieve("总结一下第三章的结论")
```

## 9.9 检索调优清单

| 症状 | 调整 |
|------|------|
| 召回太少/答非所问 | 增大 `similarity_top_k`；换更强 embedding；加 BM25 混合 |
| 噪声多、答案被无关片段带偏 | 减小 top_k；加重排（[10](10-节点后处理与重排.md)）；设相似度阈值 |
| 专有名词检索不到 | 加关键词/BM25 检索 |
| 长文档答案不完整 | 用层次解析 + 自动合并检索 |
| 多主题混杂 | 用 Router 分索引检索 |

## 关键 API 速查

| API | 说明 |
|-----|------|
| `index.as_retriever(similarity_top_k=)` | 获取向量检索器 |
| `retriever.retrieve(q)` → `NodeWithScore` | 执行检索 |
| `VectorIndexRetriever(index=, similarity_top_k=)` | 显式构造 |
| `BM25Retriever.from_defaults(docstore=)` | 关键词检索 |
| `QueryFusionRetriever([...], mode="reciprocal_rerank")` | 多检索器融合 |
| `MetadataFilters` / `MetadataFilter` | 元数据过滤 |
| `RouterRetriever(selector=, retriever_tools=)` | 路由检索 |
| `AutoMergingRetriever(base, storage_context)` | 自动合并检索 |

## 注意事项

- `similarity_top_k` 不是越大越好：过多上下文会稀释注意力并增加成本。
- 融合检索与重排通常能带来最直观的效果提升。
- 更换检索策略一般**不需要重建索引**（除非涉及不同节点解析/嵌入）。

## 下一步

→ [10-节点后处理与重排.md](10-节点后处理与重排.md)：对召回结果做过滤、重排与裁剪。
