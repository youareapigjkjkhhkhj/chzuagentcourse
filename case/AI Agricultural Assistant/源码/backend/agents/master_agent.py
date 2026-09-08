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
from backend.core.memory_manager import get_chat_history, add_message_to_history, format_history_for_prompt
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

    chat_history_list = get_chat_history(session_id)
    chat_history_str = format_history_for_prompt(chat_history_list)

    agent_kw = {"request_id": request_id, "session_id": session_id}

    if image_path and not clean_query:
        pest_output = registry["PestAgent"].handle_query(
            query="",
            image_path=image_path,
            chat_history=chat_history_str,
            **agent_kw,
        )

        payload = {
            "user_query": "Image-based diagnosis",
            "routing_mode": "image_only",
            "agent_results": [
                {
                    "agent": "PestAgent",
                    "role": "primary",
                    "score": 100,
                    "content": pest_output,
                }
            ],
        }

        if session_id:
            add_message_to_history(session_id, "user", "Uploaded an image")

        response = registry["FormatterAgent"].handle_query(payload, **agent_kw)

        if session_id:
            add_message_to_history(session_id, "assistant", response)

        return response

    if not clean_query:
        return "Please ask an agriculture-related question."

    routed = llm_route_with_scores(
        clean_query, registry, chat_history_str, request_id, session_id
    )

    if not routed:
        routed = [{"agent": "CropAgent", "role": "primary", "score": 0}]

    if not any(r["role"] == "primary" for r in routed):
        routed[0]["role"] = "primary"

    if image_path:
        pest_in_route = any(r["agent"] == "PestAgent" for r in routed)
        if not pest_in_route:
            routed.append({"agent": "PestAgent", "role": "supporting", "score": 100})

    final_execution_list = routed[:MAX_ROUTED_AGENTS]

    # Ensure PestAgent is included when image present; replace lowest-priority slot if needed
    if image_path and final_execution_list and not any(r["agent"] == "PestAgent" for r in final_execution_list):
        final_execution_list[-1] = {"agent": "PestAgent", "role": "supporting", "score": 100}

    # Run agents in parallel for faster multi-agent flows
    def _run_agent(idx_and_item) -> tuple[int, Optional[Dict[str, Any]]]:
        idx, item = idx_and_item
        agent_name = item["agent"]
        role = item["role"]
        score = item.get("score", 0)
        if agent_name not in registry:
            return (idx, None)
        if agent_name == "PestAgent" and image_path:
            output = registry[agent_name].handle_query(
                query=clean_query,
                image_path=image_path,
                chat_history=chat_history_str,
                **agent_kw,
            )
        else:
            output = registry[agent_name].handle_query(
                query=clean_query,
                chat_history=chat_history_str,
                **agent_kw,
            )
        return (idx, {"agent": agent_name, "role": role, "score": score, "content": output})

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
    agent_results = [agent_results_by_idx[i] for i in range(len(final_execution_list)) if i in agent_results_by_idx]

    payload = {
        "user_query": clean_query,
        "routing_mode": "multimodal" if image_path else "text_only",
        "agent_results": agent_results,
    }

    formatted_response = registry["FormatterAgent"].handle_query(payload, **agent_kw)

    if session_id:
        add_message_to_history(session_id, "user", clean_query)
        add_message_to_history(session_id, "assistant", formatted_response)

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
        if (
            agent in registry
            and agent not in NON_ROUTABLE_AGENTS
            and agent not in seen
        ):
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
