# 数据库管理脚本

本目录包含用于数据库初始化、迁移和维护的实用脚本。

## 脚本列表

### 1. init_complete_db.py

**用途**: 完整的数据库初始化脚本，一次性完成所有设置。

**功能**:
- 检查环境配置
- 创建业务数据库表
- 启用 pgvector 扩展
- 创建向量数据库表
- 创建所有索引
- 初始化默认设置
- 验证数据库设置

**使用方法**:
```bash
python scripts/init_complete_db.py
```

**适用场景**:
- 首次部署
- 重新初始化数据库
- 开发环境设置

---

### 2. create_vector_index.py

**用途**: 创建或重建向量索引以加速向量搜索。

**功能**:
- 创建 HNSW 索引（适合大规模数据）
- 创建 IVFFlat 索引（适合中等规模数据）
- 根据数据量推荐索引类型
- 强制重建现有索引

**使用方法**:
```bash
# 使用默认参数创建 HNSW 索引
python scripts/create_vector_index.py

# 创建 IVFFlat 索引
python scripts/create_vector_index.py --index-type ivfflat

# 强制重建索引
python scripts/create_vector_index.py --force

# 自定义 HNSW 参数
python scripts/create_vector_index.py --m 32 --ef-construction 128

# 自定义 IVFFlat 参数
python scripts/create_vector_index.py --index-type ivfflat --lists 200
```

**参数说明**:
- `--force`: 强制重建索引（删除旧索引）
- `--index-type`: 索引类型（hnsw 或 ivfflat）
- `--m`: HNSW m 参数（2-100，默认 16）
- `--ef-construction`: HNSW ef_construction 参数（4-1000，默认 64）
- `--lists`: IVFFlat lists 参数（默认为行数的平方根）

**适用场景**:
- 向量表有一定数据量后创建索引
- 数据量大幅增加后重建索引
- 优化搜索性能

**索引选择建议**:
- 数据量 < 1万: 不需要索引
- 数据量 1万-10万: IVFFlat 索引
- 数据量 > 10万: HNSW 索引

---

### 3. seed_data.py

**用途**: 创建示例知识库和文档，方便测试和演示。

**功能**:
- 创建示例知识库（医学知识库、药品信息库、临床指南）
- 创建示例文档
- 清除现有数据（可选）

**使用方法**:
```bash
# 添加示例数据
python scripts/seed_data.py

# 清除现有数据后添加示例数据
python scripts/seed_data.py --clean
```

**参数说明**:
- `--clean`: 清除所有现有数据后再添加示例数据

**适用场景**:
- 开发环境测试
- 演示系统功能
- 学习系统使用

**注意事项**:
- 使用 `--clean` 参数会删除所有现有数据，请谨慎使用
- 示例文档默认为草稿状态，需要手动发布以触发向量化

---

### 4. run_migrations.py

**用途**: 执行 SQL 迁移脚本。

**功能**:
- 执行单个迁移文件
- 执行所有迁移文件
- 支持在不同数据库上执行

**使用方法**:
```bash
# 执行所有迁移（默认在向量数据库上）
python scripts/run_migrations.py

# 执行特定迁移文件
python scripts/run_migrations.py migrations/001_setup_pgvector.sql

# 在业务数据库上执行
python scripts/run_migrations.py --db business

# 在两个数据库上都执行
python scripts/run_migrations.py --db both
```

**参数说明**:
- `migration_file`: 要执行的迁移文件路径（可选）
- `--db`: 目标数据库（vector, business, both）

**适用场景**:
- 数据库架构升级
- 应用新的索引
- 修复数据库问题

---

## 使用流程

### 首次部署

```bash
# 1. 完整初始化
python scripts/init_complete_db.py

# 2. （可选）添加示例数据
python scripts/seed_data.py

# 3. 启动应用
python run.py
```

### 添加数据后优化

```bash
# 1. 创建向量索引
python scripts/create_vector_index.py

# 2. 验证索引
psql -U kb_user -d vectors -c "\d+ document_vectors"
```

### 数据库升级

```bash
# 1. 备份数据库
pg_dump -U kb_user -d vectors > backup.sql

# 2. 运行迁移
python scripts/run_migrations.py

# 3. 验证升级
python scripts/init_complete_db.py  # 会验证数据库设置
```

### 性能优化

```bash
# 1. 重建向量索引
python scripts/create_vector_index.py --force

# 2. 优化数据库
psql -U kb_user -d vectors -c "VACUUM ANALYZE;"
```

---

## 环境变量要求

所有脚本都需要以下环境变量（在 `.env` 文件中配置）：

```env
# 必需
DATABASE_URL=sqlite:///app.db
VECTOR_DATABASE_URL=postgresql://user:password@localhost:5432/vectors

# 可选（用于默认设置）
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
```

---

## 故障排除

### 脚本执行失败

1. 检查环境变量是否正确配置
2. 检查数据库连接是否正常
3. 查看详细错误信息
4. 检查 Python 依赖是否完整安装

### 数据库连接失败

```bash
# 测试 PostgreSQL 连接
psql -U kb_user -d vectors -c "SELECT version();"

# 检查 PostgreSQL 状态
sudo systemctl status postgresql
```

### pgvector 扩展问题

```bash
# 检查扩展是否安装
psql -U postgres -c "SELECT * FROM pg_available_extensions WHERE name = 'vector';"

# 手动启用扩展
psql -U postgres -d vectors -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 权限问题

```bash
# 授予用户权限
psql -U postgres -d vectors -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO kb_user;"
psql -U postgres -d vectors -c "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO kb_user;"
```

---

## 最佳实践

1. **首次部署**: 使用 `init_complete_db.py` 一次性完成所有设置
2. **索引创建**: 在有一定数据量后再创建向量索引
3. **定期维护**: 定期运行 `VACUUM ANALYZE` 优化数据库
4. **备份**: 在运行迁移或清除数据前先备份数据库
5. **测试**: 在生产环境前先在开发环境测试脚本

---

## 脚本开发指南

如果需要添加新的管理脚本，请遵循以下规范：

1. **文件命名**: 使用小写字母和下划线，如 `backup_database.py`
2. **文档字符串**: 在文件开头添加详细的文档字符串
3. **参数解析**: 使用 `argparse` 处理命令行参数
4. **错误处理**: 捕获并友好地显示错误信息
5. **日志输出**: 使用清晰的状态符号（✓, ✗, ⚠, ⏳）
6. **环境变量**: 使用 `python-dotenv` 加载环境变量
7. **退出码**: 成功返回 0，失败返回 1

---

## 相关文档

- [部署文档](../DEPLOYMENT.md)
- [快速开始](../QUICKSTART.md)
- [迁移文档](../migrations/README.md)
- [API 文档](../docs/)

---

## 贡献

欢迎提交新的管理脚本或改进现有脚本！
