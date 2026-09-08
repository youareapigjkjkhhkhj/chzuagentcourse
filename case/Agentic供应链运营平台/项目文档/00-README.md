# 00 · README — Agentic 供应链运营平台

> **多智能体供应链决策平台**：基于 LangGraph 工作流编排 + FastAPI 后端 + React 前端的生产级多智能体系统，覆盖库存监控、需求预测、采购规划、供应商谈判、物流规划五阶段决策链路，支持实时 WebSocket 事件流、MLflow 可观测性追踪与自然语言控制室。

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- uv（Python 包管理器）

### 安装与启动

```bash
# 安装后端依赖
uv sync --extra dev

# 安装前端依赖
cd frontend && npm install

# 配置环境变量
cp .env.example .env

# 构建前端
cd frontend && npm run build

# 启动后端服务
uv run python -m uvicorn main:app --app-dir src --host 127.0.0.1 --port 8000

# 启动 MLflow（可选）
uv run mlflow server --host 127.0.0.1 --port 5001 --backend-store-uri sqlite:///mlflow.db
```

访问 `http://127.0.0.1:8000` 进入应用界面。

## 文档导航

| 文档 | 内容 | 阅读对象 |
|------|------|----------|
| [01-项目概述.md](./01-项目概述.md) | 背景、定位、技术栈、架构图、目录结构 | 所有人（先读） |
| [02-项目目标.md](./02-项目目标.md) | 功能/非功能目标、里程碑、验收清单 | 产品/技术负责人 |
| [03-技术架构.md](./03-技术架构.md) | LangGraph 工作流、状态管理、数据流 | 开发 |
| [04-后端架构.md](./04-后端架构.md) | API 路由、智能体、服务层、数据库 | 后端开发 |
| [05-前端架构.md](./05-前端架构.md) | React 组件、页面、Hooks、状态管理 | 前端开发 |

## 能力速览

| 能力 | 说明 |
|------|------|
| 多智能体编排 | 5 阶段 LangGraph 工作流：库存监控 → 需求预测 → 采购 → 谈判 → 物流 |
| 实时事件流 | WebSocket 驱动的智能体状态推送与工作流可视化 |
| 自然语言控制室 | Deep Agents 支持自然语言查询工作流、比较供应商、审查治理 |
| 控制塔仪表盘 | KPI 卡片、风险预警、仓库负载、决策剧本一览 |
| 场景实验室 | 供应冲击压力测试与概率/影响分析 |
| 治理中心 | 审批队列、护栏规则、智能体可靠性登记 |
| 供应商谈判 | 实时对话式谈判、条款演变追踪、价格让步分析 |
| 可观测性 | MLflow 工作流追踪 + ClickHouse 分析（可选） |

## API 概览

| 模块 | 前缀 | 说明 |
|------|------|------|
| 仪表盘 | `/api/dashboard/kpis` | KPI 汇总数据 |
| 库存 | `/api/inventory` | 库存查询 |
| 风险 | `/api/risks` | 风险预警 |
| 分析 | `/api/analyze/{sku}` | 全流程分析 |
| 谈判 | `/api/negotiate` | 供应商谈判 |
| 产品 | `/api/products` | 产品列表 |
| 供应商 | `/api/vendors` | 供应商列表 |
| 控制塔 | `/api/platform/control-tower` | 控制塔快照 |
| 场景 | `/api/platform/scenarios` | 场景模拟 |
| 治理 | `/api/platform/governance` | 治理控制 |
| WebSocket | `/ws/workflow/{session_id}` | 实时工作流事件 |

## 技术栈

| 层 | 技术 | 说明 |
|----|------|------|
| 后端 | Python 3.11 + FastAPI + LangGraph | 多智能体工作流编排 |
| LLM | OpenAI 兼容 API | 可配置模型端点 |
| 前端 | React 18 + TypeScript + Vite | SPA 单页应用 |
| UI | Tailwind CSS + Framer Motion | 响应式动画 |
| 可观测性 | MLflow + ClickHouse | 追踪与分析 |
| 工具 | uv + npm | 包管理 |
