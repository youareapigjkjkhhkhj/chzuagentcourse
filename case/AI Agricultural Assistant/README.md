# 🌾 AgriGPT 智能农业助手 — 企业级实训项目

> 多模态 · 多智能体（Multi-Agent）· RAG · 容器化交付的完整 AI 应用实训案例
> 本项目按企业级规范组织：**项目文档（分步实训指导书） + 源码（完整参考实现）**。

---

## 项目简介

AgriGPT 是一个端到端的农业 AI 助手：

- **文本问答**：种植、施肥、灌溉、产量、补贴五大领域专家 Agent；
- **图片诊断**：视觉大模型识别作物病害（图文可混合）；
- **意图路由**：LLM 为各专家打分，最多 3 个 Agent 并行协作；
- **RAG 防幻觉**：补贴问答仅基于向量库检索结果，护栏兜底；
- **工程闭环**：会话记忆（Redis）、指标反馈、Token 成本、Docker 部署。

---

## 目录结构

```
.
├── README.md                  ← 本文件（项目入口）
├── 设计方案.md                ← 总体设计方案（架构/选型/接口/数据设计）
├── 项目文档/                  ← 学生实训指导书（按步骤实现全系统）
│   ├── 实训总览与指导书.md
│   ├── 项目实训01-项目认知与环境搭建.md
│   ├── 项目实训02-后端骨架与配置中心.md
│   ├── 项目实训03-提示词工程与LLM服务层.md
│   ├── 项目实训04-Agent基类与首个专家Agent.md
│   ├── 项目实训05-多Agent编排与意图路由.md
│   ├── 项目实训06-多模态图像诊断.md
│   ├── 项目实训07-RAG知识库与补贴问答.md
│   ├── 项目实训08-会话记忆与天气服务.md
│   ├── 项目实训09-指标反馈与运维端点.md
│   ├── 项目实训10-前端工程初始化.md
│   ├── 项目实训11-前端页面与前后端联调.md
│   └── 项目实训12-自动化测试与容器化部署.md
└── 源码/                      ← 完整参考实现（可直接运行）
    ├── backend/               FastAPI + LangChain + 多 Agent + RAG
    ├── frontend/              React + TS + Vite + Tailwind + shadcn/ui
    ├── docker-compose.yml     redis + backend + frontend 一键编排
    ├── Dockerfile / render.yaml / pytest.ini
    └── RENDER_DEPLOY.md       Render 云部署指南（中文，可选）
```

---

## 快速开始（直接运行参考源码）

### 前置条件

- Python **3.11 或 3.12**（3.14 无依赖轮子）
- Node.js ≥ 20
- [Groq API Key](https://console.groq.com)（免费）

### 后端

```powershell
cd 源码/backend
copy env.example .env        # 编辑 .env 填入 GROQ_API_KEY
pip install -r requirements.txt
cd ..                        # 回到 源码 目录
uvicorn backend.main:app --reload
```

→ 后端：http://localhost:8000 ｜ API 文档：http://localhost:8000/docs

### 前端

```powershell
cd 源码/frontend
npm install
npm run dev
```

→ 前端：http://localhost:8080

### Docker 一键部署

```powershell
cd 源码
# 在源码目录下创建 .env 并填入 GROQ_API_KEY
docker-compose up --build
```

- 前端：http://localhost:3000 ｜ 后端：http://localhost:8000 ｜ Redis：会话记忆持久化

### 运行测试

```powershell
cd 源码
pytest
```

---

## 学生实训路线（12 次递进）

| 阶段 | 实训 | 里程碑 |
|------|------|--------|
| 环境就绪 | 01 ~ 02 | FastAPI 骨架 + `/docs` 可访问 |
| 单 Agent 问答 | 03 ~ 04 | `/ask/text` 端到端可用 |
| 多 Agent 编排 | 05 ~ 06 | 意图路由 + 图片诊断 |
| 知识增强 | 07 ~ 08 | RAG 补贴问答 + 会话记忆 |
| 运营闭环 | 09 | 指标 + 反馈接口 |
| 前端交付 | 10 ~ 11 | 完整 Web 应用 + 联调通过 |
| 工程化 | 12 | 测试全绿 + 容器化部署 |

**从 [项目文档/实训总览与指导书.md](./项目文档/实训总览与指导书.md) 开始。**

---

## 技术栈

| 端 | 技术 |
|----|------|
| 后端 | Python 3.11+ · FastAPI · LangChain/LCEL · Groq（Llama 3.3 70B / Llama 4 Scout）· FAISS/Pinecone · Redis · pytest |
| 前端 | React 18 · TypeScript · Vite · Tailwind · shadcn/ui · Zustand · Axios · React Query |
| DevOps | Docker · docker-compose · Nginx · Render |

## 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `GROQ_API_KEY` | 是 | Groq API Key（文本 + 视觉模型） |
| `OPENWEATHER_API_KEY` | 否 | 天气头部组件 |
| `REDIS_URL` | 否 | `redis://localhost:6379/0`，未配置则降级内存 |
| `PINECONE_API_KEY` | 否 | 云端向量库，未配置则用本地 FAISS |
| `LANGSMITH_API_KEY` | 否 | LLM 全链路追踪 |

---

## 说明

- 本项目用于教学实训；原始项目思路参考开源项目 AgriGPT（学术用途）。
- 所有 API Key 严禁提交到版本库（`.gitignore` 已配置）。
