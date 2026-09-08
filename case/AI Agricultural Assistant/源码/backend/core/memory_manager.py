"""
Chat memory manager with Redis (persistent) or in-memory fallback.
Redis enables: multi-worker scaling, persistence across restarts.
"""
from __future__ import annotations

import json
import collections
from typing import List, Dict, Any, Optional

from backend.core.config import settings

MAX_HISTORY_LENGTH = 10
MAX_HISTORY_MESSAGES = 5
MAX_HISTORY_CHARS = 1500

_KEY_PREFIX = "agrigpt:session:"
_KEY_TTL_SECONDS = 86400 * 7  # 7 days

# In-memory fallback when Redis unavailable
_CHAT_MEMORY: Dict[str, collections.deque] = {}

_redis_client: Optional[Any] = None


def _get_redis():
    """Lazy Redis connection; returns None if not configured or connection fails."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    url = str(settings.REDIS_URL or "").strip()
    if not url or url.lower() in ("", "none", "false"):
        return None
    try:
        import redis
        client = redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2,
        )
        client.ping()
        _redis_client = client
        return _redis_client
    except Exception:
        _redis_client = None
        return None


def _trim_history(history: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """Trim to last N messages and ~N chars for token efficiency."""
    if not history:
        return []
    trimmed = history[-MAX_HISTORY_MESSAGES:]
    total = 0
    out = []
    for msg in reversed(trimmed):
        content = str(msg.get("content", "") or "")
        total += len(content) + 20
        if total > MAX_HISTORY_CHARS and out:
            break
        out.insert(0, msg)
    return out


def get_chat_history(session_id: str) -> List[Dict[str, str]]:
    """
    Retrieve chat history for a session, trimmed for prompt efficiency.
    Uses Redis if configured, else in-memory.
    """
    if not session_id:
        return []

    r = _get_redis()
    if r:
        try:
            key = f"{_KEY_PREFIX}{session_id}"
            raw = r.lrange(key, -MAX_HISTORY_LENGTH, -1)
            if not raw:
                return []
            history = []
            for m in raw:
                if not m:
                    continue
                try:
                    history.append(json.loads(m))
                except (json.JSONDecodeError, TypeError):
                    continue
            return _trim_history(history)
        except Exception:
            global _redis_client
            _redis_client = None
            pass

    # In-memory fallback
    if session_id not in _CHAT_MEMORY:
        return []
    raw = list(_CHAT_MEMORY[session_id])
    return _trim_history(raw)


def add_message_to_history(session_id: str, role: str, content: str) -> None:
    """
    Add a message to the session's history.
    Uses Redis if configured, else in-memory.
    """
    if not session_id:
        return

    msg = {"role": role, "content": str(content or "")}

    r = _get_redis()
    if r:
        try:
            key = f"{_KEY_PREFIX}{session_id}"
            r.rpush(key, json.dumps(msg))
            r.ltrim(key, -MAX_HISTORY_LENGTH, -1)
            r.expire(key, _KEY_TTL_SECONDS)
            return
        except Exception:
            global _redis_client
            _redis_client = None
            pass

    # In-memory fallback
    if session_id not in _CHAT_MEMORY:
        _CHAT_MEMORY[session_id] = collections.deque(maxlen=MAX_HISTORY_LENGTH)
    _CHAT_MEMORY[session_id].append(msg)


def format_history_for_prompt(history: List[Dict[str, str]]) -> str:
    """Convert list of messages into a string for LLM context."""
    if not history:
        return "No previous conversation."
    formatted = []
    for msg in history:
        role = str(msg.get("role", "user")).upper()
        content = str(msg.get("content", "") or "")
        formatted.append(f"{role}: {content}")
    return "\n".join(formatted)


def redis_available() -> bool:
    """True if Redis is configured and reachable."""
    return _get_redis() is not None
