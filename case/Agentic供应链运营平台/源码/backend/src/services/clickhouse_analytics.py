from __future__ import annotations

from functools import lru_cache
from typing import Any

from clickhouse_connect import get_client

from config import config


class ClickHouseAnalytics:
    def __init__(self):
        self.enabled = True

    @lru_cache(maxsize=1)
    def _client(self):
        return get_client(
            host=config.CLICKHOUSE_HOST,
            port=config.CLICKHOUSE_PORT,
            username=config.CLICKHOUSE_USER,
            password=config.CLICKHOUSE_PASSWORD,
            database="default",
            connect_timeout=1,
            send_receive_timeout=2,
        )

    def ensure_schema(self) -> None:
        if not self.enabled:
            return
        try:
            client = self._client()
            client.command(f"CREATE DATABASE IF NOT EXISTS {config.CLICKHOUSE_DATABASE}")
            client.command(
                f"""
                CREATE TABLE IF NOT EXISTS {config.CLICKHOUSE_DATABASE}.workflow_runs (
                    event_time DateTime DEFAULT now(),
                    sku String,
                    risk_count UInt32,
                    recommended_vendor String,
                    total_cost Float64,
                    logistics_cost Float64,
                    recommendation_action String
                )
                ENGINE = MergeTree
                ORDER BY (sku, event_time)
                """
            )
        except Exception:
            self.enabled = False

    def log_workflow_run(self, state: dict[str, Any]) -> None:
        self.ensure_schema()
        if not self.enabled:
            return

        recommendation = state.get("final_recommendation") or {}
        try:
            self._client().insert(
                f"{config.CLICKHOUSE_DATABASE}.workflow_runs",
                [
                    [
                        state.get("sku", ""),
                        len(state.get("risk_alerts") or []),
                        str(recommendation.get("vendor_id") or ""),
                        float(recommendation.get("total_cost") or 0),
                        float(recommendation.get("logistics_cost") or 0),
                        str(recommendation.get("action") or ""),
                    ]
                ],
                column_names=[
                    "sku",
                    "risk_count",
                    "recommended_vendor",
                    "total_cost",
                    "logistics_cost",
                    "recommendation_action",
                ],
            )
        except Exception:
            self.enabled = False


clickhouse_analytics = ClickHouseAnalytics()
