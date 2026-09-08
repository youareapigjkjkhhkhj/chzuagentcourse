from typing import Literal
from langgraph.graph import StateGraph, END
from agents.base import AgentState, BaseAgent
from agents.demand_forecast import DemandForecastAgent
from agents.inventory_monitor import InventoryMonitorAgent
from agents.procurement import ProcurementAgent
from agents.vendor_negotiation import VendorNegotiationAgent
from agents.logistics import LogisticsAgent
from services.clickhouse_analytics import clickhouse_analytics
from services.mlflow_tracker import workflow_tracker


class SupplyChainOrchestrator:
    def __init__(self):
        self.graph = self._build_graph()
        self.execution_order = [
            "inventory_monitor",
            "demand_forecast",
            "procurement",
            "vendor_negotiation",
            "logistics",
        ]
        self.agents = {
            "inventory_monitor": InventoryMonitorAgent(),
            "demand_forecast": DemandForecastAgent(),
            "procurement": ProcurementAgent(),
            "vendor_negotiation": VendorNegotiationAgent(),
            "logistics": LogisticsAgent(),
        }

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(AgentState)

        workflow.add_node("inventory_monitor", self._run_inventory_monitor)
        workflow.add_node("demand_forecast", self._run_demand_forecast)
        workflow.add_node("procurement", self._run_procurement)
        workflow.add_node("vendor_negotiation", self._run_vendor_negotiation)
        workflow.add_node("logistics", self._run_logistics)

        workflow.set_entry_point("inventory_monitor")

        workflow.add_edge("inventory_monitor", "demand_forecast")
        workflow.add_edge("demand_forecast", "procurement")
        workflow.add_edge("procurement", "vendor_negotiation")
        workflow.add_edge("vendor_negotiation", "logistics")
        workflow.add_edge("logistics", END)

        return workflow.compile()

    def _run_inventory_monitor(self, state: AgentState) -> AgentState:
        return self.agents["inventory_monitor"].run(state)

    def _run_demand_forecast(self, state: AgentState) -> AgentState:
        return self.agents["demand_forecast"].run(state)

    def _run_procurement(self, state: AgentState) -> AgentState:
        return self.agents["procurement"].run(state)

    def _run_vendor_negotiation(self, state: AgentState) -> AgentState:
        return self.agents["vendor_negotiation"].run(state)

    def _run_logistics(self, state: AgentState) -> AgentState:
        result = self.agents["logistics"].run(state)
        purchase_requisition = result.get("purchase_requisition", {})
        negotiation_result = result.get("negotiation_result", {})
        logistics_plan = result.get("logistics_plan", {})

        result["final_recommendation"] = {
            "action": "create_purchase_order",
            "vendor_id": purchase_requisition.get("vendor_id"),
            "sku": purchase_requisition.get("sku"),
            "quantity": purchase_requisition.get("quantity"),
            "unit_price": negotiation_result.get("negotiated_price"),
            "estimated_delivery": logistics_plan.get("shipping_plan", {}).get(
                "estimated_delivery_date"
            ),
            "total_cost": purchase_requisition.get("quantity", 0)
            * negotiation_result.get("negotiated_price", 0),
            "logistics_cost": logistics_plan.get("total_logistics_cost", 0),
        }
        return result

    def _initial_state(
        self,
        sku: str,
        preferred_vendor_id: int | None = None,
        requested_quantity: int | None = None,
        initial_message: str | None = None,
    ) -> AgentState:
        return {
            "sku": sku,
            "risk_alerts": [],
            "demand_forecast": None,
            "purchase_requisition": None,
            "negotiation_result": None,
            "negotiation_transcript": None,
            "logistics_plan": None,
            "final_recommendation": None,
            "preferred_vendor_id": preferred_vendor_id,
            "requested_quantity": requested_quantity,
            "initial_message": initial_message,
            "messages": [],
        }

    def run(
        self,
        sku: str,
        preferred_vendor_id: int | None = None,
        requested_quantity: int | None = None,
        initial_message: str | None = None,
    ) -> AgentState:
        initial_state = self._initial_state(
            sku,
            preferred_vendor_id=preferred_vendor_id,
            requested_quantity=requested_quantity,
            initial_message=initial_message,
        )
        result = self.graph.invoke(initial_state)
        workflow_tracker.log_workflow_run(result)
        clickhouse_analytics.log_workflow_run(result)
        return result

    def run_live(
        self,
        sku: str,
        preferred_vendor_id: int | None = None,
        requested_quantity: int | None = None,
        initial_message: str | None = None,
    ):
        initial_state = self._initial_state(
            sku,
            preferred_vendor_id=preferred_vendor_id,
            requested_quantity=requested_quantity,
            initial_message=initial_message,
        )
        final_state = None

        for step in self.graph.stream(initial_state):
            agent_name, state = next(iter(step.items()))
            final_state = state
            yield agent_name, state

        if final_state is not None:
            workflow_tracker.log_workflow_run(final_state)
            clickhouse_analytics.log_workflow_run(final_state)


orchestrator = SupplyChainOrchestrator()
