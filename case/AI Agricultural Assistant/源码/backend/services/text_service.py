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
        for token in (
            "429",
            "rate limit",
            "too many requests",
            "timeout",
            "timed out",
            "connection reset",
            "connection aborted",
            "service unavailable",
            "gateway timeout",
            "internal server error",
            "500",
            "502",
            "503",
            "504",
        )
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
        prompt = (
            prompt[:MAX_PROMPT_CHARS]
            + f"\n[Input truncated to {MAX_PROMPT_CHARS} characters]"
        )

    sys_msg = system_msg if system_msg else DEFAULT_SYSTEM_MSG
    llm = get_llm()

    for attempt in range(MAX_RETRIES):
        try:
            response = llm.invoke(
                [
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": prompt},
                ]
            )

            content = getattr(response, "content", None)
            cleaned = _normalize_output(content)

            input_tok, output_tok = _extract_usage(response)
            if request_id or session_id:
                token_tracker.record(
                    input_tokens=input_tok,
                    output_tokens=output_tok,
                    model=settings.TEXT_MODEL_NAME,
                    request_id=request_id,
                    session_id=session_id,
                )

            usage = {"input_tokens": input_tok, "output_tokens": output_tok}

            if cleaned:
                return cleaned, usage

            return "I could not generate a response at this moment. Please try again.", usage

        except Exception as e:
            err_msg = str(e)
            print(f"[TEXT_SERVICE] Groq/LLM error (attempt {attempt + 1}): {err_msg[:200]}")
            if attempt < MAX_RETRIES - 1 and _is_retryable_error(e):
                time.sleep(RETRY_BACKOFF[attempt])
                continue

            return "The system is temporarily unavailable. Please try again later.", {
                "input_tokens": 0,
                "output_tokens": 0,
            }

    return "The system is temporarily unavailable. Please try again later.", {
        "input_tokens": 0,
        "output_tokens": 0,
    }
