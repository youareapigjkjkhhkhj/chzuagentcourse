# 项目实训03｜提示词工程与 LLM 服务层

> **训练目标**：建立版本化提示词库；实现 LLM 客户端工厂；实现带重试、截断、Token 统计的文本生成服务。
> **预计时长**：6 学时 ｜ **前置条件**：实训 02 完成
> **本次交付物**：`prompts/prompts.yaml`、`core/prompt_loader.py`、`core/llm_client.py`、`core/token_tracker.py`、`services/text_service.py`

---

## 一、知识点

### 1. 为什么要"提示词库"

企业级 AI 应用中，提示词（Prompt）是**核心资产**，必须做到：

- **集中**：散落在代码里的提示词无法统一评审与回滚；
- **版本化**：`version: "1.0"` 支持 A/B 测试与效果追溯；
- **可审计**：运营/安全团队需要检查系统对外的"话术"。

本项目采用 YAML 集中管理 + 点号路径读取（`crop_agent.template`）。

### 2. LLM 调用的工程三件套

| 问题 | 对策 |
|------|------|
| 网络抖动 / 限流（429） | 指数退避重试（1s → 2s → 4s），仅对可重试错误重试 |
| 上下文爆炸、成本失控 | 输入截断（≤4000 字符）+ Token 用量统计 |
| 输出格式不稳定 | 统一 `_normalize_output` 归一化 |

### 3. LLMOps 成本核算

每次调用记录 `input_tokens / output_tokens / model`，按内置单价表折算美元费用，按**请求**和**会话**两个维度聚合——这是企业控制 LLM 账单的标准做法。

---

## 二、操作步骤

### 步骤 1：创建提示词库 `backend/prompts/prompts.yaml`

先建两个键（后续实训逐步追加 `pest_agent`、`router` 等）：

```yaml
# AgriGPT Prompt Library - Version 1.0
# Centralized prompts for versioning, A/B testing, and auditability.

version: "1.0"

crop_agent:
  system: "You are AgriGPT CropAgent."
  template: |
    You are AgriGPT CropAgent.
    ROLE: You are a crop management specialist.
    You provide guidance ONLY on crop cultivation practices, fertilizer planning (general or conditional), soil preparation, and crop growth stage care.
    STRICT BOUNDARIES: Do NOT diagnose pests or diseases. Do NOT identify insects or leaf damage. Do NOT analyze images.
    Do NOT give subsidy or loan information. Do NOT give irrigation schedules. Do NOT override other expert agents.
    SAFETY RULES: Do NOT guess soil type, crop variety, or region unless stated.
    Use conditional language when required. If essential details are missing, say so clearly.
    Do NOT invent chemical names or dosages.
    PREVIOUS CONTEXT: {chat_history}
    FARMER QUERY: {query}
    RESPONSE INSTRUCTIONS:
    Give practical, actionable crop management advice.
    Use simple, farmer-friendly language.
    If fertilizer is mentioned, provide type (example: NPK, urea, compost) and a general dosage range or conditional guidance when exact dosage is unknown.
    Mention soil preparation steps if relevant.
    Focus ONLY on crop practices. Avoid repetition and theory.
    OUTPUT: Plain advisory text only. No formatting, no titles, no forced bullets.
```

**提示词设计要点（本项目的核心方法论）**：

1. **角色声明**（ROLE）→ 2. **硬边界**（STRICT BOUNDARIES，明确禁止事项）→ 3. **安全规则**（SAFETY RULES，禁止臆测）→ 4. **上下文注入位**（`{chat_history}` / `{query}`）→ 5. **输出格式约束**（OUTPUT）。

### 步骤 2：实现提示词加载器 `backend/core/prompt_loader.py`

```python
"""Centralized prompt loader for versioning and auditability."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPTS_PATH = BASE_DIR / "prompts" / "prompts.yaml"

_cached_prompts: Dict[str, Any] | None = None


def _load_prompts() -> Dict[str, Any]:
    """Load prompts from YAML file."""
    global _cached_prompts
    if _cached_prompts is not None:
        return _cached_prompts

    try:
        import yaml
    except ImportError:
        raise ImportError("PyYAML is required for prompt loading. pip install pyyaml")

    if not PROMPTS_PATH.exists():
        raise FileNotFoundError(f"Prompts file not found: {PROMPTS_PATH}")

    with open(PROMPTS_PATH, "r", encoding="utf-8") as f:
        _cached_prompts = yaml.safe_load(f)

    return _cached_prompts


def get_prompt(key: str, **kwargs: Any) -> str:
    """
    Get a prompt template by key and optionally format with kwargs.
    Keys use dot notation: e.g. 'router.template', 'crop_agent.template'
    """
    data = _load_prompts()
    keys = key.split(".")
    cursor: Any = data
    for k in keys:
        cursor = cursor.get(k)
        if cursor is None:
            raise KeyError(f"Prompt key not found: {key}")

    if not isinstance(cursor, str):
        raise ValueError(f"Prompt value for '{key}' is not a string")

    if kwargs:
        return cursor.format(**kwargs)
    return cursor


def get_prompt_version() -> str:
    """Return the current prompts version for audit."""
    data = _load_prompts()
    return str(data.get("version", "unknown"))
```

> **注意**：YAML 里提示词文本中的 `{query}` 是 Python `str.format` 变量；如果提示词本身要输出 JSON 示例，字面量大括号必须写成 `{{ }}` 转义。

验证：

```powershell
python -c "from backend.core.prompt_loader import get_prompt, get_prompt_version; print(get_prompt_version()); print(get_prompt('crop_agent.template', chat_history='None', query='test')[:80])"
```

### 步骤 3：实现 LLM 客户端工厂 `backend/core/llm_client.py`

```python
from __future__ import annotations
from langchain_groq import ChatGroq
from backend.core.config import settings


def get_llm() -> ChatGroq:

    return ChatGroq(
        api_key=settings.GROQ_API_KEY,
        model=settings.TEXT_MODEL_NAME,
        temperature=0.2,
        max_tokens=1500,
    )
```

> **为什么用工厂函数而不是全局单例？** 便于测试时替换（mock），也便于未来按请求调整参数；`ChatGroq` 本身是轻量对象，创建成本低。

### 步骤 4：实现 Token 追踪器 `backend/core/token_tracker.py`

```python
"""Token and cost tracking for LLM API usage (LLMOps cost optimization)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional
import threading

# Groq pricing (approximate $/1M tokens)
GROQ_PRICING = {
    "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    "meta-llama/llama-4-scout-17b-16e-instruct": {"input": 0.11, "output": 0.34},
    "llama-3.1-70b-versatile": {"input": 0.59, "output": 0.79},
}


@dataclass
class TokenUsage:
    """Single call token usage."""
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def estimated_cost_usd(self) -> float:
        """Rough cost estimate in USD."""
        pricing = GROQ_PRICING.get(self.model, {"input": 0.50, "output": 0.80})
        in_cost = (self.input_tokens / 1_000_000) * pricing["input"]
        out_cost = (self.output_tokens / 1_000_000) * pricing["output"]
        return round(in_cost + out_cost, 6)


class TokenTracker:
    """Per-request and per-session token aggregation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._request_usage: Dict[str, list[TokenUsage]] = {}
        self._session_totals: Dict[str, TokenUsage] = {}

    def record(self, input_tokens: int, output_tokens: int, model: str,
               request_id: Optional[str] = None, session_id: Optional[str] = None) -> None:
        """Record token usage for a single LLM call."""
        usage = TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens, model=model)
        with self._lock:
            if request_id:
                self._request_usage.setdefault(request_id, []).append(usage)
            if session_id:
                if session_id not in self._session_totals:
                    self._session_totals[session_id] = TokenUsage()
                s = self._session_totals[session_id]
                s.input_tokens += input_tokens
                s.output_tokens += output_tokens
                s.model = model

    def get_request_summary(self, request_id: str) -> Optional[Dict]:
        """Get token summary for a request."""
        with self._lock:
            usages = self._request_usage.get(request_id, [])
        if not usages:
            return None
        total_in = sum(u.input_tokens for u in usages)
        total_out = sum(u.output_tokens for u in usages)
        cost = sum(u.estimated_cost_usd() for u in usages)
        return {
            "input_tokens": total_in, "output_tokens": total_out,
            "total_tokens": total_in + total_out, "calls": len(usages),
            "estimated_cost_usd": round(cost, 6),
        }

    def get_session_summary(self, session_id: str) -> Optional[Dict]:
        """Get token summary for a session."""
        with self._lock:
            s = self._session_totals.get(session_id)
        if not s:
            return None
        return {
            "input_tokens": s.input_tokens, "output_tokens": s.output_tokens,
            "total_tokens": s.total_tokens,
            "estimated_cost_usd": s.estimated_cost_usd(),
        }


token_tracker = TokenTracker()
```

**设计要点**：`threading.Lock` 保证多 Agent 并行写入时计数不丢失；单价表集中维护，模型换价只改一处。

### 步骤 5：实现文本生成服务 `backend/services/text_service.py`

```python
from __future__ import annotations
import time
from typing import Optional, Tuple, Dict, Any

from backend.core.llm_client import get_llm
from backend.core.config import settings
from backend.core.token_tracker import token_tracker

MAX_RETRIES = 3
RETRY_BACKOFF = (1, 2, 4)
MAX_PROMPT_CHARS = 4000

DEFAULT_SYSTEM_MSG = (
    "You are AgriGPT, a domain-expert agricultural assistant. "
    "Follow instructions strictly. "
    "Do not add information unless explicitly asked. "
    "Be factual, concise, and safety-aware."
)


def _normalize_output(output: Optional[str]) -> str:
    """Normalize model output safely into plain text."""
    if output is None:
        return ""
    if isinstance(output, str):
        return output.strip()
    try:
        return str(output).strip()
    except Exception:
        return ""


def _is_retryable_error(error: Exception) -> bool:
    """Detect network errors that should be retried."""
    msg = str(error).lower()
    return any(
        token in msg
        for token in ("429", "rate limit", "too many requests", "timeout",
                      "timed out", "connection reset", "connection aborted",
                      "service unavailable", "gateway timeout",
                      "internal server error", "500", "502", "503", "504")
    )


def _extract_usage(response: Any) -> Tuple[int, int]:
    """Extract input/output tokens from LangChain response."""
    input_tok, output_tok = 0, 0
    try:
        meta = getattr(response, "response_metadata", None) or {}
        usage = meta.get("usage", meta.get("usage_metadata", {}))
        if isinstance(usage, dict):
            input_tok = int(usage.get("input_tokens", usage.get("input", 0)))
            output_tok = int(usage.get("output_tokens", usage.get("output", 0)))
    except Exception:
        pass
    return input_tok, output_tok


def query_groq_text(
    prompt: str,
    system_msg: Optional[str] = None,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Tuple[str, Dict[str, int]]:
    """
    Primary text-generation entrypoint.
    Returns (content, usage_dict with input_tokens, output_tokens).
    """

    if not isinstance(prompt, str) or not prompt.strip():
        return "No valid input was provided.", {"input_tokens": 0, "output_tokens": 0}

    if len(prompt) > MAX_PROMPT_CHARS:
        prompt = prompt[:MAX_PROMPT_CHARS] + f"\n[Input truncated to {MAX_PROMPT_CHARS} characters]"

    sys_msg = system_msg if system_msg else DEFAULT_SYSTEM_MSG
    llm = get_llm()

    for attempt in range(MAX_RETRIES):
        try:
            response = llm.invoke([
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": prompt},
            ])

            cleaned = _normalize_output(getattr(response, "content", None))
            input_tok, output_tok = _extract_usage(response)

            if request_id or session_id:
                token_tracker.record(
                    input_tokens=input_tok, output_tokens=output_tok,
                    model=settings.TEXT_MODEL_NAME,
                    request_id=request_id, session_id=session_id,
                )

            usage = {"input_tokens": input_tok, "output_tokens": output_tok}
            if cleaned:
                return cleaned, usage
            return "I could not generate a response at this moment. Please try again.", usage

        except Exception as e:
            print(f"[TEXT_SERVICE] Groq/LLM error (attempt {attempt + 1}): {str(e)[:200]}")
            if attempt < MAX_RETRIES - 1 and _is_retryable_error(e):
                time.sleep(RETRY_BACKOFF[attempt])
                continue
            return "The system is temporarily unavailable. Please try again later.", {
                "input_tokens": 0, "output_tokens": 0,
            }

    return "The system is temporarily unavailable. Please try again later.", {
        "input_tokens": 0, "output_tokens": 0,
    }
```

**设计要点（企业级防御式编程）**：

1. **入参防御**：空输入、超长输入都有明确行为，绝不把异常直接抛给用户；
2. **选择性重试**：只对限流/网络类错误重试，参数错误（401 等）重试没有意义；
3. **失败返回友好文案**而不是 `raise`——调用方无需到处写 try/except。

### 步骤 6：端到端验证（第一次让 AI 开口）

在项目根目录创建临时脚本 `smoke_test.py`：

```python
from backend.services.text_service import query_groq_text
from backend.core.token_tracker import token_tracker

resp, usage = query_groq_text(
    "What fertilizer should I use for tomatoes?",
    request_id="smoke-1", session_id="smoke-session",
)
print("ANSWER:", resp[:200])
print("USAGE:", usage)
print("SUMMARY:", token_tracker.get_request_summary("smoke-1"))
```

```powershell
python smoke_test.py
```

预期：输出农业建议文本、Token 用量与费用摘要。验证后删除该脚本（或移入 `tests/`）。

---

## 三、验收标准

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 1 | `get_prompt("crop_agent.template", ...)` | 变量替换正确 |
| 2 | `get_prompt("not_exist.key")` | 抛出清晰的 `KeyError` 信息 |
| 3 | `smoke_test.py` | 输出回答 + Token 用量 + 费用摘要 |
| 4 | 断网或填错误 Key 再运行 | 输出友好降级文案，无堆栈泄露 |
| 5 | 输入超过 4000 字符 | 回答中出现 `[Input truncated...]` 标记 |

---

## 四、常见问题排查

| 现象 | 原因与解决 |
|------|-----------|
| `401 Invalid API Key` | `.env` 的 Key 复制不完整；确认 `gsk_` 前缀完整 |
| `str.format` 报 KeyError | 提示词里写了未转义的字面量 `{}`，改成 `{{}}` |
| Token 用量全是 0 | 部分网关元数据字段不同——检查 `_extract_usage` 的字段兜底逻辑 |
| `RuntimeWarning: coroutine ... never awaited` | 使用了 `ainvoke` 但函数非 async——本服务统一用同步 `invoke` |

---

## 五、拓展任务（选做）

1. 给 `TokenTracker` 增加 `reset_session(session_id)` 方法与单元测试；
2. 在 `prompts.yaml` 增加 `version` 升级策略说明：当提示词大改时如何做到新旧并行（提示：`version: "1.1"` + 读取时指定版本）；
3. 用环境变量 `HTTP_PROXY` 测试重试逻辑：临时指向一个不通的代理，观察 3 次退避日志。

> **下一节预告**：实训 04 将把文本服务装配成第一个专家 Agent，并打通 `/ask/text` 接口。
