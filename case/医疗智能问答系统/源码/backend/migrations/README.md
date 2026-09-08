# 数据库迁移脚本

本目录包含 PostgreSQL + pgvector 数据库的迁移脚本。

## 迁移文件

### 001_setup_pgvector.sql
启用 pgvector 扩展并创建向量索引。

**执行时机**: 在创建数据库表之后

**内容**:
- 启用 pgvector 扩展
- 创建 HNSW 向量索引（用于高效的向量相似度搜索）

### 002_create_indexes.sql
创建额外的性能索引。

**执行时机**: 在创建数据库表之后

**内容**:
- 知识库表索引
- 文档表索引
- 全文搜索索引

## 使用方法

### 方法 1: 使用完整初始化脚本（推荐）

```bash
cd backend
python scripts/init_complete_db.py
```

此脚本会自动：
1. 检查环境配置
2. 创建业务数据库表
3. 启用 pgvector 扩展
4. 创建向量数据库表
5. 创建所有索引
6. 初始化默认设置
7. 验证数据库设置

### 方法 2: 使用迁移脚本

```bash
cd backend

# 执行所有迁移
python scripts/run_migrations.py

# 或执行特定迁移
python scripts/run_migrations.py migrations/001_setup_pgvector.sql
```

### 方法 3: 手动执行 SQL 脚本

```bash
# 1. 首先启动应用以创建表
cd backend
python run.py

# 2. 然后执行迁移脚本
psql -U your_user -d your_database -f migrations/001_setup_pgvector.sql
psql -U your_user -d your_database -f migrations/002_create_indexes.sql
```

## 环境变量配置

确保在 `.env` 文件中配置以下变量：

```env
# PostgreSQL 数据库连接
DATABASE_URL=postgresql://user:password@localhost:5432/dbname

# 嵌入模型配置
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
EMBEDDINGS_API_URL=http://localhost:11434/api/embeddings
```

## 向量索引说明

### HNSW 索引
- **优点**: 查询速度快，适合大规模数据
- **缺点**: 构建时间较长，占用内存较多
- **适用场景**: 生产环境，数据量 > 10万条

### IVFFlat 索引
- **优点**: 构建速度快，内存占用少
- **缺点**: 查询速度较 HNSW 慢
- **适用场景**: 开发环境，数据量 < 10万条

### 无索引
- **适用场景**: 数据量 < 1万条，可以不创建索引

## 索引维护

### 重建向量索引

如果向量数据发生大量变化，可能需要重建索引：

```sql
-- 删除旧索引
DROP INDEX IF EXISTS idx_document_vectors_embedding;

-- 重建索引
CREATE INDEX idx_document_vectors_embedding 
ON document_vectors 
USING hnsw (embedding vector_cosine_ops);
```

### 查看索引状态

```sql
-- 查看所有索引
SELECT 
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename IN ('knowledge_bases', 'documents', 'document_vectors')
ORDER BY tablename, indexname;

-- 查看索引大小
SELECT
    indexname,
    pg_size_pretty(pg_relation_size(indexname::regclass)) as size
FROM pg_indexes
WHERE tablename = 'document_vectors';
```

## 故障排除

### pgvector 扩展未安装

如果遇到 "extension vector does not exist" 错误：

```bash
# Ubuntu/Debian
sudo apt-get install postgresql-14-pgvector

# macOS (Homebrew)
brew install pgvector

# 或从源码编译
git clone https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install
```

### 权限不足

如果遇到权限错误，确保数据库用户有足够的权限：

```sql
-- 授予创建扩展的权限
ALTER USER your_user WITH SUPERUSER;

-- 或者由超级用户创建扩展
CREATE EXTENSION IF NOT EXISTS vector;
```

### 索引创建失败

如果索引创建失败，可以：
1. 检查是否有足够的磁盘空间
2. 检查是否有足够的内存
3. 尝试使用 IVFFlat 索引代替 HNSW
4. 先添加数据，再创建索引

## 性能优化建议

1. **向量维度**: 使用较小的向量维度（如 768 或 1536）可以提高性能
2. **批量插入**: 使用批量插入而不是单条插入
3. **定期 VACUUM**: 定期运行 `VACUUM ANALYZE` 以优化查询性能
4. **连接池**: 使用连接池以提高并发性能

```sql
-- 优化表
VACUUM ANALYZE knowledge_bases;
VACUUM ANALYZE documents;
VACUUM ANALYZE document_vectors;
```
