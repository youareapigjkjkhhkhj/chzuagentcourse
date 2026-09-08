from __future__ import annotations

from typing import Any

import mlflow

from config import config


class WorkflowTracker:
    def __init__(self):
        self.enabled = True
        try:
            mlflow.set_tracking_uri(config.MLFLOW_TRACKING_URI)
            mlflow.set_experiment(config.MLFLOW_EXPERIMENT_NAME)
        except Exception:
            self.enabled = False

    def log_workflow_run(self, state: dict[str, Any]) -> None:
        if not self.enabled:
            return

        final_recommendation = state.get("final_recommendation") or {}
        try:
            with mlflow.start_run(run_name=f"workflow-{state.get('sku', 'unknown')}"):
                mlflow.log_param("sku", state.get("sku", ""))
                mlflow.log_metric("risk_count", len(state.get("risk_alerts") or []))
                mlflow.log_metric(
                    "total_cost", float(final_recommendation.get("total_cost") or 0)
                )
                mlflow.log_metric(
                    "logistics_cost",
                    float(final_recommendation.get("logistics_cost") or 0),
                )
                vendor = final_recommendation.get("vendor_id")
                if vendor is not None:
                    mlflow.log_param("vendor_id", vendor)
                action = final_recommendation.get("action")
                if action:
                    mlflow.log_param("action", action)
        except Exception:
            self.enabled = False


workflow_tracker = WorkflowTracker()
