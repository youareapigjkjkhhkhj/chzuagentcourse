import json
from agents.base import BaseAgent, AgentState
from services import erp_gateway


SYSTEM_PROMPT = """You are the Demand Forecast Agent. Your role is to analyze historical sales data and provide accurate demand forecasts.
You have access to ERP sales history data through the query_erp_sales_history tool.
Your output should be a JSON object with:
- forecasted_quantity: number of units expected in the forecast period
- confidence_interval: object with lower and upper bounds
- growth_rate: percentage growth/decline compared to previous period
- risk_flags: array of potential shortage risks
- reasoning: explanation of the forecast
"""


class DemandForecastAgent(BaseAgent):
    def __init__(self):
        super().__init__("Demand Forecast Agent")

    def run(self, state: AgentState) -> AgentState:
        sku = state["sku"]

        sales_data = erp_gateway.query_erp_sales_history(sku, days=90)

        avg_daily_sales = round(sum(item["quantity"] for item in sales_data) / max(len(sales_data), 1), 2)
        recent_window = sales_data[-7:]
        recent_avg = round(sum(item["quantity"] for item in recent_window) / max(len(recent_window), 1), 2)

        user_prompt = f"""Analyze demand for SKU {sku}.

Summary:
- Average daily sales over {len(sales_data)} days: {avg_daily_sales}
- Average daily sales over last 7 days: {recent_avg}
- Recent samples: {json.dumps(recent_window, indent=2)}

Return JSON with:
- forecasted_quantity for next 30 days
- confidence_interval
- growth_rate
- risk_flags
- reasoning
"""

        messages = self._create_messages(SYSTEM_PROMPT, user_prompt)
        response = self._call_llm(messages, json_mode=True)

        try:
            forecast = json.loads(response)
        except json.JSONDecodeError:
            forecast = {"forecasted_quantity": 0, "error": "Failed to parse forecast"}

        state["demand_forecast"] = forecast
        state["messages"].append({"agent": self.name, "output": str(forecast)})
        return state
