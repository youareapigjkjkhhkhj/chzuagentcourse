# 00 · README — 企业级大模型和 RAG 技术的智能数据分析系统

> **ChatBI 智能问数平台**：基于大语言模型（LLM）+ RAG 的对话式数据分析系统（Text-to-SQL）。用户用自然语言提问，系统自动完成「语义理解 → 数据源/表选择（RAG 检索）→ SQL 生成 → 执行查询 → 图表渲染 → 智能分析」全链路，支持工作空间隔离、行/列级权限、术语库与 SQL 示例校准。
> 由开源项目 **SQLBot**（DataEase 出品）按本项目规范重构：**项目文档 + 源码前后端分离**。

## 快速开始

完整部署建议使用项目自带的 Docker 编排（见 `部署参考/`）：

```bash
cd 部署参考
docker run -d --name sqlbot \
  -p 8000:8000 -p 8001:8001 \
  --privileged=true dataease/sqlbot
# 访问 http://<IP>:8000  admin / SQLBot@123456
```

本地开发验证（核心模块导入 + 本地可跑测试）：

```bash
cd 源码/backend
"D:/Program Files/Python311/python.exe" -m venv .venv   # 项目限定 Python 3.11
.venv/Scripts/python.exe -m pip install -r requirements-local.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv/Scripts/python.exe -m pytest tests/test_cwe89_escape_fix.py -q   # 29 passed
.venv/Scripts/python.exe -m pytest tests/test_distributed_lock.py -q  # 9 passed
```

> ⚠️ **部署前提**：完整启动需要 PostgreSQL（启动时自动执行 72 个 Alembic 迁移）+ 大模型 API（系统管理页配置）；`sqlbot-xpack` 为官方商业扩展包（密钥加解密/license/权限/审计），生产部署由官方镜像内置，本地源码运行需自行获取。

## 文档导航

| 文档 | 内容 | 阅读对象 |
|------|------|----------|
| [01-项目概述.md](./01-项目概述.md) | 背景、定位、技术栈、架构图、目录结构、数据流 | 所有人（先读） |
| [02-项目目标.md](./02-项目目标.md) | 功能/非功能目标、里程碑、验收清单、风险 | 产品/技术负责人 |
| [04-阶段1-环境与配置中枢](./04-阶段1-环境与配置中枢.md) | Python 3.11+venv+清华源+config+依赖边界 | 开发（照做即可） |
| [05-阶段2-数据源接入与多引擎](./05-阶段2-数据源接入与多引擎.md) | 13 种数据源 + 多引擎执行 + Excel 导入 | 开发 |
| [06-阶段3-模型管理与LLM工厂](./06-阶段3-模型管理与LLM工厂.md) | 12+ 服务商 / LLMFactory / 密钥加密 | 开发 |
| [07-阶段4-Text2SQL模板与SQL示例](./07-阶段4-Text2SQL模板与SQL示例.md) | 12 种方言模板 + SQL 示例校准 | 开发 |
| [08-阶段5-RAG检索与术语库](./08-阶段5-RAG检索与术语库.md) | 表/字段/术语 embedding + 语义召回 | 开发 |
| [09-阶段6-ChatBI对话与图表](./09-阶段6-ChatBI对话与图表.md) | 对话流 + 图表渲染 + 预测/日志 | 开发 |
| [10-阶段7-工作空间与权限体系](./10-阶段7-工作空间与权限体系.md) | 资源隔离 + 行列权限 + 认证 + MCP | 开发/运维 |
| [11-阶段8-前端工作台与部署](./11-阶段8-前端工作台与部署.md) | Vue3 工作台 + Docker 部署 + FAQ | 开发/测试/运维 |

> **阅读路径**：总览式（01→02→按需查阶段手册）｜分阶段式（阶段 1→8 按模块逐步深入）。

## 能力速览

| 能力 | 说明 |
|------|------|
| ChatBI 对话问数 | 自然语言 → SQL → 数据 → 图表 → 分析（`apps/chat/task/llm.py` LLMService） |
| Text-to-SQL 模板 | 12 种数据库方言 SQL 模板 + 基础模板（`apps/template/`） |
| RAG 语义检索 | 数据表/字段/术语 embedding（text2vec 本地模型 + 相似度阈值） |
| 数据源接入 | 13 种类型：PostgreSQL/MySQL/Oracle/ClickHouse/Doris/StarRocks/ES/Excel… |
| 工作空间隔离 | 工作空间级资源隔离 + 用户绑定（`apps/system/api/workspace.py`） |
| 细粒度权限 | 行列级数据权限 + 白名单校验（CWE-89 防护） |
| 模型服务商 | 12+：OpenAI 兼容全家桶 / Azure / vLLM（LLMFactory） |
| 术语库与校准 | 术语库（embedding 召回）+ SQL 示例训练数据（Excel 导入） |
| 多端集成 | Web 嵌入 / 弹窗 / **MCP 服务**（8001 端口） |

## API 概览（前缀 /api/v1）

| 模块 | 前缀 | 锚点 |
|------|------|------|
| 登录 | `/login` | `apps/system/api/login.py:18` |
| 工作空间 | `/system/workspace` | `apps/system/api/workspace.py:18` |
| 数据源 | `/datasource` | `apps/datasource/api/datasource.py:36` |
| 对话 | `/chat` | `apps/chat/api/chat.py:29` |
| 术语库 | `/system/terminology` | `apps/terminology/api/terminology.py:25` |
| SQL 示例 | `/system/data-training` | `apps/data_training/api/data_training.py:26` |
| MCP | `/mcp` | `apps/mcp/mcp.py:38` |

## 验证结果（本地实测）

| 项 | 命令 | 结果 |
|----|------|------|
| 配置中枢 | `from common.core.config import settings` | ✅ `.env` 生效（PROJECT_NAME/DB URI/CACHE_TYPE） |
| SQL 模板 | `get_all_sql_templates()` | ✅ 13 个模板（12 种数据库 + excel） |
| LLM 工厂 | `LLMFactory.create_llm(...)` | ✅ 4 类型注册（openai/tongyi/vllm/azure），实例化成功 |
| 数据源枚举 | `from apps.db.constant import DB` | ✅ 13 种 |
| 安全 | `verify_password('SQLBot@123456', hash)` | ✅ True |
| 测试 | `pytest tests/test_cwe89_escape_fix.py` | ✅ 29 passed（SQL 注入转义） |
| 测试 | `pytest tests/test_distributed_lock.py` | ✅ 9 passed（分布式锁，mock PG） |

## 运行产物

- 上传数据：`data/excel`（Excel 建表）、`data/file`
- 图表图片：`data/images`（MCP/图表服务）
- 日志：`backend/logs`（`LOG_DIR`）
- 数据库：PostgreSQL `sqlbot` 库（72 个 Alembic 迁移自动执行）
