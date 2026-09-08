import pytest
import os

os.environ["NEBIUS_API_KEY"] = "test_key_for_testing"

from agents.orchestrator import SupplyChainOrchestrator
from agents.base import AgentState


@pytest.fixture
def orchestrator():
    return SupplyChainOrchestrator()


@pytest.fixture
def sample_state():
    return AgentState(
        sku="SKU-001",
        risk_alerts=[],
        demand_forecast=None,
        purchase_requisition=None,
        negotiation_result=None,
        logistics_plan=None,
        final_recommendation=None,
        messages=[],
    )


def test_orchestrator_initialization(orchestrator):
    assert orchestrator is not None
    assert len(orchestrator.agents) == 5
    assert "inventory_monitor" in orchestrator.agents
    assert "demand_forecast" in orchestrator.agents
    assert "procurement" in orchestrator.agents
    assert "vendor_negotiation" in orchestrator.agents
    assert "logistics" in orchestrator.agents


def test_agent_names(orchestrator):
    assert orchestrator.agents["inventory_monitor"].name == "Inventory Monitor Agent"
    assert orchestrator.agents["demand_forecast"].name == "Demand Forecast Agent"
    assert orchestrator.agents["procurement"].name == "Procurement Agent"
    assert orchestrator.agents["vendor_negotiation"].name == "Vendor Negotiation Agent"
    assert orchestrator.agents["logistics"].name == "Logistics Agent"


def test_orchestrator_graph(orchestrator):
    assert orchestrator.graph is not None
