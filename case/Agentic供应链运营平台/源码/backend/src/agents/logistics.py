import json
from agents.base import BaseAgent, AgentState
from services import erp_gateway


SYSTEM_PROMPT = """You are the Logistics Agent. Your role is to evaluate logistics options and create optimal shipping plans.
You have access to warehouse locations and vendor shipping options.
Your output should be a JSON object with:
- shipping_plan: object with route, estimated_delivery_date, shipping_cost, carrier_recommendation
- warehouse_assignments: array of which warehouses will receive inventory
- total_logistics_cost: sum of all shipping costs
- delivery_timeline: estimated days to full delivery
"""


class LogisticsAgent(BaseAgent):
    def __init__(self):
        super().__init__("Logistics Agent")

    def run(self, state: AgentState) -> AgentState:
        purchase_requisition = state.get("purchase_requisition", {})
        negotiation_result = state.get("negotiation_result", {})
        vendor_id = purchase_requisition.get("vendor_id", 1)

        warehouse_locations = erp_gateway.query_warehouse_locations()
        vendor_shipping = erp_gateway.query_vendor_shipping(vendor_id)

        user_prompt = f"""Create a logistics plan.

Inputs:
- vendor_id: {vendor_id}
- quantity: {purchase_requisition.get("quantity", 500)}
- negotiated_unit_price: {negotiation_result.get("negotiated_price", purchase_requisition.get("estimated_unit_price", 100))}
- warehouses: {json.dumps(warehouse_locations, indent=2)}
- vendor_shipping: {json.dumps(vendor_shipping, indent=2)}

Return compact JSON with:
- shipping_plan
- warehouse_assignments
- total_logistics_cost
- delivery_timeline
"""

        messages = self._create_messages(SYSTEM_PROMPT, user_prompt)
        response = self._call_llm(messages, json_mode=True)

        try:
            result = json.loads(response)
        except json.JSONDecodeError:
            result = {
                "shipping_plan": {
                    "route": "Direct shipment to primary warehouse",
                    "estimated_delivery_date": "2024-02-15",
                    "shipping_cost": 500.00,
                    "carrier_recommendation": "Standard Freight",
                },
                "warehouse_assignments": [
                    {"warehouse_id": 1, "quantity": 300},
                    {"warehouse_id": 2, "quantity": 200},
                ],
                "total_logistics_cost": 500.00,
                "delivery_timeline": 7,
            }

        state["logistics_plan"] = result
        state["messages"].append({"agent": self.name, "output": str(result)})
        return state
