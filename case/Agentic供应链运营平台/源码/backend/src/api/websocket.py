from fastapi import WebSocket
from typing import Dict
from agents.orchestrator import orchestrator
from services.clickhouse_analytics import clickhouse_analytics
from services.mlflow_tracker import workflow_tracker


class WorkflowSession:
    def __init__(self, session_id: str, websocket: WebSocket):
        self.session_id = session_id
        self.websocket = websocket
        self.state = None

    async def send_event(self, event_type: str, data: dict):
        await self.websocket.send_json(
            {"type": event_type, "data": data, "session_id": self.session_id}
        )


sessions: Dict[str, WorkflowSession] = {}


async def run_workflow_streaming(session: WorkflowSession, sku: str):
    await session.send_event("workflow_started", {"sku": sku})

    status_messages = {
        "inventory_monitor": "Analyzing inventory levels and exposure bands.",
        "demand_forecast": "Forecasting demand using the latest sales signal.",
        "procurement": "Selecting vendor and quantity strategy.",
        "vendor_negotiation": "Running live negotiation strategy synthesis.",
        "logistics": "Optimizing distribution route and landed cost.",
    }

    result = None
    for agent_name, state in orchestrator.run_live(sku):
        await session.send_event(
            "agent_started",
            {"agent": agent_name, "status": status_messages.get(agent_name, "Running agent")},
        )
        agent_message = state["messages"][-1]["output"] if state["messages"] else "Completed"
        result = state
        await session.send_event(
            "agent_completed",
            {"agent": agent_name, "status": agent_message[:280], "state": state},
        )

    await session.send_event(
        "workflow_completed",
        {
            "sku": sku,
            "result": {
                "risk_alerts": result["risk_alerts"],
                "demand_forecast": result["demand_forecast"],
                "purchase_requisition": result["purchase_requisition"],
                "negotiation_result": result["negotiation_result"],
                "logistics_plan": result["logistics_plan"],
                "final_recommendation": result["final_recommendation"],
            },
        },
    )

    return result
