# 项目实训04｜Agent 基类与首个专家 Agent

> **训练目标**：掌握"基类 + 注册表"的 Agent 设计；实现交互日志服务；完成 CropAgent 并打通 `/ask/text` 端到端链路。
> **预计时长**：6 学时 ｜ **前置条件**：实训 03 完成
> **本次交付物**：`services/history_service.py`、`agents/agri_agent_base.py`、`agents/crop_agent.py`、`routes/ask_router.py`（/ask/text）

---

## 一、知识点

### 1. 为什么要有 Agent 基类

本项目有 7 个 Agent，若各写各的会出现：日志格式不统一、异常处理不一致、路由层无法统一调度。因此抽象出 `AgriAgentBase`：

```
AgriAgentBase（抽象）
 ├─ handle_query()      抽象方法：各专家实现自己的业务
 ├─ respond_and_record() 模板方法：应答 + 自动落日志（不允许绕过）
 └─ record()            写入 history_service
```

> **企业模式**：这是经典的"模板方法模式"——把公共流程固化在基类，子类只填差异。

### 2. 日志落盘的工程细节

`query_log.json` 的写入必须考虑：

- **并发安全**：`threading.Lock`；
- **原子性**：先写临时文件再 `os.replace`（防止写一半进程崩溃导致 JSON 损坏）；
- **容量治理**：超过 5MB 自动归档轮转。

---

## 二、操作步骤

### 步骤 1：实现交互日志服务 `backend/services/history_service.py`

```python
import json
import os
import threading
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOG_PATH = DATA_DIR / "query_log.json"
TMP_PATH = DATA_DIR / "query_log_tmp.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

_log_lock = threading.Lock()
MAX_LOG_SIZE_BYTES = 5 * 1024 * 1024


def _sanitize_entry(entry: dict) -> dict:
    """
    Ensures all values are JSON-serializable UTF-8 strings.
    """
    clean = {}
    for key, val in entry.items():
        if isinstance(val, (str, int, float, bool)) or val is None:
            clean[key] = val
        else:
            clean[key] = str(val)
    return clean


def _atomic_write(data: list):
    """
    Safely writes to a temporary file, then atomically replaces the log.
    """
    with open(TMP_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(TMP_PATH, LOG_PATH)


def log_interaction(entry: dict):
    """
    Append a single query/response record to query_log.json.
    """

    clean_entry = _sanitize_entry(entry)
    clean_entry.setdefault("timestamp", datetime.utcnow().isoformat())

    with _log_lock:

        try:
            if LOG_PATH.exists():
                with open(LOG_PATH, "r", encoding="utf-8") as f:
                    logs = json.load(f)
                if not isinstance(logs, list):
                    logs = []
            else:
                logs = []
        except Exception:
            logs = []

        logs.append(clean_entry)

        try:
            approx_new_size = len(json.dumps(logs).encode("utf-8"))
        except Exception:
            approx_new_size = 0

        if approx_new_size > MAX_LOG_SIZE_BYTES:
            archive_path = LOG_PATH.with_suffix(".archive.json")
            os.replace(LOG_PATH, archive_path)
            logs = [clean_entry]  # start fresh after rotation

        try:
            _atomic_write(logs)
        except Exception as e:
            print(f"[LOG ERROR] Failed to write log: {e}")
```

### 步骤 2：实现 Agent 抽象基类 `backend/agents/agri_agent_base.py`

```python
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from backend.services.history_service import log_interaction


class AgriAgentBase(ABC):
    name: str = "AgriAgentBase"

    @abstractmethod
    def handle_query(
        self,
        query: Optional[str] = None,
        image_path: Optional[str] = None,
        chat_history: Optional[str] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs,
    ) -> str:
        pass

    @staticmethod
    def _normalize_query(q: Optional[str]) -> str:
        if q is None:
            return ""
        return q.strip()

    @staticmethod
    def _detect_query_type(query, image_path):
        normalized_query = AgriAgentBase._normalize_query(query)
        if normalized_query and image_path:
            return "multimodal"
        if image_path:
            return "image"
        return "text"

    def record(self, query, response, query_type, image_path=None, meta: Optional[dict] = None):
        safe_response = str(response)

        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "agent": self.name,
            "query": query or "",
            "response": safe_response[:5000],
            "type": query_type,
        }

        if image_path:
            entry["image_path"] = image_path
        if meta:
            entry["meta"] = meta

        try:
            log_interaction(entry)
        except Exception:
            pass  # 日志失败不能影响主流程

    def respond_and_record(self, query, response, image_path=None, meta: Optional[dict] = None):
        query_type = self._detect_query_type(query, image_path)
        safe_response = str(response)
        self.record(query=query, response=safe_response,
                    query_type=query_type, image_path=image_path, meta=meta)
        return safe_response
```

### 步骤 3：实现首个专家 `backend/agents/crop_agent.py`

```python
from backend.services.text_service import query_groq_text
from backend.agents.agri_agent_base import AgriAgentBase
from backend.core.prompt_loader import get_prompt


class CropAgent(AgriAgentBase):
    """
    CropAgent:
    Handles general crop management questions.
    DOES NOT diagnose pests, diseases, or irrigation failures.
    """

    name = "CropAgent"

    def handle_query(
        self,
        query: str = None,
        image_path: str = None,
        chat_history: str = None,
        request_id: str = None,
        session_id: str = None,
        **kwargs,
    ) -> str:

        if not query or not query.strip():
            response = (
                "Please ask a crop management question.\n"
                "Examples:\n"
                "• What fertilizer should I use for tomatoes?\n"
                "• How should I prepare soil for rice?\n"
                "• What practices improve crop growth?"
            )
            return self.respond_and_record("", response, image_path)

        clean_query = query.strip()

        try:
            prompt = get_prompt(
                "crop_agent.template",
                chat_history=chat_history or "None",
                query=clean_query,
            )
        except Exception:
            prompt = f"PREVIOUS CONTEXT: {chat_history or 'None'}\nFARMER QUERY: {clean_query}"

        try:
            resp, _ = query_groq_text(
                prompt,
                request_id=request_id,
                session_id=session_id,
            )
        except Exception:
            resp = "Crop advice could not be generated at this time."

        return self.respond_and_record(
            query=clean_query,
            response=resp,
            image_path=image_path,
        )
```

**设计要点**：

1. **空输入引导**：不是报错，而是给出示例提问——面向农户的产品体验；
2. **提示词读取带兜底**：YAML 损坏时仍能以内联模板降级运行；
3. **所有出口都经过 `respond_and_record`**：保证 100% 留痕。

### 步骤 4：实现问答路由 `backend/routes/ask_router.py`（先实现 /ask/text）

```python
from fastapi import APIRouter, Form, HTTPException
import time
import uuid
from typing import Optional

from backend.core.token_tracker import token_tracker

router = APIRouter(prefix="/ask", tags=["Query"])

MAX_QUERY_CHARS = 2000


def _build_response(
    request_id: str,
    start_time: float,
    response: str,
    session_id: Optional[str] = None,
    **extra,
) -> dict:
    """Build response with token usage when available."""
    out = {
        "request_id": request_id,
        "status": "success",
        "elapsed_ms": int((time.time() - start_time) * 1000),
        "analysis": str(response),
        **extra,
    }
    usage = token_tracker.get_request_summary(request_id)
    if usage:
        out["token_usage"] = usage
    if session_id:
        session_usage = token_tracker.get_session_summary(session_id)
        if session_usage:
            out["session_token_usage"] = session_usage
    return out


@router.post("/text")
async def ask_text(
    query: str = Form(...),
    session_id: Optional[str] = Form(None),
):
    """Text-only farming query endpoint."""
    start = time.time()
    request_id = str(uuid.uuid4())

    if not query or not query.strip():
        raise HTTPException(400, "Please enter a text query.")

    query = query.strip()
    if len(query) > MAX_QUERY_CHARS:
        raise HTTPException(413, f"Query too long. Max {MAX_QUERY_CHARS} chars.")

    from backend.agents.crop_agent import CropAgent

    try:
        response = CropAgent().handle_query(
            query=query,
            request_id=request_id,
            session_id=session_id,
        )
    except Exception as e:
        raise HTTPException(500, f"Error: {str(e)}")

    return _build_response(request_id, start, response, session_id=session_id, query=query)
```

> **说明**：这里暂时直连 CropAgent。实训 05 会把这一行替换为 `master_agent.route_query(...)`，接口层代码不再变动——这就是"接口层与编排层解耦"的价值。

> **规范**：状态码语义化——400 参数缺失、413 超长、500 内部错误；`request_id` 用 UUID，贯穿日志、Token 统计与后续反馈链路。

### 步骤 5：挂载路由到 `main.py`

```python
from backend.routes.ask_router import router as ask_router
...
app.include_router(health_router)
app.include_router(ask_router)
```

### 步骤 6：端到端验证

**方式一：Swagger**
打开 `http://localhost:8000/docs` → Query → `/ask/text` → Try it out：

- `query`: `What fertilizer should I use for tomatoes?`
- `session_id`: `demo-session-1`

**方式二：curl / PowerShell**

```powershell
curl.exe -X POST http://localhost:8000/ask/text `
  -F "query=What fertilizer should I use for tomatoes?" `
  -F "session_id=demo-session-1"
```

预期响应包含：`request_id`、`elapsed_ms`、`analysis`（施肥建议）、`token_usage`。

检查日志：打开 `backend/data/query_log.json`，应出现一条 `agent: "CropAgent"` 的记录。

再测边界：

```powershell
curl.exe -X POST http://localhost:8000/ask/text -F "query="        # → 400
```

---

## 三、验收标准

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 1 | `/ask/text` 正常提问 | 200 + 农业建议 + token_usage |
| 2 | 空 query | 400 + 清晰文案 |
| 3 | 超过 2000 字符 | 413 |
| 4 | `query_log.json` | 新增记录含 timestamp/agent/query/response/type |
| 5 | 同一进程内多次请求 | `session_token_usage` 数值递增 |

---

## 四、常见问题排查

| 现象 | 原因与解决 |
|------|-----------|
| 422 Unprocessable Entity | 参数必须用 `multipart/form-data` 发送（`-F`），不是 JSON |
| 响应很慢（>30s） | 首次请求包含模型握手；Groq 免费额度偶有排队，属正常 |
| 日志文件没有生成 | 确认 `backend/data/` 目录存在；检查控制台 `[LOG ERROR]` |
| 每次请求都新建 CropAgent 有性能问题吗？ | 单实例很轻；实训 05 引入**注册表单例缓存**统一管理 |

---

## 五、拓展任务（选做）

1. 给 `/ask/text` 增加响应模型（`response_model=...` 的 Pydantic 类），让 Swagger 文档更规范；
2. 为 `AgriAgentBase.record` 的响应截断长度（5000）做成配置项；
3. 写一个最简 pytest：mock `query_groq_text`，断言 CropAgent 空输入时返回引导文案。

> **下一节预告**：实训 05 是本项目的核心——LLM 意图路由 + 多 Agent 并行编排 + 格式化合成。
