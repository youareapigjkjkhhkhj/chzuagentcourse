from typing import Optional
from db.connection import get_db_cursor


def query_erp_sales_history(sku: str, days: int = 90) -> list[dict]:
    with get_db_cursor() as cursor:
        cursor.execute(
            """
            SELECT date, quantity, revenue
            FROM sales_history
            WHERE sku = %s AND date >= CURRENT_DATE - INTERVAL '%s days'
            ORDER BY date ASC
            """,
            (sku, days),
        )
        return [dict(row) for row in cursor.fetchall()]


def query_inventory_levels(sku: Optional[str] = None) -> list[dict]:
    with get_db_cursor() as cursor:
        if sku:
            cursor.execute(
                """
                SELECT i.sku, p.name as product_name, w.name as warehouse_name,
                       i.quantity, i.last_updated
                FROM inventory i
                JOIN products p ON i.sku = p.sku
                JOIN warehouses w ON i.warehouse_id = w.warehouse_id
                WHERE i.sku = %s
                """,
                (sku,),
            )
        else:
            cursor.execute(
                """
                SELECT i.sku, p.name as product_name, w.name as warehouse_name,
                       i.quantity, i.last_updated
                FROM inventory i
                JOIN products p ON i.sku = p.sku
                JOIN warehouses w ON i.warehouse_id = w.warehouse_id
                """
            )
        return [dict(row) for row in cursor.fetchall()]


def query_lead_times(vendor_id: Optional[int] = None) -> list[dict]:
    with get_db_cursor() as cursor:
        if vendor_id:
            cursor.execute(
                "SELECT vendor_id, name, lead_time_days, min_order_value FROM vendors WHERE vendor_id = %s",
                (vendor_id,),
            )
        else:
            cursor.execute(
                "SELECT vendor_id, name, lead_time_days, min_order_value FROM vendors"
            )
        return [dict(row) for row in cursor.fetchall()]


def query_vendor_constraints(vendor_id: int) -> dict:
    with get_db_cursor() as cursor:
        cursor.execute(
            """
            SELECT v.*, vp.sku, vp.unit_price, vp.discount_threshold, vp.discount_percent
            FROM vendors v
            LEFT JOIN vendor_products vp ON v.vendor_id = vp.vendor_id
            WHERE v.vendor_id = %s
            """,
            (vendor_id,),
        )
        rows = cursor.fetchall()
        if not rows:
            return {}
        result = dict(rows[0])
        result["products"] = [
            {
                "sku": r["sku"],
                "unit_price": r["unit_price"],
                "discount_threshold": r["discount_threshold"],
                "discount_percent": r["discount_percent"],
            }
            for r in rows
            if r["sku"]
        ]
        return result


def create_purchase_order(
    vendor_id: int, sku: str, quantity: int, unit_price: float
) -> dict:
    with get_db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO purchase_orders (vendor_id, sku, quantity, unit_price, status)
            VALUES (%s, %s, %s, %s, 'pending')
            RETURNING po_id, created_at
            """,
            (vendor_id, sku, quantity, unit_price),
        )
        row = cursor.fetchone()
        return {
            "po_id": row["po_id"],
            "created_at": row["created_at"],
            "status": "pending",
        }


def query_vendor_history(vendor_id: int) -> list[dict]:
    with get_db_cursor() as cursor:
        cursor.execute(
            """
            SELECT po.*, p.name as product_name
            FROM purchase_orders po
            JOIN products p ON po.sku = p.sku
            WHERE po.vendor_id = %s
            ORDER BY po.created_at DESC
            LIMIT 20
            """,
            (vendor_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def query_market_benchmarks() -> list[dict]:
    with get_db_cursor() as cursor:
        cursor.execute(
            """
            SELECT p.sku, p.name, MIN(vp.unit_price) as lowest_price, 
                   AVG(vp.unit_price) as avg_price, MAX(vp.unit_price) as highest_price
            FROM products p
            JOIN vendor_products vp ON p.sku = vp.sku
            GROUP BY p.sku, p.name
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def query_warehouse_locations() -> list[dict]:
    with get_db_cursor() as cursor:
        cursor.execute("SELECT warehouse_id, name, location, capacity FROM warehouses")
        return [dict(row) for row in cursor.fetchall()]


def query_vendor_shipping(vendor_id: int) -> list[dict]:
    with get_db_cursor() as cursor:
        cursor.execute(
            """
            SELECT w.warehouse_id, w.name, w.location, w.capacity,
                   v.lead_time_days, 50.00 as estimated_shipping_cost
            FROM warehouses w
            CROSS JOIN vendors v
            WHERE v.vendor_id = %s
            """,
            (vendor_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def query_all_products() -> list[dict]:
    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT sku, name, category, unit_cost, reorder_point, reorder_quantity FROM products"
        )
        return [dict(row) for row in cursor.fetchall()]


def query_risk_alerts() -> list[dict]:
    with get_db_cursor() as cursor:
        cursor.execute(
            """
            SELECT p.sku, p.name, p.reorder_point, p.reorder_quantity,
                   COALESCE(SUM(i.quantity), 0) as total_quantity,
                   CASE 
                       WHEN COALESCE(SUM(i.quantity), 0) < p.reorder_point THEN 'critical'
                       WHEN COALESCE(SUM(i.quantity), 0) < p.reorder_point * 1.5 THEN 'low'
                       WHEN COALESCE(SUM(i.quantity), 0) > p.reorder_point * 3 THEN 'excess'
                       ELSE 'normal'
                   END as risk_status
            FROM products p
            LEFT JOIN inventory i ON p.sku = i.sku
            GROUP BY p.sku, p.name, p.reorder_point, p.reorder_quantity
            HAVING COALESCE(SUM(i.quantity), 0) < p.reorder_point * 2
            ORDER BY 
                CASE risk_status
                    WHEN 'critical' THEN 1
                    WHEN 'low' THEN 2
                    WHEN 'excess' THEN 3
                END
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def query_dashboard_kpis() -> dict:
    with get_db_cursor() as cursor:
        cursor.execute(
            """
            SELECT 
                (SELECT COUNT(*) FROM products) as total_skus,
                (SELECT COUNT(*) FROM (
                    SELECT p.sku
                    FROM products p
                    LEFT JOIN inventory i ON p.sku = i.sku
                    GROUP BY p.sku
                    HAVING COALESCE(SUM(i.quantity), 0) < p.reorder_point
                ) AS at_risk) as active_risks,
                (SELECT COUNT(*) FROM purchase_orders WHERE status = 'pending') as pending_pos,
                (SELECT COALESCE(SUM(quantity * unit_price), 0) FROM purchase_orders WHERE status = 'pending') as pending_po_value
            """
        )
        row = cursor.fetchone()
        return dict(row)
