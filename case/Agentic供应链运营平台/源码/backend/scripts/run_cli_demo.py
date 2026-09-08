#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen


ROOT_DIR = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT_DIR / "demo"
PORT = int(os.environ.get("DEMO_PORT", "8010"))
BASE_URL = f"http://127.0.0.1:{PORT}"


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, cwd=cwd or ROOT_DIR, env=env, check=True)


def wait_for(url: str, timeout_seconds: int = 30) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urlopen(url) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}")


def capture_screenshot(url: str, output: Path) -> None:
    run(["npx", "agent-browser", "open", url])
    run(["npx", "agent-browser", "wait", "--load", "networkidle"])
    run(["npx", "agent-browser", "set", "viewport", "1440", "1024", "2"])
    run(["npx", "agent-browser", "screenshot", str(output)])


def build_frontend() -> None:
    run(["npm", "run", "build"], cwd=ROOT_DIR / "frontend")


def run_live_results() -> dict:
    sys.path.insert(0, str(ROOT_DIR / "src"))
    from agents.orchestrator import orchestrator

    analysis = orchestrator.run("SKU-001")
    negotiation = orchestrator.run(
        "SKU-001",
        preferred_vendor_id=1,
        requested_quantity=250,
        initial_message="Protect lead time but force a benchmark-beating concession.",
    )
    return {"analysis": analysis, "negotiation": negotiation}


def write_report(results: dict) -> None:
    DEMO_DIR.mkdir(exist_ok=True)
    analysis = results["analysis"]
    negotiation = results["negotiation"]
    final = analysis.get("final_recommendation") or {}
    negotiation_result = negotiation.get("negotiation_result") or {}

    summary = {
        "sku": analysis.get("sku"),
        "risk_count": len(analysis.get("risk_alerts") or []),
        "forecasted_quantity": (analysis.get("demand_forecast") or {}).get("forecasted_quantity"),
        "vendor_id": final.get("vendor_id"),
        "quantity": final.get("quantity"),
        "unit_price": final.get("unit_price"),
        "total_cost": final.get("total_cost"),
        "logistics_cost": final.get("logistics_cost"),
        "delivery_timeline_days": (analysis.get("logistics_plan") or {}).get("delivery_timeline"),
        "savings_vs_benchmark": (analysis.get("negotiation_result") or {}).get("savings_vs_benchmark"),
        "negotiated_price_250_units": negotiation_result.get("negotiated_price"),
        "discount_percent_250_units": (negotiation_result.get("terms_achieved") or {}).get("discount_percent"),
        "transcript_turns_250_units": len(negotiation.get("negotiation_transcript") or []),
    }

    (DEMO_DIR / "cli-demo-summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    (DEMO_DIR / "cli-demo-analysis.json").write_text(
        json.dumps(analysis, indent=2, default=str),
        encoding="utf-8",
    )
    (DEMO_DIR / "cli-demo-negotiation.json").write_text(
        json.dumps(negotiation, indent=2, default=str),
        encoding="utf-8",
    )

    markdown = f"""# CLI Demo Summary

- SKU: `{summary["sku"]}`
- Risk count: `{summary["risk_count"]}`
- Forecasted quantity: `{summary["forecasted_quantity"]}`
- Vendor selected: `{summary["vendor_id"]}`
- Quantity: `{summary["quantity"]}`
- Unit price: `${summary["unit_price"]}`
- Total cost: `${summary["total_cost"]}`
- Logistics cost: `${summary["logistics_cost"]}`
- Delivery timeline: `{summary["delivery_timeline_days"]} days`
- Savings vs benchmark: `{summary["savings_vs_benchmark"]}%`
- Negotiated price for 250 units: `${summary["negotiated_price_250_units"]}`
- Discount for 250 units: `{summary["discount_percent_250_units"]}%`
- Negotiation transcript turns: `{summary["transcript_turns_250_units"]}`
"""
    (DEMO_DIR / "cli-demo-summary.md").write_text(markdown, encoding="utf-8")


def start_backend() -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT_DIR / "src")
    process = subprocess.Popen(
        [
            "uv",
            "run",
            "python",
            "-m",
            "uvicorn",
            "main:app",
            "--app-dir",
            str(ROOT_DIR / "src"),
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
        ],
        cwd=ROOT_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    wait_for(f"{BASE_URL}/api/platform/control-tower")
    return process


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def main() -> int:
    DEMO_DIR.mkdir(exist_ok=True)
    build_frontend()
    results = run_live_results()
    write_report(results)

    backend = start_backend()
    try:
        capture_screenshot(f"{BASE_URL}/", DEMO_DIR / "cli-control-tower.png")
        capture_screenshot(f"{BASE_URL}/workflow", DEMO_DIR / "cli-workflow.png")
        capture_screenshot(f"{BASE_URL}/negotiation", DEMO_DIR / "cli-negotiation.png")
    finally:
        stop_process(backend)

    print("CLI demo artifacts ready in demo/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
