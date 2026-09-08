# 项目实训05｜多 Agent 编排与意图路由

> **训练目标**：实现 LLM 结构化输出意图路由、Agent 注册表、多 Agent 并行执行与格式化合成——本项目的**核心架构**。
> **预计时长**：8 学时 ｜ **前置条件**：实训 04 完成
> **本次交付物**：`core/router_schema.py`、`core/langchain_prompts.py`、`agents/irrigation_agent.py`、`agents/yield_agent.py`、`agents/formatter_agent.py`、`core/langchain_tools.py`、`agents/master_agent.py`

---

## 一、知识点

### 1. 为什么需要"意图路由"

用户一句话可能同时涉及多个领域（"番茄叶子发黄，是不是浇水太多？"→ 病虫害 + 灌溉）。路由器的职责：

```
用户查询 → LLM 为每个候选 Agent 打 0~100 分 → 按阈值规则选出 ≤3 个 Agent
```

**决策规则**（本项目）：

| 规则 | 数值 |
|------|------|
| 主 Agent（primary）门槛 | 最高分 ≥75；50~74 也可担任；全低于 50 回落 CropAgent |
| 辅助 Agent（supporting）门槛 | ≥50 |
| 单次上限 | 3 个 Agent |

### 2. 结构化输出（Structured Output）

让 LLM 返回"自由 JSON 文本"再正则解析是脆弱的。正确做法：用 **Pydantic 模型 + `with_structured_output`**，由框架保证返回物合法——解析零正则。

### 3. 注册表模式（Registry）

所有 Agent 单例缓存在字典中，路由层"按名字调度"，新增 Agent 只需：写一个类 → 注册一行 → 在提示词里加一句描述。

---

## 二、操作步骤

### 步骤 1：定义路由输出 Schema `backend/core/router_schema.py`

```python
"""Pydantic schema for router structured output - eliminates regex/JSON parsing."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AgentScore(BaseModel):
    """Single agent with relevance score."""
    agent: str = Field(description="Agent name, e.g. CropAgent, SubsidyAgent")
    score: int = Field(ge=0, le=100, description="Relevance score 0-100")


class RouterOutput(BaseModel):
    """Structured router response - list of agents with scores."""
    agents: list[AgentScore] = Field(
        default_factory=list,
        description="List of agents with relevance scores, sorted by score descending",
    )
```

> `Field(ge=0, le=100)` 让越界分数在反序列化时直接失败，而不是污染下游逻辑。

### 步骤 2：定义 LangChain 提示词模板 `backend/core/langchain_prompts.py`

```python
"""LangChain ChatPromptTemplate definitions - enables LCEL chains and LangSmith."""
from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

# Router prompt - used with structured output
ROUTER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an agricultural AI intent router.

TASK: Analyze the farmer's query and assign a RELEVANCE SCORE (0-100) to EACH available agent.

RULES:
1. Context Awareness: If the user says "it", "that", or refers to a previous topic, use the HISTORY to infer.
2. Score 0-100: 90-100 = Perfect match, 70-89 = Strong, 50-69 = Weak, <50 = Irrelevant
3. Identify the single most relevant agent (primary).
4. Include other agents only if they cover a DISTINCT part of the query (score > 50).
5. CropAgent Fallback: If intent unclear, prefer specific agents (Pest, Subsidy) when symptoms match.

AVAILABLE AGENTS:
{agent_map}

PREVIOUS CONVERSATION:
{chat_history}

FARMER QUERY: "{query}"
"""),
])

# Formatter prompt - final synthesis
FORMATTER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are AgriGPT FormatterAgent - the FINAL OUTPUT LAYER.
Provide a CLEAR, COMPREHENSIVE, and FRIENDLY response to the farmer.
SKIP THE PREAMBLE. Start IMMEDIATELY with the answer.
Use **Bold** for emphasis, ### for sections, bullet points for lists.
Do not invent new advice not present in the expert text.
"""),
    ("human", """User Query: "{user_query}"
Has Image: {has_image}

Expert Agent Responses:
{combined_content}

Synthesize into a clear, well-formatted response. Start with a direct answer.""")
])
```

> 用 `ChatPromptTemplate` 而非普通字符串的原因：可参与 LCEL 管道（`prompt | llm | parser`），且能被 LangSmith 逐步追踪。

### 步骤 3：补齐灌溉与产量专家

在 `prompts/prompts.yaml` 追加两段模板：

```yaml
irrigation_agent:
  template: |
    You are AgriGPT IrrigationAgent.
    ROLE: You are an irrigation and water management specialist.

    YOU HANDLE ONLY irrigation frequency (stage-based or conditional), soil moisture management,
    and drip, sprinkler, and flood irrigation practices, including water-saving methods.

    STRICT BOUNDARIES:
    Do NOT diagnose pests, diseases, or nutrient deficiencies.
    Do NOT analyze images.
    Do NOT calculate or optimize yield.
    Do NOT recommend chemicals or fertilizers.
    Do NOT give subsidy or government scheme advice.

    SAFETY RULES:
    Do NOT guess soil type or crop stage unless the farmer explicitly states it.
    Use conditional guidance such as 'if sandy soil' or 'if high temperature'.
    If essential details are missing, say so clearly.
    Avoid exact schedules when conditions are unknown.

    PREVIOUS CONTEXT: {chat_history}
    FARMER QUERY: {query}

    RESPONSE INSTRUCTIONS:
    Give clear and practical irrigation advice.
    Explain when to water and when NOT to water.
    Mention visible signs of overwatering and underwatering only.
    Suggest water-saving practices where relevant.
    Keep language farmer-friendly and easy to follow.
    Avoid repetition and theory.

    OUTPUT:
    Plain advisory text only.
    No formatting, no titles, no forced bullets.

yield_agent:
  template: |
    You are AgriGPT YieldAgent.
    Your role is to analyze yield-related problems conservatively.
    Do not give guaranteed yield numbers or exact targets.
    Use conditional language only.
    Do not prescribe chemical dosages or irrigation schedules.
    Do not override crop, irrigation, or pest specialists.

    Explain the following clearly and simply:
    First, describe broad expected yield ranges only if crop and region are mentioned,
    and clearly state that actual yield depends on conditions.

    Next, identify the most common limiting factors that reduce yield,
    such as soil fertility gaps, water stress, planting time, seed quality,
    pest pressure, or climate stress.

    Then, suggest practical next steps focused on diagnosis and prioritization only,
    for example soil testing, irrigation review, or pest inspection,
    without giving exact schedules or dosages.

    If important details are missing, say so clearly.
    Keep the language farmer-friendly and non-technical.
    Avoid repetition and avoid theory.

    PREVIOUS CONTEXT: {chat_history}
    Farmer question: {query}
```

然后创建 `agents/irrigation_agent.py` 与 `agents/yield_agent.py`——结构与 CropAgent **完全一致**，只改三处：

| 位置 | IrrigationAgent | YieldAgent |
|------|-----------------|------------|
| `name` | `"IrrigationAgent"` | `"YieldAgent"` |
| 提示词键 | `irrigation_agent.template` | `yield_agent.template` |
| 空输入引导文案 | 灌溉示例问题 | 产量问题描述引导 |
| 失败兜底文案 | `"Irrigation advice could not be generated..."` | `"Yield analysis could not be generated..."` |

> 这正是基类抽象的价值：新增一个专家 ≈ 1 个提示词 + 50 行模板代码。请独立完成这两个类（对照 `源码/` 自查）。

### 步骤 4：实现 Agent 注册表 `backend/core/langchain_tools.py`

```python
"""Agent registry - cached to avoid repeated instantiation."""
from __future__ import annotations

from typing import Dict, List, TypeAlias

from backend.agents.crop_agent import CropAgent
from backend.agents.irrigation_agent import IrrigationAgent
from backend.agents.pest_agent import PestAgent
from backend.agents.subsidy_agent import SubsidyAgent
from backend.agents.yield_agent import YieldAgent
from backend.agents.formatter_agent import FormatterAgent

AgentRegistry: TypeAlias = Dict[str, object]

# FormatterAgent must never be selected by router
NON_ROUTABLE_AGENTS = {"FormatterAgent"}

_AGENT_REGISTRY_CACHE: AgentRegistry | None = None


def get_agent_registry() -> AgentRegistry:
    """Return cached agent registry - single instance per process."""
    global _AGENT_REGISTRY_CACHE
    if _AGENT_REGISTRY_CACHE is None:
        _AGENT_REGISTRY_CACHE = {
            "CropAgent": CropAgent(),
            "PestAgent": PestAgent(),
            "IrrigationAgent": IrrigationAgent(),
            "SubsidyAgent": SubsidyAgent(),
            "YieldAgent": YieldAgent(),
            "FormatterAgent": FormatterAgent(),
        }
    return _AGENT_REGISTRY_CACHE


# Router Metadata
AGENT_DESCRIPTIONS: List[dict] = [
    {
        "name": "CropAgent",
        "description": (
            "General crop management and cultivation advice. "
            "Use for fertilizer selection and dosage, soil preparation, "
            "planting methods, crop growth stages, crop rotation, "
            "and overall best farming practices. "
            "Also use if the query is broad or unclear and needs general guidance."
        ),
    },
    {
        "name": "PestAgent",
        "description": (
            "Pest, disease, or nutrient deficiency diagnosis. "
            "Use when the farmer reports insects, worms, larvae, "
            "leaf spots, fungal or bacterial infection, "
            "yellowing, curling, wilting, discoloration, or damage symptoms. "
            "This agent MUST be selected for image-based crop problems."
        ),
    },
    {
        "name": "IrrigationAgent",
        "description": (
            "Irrigation and water management expert. "
            "Use for watering frequency, irrigation scheduling, "
            "water stress (overwatering or drought), soil moisture, "
            "drip or sprinkler systems, and water-saving practices."
        ),
    },
    {
        "name": "YieldAgent",
        "description": (
            "Yield improvement and productivity analysis. "
            "Use when the farmer mentions low yield, poor harvest, "
            "reduced output, small fruits, fewer tillers, "
            "or asks how to increase crop productivity."
        ),
    },
    {
        "name": "SubsidyAgent",
        "description": (
            "Government subsidy and agricultural scheme information (India-focused). "
            "Use for PM-Kisan, loan support, crop insurance, "
            "drip irrigation subsidy, equipment or machinery grants, "
            "and eligibility for government financial assistance."
        ),
    },
]
```

> **注意**：此文件引用了 `PestAgent`、`SubsidyAgent`，它们分别在实训 06/07 实现。**建议本步骤先临时注释这两行**，待对应实训完成后再放开；或按顺序完成 06/07 后再统一整合。

### 步骤 5：实现格式化专家 `backend/agents/formatter_agent.py`

FormatterAgent 接收 `{user_query, routing_mode, agent_results}`，按角色优先级排序后交给 LLM 做**纯排版合成**：

```python
from typing import Any, Dict, List

from backend.services.text_service import query_groq_text
from backend.agents.agri_agent_base import AgriAgentBase
from backend.core.langchain_prompts import FORMATTER_PROMPT


class FormatterAgent(AgriAgentBase):
    """
    FormatterAgent

    Responsibilities:
    - Presentation only
    - Role-aware ordering
    - Zero hallucination surface
    - LLM used strictly for formatting
    """

    name = "FormatterAgent"

    def handle_query(self, payload: Any = None, image_path: str = None,
                     chat_history: str = None, request_id: str = None,
                     session_id: str = None, **kwargs) -> str:

        if isinstance(payload, str):
            clean_text = payload.strip()
            if not clean_text:
                return self.respond_and_record("", "No content available to format.", image_path)
            return self._format_text(user_query="", ordered_blocks=[clean_text],
                                     image_path=image_path, meta=None,
                                     request_id=request_id, session_id=session_id)

        if not isinstance(payload, dict):
            return self.respond_and_record("", str(payload), image_path)

        user_query: str = str(payload.get("user_query", "")).strip()
        agent_results: List[Dict[str, str]] = payload.get("agent_results", [])
        routing_mode: str = str(payload.get("routing_mode", "unknown"))

        if not agent_results:
            return self.respond_and_record(user_query, "No agent responses were generated.", image_path)

        role_priority = {"primary": 0, "supporting": 1, "impact": 2}

        agent_results_sorted = sorted(
            agent_results,
            key=lambda x: role_priority.get(str(x.get("role", "supporting")).lower(), 99),
        )

        ordered_blocks: List[str] = []
        role_log: List[Dict[str, str]] = []

        for item in agent_results_sorted:
            role = str(item.get("role", "supporting")).lower()
            agent = str(item.get("agent", "UnknownAgent"))
            content = str(item.get("content") or "").strip()
            if content:
                ordered_blocks.append(f"[{role.upper()} | {agent}]\n{content}")
                role_log.append({"agent": agent, "role": role})

        if not ordered_blocks:
            return self.respond_and_record(user_query, "Agent responses were empty.", image_path)

        meta = {"routing_mode": routing_mode, "agents": role_log, "agent_count": len(role_log)}

        return self._format_text(user_query=user_query, ordered_blocks=ordered_blocks,
                                 image_path=image_path, meta=meta,
                                 request_id=request_id, session_id=session_id)

    def _format_text(self, user_query, ordered_blocks, image_path=None, meta=None,
                     request_id=None, session_id=None) -> str:

        combined_content = "\n\n".join(ordered_blocks)

        prompt_msgs = FORMATTER_PROMPT.format_messages(
            user_query=user_query,
            has_image="Yes" if image_path else "No",
            combined_content=combined_content,
        )
        system_content = prompt_msgs[0].content if prompt_msgs else ""
        user_content = prompt_msgs[1].content if len(prompt_msgs) > 1 else combined_content

        try:
            formatted, _ = query_groq_text(
                user_content,
                system_msg=system_content if system_content else None,
                request_id=request_id,
                session_id=session_id,
            )
        except Exception:
            formatted = combined_content

        formatted = str(formatted).strip()

        return self.respond_and_record(query=user_query, response=formatted,
                                       image_path=image_path, meta=meta)
```

**设计要点**：`meta` 里记录参与合成的 Agent 列表（`agents`、`agent_count`），最终写进 `query_log.json`——这就是实训 09 统计"各 Agent 用量"的数据来源。

### 步骤 6：实现主控编排 `backend/agents/master_agent.py`

```python
"""Master agent - structured output router, ChatPromptTemplate, no regex parsing."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Any, List

from backend.core.langchain_tools import (
    get_agent_registry,
    NON_ROUTABLE_AGENTS,
    AGENT_DESCRIPTIONS,
)
from backend.core.llm_client import get_llm
from backend.core.router_schema import RouterOutput, AgentScore
from backend.core.langchain_prompts import ROUTER_PROMPT

MAX_QUERY_CHARS = 2000
MAX_ROUTED_AGENTS = 3

PRIMARY_SCORE_THRESHOLD = 75
SECONDARY_SCORE_THRESHOLD = 50


def route_query(
    query: Optional[str] = None,
    image_path: Optional[str] = None,
    session_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> str:

    registry = get_agent_registry()

    clean_query = str(query or "").strip()

    if clean_query and len(clean_query) > MAX_QUERY_CHARS:
        return "Your question is too long. Please shorten it."

    chat_history_str = "No previous conversation."  # 实训 08 替换为记忆管理器

    agent_kw = {"request_id": request_id, "session_id": session_id}

    if not clean_query:
        return "Please ask an agriculture-related question."

    routed = llm_route_with_scores(
        clean_query, registry, chat_history_str, request_id, session_id
    )

    if not routed:
        routed = [{"agent": "CropAgent", "role": "primary", "score": 0}]

    if not any(r["role"] == "primary" for r in routed):
        routed[0]["role"] = "primary"

    final_execution_list = routed[:MAX_ROUTED_AGENTS]

    # Run agents in parallel for faster multi-agent flows
    def _run_agent(idx_and_item) -> tuple[int, Optional[Dict[str, Any]]]:
        idx, item = idx_and_item
        agent_name = item["agent"]
        if agent_name not in registry:
            return (idx, None)
        output = registry[agent_name].handle_query(
            query=clean_query,
            chat_history=chat_history_str,
            **agent_kw,
        )
        return (idx, {"agent": agent_name, "role": item["role"],
                      "score": item.get("score", 0), "content": output})

    agent_results_by_idx: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=MAX_ROUTED_AGENTS) as executor:
        tasks = [(i, item) for i, item in enumerate(final_execution_list)]
        futures = {executor.submit(_run_agent, t): t[0] for t in tasks}
        for future in as_completed(futures):
            try:
                idx, result = future.result()
                if result is not None:
                    agent_results_by_idx[idx] = result
            except Exception as e:
                print(f"[ROUTER] Agent execution failed: {e}")
    agent_results = [agent_results_by_idx[i] for i in range(len(final_execution_list))
                     if i in agent_results_by_idx]

    payload = {
        "user_query": clean_query,
        "routing_mode": "text_only",
        "agent_results": agent_results,
    }

    formatted_response = registry["FormatterAgent"].handle_query(payload, **agent_kw)

    score_summary = ", ".join(
        f"{res['agent']}: {res['score']}" for res in agent_results if "score" in res
    )
    if score_summary:
        print(f"\n[ROUTER CONFIDENCE] {score_summary}\n")

    return formatted_response


def llm_route_with_scores(
    query: str,
    registry: Dict[str, Any],
    chat_history: str = "",
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> List[Dict[str, Any]]:

    agent_map = "\n".join(
        f"- {a['name']}: {a['description']}" for a in AGENT_DESCRIPTIONS
    )

    llm = get_llm()
    structured_llm = llm.with_structured_output(RouterOutput)

    try:
        chain = ROUTER_PROMPT | structured_llm
        result: RouterOutput = chain.invoke({
            "agent_map": agent_map,
            "chat_history": chat_history or "No previous conversation.",
            "query": query,
        })
    except Exception as e:
        print(f"Router structured output failed, falling back to JSON parse: {e}")
        result = _fallback_router_parse(llm, agent_map, chat_history, query)
        if result is None:
            return []

    candidates = []
    seen = set()

    for item in result.agents:
        agent = item.agent
        score = item.score
        if (agent in registry and agent not in NON_ROUTABLE_AGENTS and agent not in seen):
            candidates.append({"agent": agent, "score": score})
            seen.add(agent)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    final_routes = []

    if not candidates:
        return []

    best = candidates[0]
    if best["score"] >= PRIMARY_SCORE_THRESHOLD:
        final_routes.append({"agent": best["agent"], "role": "primary", "score": best["score"]})
    elif best["agent"] == "CropAgent":
        final_routes.append({"agent": "CropAgent", "role": "primary", "score": best["score"]})
    elif best["score"] >= 50:
        final_routes.append({"agent": best["agent"], "role": "primary", "score": best["score"]})
    else:
        return [{"agent": "CropAgent", "role": "primary", "score": 0}]

    for cand in candidates[1:]:
        if len(final_routes) >= MAX_ROUTED_AGENTS:
            break
        if cand["score"] >= SECONDARY_SCORE_THRESHOLD:
            final_routes.append({"agent": cand["agent"], "role": "supporting", "score": cand["score"]})

    return final_routes


def _fallback_router_parse(llm, agent_map: str, chat_history: str, query: str):
    """Fallback when structured output fails - parse JSON from raw response."""
    try:
        msgs = ROUTER_PROMPT.format_messages(
            agent_map=agent_map,
            chat_history=chat_history or "No previous conversation.",
            query=query,
        )
        raw = llm.invoke(msgs).content
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return None
        parsed = json.loads(match.group())
        if not isinstance(parsed, list):
            return None
        agents = []
        for p in parsed:
            if not isinstance(p, dict):
                continue
            try:
                score_val = p.get("score", 0)
                score_val = int(score_val) if score_val is not None else 0
                score_val = max(0, min(100, score_val))
                agents.append(AgentScore(agent=str(p.get("agent", "") or ""), score=score_val))
            except (TypeError, ValueError):
                continue
        return RouterOutput(agents=agents) if agents else None
    except Exception:
        return None
```

**设计要点**：

1. **三层降级链**：结构化输出 → JSON 正则解析 → 默认 CropAgent，任何情况下用户都有回答；
2. **并行执行**：`ThreadPoolExecutor` 让 3 个 Agent 同时跑，总耗时 ≈ 最慢的一个，而非三者之和；
3. **按索引回收结果**：`as_completed` 无序返回，用原始索引重组保证输出顺序稳定；
4. **去重 + 黑名单**：`seen` 集合防重复路由，`NON_ROUTABLE_AGENTS` 阻止 Formatter 被选中。

> 实训 06/08 会在此文件基础上补入：图片强制路由（PestAgent）、会话记忆。

### 步骤 7：接口层切换为路由调度

修改 `ask_router.py` 的 `/ask/text`：

```python
    from backend.agents.master_agent import route_query

    try:
        response = route_query(
            query=query,
            image_path=None,
            session_id=session_id,
            request_id=request_id,
        )
    except Exception as e:
        raise HTTPException(500, f"Error: {str(e)}")
```

### 步骤 8：验证路由效果

启动服务后依次提问，观察控制台 `[ROUTER CONFIDENCE]` 输出：

| 测试查询 | 期望主 Agent |
|----------|--------------|
| `What fertilizer should I use for tomatoes?` | CropAgent |
| `How often should I water my wheat in summer?` | IrrigationAgent |
| `My rice yield is very low this year, why?` | YieldAgent |
| `My tomato leaves have yellow spots and are wilting, and I also want to know how to water them properly` | PestAgent 或 CropAgent + IrrigationAgent 并行 |

同时检查 `query_log.json`：`meta.agents` 字段应记录实际参与的 Agent 列表。

---

## 三、验收标准

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 1 | 四类单领域问题 | 均路由到正确专家（看控制台分数日志） |
| 2 | 混合意图问题 | 出现 ≥2 个 Agent 的 `[ROUTER CONFIDENCE]` |
| 3 | 完全无关问题（如"今天股市如何"） | 回落 CropAgent 且不崩溃 |
| 4 | 最终回答 | 带 Markdown 结构的合成文本（非原始单 Agent 输出） |
| 5 | 故意把模型名改错再提问 | 走降级文案，接口不 500 |

---

## 四、常见问题排查

| 现象 | 原因与解决 |
|------|-----------|
| `with_structured_output` 报错 | 确认 `langchain-groq` 版本较新；旧版需改用 `pydantic` 参数模式 |
| 路由总选中 CropAgent | 检查 `AGENT_DESCRIPTIONS` 是否粘贴完整——描述质量直接决定路由质量 |
| 并行时 Token 统计错乱 | `TokenTracker` 已加锁；请确认你调 `record` 时传入了同一个 `request_id` |
| Formatter 输出丢失专家内容 | 检查 `combined_content` 拼接；专家输出为空时会被跳过（设计如此） |

---

## 五、拓展任务（选做）

1. 给路由增加"置信度日志持久化"：把每次路由的完整分数表写入 `query_log.json` 的 `meta.routing_scores`；
2. 实验：把 `PRIMARY_SCORE_THRESHOLD` 从 75 调到 60，用 5 个测试问题分析路由召回/精确率变化；
3. 新增一个 `MarketAgent`（农产品市场价格咨询，可用编造数据源），完整走一遍"新 Agent 接入三件套"。

> **下一节预告**：实训 06 接入视觉模型，让系统"看得见"——图片诊断与多模态接口。
