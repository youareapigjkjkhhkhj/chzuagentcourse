"""Token and cost tracking for LLM API usage (LLMOps cost optimization)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional
import threading

# Groq pricing (approximate $/1M tokens, as of 2025 - adjust as needed)
# llama-3.3-70b: input ~$0.59, output ~$0.79 per 1M tokens
# meta-llama/llama-4-scout-17b: input ~$0.11, output ~$0.34 per 1M tokens
GROQ_PRICING = {
    "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    "meta-llama/llama-4-scout-17b-16e-instruct": {"input": 0.11, "output": 0.34},
    # Legacy (fallback for old recorded sessions)
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
        pricing = GROQ_PRICING.get(
            self.model,
            {"input": 0.50, "output": 0.80}
        )
        in_cost = (self.input_tokens / 1_000_000) * pricing["input"]
        out_cost = (self.output_tokens / 1_000_000) * pricing["output"]
        return round(in_cost + out_cost, 6)


class TokenTracker:
    """Per-request and per-session token aggregation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._request_usage: Dict[str, list[TokenUsage]] = {}
        self._session_totals: Dict[str, TokenUsage] = {}

    def record(
        self,
        input_tokens: int,
        output_tokens: int,
        model: str,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Record token usage for a single LLM call."""
        usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
        )
        with self._lock:
            if request_id:
                if request_id not in self._request_usage:
                    self._request_usage[request_id] = []
                self._request_usage[request_id].append(usage)

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
            "input_tokens": total_in,
            "output_tokens": total_out,
            "total_tokens": total_in + total_out,
            "calls": len(usages),
            "estimated_cost_usd": round(cost, 6),
        }

    def get_session_summary(self, session_id: str) -> Optional[Dict]:
        """Get token summary for a session."""
        with self._lock:
            s = self._session_totals.get(session_id)
        if not s:
            return None
        return {
            "input_tokens": s.input_tokens,
            "output_tokens": s.output_tokens,
            "total_tokens": s.total_tokens,
            "estimated_cost_usd": s.estimated_cost_usd(),
        }


token_tracker = TokenTracker()
