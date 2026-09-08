"""
LCEL RAG chain for SubsidyAgent - composable, LangSmith-traced pipeline.
Single retrieve, then prompt | llm | parse for full trace.
"""
from __future__ import annotations

from typing import List, Optional

from langchain_core.output_parsers import StrOutputParser

from backend.core.llm_client import get_llm
from backend.core.langchain_prompts import SUBSIDY_RAG_PROMPT
from backend.services.rag_service import rag_service
from backend.core.config import settings
from backend.core.token_tracker import token_tracker


def _format_subsidy_docs(docs: List[dict]) -> str:
    """Convert retrieved subsidy dicts to context string."""
    if not docs:
        return "No verified government scheme information was found for this query."
    parts = []
    for i, d in enumerate(docs, 1):
        parts.append(
            f"Scheme information {i}: "
            f"Scheme name: {d.get('scheme_name', 'Not specified')}. "
            f"Eligibility: {d.get('eligibility', 'Not specified')}. "
            f"Benefits: {d.get('benefits', 'Not specified')}. "
            f"Application steps: {d.get('application_steps', 'Not specified')}. "
            f"Required documents: {d.get('documents', 'Not specified')}. "
            f"Additional notes: {d.get('notes', 'Not specified')}. "
        )
    return " ".join(parts)


_SUBSIDY_CHAIN = None


def _get_subsidy_chain():
    """Cached LCEL chain: prompt | llm | parse."""
    global _SUBSIDY_CHAIN
    if _SUBSIDY_CHAIN is None:
        _SUBSIDY_CHAIN = (
            SUBSIDY_RAG_PROMPT
            | get_llm()
            | StrOutputParser()
        )
    return _SUBSIDY_CHAIN


def invoke_subsidy_rag_chain(
    query: str,
    chat_history: str = "None",
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> tuple[str, list[dict]]:
    """
    Invoke the RAG chain. Returns (response, retrieved_docs) for guardrails.
    Single retrieve, then LCEL chain for traceability.
    """
    docs = rag_service.retrieve(query, k=2)
    context = _format_subsidy_docs(docs)

    inputs = {
        "query": query,
        "chat_history": chat_history or "None",
        "context": context,
    }

    chain = _get_subsidy_chain()
    raw = chain.invoke(inputs)
    response = str(raw).strip() if raw is not None else ""

    if request_id or session_id:
        approx_in = (len(str(inputs)) + 500) // 4
        approx_out = len(response) // 4
        token_tracker.record(
            input_tokens=approx_in,
            output_tokens=approx_out,
            model=settings.TEXT_MODEL_NAME,
            request_id=request_id,
            session_id=session_id,
        )

    return response, docs
