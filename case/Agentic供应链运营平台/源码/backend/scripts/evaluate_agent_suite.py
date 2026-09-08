#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from agents.orchestrator import orchestrator  # noqa: E402
from deep_control_room import build_agent  # noqa: E402
from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
from services.clickhouse_analytics import clickhouse_analytics  # noqa: E402
from services.mlflow_tracker import workflow_tracker  # noqa: E402


DATASET_PATH = ROOT_DIR / "evals" / "agentic_test_set.csv"
DEMO_DIR = ROOT_DIR / "demo"
RESULTS_CSV = DEMO_DIR / "agentic_eval_results.csv"
RESULTS_JSON = DEMO_DIR / "agentic_eval_results.json"
DASHBOARD_HTML = DEMO_DIR / "agentic_eval_dashboard.html"


def _disable_telemetry() -> None:
    workflow_tracker.enabled = False
    clickhouse_analytics.enabled = False


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    return int(value)


def _strip_think(text: str) -> str:
    if "<think>" not in text:
        return text.strip()
    while "<think>" in text and "</think>" in text:
        start = text.index("<think>")
        end = text.index("</think>") + len("</think>")
        text = text[:start] + text[end:]
    return text.strip()


def _read_dataset() -> list[dict[str, str]]:
    with DATASET_PATH.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _select_cases(
    rows: list[dict[str, str]],
    quick: bool = False,
    max_cases: int | None = None,
    track: str = "all",
) -> list[dict[str, str]]:
    if track != "all":
        rows = [row for row in rows if row["track"] == track]

    if quick:
        workflow_rows = [row for row in rows if row["track"] == "workflow"][:3]
        control_rows = [row for row in rows if row["track"] == "control_room"][:1]
        rows = workflow_rows + control_rows

    if max_cases is not None:
        rows = rows[:max_cases]
    return rows


def _run_workflow_case(case: dict[str, str]) -> dict[str, Any]:
    start = time.perf_counter()
    result = orchestrator.run(
        case["sku"],
        preferred_vendor_id=_to_int(case["vendor_id"]),
        requested_quantity=_to_int(case["quantity"]),
        initial_message=(case["brief"] or None),
    )
    latency = round(time.perf_counter() - start, 2)

    final = result.get("final_recommendation") or {}
    forecast = result.get("demand_forecast") or {}
    negotiation = result.get("negotiation_result") or {}
    transcript = result.get("negotiation_transcript") or []
    logistics = result.get("logistics_plan") or {}

    output_completeness = sum(
        1
        for item in [
            result.get("risk_alerts"),
            result.get("demand_forecast"),
            result.get("purchase_requisition"),
            result.get("negotiation_result"),
            result.get("logistics_plan"),
            result.get("final_recommendation"),
        ]
        if item
    )

    unit_price = _safe_float(final.get("unit_price"))
    total_cost = _safe_float(final.get("total_cost"))
    logistics_cost = _safe_float(final.get("logistics_cost"))
    estimated_unit_price = _safe_float((result.get("purchase_requisition") or {}).get("estimated_unit_price"))
    savings_pct = 0.0
    if estimated_unit_price > 0 and unit_price > 0:
        savings_pct = round(((estimated_unit_price - unit_price) / estimated_unit_price) * 100, 2)

    return {
        "case_id": case["case_id"],
        "track": case["track"],
        "scenario_goal": case["scenario_goal"],
        "sku": case["sku"],
        "latency_seconds": latency,
        "risk_count": len(result.get("risk_alerts") or []),
        "forecasted_quantity": forecast.get("forecasted_quantity"),
        "selected_vendor_id": final.get("vendor_id"),
        "ordered_quantity": final.get("quantity"),
        "unit_price": unit_price,
        "estimated_unit_price": estimated_unit_price,
        "savings_vs_estimate_pct": savings_pct,
        "savings_vs_benchmark_pct": negotiation.get("savings_vs_benchmark"),
        "discount_percent": (negotiation.get("terms_achieved") or {}).get("discount_percent"),
        "negotiation_turns": len(transcript),
        "delivery_timeline": logistics.get("delivery_timeline"),
        "total_cost": total_cost,
        "logistics_cost": logistics_cost,
        "output_completeness": output_completeness,
        "status": "passed" if output_completeness == 6 else "partial",
        "summary": (
            f"Vendor {final.get('vendor_id')} selected for {final.get('quantity')} units at "
            f"${unit_price:.2f}, total cost ${total_cost:.2f}."
        ),
    }


def _run_control_room_case(agent, case: dict[str, str], thread_id: str) -> dict[str, Any]:
    start = time.perf_counter()
    result = agent.invoke(
        {"messages": [{"role": "user", "content": case["prompt"]}]},
        config={"configurable": {"thread_id": thread_id}},
    )
    latency = round(time.perf_counter() - start, 2)

    messages = result["messages"]
    tool_calls = 0
    tool_results = 0
    final_answer = ""
    for message in messages:
        if isinstance(message, AIMessage) and message.tool_calls:
            tool_calls += len(message.tool_calls)
        elif isinstance(message, ToolMessage):
            tool_results += 1
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls:
            final_answer = _strip_think(message.content or "")
            if final_answer:
                break

    return {
        "case_id": case["case_id"],
        "track": case["track"],
        "scenario_goal": case["scenario_goal"],
        "sku": case["sku"] or "",
        "latency_seconds": latency,
        "risk_count": "",
        "forecasted_quantity": "",
        "selected_vendor_id": "",
        "ordered_quantity": "",
        "unit_price": "",
        "estimated_unit_price": "",
        "savings_vs_estimate_pct": "",
        "savings_vs_benchmark_pct": "",
        "discount_percent": "",
        "negotiation_turns": "",
        "delivery_timeline": "",
        "total_cost": "",
        "logistics_cost": "",
        "output_completeness": tool_results,
        "status": "passed" if final_answer and tool_calls > 0 else "partial",
        "summary": final_answer[:260],
        "tool_calls": tool_calls,
        "tool_results": tool_results,
    }


def _write_results(rows: list[dict[str, Any]]) -> None:
    DEMO_DIR.mkdir(exist_ok=True)
    fieldnames = [
        "case_id",
        "track",
        "scenario_goal",
        "sku",
        "latency_seconds",
        "risk_count",
        "forecasted_quantity",
        "selected_vendor_id",
        "ordered_quantity",
        "unit_price",
        "estimated_unit_price",
        "savings_vs_estimate_pct",
        "savings_vs_benchmark_pct",
        "discount_percent",
        "negotiation_turns",
        "delivery_timeline",
        "total_cost",
        "logistics_cost",
        "output_completeness",
        "tool_calls",
        "tool_results",
        "status",
        "summary",
    ]
    with RESULTS_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(DATASET_PATH.relative_to(ROOT_DIR)),
        "results": rows,
    }
    RESULTS_JSON.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _dashboard_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    workflow_rows = [row for row in rows if row["track"] == "workflow"]
    control_rows = [row for row in rows if row["track"] == "control_room"]
    passed = [row for row in rows if row["status"] == "passed"]
    avg_latency = round(statistics.mean(float(row["latency_seconds"]) for row in rows), 2) if rows else 0.0
    workflow_costs = [
        _safe_float(row["total_cost"])
        for row in workflow_rows
        if _safe_float(row["total_cost"]) > 0
    ]
    workflow_savings = [
        _safe_float(row["savings_vs_estimate_pct"])
        for row in workflow_rows
        if row["savings_vs_estimate_pct"] != ""
    ]

    return {
        "total_cases": len(rows),
        "passed_cases": len(passed),
        "workflow_cases": len(workflow_rows),
        "control_room_cases": len(control_rows),
        "avg_latency": avg_latency,
        "avg_workflow_cost": round(statistics.mean(workflow_costs), 2) if workflow_costs else 0.0,
        "avg_savings_pct": round(statistics.mean(workflow_savings), 2) if workflow_savings else 0.0,
        "max_discount_pct": max(
            (_safe_float(row["discount_percent"]) for row in workflow_rows if row["discount_percent"] != ""),
            default=0.0,
        ),
    }


def _render_html(rows: list[dict[str, Any]]) -> str:
    metrics = _dashboard_metrics(rows)
    workflow_rows = [row for row in rows if row["track"] == "workflow"]
    control_rows = [row for row in rows if row["track"] == "control_room"]

    def card(label: str, value: Any, detail: str) -> str:
        return f"""
        <article class="metric-card">
          <span class="metric-label">{html.escape(label)}</span>
          <strong class="metric-value">{html.escape(str(value))}</strong>
          <p class="metric-detail">{html.escape(detail)}</p>
        </article>
        """

    workflow_table_rows = "".join(
        f"""
        <tr>
          <td>{html.escape(row['case_id'])}</td>
          <td>{html.escape(row['sku'])}</td>
          <td>{html.escape(str(row['selected_vendor_id']))}</td>
          <td>{html.escape(str(row['ordered_quantity']))}</td>
          <td>${html.escape(str(row['unit_price']))}</td>
          <td>{html.escape(str(row['savings_vs_estimate_pct']))}%</td>
          <td>{html.escape(str(row['discount_percent']))}%</td>
          <td>{html.escape(str(row['latency_seconds']))}s</td>
          <td>{html.escape(row['status'])}</td>
        </tr>
        """
        for row in workflow_rows
    )

    control_cards = "".join(
        f"""
        <article class="prompt-card">
          <div class="prompt-top">
            <span class="badge">{html.escape(row['case_id'])}</span>
            <span class="badge badge-neutral">{html.escape(str(row.get('tool_calls', 0)))} tool call(s)</span>
          </div>
          <h3>{html.escape(row['scenario_goal'])}</h3>
          <p>{html.escape(row['summary'])}</p>
          <div class="prompt-meta">
            <span>{html.escape(str(row['latency_seconds']))}s</span>
            <span>{html.escape(row['status'])}</span>
          </div>
        </article>
        """
        for row in control_rows
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Atlas AI Agentic Evaluation Dashboard</title>
  <style>
    :root {{
      --bg: #f5f4ed;
      --panel: #faf9f5;
      --line: #e8e6dc;
      --text: #141413;
      --muted: #5e5d59;
      --subtle: #87867f;
      --accent: #c96442;
      --accent-soft: rgba(201, 100, 66, 0.12);
      --ok: #4d6454;
      --shadow: 0 4px 24px rgba(0,0,0,0.05);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", system-ui, sans-serif;
      color: var(--text);
      background: var(--bg);
    }}
    .shell {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 40px 24px 56px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: 1.4fr 1fr;
      gap: 20px;
      padding: 28px;
      border-radius: 28px;
      border: 1px solid var(--line);
      background: var(--panel);
      box-shadow: var(--shadow);
    }}
    .eyebrow {{
      font-size: 11px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--subtle);
    }}
    h1, h2, h3 {{
      font-family: Georgia, serif;
      font-weight: 500;
      margin: 0;
    }}
    h1 {{
      margin-top: 10px;
      font-size: 2.1rem;
      line-height: 1.15;
      max-width: 14ch;
    }}
    .hero p {{
      margin-top: 14px;
      color: var(--muted);
      line-height: 1.6;
      max-width: 62ch;
    }}
    .hero-list {{
      display: grid;
      gap: 14px;
      align-content: end;
    }}
    .hero-item {{
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: var(--bg);
    }}
    .hero-item span {{
      display: block;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: var(--subtle);
    }}
    .hero-item strong {{
      display: block;
      margin-top: 6px;
      font-size: 1.15rem;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 16px;
      margin-top: 20px;
    }}
    .metric-card {{
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 20px;
      background: var(--panel);
      box-shadow: var(--shadow);
    }}
    .metric-label {{
      display: block;
      font-size: 11px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--subtle);
    }}
    .metric-value {{
      display: block;
      margin-top: 8px;
      font-size: 1.55rem;
    }}
    .metric-detail {{
      margin: 10px 0 0;
      color: var(--muted);
      line-height: 1.5;
      font-size: 13px;
    }}
    .section {{
      margin-top: 24px;
      padding: 24px;
      border: 1px solid var(--line);
      border-radius: 24px;
      background: var(--panel);
      box-shadow: var(--shadow);
    }}
    .section-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: end;
      margin-bottom: 16px;
    }}
    .section-head p {{
      margin: 10px 0 0;
      color: var(--muted);
      max-width: 60ch;
      line-height: 1.6;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    th, td {{
      text-align: left;
      padding: 12px 10px;
      border-top: 1px solid var(--line);
    }}
    th {{
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--subtle);
      border-top: none;
    }}
    .prompt-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
    }}
    .prompt-card {{
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 20px;
      background: var(--bg);
    }}
    .prompt-card p {{
      margin: 12px 0 0;
      color: var(--muted);
      line-height: 1.6;
      font-size: 14px;
    }}
    .prompt-top, .prompt-meta {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .prompt-card h3 {{
      margin-top: 12px;
      font-size: 1.1rem;
    }}
    .prompt-meta {{
      margin-top: 14px;
      color: var(--subtle);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      padding: 6px 10px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: #9f4d33;
      font-size: 12px;
      font-weight: 600;
    }}
    .badge-neutral {{
      background: #f0eee6;
      color: var(--muted);
    }}
    .footer {{
      margin-top: 22px;
      color: var(--subtle);
      font-size: 13px;
    }}
    @media (max-width: 1024px) {{
      .hero, .metrics, .prompt-grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div>
        <span class="eyebrow">Resume-Ready Evaluation</span>
        <h1>Atlas AI agentic suite benchmark pack for sourcing, negotiation, and governance workflows.</h1>
        <p>
          This dashboard summarizes a reproducible evaluation of the real multi-agent workflow and the Deep Agents
          control-room CLI. The suite measures execution latency, sourcing economics, negotiation performance, and
          control-room tool usage across structured test scenarios.
        </p>
      </div>
      <div class="hero-list">
        <div class="hero-item">
          <span>Generated at</span>
          <strong>{html.escape(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))}</strong>
        </div>
        <div class="hero-item">
          <span>Test set</span>
          <strong>{html.escape(str(DATASET_PATH.relative_to(ROOT_DIR)))}</strong>
        </div>
        <div class="hero-item">
          <span>Coverage</span>
          <strong>{metrics["workflow_cases"]} workflow cases, {metrics["control_room_cases"]} control-room cases</strong>
        </div>
      </div>
    </section>

    <section class="metrics">
      {card("Total Cases", metrics["total_cases"], "Structured suite coverage across workflow and control-room evaluation.")}
      {card("Passed Cases", metrics["passed_cases"], "Cases that returned complete, non-empty outputs through the live suite.")}
      {card("Average Latency", f'{metrics["avg_latency"]}s', "Mean end-to-end execution time across all evaluation cases.")}
      {card("Average Workflow Cost", f'${metrics["avg_workflow_cost"]}', "Average recommended total sourcing cost across workflow cases.")}
      {card("Average Savings", f'{metrics["avg_savings_pct"]}%', "Average savings against procurement estimate across workflow runs.")}
      {card("Max Discount", f'{metrics["max_discount_pct"]}%', "Highest discount captured by the negotiation agent in the evaluated set.")}
      {card("Deep Agents Layer", "Enabled", "Natural-language control room routes prompts into live workflow and platform tools.")}
      {card("Execution Engine", "LangGraph", "Underlying workflow remains a real multi-step graph with inventory, forecast, procurement, negotiation, and logistics stages.")}
    </section>

    <section class="section">
      <div class="section-head">
        <div>
          <span class="eyebrow">Workflow Cases</span>
          <h2>Operational decision runs</h2>
          <p>These cases execute the real multi-agent workflow and record sourcing, pricing, timeline, and completeness KPIs.</p>
        </div>
      </div>
      <table>
        <thead>
          <tr>
            <th>Case</th>
            <th>SKU</th>
            <th>Vendor</th>
            <th>Quantity</th>
            <th>Unit Price</th>
            <th>Savings</th>
            <th>Discount</th>
            <th>Latency</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {workflow_table_rows}
        </tbody>
      </table>
    </section>

    <section class="section">
      <div class="section-head">
        <div>
          <span class="eyebrow">Control-Room Cases</span>
          <h2>Deep Agents supervisory prompts</h2>
          <p>These cases validate the Deep Agents control-room layer by measuring tool usage, response latency, and operational answer quality.</p>
        </div>
      </div>
      <div class="prompt-grid">
        {control_cards}
      </div>
    </section>

    <p class="footer">
      Artifacts: <code>demo/agentic_eval_results.csv</code>, <code>demo/agentic_eval_results.json</code>, and this dashboard.
    </p>
  </div>
</body>
</html>
"""


def _write_dashboard(rows: list[dict[str, Any]]) -> None:
    DASHBOARD_HTML.write_text(_render_html(rows), encoding="utf-8")


def _print_progress(index: int, total: int, case: dict[str, str], row: dict[str, Any], elapsed: float) -> None:
    label = case["prompt"] if case["track"] == "control_room" else case["sku"]
    print(
        f"[{index}/{total}] {case['case_id']} {case['track']} {row['status']} "
        f"in {elapsed:.2f}s :: {label[:90]}",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the agentic suite and produce KPI artifacts.")
    parser.add_argument("--quick", action="store_true", help="Run a smaller benchmark set for faster output.")
    parser.add_argument("--max-cases", type=int, default=None, help="Limit the number of cases executed.")
    parser.add_argument(
        "--track",
        choices=["all", "workflow", "control_room"],
        default="all",
        help="Restrict the run to one track.",
    )
    args = parser.parse_args()

    _disable_telemetry()
    DEMO_DIR.mkdir(exist_ok=True)

    dataset = _select_cases(_read_dataset(), quick=args.quick, max_cases=args.max_cases, track=args.track)
    if not dataset:
        print("No evaluation cases selected.", flush=True)
        return 1

    print(
        f"Running {len(dataset)} evaluation case(s) from {DATASET_PATH.relative_to(ROOT_DIR)} "
        f"[quick={args.quick}, track={args.track}]",
        flush=True,
    )

    rows: list[dict[str, Any]] = []
    control_room_agent = build_agent()

    for index, case in enumerate(dataset, start=1):
        started_at = time.perf_counter()
        if case["track"] == "workflow":
            row = _run_workflow_case(case)
        elif case["track"] == "control_room":
            row = _run_control_room_case(control_room_agent, case, thread_id=f"eval-{case['case_id']}")
        else:
            raise ValueError(f"Unknown track: {case['track']}")
        rows.append(row)
        _print_progress(index, len(dataset), case, row, time.perf_counter() - started_at)

    _write_results(rows)
    _write_dashboard(rows)
    metrics = _dashboard_metrics(rows)
    print(
        "Evaluation complete: "
        f"{metrics['passed_cases']}/{metrics['total_cases']} passed, "
        f"avg latency {metrics['avg_latency']}s, "
        f"avg savings {metrics['avg_savings_pct']}%",
        flush=True,
    )
    print(f"Wrote {RESULTS_CSV.relative_to(ROOT_DIR)}", flush=True)
    print(f"Wrote {RESULTS_JSON.relative_to(ROOT_DIR)}", flush=True)
    print(f"Wrote {DASHBOARD_HTML.relative_to(ROOT_DIR)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
