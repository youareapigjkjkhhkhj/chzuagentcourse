from typing import Any
from mcp.server import Server
from mcp.types import Tool, Resource
from db import erp_simulator


class MCPServer:
    def __init__(self):
        self.server = Server("supply-chain-mcp")

    async def handle_query_erp_sales_history(
        self, sku: str, days: int = 90
    ) -> list[dict]:
        return erp_simulator.query_erp_sales_history(sku, days)

    async def handle_query_inventory_levels(self, sku: str) -> list[dict]:
        return erp_simulator.query_inventory_levels(sku)

    async def handle_query_lead_times(self, vendor_id: int) -> list[dict]:
        return erp_simulator.query_lead_times(vendor_id)

    async def handle_query_vendor_constraints(self, vendor_id: int) -> dict:
        return erp_simulator.query_vendor_constraints(vendor_id)

    async def handle_create_purchase_order(
        self, vendor_id: int, sku: str, quantity: int, unit_price: float
    ) -> dict:
        return erp_simulator.create_purchase_order(vendor_id, sku, quantity, unit_price)

    async def handle_query_vendor_history(self, vendor_id: int) -> list[dict]:
        return erp_simulator.query_vendor_history(vendor_id)

    async def handle_query_market_benchmarks(self) -> list[dict]:
        return erp_simulator.query_market_benchmarks()

    async def handle_query_warehouse_locations(self) -> list[dict]:
        return erp_simulator.query_warehouse_locations()

    async def handle_query_vendor_shipping(self, vendor_id: int) -> list[dict]:
        return erp_simulator.query_vendor_shipping(vendor_id)


mcp_server = MCPServer()
