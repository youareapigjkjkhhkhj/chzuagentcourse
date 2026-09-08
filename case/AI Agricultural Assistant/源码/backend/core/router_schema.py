"""Pydantic schema for router structured output - eliminates regex/JSON parsing."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AgentScore(BaseModel):
    """Single agent with relevance score."""
    agent: str = Field(description="Agent name, e.g. CropAgent, SubsidyAgent")
    score: int = Field(ge=0, le=100, description="Relevance score 0-100")


class RouterOutput(BaseModel):
    """Structured router response - list of agents with scores."""
    agents: list[AgentScore] = Field(
        default_factory=list,
        description="List of agents with relevance scores, sorted by score descending",
    )
