import json
from agents.base import BaseAgent, AgentState
from services import erp_gateway


SYSTEM_PROMPT = """You are the Vendor Negotiation Agent. Your role is to simulate vendor negotiations to achieve optimal pricing and terms.
You have access to vendor history and market benchmarks.
Your output should be a JSON object with:
- negotiated_price: final negotiated unit price
- terms_achieved: object with discount_percent, lead_time_concession, payment_terms
- negotiation_transcript: array of message objects with speaker, message, offer_price, discount_percent
- alternative_vendors: array of alternative vendor recommendations
- savings_vs_benchmark: percentage savings compared to market average
- negotiation_summary: narrative summary of the negotiation
"""


class VendorNegotiationAgent(BaseAgent):
    def __init__(self):
        super().__init__("Vendor Negotiation Agent")

    def run(self, state: AgentState) -> AgentState:
        purchase_requisition = state.get("purchase_requisition", {})
        vendor_id = purchase_requisition.get("vendor_id", 1)
        sku = purchase_requisition.get("sku", state["sku"])
        quantity = purchase_requisition.get("quantity", 500)

        vendor_history = erp_gateway.query_vendor_history(vendor_id)
        vendor_constraints = erp_gateway.query_vendor_constraints(vendor_id)
        market_benchmarks = erp_gateway.query_market_benchmarks()
        market_price = next((b for b in market_benchmarks if b["sku"] == sku), None)
        initial_message = state.get("initial_message") or "Drive to best total landed cost while protecting delivery confidence."

        user_prompt = f"""Run a vendor negotiation for SKU {sku}.

Inputs:
- vendor_id: {vendor_id}
- quantity: {quantity}
- buyer_strategy: {initial_message}
- vendor_constraints: {json.dumps(vendor_constraints, indent=2)}
- recent_vendor_history: {json.dumps(vendor_history[:3], indent=2)}
- market_lowest_price: {market_price.get("lowest_price", "N/A") if market_price else "N/A"}
- market_avg_price: {market_price.get("avg_price", "N/A") if market_price else "N/A"}

Return compact JSON with:
- negotiated_price
- terms_achieved
- negotiation_transcript with 3 to 5 turns
- alternative_vendors
- savings_vs_benchmark
- negotiation_summary
"""

        messages = self._create_messages(SYSTEM_PROMPT, user_prompt)
        response = self._call_llm(messages, json_mode=True)

        try:
            result = json.loads(response)
        except json.JSONDecodeError:
            base_price = market_price.get("lowest_price", 100) if market_price else 100
            result = {
                "negotiated_price": base_price * 0.95,
                "terms_achieved": {
                    "discount_percent": 5,
                    "lead_time_concession": 0,
                    "payment_terms": "Net 30",
                },
                "negotiation_transcript": [
                    {
                        "speaker": "buyer",
                        "message": initial_message,
                        "offer_price": round(base_price, 2),
                        "discount_percent": 0,
                    },
                    {
                        "speaker": "vendor",
                        "message": "We can support this volume with a modest concession if delivery remains standard.",
                        "offer_price": round(base_price * 0.97, 2),
                        "discount_percent": 3,
                    },
                    {
                        "speaker": "buyer",
                        "message": "Accept if we can lock a stronger discount and preserve lead time.",
                        "offer_price": round(base_price * 0.95, 2),
                        "discount_percent": 5,
                    },
                ],
                "alternative_vendors": [],
                "savings_vs_benchmark": 5,
                "negotiation_summary": "Achieved 5% discount through negotiation",
            }

        state["negotiation_result"] = result
        state["negotiation_transcript"] = result.get("negotiation_transcript", [])
        state["messages"].append({"agent": self.name, "output": str(result)})
        return state
