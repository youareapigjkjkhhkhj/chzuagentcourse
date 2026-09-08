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

    def handle_query(
        self,
        payload: Any = None,
        image_path: str = None,
        chat_history: str = None,
        request_id: str = None,
        session_id: str = None,
        **kwargs,
    ) -> str:

        if isinstance(payload, str):
            clean_text = payload.strip()
            if not clean_text:
                return self.respond_and_record(
                    "", "No content available to format.", image_path
                )

            return self._format_text(
                user_query="",
                ordered_blocks=[clean_text],
                image_path=image_path,
                meta=None,
                request_id=request_id,
                session_id=session_id,
            )

        if not isinstance(payload, dict):
            return self.respond_and_record("", str(payload), image_path)

        user_query: str = str(payload.get("user_query", "")).strip()
        agent_results: List[Dict[str, str]] = payload.get("agent_results", [])
        routing_mode: str = str(payload.get("routing_mode", "unknown"))

        if not agent_results:
            return self.respond_and_record(
                user_query, "No agent responses were generated.", image_path
            )

        role_priority = {
            "primary": 0,
            "supporting": 1,
            "impact": 2,
        }

        agent_results_sorted = sorted(
            agent_results,
            key=lambda x: role_priority.get(
                str(x.get("role", "supporting")).lower(), 99
            ),
        )

        ordered_blocks: List[str] = []
        role_log: List[Dict[str, str]] = []

        for item in agent_results_sorted:
            role = str(item.get("role", "supporting")).lower()
            agent = str(item.get("agent", "UnknownAgent"))
            raw_content = item.get("content")
            content = str(raw_content or "").strip()

            if content:
                ordered_blocks.append(
                    f"[{role.upper()} | {agent}]\n{content}"
                )
                role_log.append({
                    "agent": agent,
                    "role": role,
                })

        if not ordered_blocks:
            return self.respond_and_record(
                user_query, "Agent responses were empty.", image_path
            )

        meta = {
            "routing_mode": routing_mode,
            "agents": role_log,
            "agent_count": len(role_log),
        }

        return self._format_text(
            user_query=user_query,
            ordered_blocks=ordered_blocks,
            image_path=image_path,
            meta=meta,
            request_id=request_id,
            session_id=session_id,
        )

    def _format_text(
        self,
        user_query: str,
        ordered_blocks: List[str],
        image_path: str = None,
        meta: Dict[str, Any] = None,
        request_id: str = None,
        session_id: str = None,
    ) -> str:

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

        return self.respond_and_record(
            query=user_query,
            response=formatted,
            image_path=image_path,
            meta=meta,
        )
