# 快速开始指南

本指南帮助您在 5 分钟内启动知识库管理系统。

## 前置要求

- Python 3.9+
- PostgreSQL 14+ (带 pgvector 扩展)
- Git

## 步骤 1: 克隆代码

```bash
git clone <repository-url>
cd knowledge-base-system
```

## 步骤 2: 安装 PostgreSQL 和 pgvector

### Ubuntu/Debian

```bash
sudo apt-get update
sudo apt-get install postgresql-16 postgresql-16-pgvector
```

### macOS

```bash
brew install postgresql@16 pgvector
brew services start postgresql@16
```

### Windows

下载并安装 PostgreSQL 16，然后从源码编译 pgvector。

## 步骤 3: 创建数据库

```bash
# 切换到 postgres 用户
sudo -u postgres psql

# 创建数据库和用户
CREATE DATABASE vectors;
CREATE USER kb_user WITH PASSWORD 'kb_password';
GRANT ALL PRIVILEGES ON DATABASE vectors TO kb_user;

# 启用 pgvector 扩展
\c vectors
CREATE EXTENSION vector;
\q
```

## 步骤 4: 配置后端

```bash
cd backend

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
```

编辑 `.env` 文件，修改数据库连接：

```env
VECTOR_DATABASE_URL=postgresql://kb_user:kb_password@localhost:5432/vectors
```

## 步骤 5: 初始化数据库

```bash
python scripts/init_complete_db.py
```

## 步骤 6: （可选）添加示例数据

```bash
python scripts/seed_data.py
```

## 步骤 7: 启动后端

```bash
python run.py
```

后端将在 http://localhost:5000 启动。

## 步骤 8: 配置前端

```bash
cd ../frotend

# 安装依赖
npm install
# 或使用 pnpm
pnpm install

# 启动开发服务器
npm run dev
# 或
pnpm dev
```

前端将在 http://localhost:5173 启动。

## 步骤 9: 访问应用

打开浏览器访问 http://localhost:5173

## 下一步

- 创建知识库
- 上传文档
- 进行搜索测试

## 使用 Docker（更简单）

如果您安装了 Docker 和 Docker Compose：

```bash
# 配置环境变量
cp backend/.env.example backend/.env

# 启动所有服务
docker-compose up -d

# 初始化数据库
docker-compose exec backend python scripts/init_complete_db.py

# 访问应用
# 前端: http://localhost:3000
# 后端: http://localhost:5000
```

## 故障排除

### PostgreSQL 连接失败

```bash
# 检查 PostgreSQL 状态
sudo systemctl status postgresql

# 启动 PostgreSQL
sudo systemctl start postgresql
```

### pgvector 扩展未安装

```bash
# Ubuntu
sudo apt-get install postgresql-16-pgvector

# 然后在数据库中启用
sudo -u postgres psql -d vectors -c "CREATE EXTENSION vector;"
```

### 端口被占用

修改 `.env` 文件中的 `PORT` 配置，或停止占用端口的程序。

## 获取帮助

- 查看完整部署文档: [DEPLOYMENT.md](DEPLOYMENT.md)
- 查看 API 文档: [docs/](docs/)
- 提交 Issue

## 配置嵌入模型

### 使用 Ollama（推荐用于本地开发）

```bash
# 安装 Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 下载嵌入模型
ollama pull nomic-embed-text

# 修改 .env
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSION=768
EMBEDDINGS_API_URL=http://localhost:11434/api/embeddings
```

### 使用 OpenAI

修改 `.env`:

```env
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536
EMBEDDINGS_API_URL=https://api.openai.com/v1/embeddings
OPENAI_API_KEY=sk-your-api-key-here
```

## 测试安装

```bash
# 测试后端健康状态
curl http://localhost:5000/api/health

# 测试数据库连接
python -c "from models.document_vector import get_vector_session; print('✓ 数据库连接成功')"

# 测试嵌入 API
curl -X POST http://localhost:11434/api/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"nomic-embed-text","prompt":"test"}'
```


