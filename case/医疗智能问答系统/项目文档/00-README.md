# 医疗智能问答系统 - 项目文档

## 项目简介

基于 Flask + React 的医疗智能问答系统，集成了 **AI 智能问答（RAG）**、**医学图像分析**、**知识库管理** 三大核心能力，面向眼科糖尿病视网膜病变（DR）辅助诊断场景。

## 系统能力

| 能力 | 说明 |
|------|------|
| AI 智能问答 | 基于知识库的 RAG 检索增强生成，支持多轮对话、SSE 流式输出 |
| 医学图像分析 | 6 模型集成推理，自动分级糖尿病视网膜病变（0-4 级），生成诊断报告 |
| 知识库管理 | 文档上传、自动向量化（pgvector）、混合检索、全文搜索 |
| 用户认证 | JWT 认证、角色权限（admin/doctor/user）、个人信息管理 |
| 模型管理 | 支持 OpenAI、Ollama、通义千问等多种 LLM/Embedding 模型配置 |
| 会话历史 | 聊天会话持久化、历史记录查询、统计分析 |

## 技术栈

| 层级 | 技术 |
|------|------|
| **前端** | React 18 + TypeScript + Vite + Tailwind CSS + React Router |
| **后端** | Python 3.9+ + Flask + SQLAlchemy + Flask-Login |
| **数据库** | SQLite（元数据） + PostgreSQL + pgvector（向量存储） |
| **向量模型** | Ollama（bge-m3/nomic-embed-text）或 OpenAI text-embedding |
| **大语言模型** | OpenAI / Ollama / 通义千问 |
| **图像模型** | EfficientNet-B3/B5/B8 + ResNet50/152 + DenseNet121 + ViT（集成推理） |
| **文件处理** | pypdf / python-docx / openpyxl / python-pptx / BeautifulSoup |

## 项目结构

```
源码/
├── backend/                    # 后端 Flask 应用
│   ├── app/                    # 应用工厂
│   │   └── __init__.py         # create_app() 入口
│   ├── models/                 # SQLAlchemy 数据模型
│   │   ├── base.py             # db 实例
│   │   ├── user.py             # 用户模型
│   │   ├── chat.py             # 聊天会话/消息模型
│   │   ├── knowledge_base.py   # 知识库模型
│   │   ├── document.py         # 文档模型
│   │   ├── document_vector.py  # pgvector 向量模型
│   │   ├── model.py            # AI 模型配置
│   │   ├── image_analysis.py   # 图像分析/诊断报告模型
│   │   └── settings.py         # 全局设置模型
│   ├── routes/                 # API 路由蓝图
│   │   ├── auth.py             # 认证（注册/登录/Token）
│   │   ├── users.py            # 用户管理
│   │   ├── chat.py             # AI 问答（含 SSE 流式）
│   │   ├── chat_history.py     # 聊天历史
│   │   ├── kb.py               # 知识库 CRUD
│   │   ├── models.py           # 模型管理
│   │   ├── settings.py         # 系统设置
│   │   ├── image_analysis.py   # 图像分析
│   │   └── reports.py          # 诊断报告
│   ├── services/               # 业务服务层
│   │   ├── chat_service.py     # 聊天会话/消息 CRUD
│   │   ├── image_processor.py  # 图像预处理
│   │   └── model_manager.py    # 深度学习模型管理
│   ├── utils/                  # 工具函数
│   │   ├── auth.py             # JWT 认证工具
│   │   ├── response.py         # 统一响应格式
│   │   ├── validators.py       # 数据验证器
│   │   ├── file_processor.py   # 文件文本提取
│   │   └── vector_manager.py   # 向量存储/检索管理
│   ├── scripts/                # 数据库初始化脚本
│   ├── migrations/             # SQL 迁移脚本
│   ├── train_model/            # 预训练模型权重目录
│   ├── datasets/               # 训练数据集
│   ├── detect/                 # 模型检测/评估脚本
│   ├── requirements.txt        # Python 依赖
│   ├── run.py                  # 应用启动入口
│   └── .env.example            # 环境变量模板
├── frotend/                    # 前端 React 应用
│   ├── src/
│   │   ├── App.tsx             # 路由配置
│   │   ├── main.tsx            # 入口文件
│   │   ├── pages/              # 页面组件
│   │   ├── components/         # 通用组件
│   │   ├── contexts/           # React Context（Auth/Model/KB）
│   │   ├── services/           # API 调用层
│   │   ├── hooks/              # 自定义 Hooks
│   │   ├── types/              # TypeScript 类型定义
│   │   └── lib/                # 工具函数
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig.json
├── train_code/                 # 模型训练脚本
│   ├── train_efficb3.py        # EfficientNet-B3 训练
│   ├── train_resnet50.py       # ResNet-50 训练
│   └── ...                     # 其他模型训练脚本
└── 汇总/                       # 项目文档汇总
```

## 文档导航

| 文档 | 内容 |
|------|------|
| [01-项目概述](01-项目概述.md) | 系统定位、架构设计、数据流 |
| [02-项目目标](02-项目目标.md) | 功能目标、非功能目标、验收标准 |
| [04-阶段1-环境与后端基础](04-阶段1-环境与后端基础.md) | 环境搭建、Flask 应用工厂、数据库配置 |
| [05-阶段2-用户认证与权限](05-阶段2-用户认证与权限.md) | JWT 认证、角色权限、用户管理 API |
| [06-阶段3-知识库与文档管理](06-阶段3-知识库与文档管理.md) | 知识库 CRUD、文档上传、文件处理 |
| [07-阶段4-向量化与检索](07-阶段4-向量化与检索.md) | pgvector 向量化、混合检索、语义搜索 |
| [08-阶段5-AI智能问答](08-阶段5-AI智能问答.md) | RAG 问答链、多 LLM 支持、SSE 流式 |
| [09-阶段6-医学图像分析](09-阶段6-医学图像分析.md) | 图像预处理、多模型集成推理、诊断报告 |
| [10-阶段7-前端React应用](10-阶段7-前端React应用.md) | 前端架构、页面路由、组件设计 |
| [11-阶段8-集成测试与部署](11-阶段8-集成测试与部署.md) | 测试策略、部署方案、运维指南 |
| [部署文档](部署文档.md) | 完整部署指南（手动/Docker） |

## 快速体验

```bash
# 1. 后端
cd 源码/backend
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env           # 编辑配置
python scripts/init_complete_db.py
python run.py

# 2. 前端
cd 源码/frotend
pnpm install
pnpm dev

# 3. 访问
# 前端: http://localhost:3000
# 后端: http://localhost:5000
```
