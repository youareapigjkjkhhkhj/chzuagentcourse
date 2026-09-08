"""Tests for structured router output."""
import pytest
from backend.core.router_schema import RouterOutput, AgentScore


def test_router_output_parse():
    r = RouterOutput(agents=[
        AgentScore(agent="CropAgent", score=85),
        AgentScore(agent="SubsidyAgent", score=70),
    ])
    assert len(r.agents) == 2
    assert r.agents[0].agent == "CropAgent"
    assert r.agents[0].score == 85


def test_agent_score_bounds():
    a = AgentScore(agent="PestAgent", score=100)
    assert a.score == 100
