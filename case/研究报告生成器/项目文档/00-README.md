# 00 · README — 研究报告生成器

> **Multi-Agent Research Report Studio**：输入研究主题，自动完成「规划 → 多论文源检索 → PDF 阅读 → 本地混合 RAG → LLM 分析 → 结构化写作 → Markdown/PDF 导出」全链路。
> 由开源项目 `multi-agent-research-assistant` 按本项目规范重构：**项目文档 + 源码前后端分离**，每阶段独立可运行。

## 快速开始

```bash
# 1) 后端环境（清华源）
cd 源码/backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
# 2) 复制并填写 .env（已含 OpenAI 兼容代理示例）
# 3) 启动后端
.venv/Scripts/python.exe -m uvicorn api.app:app --host 127.0.0.1 --port 8000

# 4) 前端（可选：仅开发热更新；生产直接用后端同源托管 dist）
cd 源码/frontend
npm install
npm run build    # 构建后由 FastAPI 托管，直接访问 http://127.0.0.1:8000
```

> 大模型默认走 `OPENAI_BASE_URL` + `gpt-5-mini`（OpenAI 兼容代理，配置见 `源码/backend/.env`）。未配置 Key 或断网时自动产出**抽取式兜底报告**，系统始终可用。

## 文档导航

| 文档 | 内容 | 阅读对象 |
|------|------|----------|
| [01-项目概述.md](./01-项目概述.md) | 背景、定位、技术栈、架构图、目录结构、数据流 | 所有人（先读） |
| [02-项目目标.md](./02-项目目标.md) | 功能/非功能目标、里程碑、验收清单、风险 | 产品/技术负责人 |
| [04-阶段1-环境与最小后端](./04-阶段1-环境与最小后端.md) | venv+清华源+.env+Uvicorn+健康检查 | 开发（照做即可） |
| [05-阶段2-LLM客户端与规划代理](./05-阶段2-LLM客户端与规划代理.md) | 多服务商解析+本地缓存+任务规划 | 开发 |
| [06-阶段3-论文检索工具](./06-阶段3-论文检索工具.md) | arXiv/SS/EPMC/Crossref+中文检索词 | 开发 |
| [07-阶段4-PDF阅读与阅读代理](./07-阶段4-PDF阅读与阅读代理.md) | PDF 下载抽取+批量阅读 | 开发 |
| [08-阶段5-本地混合RAG](./08-阶段5-本地混合RAG.md) | 哈希向量+FAISS+BM25+证据上下文 | 开发 |
| [09-阶段6-分析与写作代理](./09-阶段6-分析与写作代理.md) | LLM 分析/写作+兜底报告 | 开发 |
| [10-阶段7-API层与异步任务](./10-阶段7-API层与异步任务.md) | 任务队列+轮询+下载+静态托管 | 开发/运维 |
| [11-阶段8-前端Vue3与集成测试](./11-阶段8-前端Vue3与集成测试.md) | 工作台+两套测试+FAQ+部署 | 开发/测试 |

> **阅读路径**：总览式（01→02→按需查阶段手册）｜分阶段式（从阶段 1 顺序执行，每阶段可独立运行并逐步长成完整项目）。

## 能力速览

| 能力 | 说明 |
|------|------|
| 多智能体流水线 | planner → search → reader → RAG → analyst → writer，8 阶段进度可视化 |
| 多论文源 | arXiv / Semantic Scholar / Europe PMC / Crossref / 综合开放源（并集去重） |
| 中文主题适配 | LLM 翻译 + 内置 22 组词典翻译 + ASCII 变体 |
| 本地混合 RAG | 哈希特征向量 + FAISS 内积 + BM25 + 词覆盖率（`0.42/0.43/0.15` 加权），零远程 embedding 依赖 |
| LLM 客户端 | DeepSeek/OpenAI/自定义 三服务商；`OPENAI_BASE_URL` 兼容代理；本地响应缓存 |
| 兜底可用性 | 无 Key/断网/PDF 失败自动降级抽取式报告，主流程不中断 |
| 导出 | Markdown + PDF（Playwright A4）；下载接口附件返回 |

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| POST | `/api/reports` | 创建报告任务（异步后台线程执行） |
| GET | `/api/reports` | 任务列表（进程内，倒序） |
| GET | `/api/reports/{job_id}` | 任务详情：stage/progress/logs/papers/evidence/report |
| GET | `/api/reports/{job_id}/download/markdown` | 下载 Markdown |
| GET | `/api/reports/{job_id}/download/pdf` | 下载 PDF |

## 测试与验证（实测）

```bash
cd 源码/backend
.venv/Scripts/python.exe tests/test_unit_rag.py    # ✅ 12/12（本地，无网络）
.venv/Scripts/python.exe tests/test_api_smoke.py   # ✅ 12/12（真实全链路：arXiv 检索+LLM 调用+报告生成）
```

真实端口 8000：`GET /`=200（前端托管）、静态资源 200、MD 下载 9016B、PDF 下载 272KB、`/api/health` ok。

## 运行产物

- 报告文件：`源码/backend/generated_reports/{job_id}/`（md + pdf）
- LLM 缓存：`源码/backend/runtime_cache/llm/`（`LLM_RESPONSE_CACHE=0` 关闭）
- 临时 html：PDF 导出中间产物，正常自动清理

## 排错速查

| 现象 | 处理 |
|------|------|
| `GET /` 404 | `cd 源码/frontend && npm run build` |
| PDF 下载 404 | `playwright install chromium`（仅影响 PDF，Markdown 不受影响） |
| 任务列表重启为空 | 进程内存储属预期，文件仍在 `generated_reports/` |
| 报告全英文 | 前端语言选「中文」或主题用中文 |

详见 `11-阶段8` FAQ。
