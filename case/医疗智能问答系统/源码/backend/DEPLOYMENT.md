# 知识库管理系统 - 部署文档
若需要token提供一个测试账户：admin@example.com密码：123456
本文档描述如何部署知识库管理系统（基于 PostgreSQL + pgvector）。

## 目录

- [系统要求](#系统要求)
- [快速开始](#快速开始)
- [部署方式](#部署方式)
  - [方式 1: Docker 部署（推荐）](#方式-1-docker-部署推荐)
  - [方式 2: 手动部署](#方式-2-手动部署)
- [数据库初始化](#数据库初始化)
- [配置说明](#配置说明)
- [生产环境优化](#生产环境优化)
- [故障排除](#故障排除)

---

## 系统要求

### 最低要求

- **操作系统**: Linux (Ubuntu 20.04+), macOS, Windows Server
- **Python**: 3.9+
- **PostgreSQL**: 14+ (带 pgvector 扩展)
- **内存**: 2GB+
- **磁盘**: 10GB+

### 推荐配置

- **操作系统**: Ubuntu 22.04 LTS
- **Python**: 3.11
- **PostgreSQL**: 16 (带 pgvector 扩展)
- **内存**: 4GB+
- **磁盘**: 50GB+ (SSD)
- **CPU**: 2 核+

---

## 快速开始

### 使用 Docker Compose（最简单）

```bash
# 1. 克隆代码
git clone <repository-url>
cd knowledge-base-system

# 2. 配置环境变量
cp backend/.env.example backend/.env
# 编辑 backend/.env 文件，设置必要的配置

# 3. 启动服务
docker-compose up -d

# 4. 初始化数据库
docker-compose exec backend python scripts/init_complete_db.py

# 5. （可选）添加示例数据
docker-compose exec backend python scripts/seed_data.py

# 6. 访问应用
# 前端: http://localhost:3000
# 后端: http://localhost:5000
```

---

## 部署方式

### 方式 1: Docker 部署（推荐）

Docker 部署是最简单和可靠的方式，适合生产环境。

#### 1.1 安装 Docker 和 Docker Compose

```bash
# Ubuntu
sudo apt-get update
sudo apt-get install docker.io docker-compose

# 启动 Docker 服务
sudo systemctl start docker
sudo systemctl enable docker
```

#### 1.2 配置环境变量

```bash
cd backend
cp .env.example .env
```

编辑 `.env` 文件，至少修改以下配置：

```env
# 数据库密码（与 docker-compose.yml 中保持一致）
VECTOR_DATABASE_URL=postgresql://knowledge_base:kb_password_change_this@postgres:5432/vectors

# 安全密钥（使用强随机字符串）
SECRET_KEY=your-super-secret-key-change-this-in-production

# 嵌入模型配置（根据实际情况）
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
EMBEDDINGS_API_URL=http://host.docker.internal:11434/api/embeddings
```

#### 1.3 修改 docker-compose.yml

编辑 `docker-compose.yml`，修改数据库密码和其他配置：

```yaml
environment:
  POSTGRES_PASSWORD: your-secure-password-here
```

#### 1.4 启动服务

```bash
# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 查看服务状态
docker-compose ps
```

#### 1.5 初始化数据库

```bash
# 进入后端容器
docker-compose exec backend bash

# 运行初始化脚本
python scripts/init_complete_db.py

# 退出容器
exit
```

#### 1.6 验证部署

```bash
# 检查后端健康状态
curl http://localhost:5000/api/health

# 检查前端
curl http://localhost:3000
```

---

### 方式 2: 手动部署

手动部署适合开发环境或需要更多控制的场景。

#### 2.1 安装 PostgreSQL 和 pgvector

**Ubuntu/Debian:**

```bash
# 安装 PostgreSQL
sudo apt-get update
sudo apt-get install postgresql-16 postgresql-contrib-16

# 安装 pgvector
sudo apt-get install postgresql-16-pgvector

# 或从源码编译
git clone https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install
```

**macOS (Homebrew):**

```bash
# 安装 PostgreSQL
brew install postgresql@16

# 安装 pgvector
brew install pgvector
```

#### 2.2 创建数据库

```bash
# 切换到 postgres 用户
sudo -u postgres psql

# 在 PostgreSQL 中执行
CREATE DATABASE vectors;
CREATE USER knowledge_base WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE vectors TO knowledge_base;

# 启用 pgvector 扩展
\c vectors
CREATE EXTENSION vector;

# 退出
\q
```

#### 2.3 安装 Python 依赖

```bash
cd backend

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install --upgrade pip
pip install -r requirements.txt
```

#### 2.4 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
# 数据库配置
DATABASE_URL=sqlite:///app.db
VECTOR_DATABASE_URL=postgresql://knowledge_base:your_password@localhost:5432/vectors

# 应用配置
FLASK_ENV=production
DEBUG=False
HOST=0.0.0.0
PORT=5000

# 安全配置
SECRET_KEY=your-super-secret-key-change-this-in-production

# 嵌入模型配置
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
EMBEDDINGS_API_URL=http://localhost:11434/api/embeddings
```

#### 2.5 初始化数据库

```bash
# 运行完整初始化脚本
python scripts/init_complete_db.py

# 或分步执行
python init_db.py  # 初始化业务数据库
python init_pgvector_db.py  # 初始化向量数据库
python scripts/run_migrations.py  # 运行迁移脚本
```

#### 2.6 启动应用

```bash
# 开发模式
python run.py

# 生产模式（使用 Gunicorn）
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 run:app
```

#### 2.7 配置系统服务（可选）

创建 systemd 服务文件 `/etc/systemd/system/knowledge-base.service`:

```ini
[Unit]
Description=Knowledge Base Backend Service
After=network.target postgresql.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/backend
Environment="PATH=/path/to/backend/venv/bin"
ExecStart=/path/to/backend/venv/bin/gunicorn -w 4 -b 0.0.0.0:5000 run:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl start knowledge-base
sudo systemctl enable knowledge-base
sudo systemctl status knowledge-base
```

---

## 数据库初始化

### 完整初始化（推荐）

使用完整初始化脚本一次性完成所有设置：

```bash
python scripts/init_complete_db.py
```

此脚本会：
1. 检查环境配置
2. 创建业务数据库表
3. 启用 pgvector 扩展
4. 创建向量数据库表
5. 创建所有索引
6. 初始化默认设置
7. 验证数据库设置

### 分步初始化

如果需要更多控制，可以分步执行：

```bash
# 1. 初始化业务数据库（SQLite）
python init_db.py

# 2. 初始化向量数据库（PostgreSQL + pgvector）
python init_pgvector_db.py

# 3. 运行迁移脚本
python scripts/run_migrations.py

# 4. 创建向量索引（在有数据后）
python scripts/create_vector_index.py
```

### 添加示例数据

```bash
# 添加示例知识库和文档
python scripts/seed_data.py

# 清除现有数据并添加示例数据
python scripts/seed_data.py --clean
```

---

## 配置说明

### 数据库配置

```env
# 业务数据库（元数据）
DATABASE_URL=sqlite:///app.db  # 开发环境
# DATABASE_URL=postgresql://user:pass@host:5432/db  # 生产环境

# 向量数据库（必须是 PostgreSQL）
VECTOR_DATABASE_URL=postgresql://user:pass@host:5432/vectors
```

### 嵌入模型配置

#### 使用 Ollama（本地部署）

```env
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSION=768
EMBEDDINGS_API_URL=http://localhost:11434/api/embeddings
```

#### 使用 OpenAI

```env
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
EMBEDDINGS_API_URL=https://api.openai.com/v1/embeddings
OPENAI_API_KEY=sk-your-api-key-here
```

### 性能配置

```env
# 文本处理
CHUNK_SIZE=1000  # 文本块大小
CHUNK_OVERLAP=200  # 文本块重叠

# 搜索
SIMILARITY_THRESHOLD=0.7  # 相似度阈值
MAX_SEARCH_RESULTS=10  # 最大结果数

# 文件上传
MAX_CONTENT_LENGTH=52428800  # 50MB
```

---

## 生产环境优化

### 1. 数据库优化

#### PostgreSQL 配置

编辑 `/etc/postgresql/16/main/postgresql.conf`:

```conf
# 内存配置（根据服务器内存调整）
shared_buffers = 256MB
effective_cache_size = 1GB
maintenance_work_mem = 64MB
work_mem = 16MB

# 连接配置
max_connections = 100

# 查询优化
random_page_cost = 1.1  # SSD
effective_io_concurrency = 200  # SSD

# WAL 配置
wal_buffers = 16MB
checkpoint_completion_target = 0.9
```

#### 向量索引优化

```bash
# 创建 HNSW 索引（大规模数据）
python scripts/create_vector_index.py --index-type hnsw

# 或 IVFFlat 索引（中等规模数据）
python scripts/create_vector_index.py --index-type ivfflat
```

#### 定期维护

```bash
# 创建维护脚本
cat > /etc/cron.daily/postgres-maintenance << 'EOF'
#!/bin/bash
psql -U knowledge_base -d vectors -c "VACUUM ANALYZE;"
EOF

chmod +x /etc/cron.daily/postgres-maintenance
```

### 2. 应用优化

#### 使用 Gunicorn

```bash
# 安装 Gunicorn
pip install gunicorn

# 启动（4 个 worker）
gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 run:app
```

#### 使用 Nginx 反向代理

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /api {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
    }
}
```

### 3. 安全配置

```env
# 生产环境配置
FLASK_ENV=production
DEBUG=False
SECRET_KEY=<strong-random-key>
CORS_ORIGINS=https://your-domain.com
```

### 4. 监控和日志

```env
# 日志配置
LOG_LEVEL=INFO
LOG_FILE=./logs/app.log
```

---

## 故障排除

### 问题 1: pgvector 扩展未安装

**错误**: `extension "vector" does not exist`

**解决**:
```bash
# Ubuntu
sudo apt-get install postgresql-16-pgvector

# 或从源码编译
git clone https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install

# 然后在数据库中启用
psql -U postgres -d vectors -c "CREATE EXTENSION vector;"
```

### 问题 2: 数据库连接失败

**错误**: `could not connect to server`

**解决**:
1. 检查 PostgreSQL 是否运行: `sudo systemctl status postgresql`
2. 检查连接字符串是否正确
3. 检查防火墙设置: `sudo ufw allow 5432`
4. 检查 PostgreSQL 配置: `/etc/postgresql/16/main/pg_hba.conf`

### 问题 3: 向量索引创建失败

**错误**: `insufficient memory` 或 `timeout`

**解决**:
1. 增加 PostgreSQL 内存配置
2. 使用 IVFFlat 索引代替 HNSW
3. 分批创建索引
4. 在数据量较小时创建索引

### 问题 4: 嵌入 API 不可用

**错误**: `Connection refused` 或 `timeout`

**解决**:
1. 检查 Ollama 是否运行: `ollama list`
2. 检查 API 地址是否正确
3. 测试 API 连接: `curl http://localhost:11434/api/embeddings`
4. 检查防火墙设置

### 问题 5: 文件上传失败

**错误**: `413 Request Entity Too Large`

**解决**:
1. 增加 `MAX_CONTENT_LENGTH` 配置
2. 如果使用 Nginx，增加 `client_max_body_size`
3. 检查磁盘空间

---

## 备份和恢复

### 备份数据库

```bash
# 备份业务数据库（SQLite）
cp backend/app.db backup/app_$(date +%Y%m%d).db

# 备份向量数据库（PostgreSQL）
pg_dump -U knowledge_base -d vectors > backup/vectors_$(date +%Y%m%d).sql
```

### 恢复数据库

```bash
# 恢复业务数据库
cp backup/app_20241112.db backend/app.db

# 恢复向量数据库
psql -U knowledge_base -d vectors < backup/vectors_20241112.sql
```

---

## 升级指南

### 升级步骤

1. 备份数据库
2. 停止应用
3. 更新代码
4. 安装新依赖: `pip install -r requirements.txt`
5. 运行迁移: `python scripts/run_migrations.py`
6. 启动应用
7. 验证功能

---

## 性能基准

### 推荐配置下的性能指标

- **向量搜索**: < 100ms (10万条向量)
- **文档上传**: < 5s (10MB 文件)
- **向量化处理**: ~1s/页
- **并发请求**: 100+ req/s

---

## 支持和联系

如有问题，请：
1. 查看日志文件: `logs/app.log`
2. 检查数据库状态
3. 参考故障排除章节
4. 提交 Issue

---

## 许可证

[添加许可证信息]
