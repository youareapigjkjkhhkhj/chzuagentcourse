# 09 · 阶段 6 — ChatBI 对话与图表

> 本阶段目标：掌握系统核心——ChatBI 对话链路（`apps/chat/`）：对话 API、LLMService（1978 行）、SQL 执行、流式输出、图表与预测。

---

## 1. 目标

- 掌握 `apps/chat/api/chat.py` 对话路由体系。
- 掌握 `apps/chat/task/llm.py` 的 `LLMService` 核心链路（SQL 生成 → 执行 → 图表 → 分析）。
- 掌握流式输出 `process_stream` 与 token 用量统计。
- 命令行实测：SQL 表名提取工具（纯逻辑，本地可验证）。

## 2. 关键设计

### 2.1 对话路由（`apps/chat/api/chat.py`）

`router = APIRouter(tags=["Data Q&A"], prefix="/chat")`（`chat.py:29`）：

| 路由 | 锚点 | 作用 |
|------|------|------|
| `GET /list` | `chat.py:32` | 会话列表 |
| `GET /{chart_id}` | `chat.py:37` | 会话详情 |
| `GET /{chart_id}/with_data` | `chat.py:47` | 详情+数据 |
| `GET /record/{chat_record_id}/data` | `chat.py:75` | 记录数据 |
| `GET /record/{chat_record_id}/data_live` | `chat.py:84` | 实时数据（SSE） |
| `GET /record/{chat_record_id}/predict_data` | `chat.py:93` | 预测数据 |
| `GET /record/{chat_record_id}/log` | `chat.py:103` | 运行日志 |
| `GET /record/{chat_record_id}/usage` | `chat.py:111` | token 用量 |

### 2.2 LLMService（`apps/chat/task/llm.py`）

`class LLMService`（`llm.py:92`，共 1978 行）是 ChatBI 核心：

| 锚点 | 作用 |
|------|------|
| `llm.py:71` | `extract_tables_from_sql`：从 SQL 提取表名（工具函数） |
| `llm.py:1184` | `execute_sql`：执行查询（含错误详情返回） |
| `llm.py:1744` | `execute_sql_with_db`：LangChain SQLDatabase 执行 |
| `llm.py:1770` | `request_picture`：图表图片渲染 |
| `llm.py:1832` | `get_token_usage`：token 统计 |
| `llm.py:1844` | `process_stream`：流式分块输出 |
| `llm.py:1955` | `get_last_conversation_rounds`：多轮上下文（`GENERATE_SQL_QUERY_HISTORY_ROUND_COUNT`，`config.py:114`） |

### 2.3 SQL 安全执行配置

`config.py:113-118`：`GENERATE_SQL_QUERY_LIMIT_ENABLED`（行数限制）、`SQLBOT_ALLOW_METADATA_QUERIES`（默认禁元数据查询防泄露）。

## 3. 实操步骤

### 3.1 验证 SQL 表名提取（纯逻辑）

```bash
cd 源码/backend
.venv/Scripts/python.exe -c "
import sys, types, warnings
warnings.filterwarnings('ignore')
# stub sqlbot_xpack（chat/task/llm.py 顶部 import 依赖）
pkg = types.ModuleType('sqlbot_xpack')
cfg_m = types.ModuleType('sqlbot_xpack.config'); cfg_m.model = types.ModuleType('sqlbot_xpack.config.model')
class _SysArg: pass
cfg_m.model.SysArgModel = _SysArg
pkg.config = cfg_m
cp = types.ModuleType('sqlbot_xpack.custom_prompt')
cp.curd = types.ModuleType('sqlbot_xpack.custom_prompt.curd')
cp.curd.custom_prompt = types.ModuleType('sqlbot_xpack.custom_prompt.curd.custom_prompt')
cp.curd.custom_prompt.find_custom_prompts = lambda *a, **k: []
cp.models = types.ModuleType('sqlbot_xpack.custom_prompt.models')
from enum import Enum
class _E(Enum): pass
cp.models.custom_prompt_model = types.ModuleType('sqlbot_xpack.custom_prompt.models.custom_prompt_model')
cp.models.custom_prompt_model.CustomPromptTypeEnum = _E
pkg.custom_prompt = cp
lic = types.ModuleType('sqlbot_xpack.license'); lic.license_manage = types.ModuleType('sqlbot_xpack.license.license_manage')
lic.license_manage.SQLBotLicenseUtil = type('L', (), {})
pkg.license = lic
sys.modules['sqlbot_xpack'] = pkg
sys.modules['sqlbot_xpack.config'] = cfg_m
sys.modules['sqlbot_xpack.config.model'] = cfg_m.model
sys.modules['sqlbot_xpack.custom_prompt'] = cp
sys.modules['sqlbot_xpack.custom_prompt.curd.custom_prompt'] = cp.curd.custom_prompt
sys.modules['sqlbot_xpack.custom_prompt.models.custom_prompt_model'] = cp.models.custom_prompt_model
sys.modules['sqlbot_xpack.license.license_manage'] = lic.license_manage

from apps.chat.task.llm import extract_tables_from_sql
print('表名提取:', extract_tables_from_sql('SELECT * FROM orders o JOIN users u ON o.uid=u.id WHERE u.age>18', 'pg'))
print('无表:', extract_tables_from_sql('SELECT 1', 'pg'))
"
```

### 3.2 验证多轮上下文工具

```bash
.venv/Scripts/python.exe -c "
from apps.chat.task.llm import get_lang_name
print('语言名:', get_lang_name('zh'))
"
```

## 4. 可运行验证

| 验证项 | 命令 | 期望 |
|--------|------|------|
| 表名提取 | 3.1 | 返回 `{'orders','users'}`（pg 方言） |
| 语言映射 | 3.2 | 中文 |
| 完整对话 | 需 PG+模型 | Docker 部署后 UI 提问（`部署参考/`） |

**Checkpoint 达成标准**：核心纯逻辑（表名提取/多轮上下文）本地验证通过；完整对话链路在 Docker 环境可跑。

## 5. 排错速查

| 现象 | 原因 | 处理 |
|------|------|------|
| SQL 生成错误 | 模型未配置/Key 失效 | 模型管理页检查默认模型 |
| 查询超限 | 行数限制开启 | `GENERATE_SQL_QUERY_LIMIT_ENABLED`（`config.py:113`） |
| 元数据查询被拒 | 安全开关默认关闭 | `SQLBOT_ALLOW_METADATA_QUERIES=True`（仅信任环境） |
