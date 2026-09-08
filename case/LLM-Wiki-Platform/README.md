# LLM Wiki知识管理平台

面向企业运维团队的LLM Wiki知识管理平台，基于Flask + Vue 3 + TypeScript + MySQL构建，集成LangChain和LangGraph实现智能问答功能。

## 项目特性

- 基于大语言模型的智能问答系统
- 支持Markdown文档编辑和预览
- 多级分类和标签管理
- 全文搜索和语义搜索
- 用户权限管理
- 响应式设计，支持移动端

## 技术栈

### 后端
- Flask 3.0
- SQLAlchemy 2.0
- MySQL 8.0
- Redis
- Milvus向量数据库
- LangChain + LangGraph
- OpenAI API

### 前端
- Vue 3 + TypeScript
- Vite
- Element Plus
- Pinia状态管理
- Vue Router 4
- Axios

## 快速开始

### 环境要求

- Python 3.11+（Python 3.13 需 SQLAlchemy >= 2.0.31，见 requirements.txt 注释）
- Node.js 18+
- MySQL 8.0
- Redis 7.x
- Milvus 2.3+（当前开发环境连接远程 Milvus 3.0）

### 1. 克隆项目

```bash
git clone https://github.com/your-org/llm-wiki-platform.git
cd llm-wiki-platform
```

### 2. 后端设置

```bash
cd backend

# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows
.venv\Scripts\activate

# Linux/Mac
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件，配置数据库连接、Milvus 地址等信息
#   数据库:   DATABASE_URL=mysql+pymysql://wiki_user:wiki_password_2024@localhost:3306/wiki_platform
#   Milvus:   MILVUS_HOST=172.16.2.125   MILVUS_PORT=19530（可指向远程向量数据库）
#   OpenAI:   OPENAI_API_KEY / OPENAI_BASE_URL（chatanywhere 等兼容网关）

# 启动后端服务（自动建表并创建默认管理员 admin/admin123456）
python run.py
```

> 说明：项目无需 `flask db init/migrate/upgrade` 迁移流程——`run.py` 启动时会自动执行 `db.create_all()` 建表，并确保默认管理员账户存在。

### 3. 前端设置

```bash
cd frontend

# 安装依赖（npm 或 pnpm 均可）
npm install --registry=https://registry.npmmirror.com
# 或
pnpm install

# 启动开发服务器
npm run dev
# 或
pnpm dev
```

### 4. Docker部署（可选）

```bash
# 启动所有服务
docker-compose -f docker-compose.dev.yml up -d

# 访问应用
# 前端: http://localhost:3000
# 后端: http://localhost:5000
```

## 项目结构

```
LLM-Wiki-Platform/
├── docs/                    # 项目文档
│   ├── 01-项目概述.md
│   ├── 02-技术架构.md
│   ├── 03-数据库设计.md
│   ├── 04-后端开发手册.md
│   ├── 05-前端开发手册.md
│   └── 06-部署手册.md
├── backend/                 # 后端代码
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── models/
│   │   ├── api/
│   │   ├── services/
│   │   └── utils/
│   ├── requirements.txt
│   └── .env
├── frontend/                # 前端代码
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── views/
│   │   ├── stores/
│   │   └── types/
│   ├── package.json
│   └── tsconfig.json
└── docker-compose.yml
```

## 功能模块

1. **用户认证** - 登录、注册、权限管理
2. **文档管理** - 创建、编辑、删除、版本控制
3. **智能问答** - 基于知识库的AI问答
4. **分类标签** - 多级分类和标签管理
5. **搜索功能** - 全文搜索和语义搜索
6. **系统管理** - 用户管理、系统设置

## 默认账户

- 管理员: admin / admin123456

## 开发指南

### 后端开发

```bash
cd backend
flask run --debug
```

### 前端开发

```bash
cd frontend
npm run dev
```

### 代码规范

```bash
# 后端代码检查
flake8 app/
black app/
isort app/

# 前端代码检查
npm run lint
npm run type-check
```

## 测试

### 后端测试

```bash
cd backend
pytest tests/ -v
```

### 前端测试

```bash
cd frontend
npm run test:unit
```

## 部署

详细的部署指南请参考 [部署手册](docs/06-部署手册.md)。

## 文档

- [项目概述](docs/01-项目概述.md)
- [技术架构](docs/02-技术架构.md)
- [数据库设计](docs/03-数据库设计.md)
- [后端开发手册](docs/04-后端开发手册.md)
- [前端开发手册](docs/05-前端开发手册.md)
- [部署手册](docs/06-部署手册.md)

## 贡献指南

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

## 许可证

本项目使用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情

## 联系方式

- 项目主页: https://github.com/your-org/llm-wiki-platform
- 问题反馈: https://github.com/your-org/llm-wiki-platform/issues