# 数据库架构文档

## 概述

本系统采用**混合数据库架构**，将业务数据和向量数据分离存储：

- **SQLite**: 存储业务元数据（知识库、文档、用户等）
- **PostgreSQL + pgvector**: 存储向量数据（文档嵌入向量）

## 架构优势

1. **简化部署**: 业务数据使用 SQLite，无需额外配置
2. **性能优化**: 向量搜索使用 PostgreSQL + pgvector，获得最佳性能
3. **灵活扩展**: 可以独立扩展向量数据库
4. **数据隔离**: 业务数据和向量数据物理隔离，提高安全性

## 数据库连接配置

### SQLite（业务数据库）

```env
DATABASE_URL=sqlite:///app.db
```

### PostgreSQL（向量数据库）

```env
VECTOR_DATABASE_URL=postgresql://user:password@localhost:5432/vectors
```

## 数据模型

### SQLite 数据库表

#### 1. knowledge_bases（知识库）

存储知识库的基本信息。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | String(50) | 主键 |
| name | String(200) | 知识库名称 |
| description | Text | 描述 |
| embedding_model | String(100) | 使用的嵌入模型 |
| status | String(20) | 状态：active, archived |
| created_by | String(100) | 创建者 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

#### 2. documents（文档）

存储文档的元数据和内容。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | String(50) | 主键 |
| kb_id | String(50) | 外键 → knowledge_bases.id |
| title | String(200) | 文档标题 |
| content | Text | 文档内容 |
| category | String(50) | 分类 |
| tags | Text | 标签（JSON 格式） |
| author | String(100) | 作者 |
| views | Integer | 浏览量 |
| status | String(20) | 状态：draft, processing, published, failed |
| file_name | String(255) | 文件名 |
| file_type | String(50) | 文件类型 |
| file_size | Integer | 文件大小 |
| chunk_count | Integer | 分块数量 |
| vector_status | String(20) | 向量化状态：pending, processing, completed, failed |
| vector_error | Text | 向量化错误信息 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

#### 3. knowledge_base_settings（设置）

存储知识库系统的全局设置。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | String(50) | 主键（默认 'default'） |
| vector_db_type | String(50) | 向量数据库类型（pgvector） |
| embedding_model | String(100) | 嵌入模型名称 |
| embedding_dimension | Integer | 向量维度 |
| chunk_size | Integer | 文本块大小 |
| chunk_overlap | Integer | 文本块重叠 |
| similarity_threshold | Float | 相似度阈值 |
| max_search_results | Integer | 最大搜索结果数 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

#### 4. users（用户）

存储用户信息。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| username | String(80) | 用户名 |
| password_hash | String(255) | 密码哈希 |
| email | String(120) | 邮箱 |
| role | String(20) | 角色 |
| created_at | DateTime | 创建时间 |

#### 5. model_config（模型配置）

存储 AI 模型配置。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | String(50) | 主键 |
| name | String(100) | 模型名称 |
| provider | String(50) | 提供商 |
| type | String(20) | 类型 |
| model_name | String(100) | 模型标识 |
| api_key | String(255) | API 密钥 |
| api_endpoint | String(255) | API 端点 |
| temperature | Float | 温度参数 |
| max_tokens | Integer | 最大 token 数 |
| top_p | Float | Top-p 参数 |
| status | String(20) | 状态 |
| is_default | Boolean | 是否默认 |
| description | Text | 描述 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### PostgreSQL 数据库表

#### document_vectors（文档向量）

存储文档的向量数据，用于语义搜索。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | String(50) | 主键 |
| document_id | String(50) | 文档 ID（引用 SQLite 中的 documents.id） |
| kb_id | String(50) | 知识库 ID（引用 SQLite 中的 knowledge_bases.id） |
| chunk_index | Integer | 文本块索引 |
| chunk_text | Text | 文本块内容 |
| embedding | Vector(1536) | 嵌入向量（pgvector 类型） |
| metadata | JSON | 元数据 |
| created_at | DateTime | 创建时间 |

**索引**:
- `idx_document_vectors_kb_doc`: (kb_id, document_id)
- `idx_document_vectors_chunk`: (document_id, chunk_index)
- `idx_document_vectors_embedding`: HNSW 向量索引

## 数据流

### 文档创建流程

```
1. 用户上传文档
   ↓
2. 保存文档元数据到 SQLite (documents 表)
   status = 'draft'
   vector_status = 'pending'
   ↓
3. 用户发布文档
   ↓
4. 更新 status = 'published'
   vector_status = 'processing'
   ↓
5. 文本分块 + 生成向量
   ↓
6. 保存向量到 PostgreSQL (document_vectors 表)
   ↓
7. 更新 SQLite 中的文档
   vector_status = 'completed'
   chunk_count = N
```

### 向量搜索流程

```
1. 用户输入搜索关键词
   ↓
2. 生成查询向量
   ↓
3. 在 PostgreSQL 中进行向量相似度搜索
   SELECT * FROM document_vectors
   ORDER BY embedding <=> query_vector
   LIMIT 10
   ↓
4. 获取匹配的 document_id 列表
   ↓
5. 从 SQLite 中查询文档详情
   SELECT * FROM documents
   WHERE id IN (...)
   ↓
6. 返回搜索结果
```

### 文档删除流程

```
1. 用户删除文档
   ↓
2. 从 PostgreSQL 删除向量数据
   DELETE FROM document_vectors
   WHERE document_id = ?
   ↓
3. 从 SQLite 删除文档元数据
   DELETE FROM documents
   WHERE id = ?
```

## 数据一致性

### 外键关系

由于使用了两个独立的数据库，无法使用数据库级别的外键约束。需要在应用层保证数据一致性：

1. **删除文档时**: 先删除 PostgreSQL 中的向量，再删除 SQLite 中的文档
2. **删除知识库时**: 先删除所有文档的向量，再删除文档，最后删除知识库
3. **事务处理**: 使用应用层事务确保操作的原子性

### 数据同步

提供数据同步工具，确保两个数据库的数据一致：

```python
# 检查孤立的向量数据（在 PostgreSQL 中存在，但在 SQLite 中不存在）
def find_orphaned_vectors():
    vector_session = get_vector_session()
    sqlite_session = db.session
    
    # 获取所有向量的 document_id
    vector_doc_ids = set([v.document_id for v in vector_session.query(DocumentVector.document_id).distinct()])
    
    # 获取所有文档的 id
    doc_ids = set([d.id for d in sqlite_session.query(Document.id).all()])
    
    # 找出孤立的向量
    orphaned = vector_doc_ids - doc_ids
    return orphaned

# 清理孤立的向量数据
def cleanup_orphaned_vectors():
    orphaned = find_orphaned_vectors()
    if orphaned:
        vector_session = get_vector_session()
        vector_session.query(DocumentVector).filter(
            DocumentVector.document_id.in_(orphaned)
        ).delete(synchronize_session=False)
        vector_session.commit()
```

## 初始化步骤

### 1. 初始化 SQLite 数据库

```bash
cd backend
python init_db.py
```

这将创建所有业务数据表。

### 2. 初始化 PostgreSQL 向量数据库

```bash
cd backend
python init_pgvector_db.py
```

这将：
- 启用 pgvector 扩展
- 创建 document_vectors 表
- 创建向量索引

## 备份和恢复

### SQLite 备份

```bash
# 备份
cp backend/app.db backend/app.db.backup

# 恢复
cp backend/app.db.backup backend/app.db
```

### PostgreSQL 备份

```bash
# 备份
pg_dump -U user -d vectors > vectors_backup.sql

# 恢复
psql -U user -d vectors < vectors_backup.sql
```

## 性能优化

### SQLite 优化

```sql
-- 启用 WAL 模式
PRAGMA journal_mode=WAL;

-- 增加缓存大小
PRAGMA cache_size=-64000;  -- 64MB

-- 启用外键约束
PRAGMA foreign_keys=ON;
```

### PostgreSQL 优化

```sql
-- 定期 VACUUM
VACUUM ANALYZE document_vectors;

-- 重建向量索引（如果性能下降）
REINDEX INDEX idx_document_vectors_embedding;

-- 查看索引使用情况
SELECT * FROM pg_stat_user_indexes WHERE indexrelname LIKE 'idx_document_vectors%';
```

## 故障排除

### 问题 1: 向量数据库连接失败

**症状**: 无法连接到 PostgreSQL

**解决方案**:
1. 检查 `VECTOR_DATABASE_URL` 配置
2. 确认 PostgreSQL 服务正在运行
3. 检查防火墙设置
4. 验证用户名和密码

### 问题 2: 数据不一致

**症状**: SQLite 中有文档，但 PostgreSQL 中没有向量

**解决方案**:
1. 检查文档的 `vector_status` 字段
2. 如果是 `failed`，查看 `vector_error` 字段
3. 重新向量化文档：`POST /api/kb/{kb_id}/documents/{doc_id}/vectorize`

### 问题 3: 向量搜索性能差

**症状**: 搜索响应时间过长

**解决方案**:
1. 检查是否创建了向量索引
2. 运行 `VACUUM ANALYZE document_vectors`
3. 考虑增加 PostgreSQL 的 `shared_buffers` 和 `work_mem`
4. 如果数据量很大，考虑使用 IVFFlat 索引代替 HNSW

## 监控和维护

### 数据库大小监控

```python
# SQLite 大小
import os
sqlite_size = os.path.getsize('backend/app.db')
print(f"SQLite 大小: {sqlite_size / 1024 / 1024:.2f} MB")

# PostgreSQL 大小
SELECT pg_size_pretty(pg_database_size('vectors'));
```

### 向量数据统计

```sql
-- 总向量数
SELECT COUNT(*) FROM document_vectors;

-- 每个知识库的向量数
SELECT kb_id, COUNT(*) as vector_count
FROM document_vectors
GROUP BY kb_id;

-- 向量索引大小
SELECT pg_size_pretty(pg_relation_size('idx_document_vectors_embedding'));
```
