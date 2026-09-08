import json
from agents.base import BaseAgent, AgentState
from services import erp_gateway


SYSTEM_PROMPT = """You are the Procurement Agent. Your role is to determine optimal procurement quantities, timing, and vendor selection.
You have access to vendor constraints and can create purchase orders.
Your output should be a JSON object with:
- purchase_requisition: object with vendor_id, sku, quantity, estimated_unit_price, urgency
- vendor_ranking: array of vendors ranked by suitability
- order_timing: recommended order date
- reasoning: explanation of procurement decision
"""


class ProcurementAgent(BaseAgent):
    def __init__(self):
        super().__init__("Procurement Agent")

    def run(self, state: AgentState) -> AgentState:
        sku = state["sku"]
        risk_alerts = state.get("risk_alerts", [])
        demand_forecast = state.get("demand_forecast", {})

        vendors = erp_gateway.query_lead_times()
        vendor_constraints = {
            v["vendor_id"]: erp_gateway.query_vendor_constraints(v["vendor_id"])
            for v in vendors
        }

        market_benchmarks = erp_gateway.query_market_benchmarks()
        market_price = next((b for b in market_benchmarks if b["sku"] == sku), None)
        preferred_vendor_id = state.get("preferred_vendor_id")
        requested_quantity = state.get("requested_quantity")

        recommended_qty = 0
        for alert in risk_alerts:
            if alert.get("sku") == sku:
                recommended_qty = max(
                    recommended_qty, alert.get("recommended_quantity", 500)
                )

        if requested_quantity:
            recommended_qty = max(recommended_qty, requested_quantity)
        if not recommended_qty and demand_forecast:
            recommended_qty = demand_forecast.get("forecasted_quantity", 500)

        if not recommended_qty:
            recommended_qty = 500

        vendor_summary = [
            {"vendor_id": v["vendor_id"], "name": v["name"], "lead_time_days": v["lead_time_days"]}
            for v in vendors
        ]

        user_prompt = f"""Create a procurement recommendation for SKU {sku}.

Inputs:
- risk_alerts: {json.dumps(risk_alerts, indent=2)}
- demand_forecast: {json.dumps(demand_forecast, indent=2)}
- market_lowest_price: {market_price.get("lowest_price", "N/A") if market_price else "N/A"}
- market_avg_price: {market_price.get("avg_price", "N/A") if market_price else "N/A"}
- recommended_quantity: {recommended_qty}
- preferred_vendor: {preferred_vendor_id or "none"}
- vendor_options: {json.dumps(vendor_summary, indent=2)}

Return JSON with:
- purchase_requisition
- vendor_ranking
- order_timing
- reasoning
"""

        messages = self._create_messages(SYSTEM_PROMPT, user_prompt)
        response = self._call_llm(messages, json_mode=True)

        try:
            result = json.loads(response)
            purchase_requisition = result.get(
                "purchase_requisition",
                {
                    "vendor_id": preferred_vendor_id or (vendors[0]["vendor_id"] if vendors else 1),
                    "sku": sku,
                    "quantity": recommended_qty,
                    "estimated_unit_price": market_price.get("lowest_price", 100)
                    if market_price
                    else 100,
                    "urgency": "high",
                },
            )
        except json.JSONDecodeError:
            purchase_requisition = {
                "vendor_id": preferred_vendor_id or (vendors[0]["vendor_id"] if vendors else 1),
                "sku": sku,
                "quantity": recommended_qty,
                "estimated_unit_price": market_price.get("lowest_price", 100)
                if market_price
                else 100,
                "urgency": "high",
            }

        state["purchase_requisition"] = purchase_requisition
        state["messages"].append(
            {"agent": self.name, "output": str(purchase_requisition)}
        )
        return state
