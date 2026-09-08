"""Tests for memory manager - trim logic and session flow."""
import pytest
from backend.core.memory_manager import (
    get_chat_history,
    add_message_to_history,
    format_history_for_prompt,
    _trim_history,
    MAX_HISTORY_MESSAGES,
    MAX_HISTORY_CHARS,
)


def test_trim_history_empty():
    assert _trim_history([]) == []


def test_trim_history_under_limits():
    h = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    assert len(_trim_history(h)) == 2
    assert _trim_history(h)[0]["content"] == "hi"
    assert _trim_history(h)[1]["content"] == "hello"


def test_trim_history_message_limit():
    h = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
    out = _trim_history(h)
    assert len(out) <= MAX_HISTORY_MESSAGES
    assert out[-1]["content"] == "msg9"  # most recent kept


def test_trim_history_char_limit():
    long = "x" * 600
    h = [
        {"role": "user", "content": long},
        {"role": "assistant", "content": long},
        {"role": "user", "content": long},
    ]
    out = _trim_history(h)
    total_chars = sum(len(m.get("content", "")) for m in out)
    assert total_chars <= MAX_HISTORY_CHARS + 100  # allowance for header


def test_get_chat_history_empty_session():
    assert get_chat_history("") == []
    assert get_chat_history("nonexistent-sid-12345") == []


def test_add_and_get_chat_history():
    sid = "test-session-add-get"
    add_message_to_history(sid, "user", "What fertilizer?")
    add_message_to_history(sid, "assistant", "Use NPK for tomatoes.")
    hist = get_chat_history(sid)
    assert len(hist) == 2
    assert hist[0]["role"] == "user" and hist[0]["content"] == "What fertilizer?"
    assert hist[1]["role"] == "assistant" and hist[1]["content"] == "Use NPK for tomatoes."
    # Clean up - memory is global, could affect other tests
    from backend.core import memory_manager
    if sid in memory_manager._CHAT_MEMORY:
        del memory_manager._CHAT_MEMORY[sid]


def test_format_history_for_prompt():
    h = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    s = format_history_for_prompt(h)
    assert "USER:" in s and "ASSISTANT:" in s
    assert "hi" in s and "hello" in s


def test_format_history_empty():
    assert "No previous conversation" in format_history_for_prompt([])
