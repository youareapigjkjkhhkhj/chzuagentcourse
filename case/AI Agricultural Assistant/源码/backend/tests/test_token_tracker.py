"""Tests for token tracker."""
import pytest
from backend.core.token_tracker import TokenUsage, token_tracker


def test_token_usage_cost():
    u = TokenUsage(input_tokens=1000, output_tokens=500, model="llama-3.3-70b-versatile")
    assert u.total_tokens == 1500
    cost = u.estimated_cost_usd()
    assert cost > 0
    assert cost < 0.01


def test_token_tracker_record():
    tid = "test-req-123"
    token_tracker.record(100, 50, "llama-3.3-70b-versatile", request_id=tid)
    summary = token_tracker.get_request_summary(tid)
    assert summary is not None
    assert summary["input_tokens"] == 100
    assert summary["output_tokens"] == 50
    assert summary["total_tokens"] == 150
