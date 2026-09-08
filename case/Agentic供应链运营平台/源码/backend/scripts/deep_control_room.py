#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from deepagents import create_deep_agent  # noqa: E402
from deepagents.backends import FilesystemBackend  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.store.memory import InMemoryStore  # noqa: E402

from agents.orchestrator import orchestrator  # noqa: E402
from config import config  # noqa: E402
from services.clickhouse_analytics import clickhouse_analytics  # noqa: E402
from services.mlflow_tracker import workflow_tracker  # noqa: E402
from services.platform_intelligence import (  # noqa: E402
    get_control_tower_snapshot,
    get_governance_hub,
    get_scenario_lab,
)


console = Console()


def _disable_telemetry() -> None:
    workflow_tracker.enabled = False
    clickhouse_analytics.enabled = False


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _strip_think_blocks(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _step_trace(
    sku: str,
    preferred_vendor_id: int | None = None,
    requested_quantity: int | None = None,
    initial_message: str | None = None,
) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    for agent_name, state in orchestrator.run_live(
        sku,
        preferred_vendor_id=preferred_vendor_id,
        requested_quantity=requested_quantity,
        initial_message=initial_message,
    ):
        item: dict[str, Any] = {"agent": agent_name}
        if agent_name == "inventory_monitor":
            item["risk_alerts"] = state.get("risk_alerts") or []
        elif agent_name == "demand_forecast":
            item["demand_forecast"] = state.get("demand_forecast") or {}
        elif agent_name == "procurement":
            item["purchase_requisition"] = state.get("purchase_requisition") or {}
        elif agent_name == "vendor_negotiation":
            item["negotiation_result"] = state.get("negotiation_result") or {}
            item["negotiation_transcript"] = state.get("negotiation_transcript") or []
        elif agent_name == "logistics":
            item["logistics_plan"] = state.get("logistics_plan") or {}
            item["final_recommendation"] = state.get("final_recommendation") or {}
        trace.append(item)
    return trace


@tool
def analyze_supply_workflow(
    sku: str,
    preferred_vendor_id: int | None = None,
    requested_quantity: int | None = None,
    initial_message: str | None = None,
) -> str:
    """Run the real multi-agent supply workflow for a SKU and return structured output."""
    _disable_telemetry()
    result = orchestrator.run(
        sku,
        preferred_vendor_id=preferred_vendor_id,
        requested_quantity=requested_quantity,
        initial_message=initial_message,
    )
    return _json(result)


@tool
def trace_supply_workflow(
    sku: str,
    preferred_vendor_id: int | None = None,
    requested_quantity: int | None = None,
    initial_message: str | None = None,
) -> str:
    """Run the real multi-agent workflow and return agent-by-agent step output."""
    _disable_telemetry()
    return _json(
        _step_trace(
            sku,
            preferred_vendor_id=preferred_vendor_id,
            requested_quantity=requested_quantity,
            initial_message=initial_message,
        )
    )


@tool
def compare_vendor_options(sku: str, quantity: int, vendor_ids_csv: str = "1,2,3") -> str:
    """Compare multiple vendors for the same SKU and quantity. vendor_ids_csv should be a comma-separated list like '1,2,3'."""
    _disable_telemetry()
    comparisons: list[dict[str, Any]] = []
    vendor_ids = [int(item.strip()) for item in vendor_ids_csv.split(",") if item.strip()]
    for vendor_id in vendor_ids:
        result = orchestrator.run(
            sku,
            preferred_vendor_id=vendor_id,
            requested_quantity=quantity,
            initial_message="Prioritize price discipline and delivery confidence.",
        )
        final = result.get("final_recommendation") or {}
        negotiation = result.get("negotiation_result") or {}
        comparisons.append(
            {
                "vendor_id": vendor_id,
                "unit_price": final.get("unit_price"),
                "total_cost": final.get("total_cost"),
                "logistics_cost": final.get("logistics_cost"),
                "delivery": final.get("estimated_delivery"),
                "discount_percent": (negotiation.get("terms_achieved") or {}).get("discount_percent"),
            }
        )
    return _json(comparisons)


@tool
def get_control_tower() -> str:
    """Return the latest control tower snapshot."""
    return _json(get_control_tower_snapshot())


@tool
def get_scenario_lab_data() -> str:
    """Return the scenario lab data."""
    return _json(get_scenario_lab())


@tool
def get_governance_data() -> str:
    """Return the governance and approval posture."""
    return _json(get_governance_hub())


@tool
def list_demo_files() -> str:
    """List generated demo artifacts and reports in the demo directory."""
    demo_dir = ROOT_DIR / "demo"
    files = sorted(path.name for path in demo_dir.glob("*") if path.is_file())
    return _json(files)


def build_agent():
    model = ChatOpenAI(
        model=config.LLM_MODEL,
        base_url=config.LLM_BASE_URL,
        api_key=config.NEBIUS_API_KEY,
        temperature=0.2,
    )
    return create_deep_agent(
        name="atlas-control-room",
        model=model,
        tools=[
            analyze_supply_workflow,
            trace_supply_workflow,
            compare_vendor_options,
            get_control_tower,
            get_scenario_lab_data,
            get_governance_data,
            list_demo_files,
        ],
        system_prompt=(
            "You are Atlas AI Control Room, a precise supply-chain operations copilot. "
            "Use tools to get real workflow outputs, then explain them clearly and operationally. "
            "Prefer concrete metrics, prices, vendor ids, quantities, and delivery timing. "
            "When useful, trace the full agent chain instead of summarizing from memory."
        ),
        backend=FilesystemBackend(root_dir=".", virtual_mode=True),
        skills=["./skills/"],
        checkpointer=MemorySaver(),
        store=InMemoryStore(),
    )


def render_tool_ledger(messages: list[Any], start_index: int) -> None:
    table = Table(title="Tool Ledger", show_header=True, header_style="bold #c96442")
    table.add_column("Type", style="#5e5d59", width=10)
    table.add_column("Name", style="#141413", width=26)
    table.add_column("Preview", style="#5e5d59")

    rows = 0
    for message in messages[start_index:]:
        if isinstance(message, AIMessage) and message.tool_calls:
            for tool_call in message.tool_calls:
                rows += 1
                table.add_row(
                    "call",
                    tool_call.get("name", ""),
                    _strip_think_blocks(message.content or "")[:110] or str(tool_call.get("args", {}))[:110],
                )
        elif isinstance(message, ToolMessage):
            rows += 1
            table.add_row(
                "result",
                message.name or "tool",
                (message.content or "")[:110].replace("\n", " "),
            )

    if rows:
        console.print(table)


def render_answer(messages: list[Any], start_index: int) -> None:
    final_text = ""
    for message in reversed(messages[start_index:]):
        if isinstance(message, AIMessage) and not message.tool_calls:
            final_text = _strip_think_blocks(message.content or "")
            if final_text:
                break
    if not final_text:
        final_text = "No final response produced."

    console.print(
        Panel(
            Markdown(final_text),
            title="Atlas Control Room",
            border_style="#c96442",
            padding=(1, 2),
        )
    )


def run_prompt(agent, thread_id: str, prompt: str, history_len: int) -> int:
    console.print(Rule("[bold #141413]Control Room Request[/bold #141413]", style="#d1cfc5"))
    console.print(Panel(prompt, border_style="#e8e6dc"))
    with console.status("[bold #141413]Atlas control room is reasoning and calling tools...[/bold #141413]", spinner="dots"):
        result = agent.invoke(
            {"messages": [{"role": "user", "content": prompt}]},
            config={"configurable": {"thread_id": thread_id}},
        )
    messages = result["messages"]
    render_tool_ledger(messages, history_len)
    render_answer(messages, history_len)
    return len(messages)


def main() -> int:
    parser = argparse.ArgumentParser(description="Deep Agents powered CLI control room for Atlas AI.")
    parser.add_argument("prompt", nargs="*", help="Optional one-shot prompt.")
    parser.add_argument("--thread-id", default="atlas-cli")
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args()

    _disable_telemetry()
    agent = build_agent()

    console.print(
        Panel(
            "[bold #141413]Atlas AI Deep Control Room[/bold #141413]\n"
            "[#5e5d59]Natural-language CLI for live workflow analysis, negotiation review, vendor comparison, and governance interpretation.[/#5e5d59]\n\n"
            "[#87867f]Examples[/#87867f]\n"
            "- Trace the full workflow for SKU-001 and explain where risk enters.\n"
            "- Compare vendors 1,2,3 for SKU-001 at quantity 500.\n"
            "- Show the governance posture and tell me what needs human approval.\n"
            "- Summarize the latest control tower KPI movements.\n\n"
            "[#87867f]Commands[/#87867f]\n"
            "- /quit\n"
            "- /help",
            border_style="#c96442",
            padding=(1, 2),
        )
    )

    history_len = 0
    if args.prompt:
        history_len = run_prompt(agent, args.thread_id, " ".join(args.prompt), history_len)
        return 0

    if not args.interactive:
        console.print("[#5e5d59]No prompt provided. Starting interactive mode.[/#5e5d59]")

    while True:
        prompt = Prompt.ask("[bold #141413]atlas[/bold #141413]")
        if prompt.strip() in {"/quit", "quit", "exit"}:
            break
        if prompt.strip() == "/help":
            console.print("[#5e5d59]Ask in natural language. Example: Compare vendors 1,2,3 for SKU-001 at quantity 500.[/#5e5d59]")
            continue
        if not prompt.strip():
            continue
        history_len = run_prompt(agent, args.thread_id, prompt, history_len)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
