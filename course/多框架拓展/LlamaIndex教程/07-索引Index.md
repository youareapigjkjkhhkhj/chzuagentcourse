# 07 - 索引 Index

本篇目标：理解索引在 RAG 中的角色，掌握 `VectorStoreIndex` 及 LlamaIndex 提供的其他索引结构与选择依据。

## 7.1 前置准备

```bash
pip install llama-index
```

## 7.2 索引是什么（官方定义）

摄入数据后，LlamaIndex 帮你把数据索引成**便于检索的结构**。这通常意味着生成 **vector embeddings** 并存入专门的数据库（**vector store**），索引也可以存储关于数据的各种元数据。

它对应 RAG 五阶段中的 **Indexing** 阶段。

## 7.3 VectorStoreIndex（默认且最常用）

```python
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader

documents = SimpleDirectoryReader("data").load_data()
index = VectorStoreIndex.from_documents(documents)
```

背后发生的事：

1. 用节点解析器把 `Document` 切成 `Node`
2. 用 `Settings.embed_model` 为每个 Node 生成 embedding
3. 把向量写入向量存储（默认是内存中的 `SimpleVectorStore`）
4. 保留文本与元数据以便检索后取回

### 增量插入

```python
from llama_index.core import Document

index.insert(Document(text="新增的一段内容"))   # 插入单个文档
# 或 index.insert_nodes(nodes)
```

### 删除

```python
index.delete_ref_doc("doc_id")          # 按源文档 ID 删除
index.delete_nodes([node.node_id])      # 按节点 ID 删除
```

## 7.4 其他索引类型

| 索引 | 结构 | 适用 |
|------|------|------|
| `VectorStoreIndex` | 向量（embedding） | 通用语义检索，绝大多数场景 |
| `SummaryIndex` | 顺序存储所有节点 | 顺序阅读/摘要；检索时默认取全部节点 |
| `TreeIndex` | 树形层级摘要 | 长文档自顶向下归纳 |
| `KeywordTableIndex` | 关键词 → 节点映射 | 关键词匹配/精确术语检索 |
| `KnowledgeGraphIndex` | 知识图谱三元组 | 实体关系推理、多跳问答 |
| `DocumentSummaryIndex` | 每文档一份摘要 + 文档内节点 | 大批量文档的"先选文档再选片段" |
| `PropertyGraphIndex` | 属性图（节点+边带属性） | 结构化关系检索（较新的图索引实现） |

```python
from llama_index.core import SummaryIndex, KeywordTableIndex

summary_index = SummaryIndex.from_documents(documents)
keyword_index = KeywordTableIndex.from_documents(documents)
```

## 7.5 组合索引（Composability）

可以把多个索引包装成一个"可检索的整体"，配合路由器使用（见 [09-检索器Retriever.md](09-检索器Retriever.md)）：

```python
from llama_index.core import VectorStoreIndex, SummaryIndex

# 为同一批文档建立两种索引，各自转成工具/检索器后再路由
vector_index = VectorStoreIndex.from_documents(documents)
summary_index = SummaryIndex.from_documents(documents)
```

## 7.6 索引 → 检索器 / 查询引擎

索引本身只负责"组织数据"，真正问答要靠上层：

```python
retriever = index.as_retriever(similarity_top_k=5)     # 只要检索
query_engine = index.as_query_engine()                 # 检索 + 生成
chat_engine = index.as_chat_engine()                   # 检索 + 生成 + 多轮
```

## 7.7 索引类型选择建议

官方/社区经验：**先确定检索形态，再摄入数据**。如果先摄入后改策略，往往要重新切分与重建索引。

| 你的需求 | 建议 |
|----------|------|
| 通用问答、语义相似 | `VectorStoreIndex` |
| 全文摘要、顺读 | `SummaryIndex` |
| 精确术语/关键词命中 | `KeywordTableIndex` 或向量 + 关键词混合 |
| 实体关系、多跳推理 | `KnowledgeGraphIndex` / `PropertyGraphIndex` |
| 海量文档先筛文档 | `DocumentSummaryIndex` |

## 关键 API 速查

| API | 说明 |
|-----|------|
| `VectorStoreIndex.from_documents(docs)` | 建向量索引 |
| `VectorStoreIndex(nodes)` | 从已有节点建索引 |
| `index.insert(doc)` / `insert_nodes(nodes)` | 增量插入 |
| `index.delete_ref_doc(doc_id)` | 按源文档删除 |
| `index.as_retriever(...)` | 转检索器 |
| `index.as_query_engine(...)` | 转查询引擎 |
| `index.as_chat_engine(...)` | 转聊天引擎 |

## 注意事项

- 默认向量存储是**内存**的——进程结束即丢失，需要持久化请看 [08-存储与持久化.md](08-存储与持久化.md)。
- 更换 embedding 模型必须**重建索引**。
- 索引不是"越多越好"：先用 `VectorStoreIndex` 打底，检索质量不够再叠加策略（重排、混合、路由）。

## 下一步

→ [08-存储与持久化.md](08-存储与持久化.md)：把索引存下来，避免重复付费与等待。
