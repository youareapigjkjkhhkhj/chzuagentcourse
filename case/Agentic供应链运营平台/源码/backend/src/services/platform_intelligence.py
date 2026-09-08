from __future__ import annotations

from collections import defaultdict
from statistics import mean

from db import erp_simulator


def _safe(default, loader):
    try:
        return loader()
    except Exception:
        return default


def _fallback_products() -> list[dict]:
    return [
        {
            "sku": "SKU-001",
            "name": "Industrial Bearing A",
            "category": "Mechanical",
            "unit_cost": 45.0,
            "reorder_point": 100,
            "reorder_quantity": 500,
        },
        {
            "sku": "SKU-002",
            "name": "Hydraulic Pump X",
            "category": "Hydraulics",
            "unit_cost": 320.0,
            "reorder_point": 50,
            "reorder_quantity": 200,
        },
        {
            "sku": "SKU-003",
            "name": "Steel Plate 10mm",
            "category": "Raw Materials",
            "unit_cost": 120.0,
            "reorder_point": 200,
            "reorder_quantity": 1000,
        },
        {
            "sku": "SKU-004",
            "name": "Circuit Board Z",
            "category": "Electronics",
            "unit_cost": 85.0,
            "reorder_point": 75,
            "reorder_quantity": 300,
        },
        {
            "sku": "SKU-005",
            "name": "Motor Assembly M",
            "category": "Motors",
            "unit_cost": 560.0,
            "reorder_point": 30,
            "reorder_quantity": 100,
        },
    ]


def _fallback_inventory() -> list[dict]:
    return [
        {
            "sku": "SKU-001",
            "product_name": "Industrial Bearing A",
            "warehouse_name": "Warehouse A - Chicago",
            "quantity": 150,
            "last_updated": "2026-04-04T09:00:00Z",
        },
        {
            "sku": "SKU-001",
            "product_name": "Industrial Bearing A",
            "warehouse_name": "Warehouse B - Dallas",
            "quantity": 80,
            "last_updated": "2026-04-04T09:00:00Z",
        },
        {
            "sku": "SKU-002",
            "product_name": "Hydraulic Pump X",
            "warehouse_name": "Warehouse A - Chicago",
            "quantity": 45,
            "last_updated": "2026-04-04T09:00:00Z",
        },
        {
            "sku": "SKU-002",
            "product_name": "Hydraulic Pump X",
            "warehouse_name": "Warehouse B - Dallas",
            "quantity": 60,
            "last_updated": "2026-04-04T09:00:00Z",
        },
        {
            "sku": "SKU-003",
            "product_name": "Steel Plate 10mm",
            "warehouse_name": "Warehouse A - Chicago",
            "quantity": 500,
            "last_updated": "2026-04-04T09:00:00Z",
        },
        {
            "sku": "SKU-003",
            "product_name": "Steel Plate 10mm",
            "warehouse_name": "Warehouse C - Phoenix",
            "quantity": 300,
            "last_updated": "2026-04-04T09:00:00Z",
        },
        {
            "sku": "SKU-004",
            "product_name": "Circuit Board Z",
            "warehouse_name": "Warehouse B - Dallas",
            "quantity": 90,
            "last_updated": "2026-04-04T09:00:00Z",
        },
        {
            "sku": "SKU-005",
            "product_name": "Motor Assembly M",
            "warehouse_name": "Warehouse A - Chicago",
            "quantity": 25,
            "last_updated": "2026-04-04T09:00:00Z",
        },
    ]


def _fallback_vendors() -> list[dict]:
    return [
        {
            "vendor_id": 1,
            "name": "Acme Industrial",
            "lead_time_days": 7,
            "min_order_value": 500.0,
        },
        {
            "vendor_id": 2,
            "name": "Global Parts Co",
            "lead_time_days": 14,
            "min_order_value": 250.0,
        },
        {
            "vendor_id": 3,
            "name": "Prime Materials Ltd",
            "lead_time_days": 10,
            "min_order_value": 1000.0,
        },
    ]


def _fallback_kpis() -> dict:
    return {
        "total_skus": 5,
        "active_risks": 2,
        "pending_pos": 4,
        "pending_po_value": 86400.0,
    }


def _load_products() -> list[dict]:
    return _safe(_fallback_products(), erp_simulator.query_all_products)


def _load_inventory() -> list[dict]:
    return _safe(_fallback_inventory(), erp_simulator.query_inventory_levels)


def _load_vendors() -> list[dict]:
    return _safe(_fallback_vendors(), erp_simulator.query_lead_times)


def get_dashboard_kpis() -> dict:
    return _safe(_fallback_kpis(), erp_simulator.query_dashboard_kpis)


def get_inventory(sku: str | None = None) -> list[dict]:
    if sku is None:
        return _load_inventory()
    return _safe(
        [item for item in _fallback_inventory() if item["sku"] == sku],
        lambda: erp_simulator.query_inventory_levels(sku),
    )


def get_risk_alerts() -> list[dict]:
    fallback = [
        {
            "sku": "SKU-002",
            "name": "Hydraulic Pump X",
            "reorder_point": 50,
            "reorder_quantity": 200,
            "total_quantity": 105,
            "risk_status": "low",
        },
        {
            "sku": "SKU-005",
            "name": "Motor Assembly M",
            "reorder_point": 30,
            "reorder_quantity": 100,
            "total_quantity": 25,
            "risk_status": "critical",
        },
    ]
    return _safe(fallback, erp_simulator.query_risk_alerts)


def get_products() -> list[dict]:
    return _load_products()


def get_vendors() -> list[dict]:
    return _load_vendors()


def get_control_tower_snapshot() -> dict:
    products = _load_products()
    inventory = _load_inventory()
    vendors = _load_vendors()
    kpis = get_dashboard_kpis()
    risks = get_risk_alerts()

    quantity_by_sku = defaultdict(int)
    warehouse_pressure = defaultdict(int)
    for item in inventory:
        quantity_by_sku[item["sku"]] += int(item["quantity"])
        warehouse_pressure[item["warehouse_name"]] += int(item["quantity"])

    replenishment_candidates = []
    for product in products:
        available = quantity_by_sku.get(product["sku"], 0)
        gap = max(product["reorder_point"] - available, 0)
        health = max(0, min(100, round((available / max(product["reorder_point"], 1)) * 100)))
        replenishment_candidates.append(
            {
                "sku": product["sku"],
                "name": product["name"],
                "category": product["category"],
                "available_units": available,
                "reorder_point": product["reorder_point"],
                "recommended_buy": max(gap, product["reorder_quantity"] if gap else 0),
                "inventory_health": health,
            }
        )

    replenishment_candidates.sort(key=lambda item: item["inventory_health"])

    avg_lead_time = round(mean(vendor["lead_time_days"] for vendor in vendors), 1) if vendors else 0
    autonomy_score = max(55, 91 - len(risks) * 8)
    resilience_score = max(48, 88 - len([r for r in risks if r["risk_status"] == "critical"]) * 14)

    warehouse_network = [
        {
            "warehouse": warehouse,
            "utilization_band": "high" if qty > 450 else "medium" if qty > 180 else "low",
            "units": qty,
        }
        for warehouse, qty in warehouse_pressure.items()
    ]
    warehouse_network.sort(key=lambda item: item["units"], reverse=True)

    return {
        "headline": {
            "platform_name": "Atlas AI Control Tower",
            "autonomy_score": autonomy_score,
            "resilience_score": resilience_score,
            "network_health": "stable" if resilience_score >= 70 else "degraded",
            "avg_vendor_lead_time_days": avg_lead_time,
        },
        "kpis": kpis,
        "priority_recommendations": [
            {
                "title": "Rebalance Motor Assembly coverage",
                "impact": "Avoid production interruption in the Chicago node within 72 hours.",
                "action": "Trigger expedited replenishment and dual-source approval.",
                "confidence": 0.92,
            },
            {
                "title": "Shift Hydraulic Pump demand to Dallas",
                "impact": "Create 11 days of additional buffer without new procurement.",
                "action": "Reassign open service orders to lower-risk warehouse stock.",
                "confidence": 0.87,
            },
            {
                "title": "Pre-negotiate steel capacity option",
                "impact": "Protect margin under a commodity spike scenario.",
                "action": "Open option contract with Prime Materials Ltd for Q2 surge buffer.",
                "confidence": 0.79,
            },
        ],
        "replenishment_candidates": replenishment_candidates[:5],
        "warehouse_network": warehouse_network,
        "risk_digest": risks,
    }


def get_scenario_lab() -> dict:
    scenarios = [
        {
            "id": "port-closure-west",
            "name": "West Coast Port Closure",
            "severity": "high",
            "probability": 0.31,
            "inventory_impact_pct": -18,
            "margin_impact_pct": -6.4,
            "recommended_response": "Shift inbound routing to Dallas and split orders across two vendors.",
        },
        {
            "id": "supplier-insolvency",
            "name": "Tier-1 Supplier Insolvency",
            "severity": "critical",
            "probability": 0.16,
            "inventory_impact_pct": -27,
            "margin_impact_pct": -8.9,
            "recommended_response": "Launch supplier substitution workflow and require CFO approval above $250k.",
        },
        {
            "id": "demand-spike-industrial",
            "name": "Industrial Demand Spike",
            "severity": "medium",
            "probability": 0.44,
            "inventory_impact_pct": -12,
            "margin_impact_pct": 3.1,
            "recommended_response": "Increase reorder band for fast-moving SKUs and allocate premium freight budget.",
        },
    ]

    return {
        "simulation_window": "14 day forward simulation",
        "recommended_playbook": "Contain critical shortages first, then optimize working capital.",
        "scenarios": scenarios,
    }


def get_governance_hub() -> dict:
    return {
        "policy_posture": "human-supervised autonomy",
        "approval_queues": [
            {
                "name": "Spend approvals",
                "pending": 3,
                "sla": "< 4h",
                "threshold": "$250k or non-preferred vendor",
            },
            {
                "name": "Supplier exceptions",
                "pending": 2,
                "sla": "< 8h",
                "threshold": "ESG or sanctions deviation",
            },
            {
                "name": "Logistics escalations",
                "pending": 1,
                "sla": "< 2h",
                "threshold": "Premium freight above 15% budget variance",
            },
        ],
        "guardrails": [
            "Block autonomous purchase order creation for unvetted vendors.",
            "Require human approval when forecast confidence drops below 0.72.",
            "Log all negotiation deltas above 4% from benchmark price.",
        ],
        "agent_registry": [
            {
                "agent": "Inventory Monitor",
                "status": "healthy",
                "last_decision": "SKU-005 shortage escalation",
                "reliability": 0.96,
            },
            {
                "agent": "Demand Forecast",
                "status": "healthy",
                "last_decision": "Hydraulic pump demand uplift +9.4%",
                "reliability": 0.9,
            },
            {
                "agent": "Procurement",
                "status": "watch",
                "last_decision": "Split-sourcing recommendation pending approval",
                "reliability": 0.83,
            },
            {
                "agent": "Vendor Negotiation",
                "status": "healthy",
                "last_decision": "Benchmark-aligned 5.2% concession capture",
                "reliability": 0.88,
            },
            {
                "agent": "Logistics",
                "status": "healthy",
                "last_decision": "Dallas reroute to protect service levels",
                "reliability": 0.91,
            },
        ],
    }
