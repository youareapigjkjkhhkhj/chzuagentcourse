# 06 - 模型配置 Settings

本篇目标：用 `Settings` 统一管理 LLM、Embedding、切分参数等全局配置，并掌握本地模型接入方式。

## 6.1 前置准备

```bash
pip install llama-index                                  # 默认含 OpenAI LLM/Embedding
# 本地模型可选
pip install llama-index-llms-ollama llama-index-embeddings-ollama
pip install llama-index-embeddings-huggingface
```

## 6.2 Settings 是什么

`Settings` 是 LlamaIndex 的**全局配置单例**，一次性设置后，所有未显式指定模型的组件都会使用它：

```python
from llama_index.core import Settings

Settings.llm = ...           # LLM
Settings.embed_model = ...   # Embedding 模型
Settings.chunk_size = 512    # 切分大小
Settings.chunk_overlap = 50  # 切分重叠
Settings.num_output = 512    # LLM 输出长度
Settings.context_window = 4096
```

## 6.3 配置 LLM（OpenAI）

```python
from llama_index.core import Settings
from llama_index.llms.openai import OpenAI

Settings.llm = OpenAI(model="gpt-4o-mini", temperature=0.1)
```

之后：

```python
index = VectorStoreIndex.from_documents(documents)   # embedding 用 Settings.embed_model
query_engine = index.as_query_engine()               # 生成用 Settings.llm
```

## 6.4 配置 Embedding

```python
from llama_index.core import Settings
from llama_index.embeddings.openai import OpenAIEmbedding

Settings.embed_model = OpenAIEmbedding(model="text-embedding-3-small")
```

常见 embedding 包：

| 提供方 | 包 |
|--------|-----|
| OpenAI | `llama-index-embeddings-openai` |
| HuggingFace（本地） | `llama-index-embeddings-huggingface` |
| Ollama（本地） | `llama-index-embeddings-ollama` |
| Azure OpenAI | `llama-index-embeddings-azure-openai` |
| FastEmbed（本地轻量） | `llama-index-embeddings-fastembed` |

## 6.5 本地模型（无 API Key）

### Ollama

```python
from llama_index.core import Settings, VectorStoreIndex, SimpleDirectoryReader
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding

Settings.llm = Ollama(model="llama3.2", request_timeout=120.0)
Settings.embed_model = OllamaEmbedding(model_name="nomic-embed-text")

index = VectorStoreIndex.from_documents(SimpleDirectoryReader("data").load_data())
print(index.as_query_engine().query("文档要点是什么？"))
```

### HuggingFace 本地 Embedding

```python
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

Settings.embed_model = HuggingFaceEmbedding(
    model_name="BAAI/bge-small-zh-v1.5"   # 中文场景常用
)
```

> 首次使用会下载模型权重，需联网并占用磁盘/内存。

## 6.6 局部覆盖（不污染全局）

某些组件需要不同模型时，直接传参覆盖：

```python
from llama_index.llms.openai import OpenAI

# 这个查询引擎用更强的模型，其他仍用 Settings.llm
strong_qe = index.as_query_engine(llm=OpenAI(model="gpt-4o"))

# 这个索引用另一种 embedding
index = VectorStoreIndex.from_documents(documents, embed_model=some_other_embedding)
```

## 6.7 常用 Settings 字段

| 字段 | 说明 |
|------|------|
| `llm` | 默认 LLM |
| `embed_model` | 默认 Embedding |
| `chunk_size` / `chunk_overlap` | 默认切分参数 |
| `num_output` | LLM 默认最大输出 token |
| `context_window` | 模型上下文窗口（影响上下文填充策略） |
| `node_parser` | 默认节点解析器 |
| `callback_manager` | 回调/可观测入口 |

## 6.8 验证配置是否生效

```python
from llama_index.core import Settings

print("LLM      :", Settings.llm)
print("Embedding:", Settings.embed_model)

# 单独测一次 embedding，确认维度正常
vec = Settings.embed_model.get_text_embedding("hello")
print("dim:", len(vec))
```

## 6.9 成本控制小贴士

| 做法 | 效果 |
|------|------|
| 索引持久化（[08](08-存储与持久化.md)） | 避免重复 embedding 付费 |
| 小文档用小 embedding 模型 | 降低索引成本 |
| 简单问答用便宜 LLM，复杂任务局部换强模型 | 降低推理成本 |
| 限制 `similarity_top_k` | 减少输入 token |

## 关键 API 速查

| API | 说明 |
|-----|------|
| `from llama_index.core import Settings` | 全局配置入口 |
| `Settings.llm = OpenAI(model=...)` | 配置 LLM |
| `Settings.embed_model = OpenAIEmbedding(model=...)` | 配置 Embedding |
| `Settings.chunk_size` / `chunk_overlap` | 切分参数 |
| `index.as_query_engine(llm=...)` | 局部覆盖 LLM |
| `embed_model.get_text_embedding(text)` | 手动验证 embedding |

## 注意事项

- 默认 LLM 与 Embedding 都是 **OpenAI**——未设 `OPENAI_API_KEY` 会在调用时报鉴权错误。
- 更改 `embed_model` 后**必须重建索引**（不同模型的向量空间不兼容）。
- Agents 需要能力较强的模型；官方提示小模型可靠性会下降。
- 生产环境建议显式设置 `llm` 与 `embed_model`，不要依赖默认值。

## 下一步

→ [07-索引Index.md](07-索引Index.md)：选择并创建合适的索引结构。
