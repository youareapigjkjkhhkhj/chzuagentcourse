import pytest
from agents.base import BaseAgent, AgentState


class MockAgent(BaseAgent):
    def run(self, state: AgentState) -> AgentState:
        state["messages"].append({"agent": self.name, "output": "mock output"})
        return state


def test_base_agent_initialization():
    agent = MockAgent("Test Agent")
    assert agent.name == "Test Agent"
    assert agent.llm is not None


def test_create_messages():
    agent = MockAgent("Test Agent")
    messages = agent._create_messages("You are a test agent.", "Hello, agent!")
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "You are a test agent."
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Hello, agent!"


def test_agent_run_returns_state():
    agent = MockAgent("Test Agent")
    state: AgentState = {
        "sku": "SKU-001",
        "risk_alerts": [],
        "demand_forecast": None,
        "purchase_requisition": None,
        "negotiation_result": None,
        "logistics_plan": None,
        "final_recommendation": None,
        "messages": [],
    }
    result = agent.run(state)
    assert len(result["messages"]) == 1
    assert result["messages"][0]["agent"] == "Test Agent"
