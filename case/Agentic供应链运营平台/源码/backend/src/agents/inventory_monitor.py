import json
from agents.base import BaseAgent, AgentState
from services import erp_gateway


SYSTEM_PROMPT = """You are the Inventory Monitor Agent. Your role is to continuously monitor inventory levels and detect risks.
You have access to current inventory levels and lead times through the query_inventory_levels and query_lead_times tools.
Your output should be a JSON object with:
- risk_alerts: array of risk objects with sku, severity (critical/low/excess), days_of_supply, recommendation
- overall_status: overall inventory health status
- reorder_urgency: how urgently reordering is needed
"""


class InventoryMonitorAgent(BaseAgent):
    def __init__(self):
        super().__init__("Inventory Monitor Agent")

    def run(self, state: AgentState) -> AgentState:
        sku = state["sku"]

        inventory_data = erp_gateway.query_inventory_levels(sku)
        products = erp_gateway.query_all_products()
        product = next((p for p in products if p["sku"] == sku), None)

        if not product:
            state["risk_alerts"] = []
            return state

        total_quantity = sum(inv["quantity"] for inv in inventory_data)
        reorder_point = product["reorder_point"]
        reorder_qty = product["reorder_quantity"]

        user_prompt = f"""Monitor inventory for SKU {sku}.

Product:
- name: {product["name"]}
- reorder_point: {reorder_point}
- reorder_quantity: {reorder_qty}

Inventory by warehouse:
{json.dumps(inventory_data, indent=2)}

Total quantity: {total_quantity}

Return compact JSON with:
- risk_alerts
- overall_status
- reorder_urgency
"""

        messages = self._create_messages(SYSTEM_PROMPT, user_prompt)
        response = self._call_llm(messages, json_mode=True)

        try:
            result = json.loads(response)
            risk_alerts = result.get("risk_alerts", [])
        except json.JSONDecodeError:
            days_of_supply = 30 if total_quantity > 0 else 0
            severity = (
                "critical"
                if total_quantity < reorder_point
                else "low"
                if total_quantity < reorder_point * 1.5
                else "normal"
            )
            risk_alerts = [
                {
                    "sku": sku,
                    "severity": severity,
                    "days_of_supply": days_of_supply,
                    "recommendation": f"Reorder {product['reorder_quantity']} units"
                    if severity != "normal"
                    else "Stock levels adequate",
                }
            ]

        state["risk_alerts"] = risk_alerts
        state["messages"].append({"agent": self.name, "output": str(risk_alerts)})
        return state
