# VectorManager 实现文档

## 概述

本文档描述了 `VectorManager` 类的实现，该类用于处理基于 pgvector 的文档向量化、存储和检索功能。

## 文件位置

- **主实现**: `backend/utils/vector_manager.py`
- **数据模型**: `backend/models/document_vector.py`
- **测试脚本**: `backend/test_vector_manager.py`

## 核心功能

### 1. 嵌入向量生成 (`generate_embedding`)

- 支持两种 API 格式：
  - **OpenAI 风格**: `{model, input}`
  - **Ollama 风格**: `{model, prompt}`
- 自动尝试两种格式，提高兼容性
- 返回向量列表或 None（失败时）

### 2. 文本分割 (`split_text`)

- 使用 `langchain` 的 `RecursiveCharacterTextSplitter`
- 支持自定义块大小和重叠大小
- 使用多种分隔符（段落、句子、标点等）
- 失败时返回原始文本

### 3. 文档向量化处理 (`process_document`)

- 完整的文档处理流程：
  1. 更新文档状态为 `processing`
  2. 分割文本为多个块
  3. 为每个块生成嵌入向量
  4. 存储到 pgvector 数据库
  5. 更新文档的 `chunk_count` 和 `vector_status`
- 支持自定义块大小和重叠
- 包含完整的错误处理和回滚机制
- 自动删除旧向量（重新处理时）

### 4. 向量删除 (`delete_document_vectors`, `delete_kb_vectors`)

- `delete_document_vectors`: 删除单个文档的所有向量
- `delete_kb_vectors`: 删除整个知识库的所有向量
- 包含事务管理和错误处理

### 5. 向量相似度搜索 (`search_similar`)

- 使用 pgvector 的余弦距离操作符 `<=>`
- 支持相似度阈值过滤
- 支持知识库范围限制
- 自动聚合同一文档的多个块
- 返回包含相似度分数的结果

### 6. 混合搜索 (`hybrid_search`)

- 结合向量搜索和 SQL 全文搜索
- 当向量搜索结果不足时，自动补充 SQL 搜索结果
- 去重处理（避免重复返回同一文档）
- 统一的结果格式

## 数据模型更新

### DocumentVector 模型修改

- 将 `metadata` 字段重命名为 `meta_data`（避免与 SQLAlchemy 保留字冲突）
- 字段说明：
  - `id`: 主键
  - `document_id`: 关联的文档ID
  - `kb_id`: 关联的知识库ID
  - `chunk_index`: 文本块索引
  - `chunk_text`: 文本块内容
  - `embedding`: 向量数据（pgvector Vector 类型）
  - `meta_data`: JSON 元数据（标题、分类、作者等）
  - `created_at`: 创建时间

## 使用示例

### 初始化

```python
from utils.vector_manager import VectorManager, get_vector_manager

# 方式1: 直接创建
vm = VectorManager(embedding_model='nomic-embed-text', dimension=1536)

# 方式2: 使用全局实例
vm = get_vector_manager()
```

### 处理文档

```python
from models.document import Document
from models.knowledge_base import KnowledgeBase

# 获取文档和知识库
document = Document.query.get(doc_id)
kb = KnowledgeBase.query.get(kb_id)

# 向量化处理
success = vm.process_document(document, kb)
```

### 搜索文档

```python
# 向量搜索
results = vm.search_similar(
    query="知识库管理",
    kb_id="kb123",
    limit=10,
    similarity_threshold=0.7
)

# 混合搜索
results = vm.hybrid_search(
    query="知识库管理",
    kb_id="kb123",
    limit=10
)
```

### 删除向量

```python
# 删除文档向量
vm.delete_document_vectors(document_id)

# 删除知识库所有向量
vm.delete_kb_vectors(kb_id)
```

## 配置

### 环境变量

- `EMBEDDING_MODEL`: 嵌入模型名称（默认: `nomic-embed-text`）
- `EMBEDDINGS_API_URL`: 嵌入 API 地址（默认: `http://127.0.0.1:11434/api/embeddings`）
- `VECTOR_DATABASE_URL`: 向量数据库连接字符串

### 默认参数

- 向量维度: 1536
- 块大小: 1000
- 块重叠: 200
- 相似度阈值: 0.7

## 错误处理

所有方法都包含完整的错误处理：

1. **嵌入生成失败**: 记录警告，返回 None
2. **文本分割失败**: 返回原始文本
3. **向量化失败**: 更新文档状态为 `failed`，记录错误信息
4. **数据库操作失败**: 自动回滚事务，记录错误日志

## 性能优化

1. **批量处理**: 在单个事务中处理所有文本块
2. **索引优化**: 使用复合索引加速查询
3. **结果聚合**: 智能合并同一文档的多个块
4. **降级策略**: 向量搜索失败时降级到 SQL 搜索

## 测试

运行测试脚本验证功能：

```bash
cd backend
python test_vector_manager.py
```

测试内容：
- VectorManager 初始化
- 文本分割功能
- 嵌入向量生成（需要 API 服务）

## 依赖项

- `langchain-text-splitters`: 文本分割
- `pgvector`: PostgreSQL 向量扩展
- `psycopg2-binary`: PostgreSQL 驱动
- `sqlalchemy`: ORM
- `requests`: HTTP 请求

## 下一步

1. 实现文件处理器（FileProcessor）
2. 创建 API 路由
3. 集成到前端界面
4. 添加批量处理功能
5. 性能测试和优化
