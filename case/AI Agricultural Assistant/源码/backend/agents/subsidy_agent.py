"""SubsidyAgent - uses LCEL RAG chain for traced, composable pipeline."""
from __future__ import annotations

import unicodedata

from backend.agents.agri_agent_base import AgriAgentBase
from backend.services.rag_chain import invoke_subsidy_rag_chain
from backend.core.guardrails import detect_subsidy_hallucination


class SubsidyAgent(AgriAgentBase):
    """
    SubsidyAgent:
    Handles government schemes and agricultural subsidy information.
    Uses LCEL RAG chain - LangSmith-traced, composable pipeline.
    Guardrails ensure responses are grounded in retrieved docs.
    """

    name = "SubsidyAgent"

    def _sanitize_query(self, text: str) -> str:
        if not text:
            return ""
        text = unicodedata.normalize("NFKC", text)
        text = text.replace("\x00", "").replace("\u200c", "")
        return text.strip()

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
                "Please ask about a specific agricultural subsidy or government scheme. "
                "For example, drip irrigation subsidy, PM-Kisan eligibility, or equipment support schemes."
            )
            return self.respond_and_record("", response, image_path)

        query_clean = self._sanitize_query(query)

        try:
            result, retrieved_docs = invoke_subsidy_rag_chain(
                query=query_clean,
                chat_history=chat_history or "None",
                request_id=request_id,
                session_id=session_id,
            )
        except Exception:
            result = "Subsidy information could not be generated at this time."
            retrieved_docs = []

        # Guardrails: verify response is grounded in retrieved docs
        _, safe_result = detect_subsidy_hallucination(result, retrieved_docs)

        return self.respond_and_record(query_clean, safe_result, image_path)
