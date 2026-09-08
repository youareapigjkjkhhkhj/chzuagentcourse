from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from agents.orchestrator import orchestrator
from services.platform_intelligence import (
    get_control_tower_snapshot,
    get_dashboard_kpis as get_dashboard_kpis_data,
    get_governance_hub,
    get_inventory as get_inventory_data,
    get_products as get_products_data,
    get_risk_alerts as get_risk_alerts_data,
    get_scenario_lab,
    get_vendors as get_vendors_data,
)

router = APIRouter(prefix="/api")


class AnalyzeRequest(BaseModel):
    sku: str


class NegotiateRequest(BaseModel):
    vendor_id: int
    sku: str
    quantity: int
    initial_message: Optional[str] = None


@router.get("/dashboard/kpis")
async def get_dashboard_kpis():
    return get_dashboard_kpis_data()


@router.get("/inventory")
async def list_inventory():
    return get_inventory_data()


@router.get("/inventory/{sku}")
async def get_inventory(sku: str):
    return get_inventory_data(sku)


@router.get("/risks")
async def get_risks():
    return get_risk_alerts_data()


@router.post("/analyze/{sku}")
async def analyze_sku(sku: str):
    result = orchestrator.run(sku)
    return {
        "sku": sku,
        "risk_alerts": result["risk_alerts"],
        "demand_forecast": result["demand_forecast"],
        "purchase_requisition": result["purchase_requisition"],
        "negotiation_result": result["negotiation_result"],
        "negotiation_transcript": result["negotiation_transcript"],
        "logistics_plan": result["logistics_plan"],
        "final_recommendation": result["final_recommendation"],
    }


@router.get("/negotiations")
async def get_negotiations():
    return []


@router.post("/negotiate")
async def negotiate(request: NegotiateRequest):
    result = orchestrator.run(
        request.sku,
        preferred_vendor_id=request.vendor_id,
        requested_quantity=request.quantity,
        initial_message=request.initial_message,
    )
    return {
        "negotiation_id": "neg_" + str(hash(request.sku))[:8],
        "vendor_id": request.vendor_id,
        "sku": request.sku,
        "quantity": request.quantity,
        "purchase_requisition": result["purchase_requisition"],
        "result": result["negotiation_result"],
        "transcript": result["negotiation_transcript"],
        "final_recommendation": result["final_recommendation"],
    }


@router.get("/workflow/state/{session_id}")
async def get_workflow_state(session_id: str):
    return {"session_id": session_id, "status": "completed"}


@router.get("/products")
async def get_products():
    return get_products_data()


@router.get("/vendors")
async def get_vendors():
    return get_vendors_data()


@router.get("/platform/control-tower")
async def get_platform_control_tower():
    return get_control_tower_snapshot()


@router.get("/platform/scenarios")
async def get_platform_scenarios():
    return get_scenario_lab()


@router.get("/platform/governance")
async def get_platform_governance():
    return get_governance_hub()
