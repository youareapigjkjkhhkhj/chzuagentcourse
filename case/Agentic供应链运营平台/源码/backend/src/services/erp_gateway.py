from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

from db import erp_simulator


def _safe(loader: Callable[[], Any], fallback: Any) -> Any:
    try:
        return loader()
    except Exception:
        return fallback


FALLBACK_PRODUCTS = [
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

FALLBACK_VENDORS = [
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

FALLBACK_VENDOR_PRODUCTS = {
    1: {
        "SKU-001": {"unit_price": 42.0, "discount_threshold": 200, "discount_percent": 5.0},
        "SKU-002": {"unit_price": 295.0, "discount_threshold": 100, "discount_percent": 7.5},
        "SKU-003": {"unit_price": 110.0, "discount_threshold": 500, "discount_percent": 10.0},
    },
    2: {
        "SKU-001": {"unit_price": 43.5, "discount_threshold": 150, "discount_percent": 3.0},
        "SKU-004": {"unit_price": 78.0, "discount_threshold": 100, "discount_percent": 5.0},
        "SKU-005": {"unit_price": 520.0, "discount_threshold": 50, "discount_percent": 8.0},
    },
    3: {
        "SKU-003": {"unit_price": 115.0, "discount_threshold": 400, "discount_percent": 8.0},
        "SKU-005": {"unit_price": 540.0, "discount_threshold": 75, "discount_percent": 6.0},
    },
}

FALLBACK_INVENTORY = [
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

FALLBACK_WAREHOUSES = [
    {"warehouse_id": 1, "name": "Warehouse A - Chicago", "location": "Chicago, IL", "capacity": 10000},
    {"warehouse_id": 2, "name": "Warehouse B - Dallas", "location": "Dallas, TX", "capacity": 8000},
    {"warehouse_id": 3, "name": "Warehouse C - Phoenix", "location": "Phoenix, AZ", "capacity": 6000},
]


def query_erp_sales_history(sku: str, days: int = 90) -> list[dict]:
    fallback = []
    product = next((p for p in FALLBACK_PRODUCTS if p["sku"] == sku), None)
    unit_cost = product["unit_cost"] if product else 100.0
    base = {"SKU-001": 14, "SKU-002": 6, "SKU-003": 20, "SKU-004": 10, "SKU-005": 4}.get(sku, 8)
    today = date.today()
    for idx in range(days):
        quantity = base + (idx % 7) + (2 if idx % 11 == 0 else 0)
        day = today - timedelta(days=(days - idx))
        fallback.append(
            {"date": str(day), "quantity": quantity, "revenue": round(quantity * unit_cost, 2)}
        )
    return _safe(lambda: erp_simulator.query_erp_sales_history(sku, days), fallback)


def query_inventory_levels(sku: str | None = None) -> list[dict]:
    fallback = FALLBACK_INVENTORY if sku is None else [i for i in FALLBACK_INVENTORY if i["sku"] == sku]
    return _safe(lambda: erp_simulator.query_inventory_levels(sku), fallback)


def query_all_products() -> list[dict]:
    return _safe(erp_simulator.query_all_products, FALLBACK_PRODUCTS)


def query_lead_times(vendor_id: int | None = None) -> list[dict]:
    fallback = FALLBACK_VENDORS if vendor_id is None else [v for v in FALLBACK_VENDORS if v["vendor_id"] == vendor_id]
    return _safe(lambda: erp_simulator.query_lead_times(vendor_id), fallback)


def query_vendor_constraints(vendor_id: int) -> dict:
    fallback_vendor = next((v for v in FALLBACK_VENDORS if v["vendor_id"] == vendor_id), {})
    products = [
        {
            "sku": sku,
            "unit_price": data["unit_price"],
            "discount_threshold": data["discount_threshold"],
            "discount_percent": data["discount_percent"],
        }
        for sku, data in FALLBACK_VENDOR_PRODUCTS.get(vendor_id, {}).items()
    ]
    fallback = {**fallback_vendor, "products": products}
    return _safe(lambda: erp_simulator.query_vendor_constraints(vendor_id), fallback)


def query_vendor_history(vendor_id: int) -> list[dict]:
    fallback = []
    for idx in range(5):
        fallback.append(
            {
                "po_id": 1000 + idx,
                "vendor_id": vendor_id,
                "sku": list(FALLBACK_VENDOR_PRODUCTS.get(vendor_id, {"SKU-001": {}}).keys())[0],
                "quantity": 100 + idx * 25,
                "unit_price": 100 - idx,
                "status": "completed",
                "created_at": f"2026-03-{10 + idx}T08:00:00Z",
                "product_name": "Historical Order",
            }
        )
    return _safe(lambda: erp_simulator.query_vendor_history(vendor_id), fallback)


def query_market_benchmarks() -> list[dict]:
    fallback = []
    for product in FALLBACK_PRODUCTS:
        prices = [
            vendor_products[product["sku"]]["unit_price"]
            for vendor_products in FALLBACK_VENDOR_PRODUCTS.values()
            if product["sku"] in vendor_products
        ]
        if prices:
            fallback.append(
                {
                    "sku": product["sku"],
                    "name": product["name"],
                    "lowest_price": min(prices),
                    "avg_price": round(sum(prices) / len(prices), 2),
                    "highest_price": max(prices),
                }
            )
    return _safe(erp_simulator.query_market_benchmarks, fallback)


def query_warehouse_locations() -> list[dict]:
    return _safe(erp_simulator.query_warehouse_locations, FALLBACK_WAREHOUSES)


def query_vendor_shipping(vendor_id: int) -> list[dict]:
    lead_time = next((v["lead_time_days"] for v in FALLBACK_VENDORS if v["vendor_id"] == vendor_id), 10)
    fallback = [
        {
            "warehouse_id": warehouse["warehouse_id"],
            "name": warehouse["name"],
            "location": warehouse["location"],
            "capacity": warehouse["capacity"],
            "lead_time_days": lead_time,
            "estimated_shipping_cost": round(40 + warehouse["warehouse_id"] * 12.5, 2),
        }
        for warehouse in FALLBACK_WAREHOUSES
    ]
    return _safe(lambda: erp_simulator.query_vendor_shipping(vendor_id), fallback)
