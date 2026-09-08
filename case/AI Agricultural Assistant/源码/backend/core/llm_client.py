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
