#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from agents.orchestrator import orchestrator  # noqa: E402
from services.clickhouse_analytics import clickhouse_analytics  # noqa: E402
from services.mlflow_tracker import workflow_tracker  # noqa: E402


console = Console()


def pretty_json(value: object) -> str:
    return json.dumps(value, indent=2, default=str)


def summary_table(state: dict) -> Table:
    recommendation = state.get("final_recommendation") or {}
    forecast = state.get("demand_forecast") or {}
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold #5e5d59", width=22)
    table.add_column(style="#141413")
    table.add_row("SKU", str(state.get("sku", "")))
    table.add_row("Risk Count", str(len(state.get("risk_alerts") or [])))
    table.add_row("Forecasted Quantity", str(forecast.get("forecasted_quantity", "n/a")))
    table.add_row("Vendor", str(recommendation.get("vendor_id", "n/a")))
    table.add_row("Quantity", str(recommendation.get("quantity", "n/a")))
    table.add_row("Unit Price", f"${recommendation.get('unit_price', 'n/a')}")
    table.add_row("Total Cost", f"${recommendation.get('total_cost', 'n/a')}")
    table.add_row("Logistics Cost", f"${recommendation.get('logistics_cost', 'n/a')}")
    return table


def print_payload(title: str, value: object) -> None:
    payload = pretty_json(value)
    console.print(
        Panel(
            JSON(payload),
            title=title,
            border_style="#d1cfc5",
            padding=(0, 1),
        )
    )


def print_latest_message(message: str) -> None:
    if not message:
        return
    console.print(
        Panel(
            Syntax(message[:2200], "python", theme="friendly", word_wrap=True),
            title="Latest Agent Message",
            border_style="#e8e6dc",
            padding=(0, 1),
        )
    )


def render_step(agent_name: str, state: dict, duration_seconds: float) -> None:
    latest_message = state.get("messages", [])[-1]["output"] if state.get("messages") else ""
    title = Text.assemble(
        ("Step Complete", "bold #141413"),
        ("  "),
        (agent_name.replace("_", " ").title(), "bold #c96442"),
        ("  "),
        (f"{duration_seconds:.1f}s", "#87867f"),
    )
    console.print(Rule(title, style="#e8e6dc"))

    if agent_name == "inventory_monitor":
        risk_alerts = state.get("risk_alerts") or []
        console.print(
            Panel(
                Text(f"{len(risk_alerts)} risk alert(s) detected", style="bold #141413"),
                title="Inventory Signal",
                border_style="#d1cfc5",
            )
        )
        print_payload("Risk Alerts", risk_alerts)
    elif agent_name == "demand_forecast":
        print_payload("Demand Forecast", state.get("demand_forecast") or {})
    elif agent_name == "procurement":
        print_payload("Purchase Requisition", state.get("purchase_requisition") or {})
    elif agent_name == "vendor_negotiation":
        result = state.get("negotiation_result") or {}
        transcript = state.get("negotiation_transcript") or []
        console.print(
            Panel(
                Text(
                    f"Negotiation transcript captured with {len(transcript)} turn(s)",
                    style="bold #141413",
                ),
                title="Negotiation Status",
                border_style="#d1cfc5",
            )
        )
        print_payload("Negotiation Result", result)
    elif agent_name == "logistics":
        print_payload("Logistics Plan", state.get("logistics_plan") or {})
        print_payload("Final Recommendation", state.get("final_recommendation") or {})

    print_latest_message(latest_message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the real agent workflow and print each step.")
    parser.add_argument("--sku", default="SKU-001")
    parser.add_argument("--vendor-id", type=int, default=None)
    parser.add_argument("--quantity", type=int, default=None)
    parser.add_argument("--brief", default=None)
    parser.add_argument(
        "--telemetry",
        action="store_true",
        help="Keep MLflow and ClickHouse logging enabled during the trace.",
    )
    args = parser.parse_args()

    if not args.telemetry:
        workflow_tracker.enabled = False
        clickhouse_analytics.enabled = False

    console.print(
        Panel(
            JSON(
                pretty_json(
                    {
                        "sku": args.sku,
                        "preferred_vendor_id": args.vendor_id,
                        "requested_quantity": args.quantity,
                        "initial_message": args.brief,
                        "telemetry": args.telemetry,
                    }
                )
            ),
            title="Workflow Input",
            border_style="#c96442",
            padding=(0, 1),
        )
    )

    iterator = iter(
        orchestrator.run_live(
            args.sku,
            preferred_vendor_id=args.vendor_id,
            requested_quantity=args.quantity,
            initial_message=args.brief,
        )
    )

    last_state = None
    for expected_agent in orchestrator.execution_order:
        start = time.perf_counter()
        with console.status(
            f"[bold #141413]Running[/bold #141413] [#c96442]{expected_agent.replace('_', ' ')}[/#c96442]...",
            spinner="dots",
        ):
            try:
                agent_name, state = next(iterator)
            except StopIteration:
                break
        duration = time.perf_counter() - start
        last_state = state
        render_step(agent_name, state, duration)

    if last_state is None:
        console.print("[bold red]No workflow output produced.[/bold red]")
        return 1

    console.print(Rule(Text("Workflow Complete", style="bold #141413"), style="#c96442"))
    console.print(
        Panel(
            summary_table(last_state),
            title="Final Summary",
            border_style="#c96442",
            padding=(0, 1),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
