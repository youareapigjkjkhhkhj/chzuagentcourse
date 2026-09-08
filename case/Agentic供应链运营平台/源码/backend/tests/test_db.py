import pytest
from unittest.mock import patch, MagicMock


@patch("db.erp_simulator.get_db_cursor")
def test_query_all_products(mock_cursor):
    from db import erp_simulator

    cursor = MagicMock()
    mock_cursor.return_value.__enter__.return_value = cursor
    mock_cursor.return_value.__exit__.return_value = None
    cursor.fetchall.return_value = [
        {
            "sku": "SKU-001",
            "name": "Product 1",
            "category": "Cat1",
            "unit_cost": 10.0,
            "reorder_point": 100,
            "reorder_quantity": 500,
        }
    ]

    result = erp_simulator.query_all_products()
    assert len(result) == 1
    assert result[0]["sku"] == "SKU-001"


@patch("db.erp_simulator.get_db_cursor")
def test_query_dashboard_kpis(mock_cursor):
    from db import erp_simulator

    cursor = MagicMock()
    mock_cursor.return_value.__enter__.return_value = cursor
    mock_cursor.return_value.__exit__.return_value = None
    cursor.fetchone.return_value = {
        "total_skus": 10,
        "active_risks": 3,
        "pending_pos": 5,
        "pending_po_value": 15000.0,
    }

    result = erp_simulator.query_dashboard_kpis()
    assert result["total_skus"] == 10
    assert result["active_risks"] == 3
    assert result["pending_pos"] == 5


def test_config_validation():
    from config import Config

    original_key = Config.NEBIUS_API_KEY
    Config.NEBIUS_API_KEY = None

    with pytest.raises(ValueError, match="NEBIUS_API_KEY"):
        Config.validate()

    Config.NEBIUS_API_KEY = original_key
