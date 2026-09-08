"""Metrics endpoints - feedback, usage, and quality aggregation."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.services.feedback_service import get_feedback_log
from backend.services.history_service import LOG_PATH

router = APIRouter(prefix="/metrics", tags=["Metrics"])


def _load_query_log() -> List[dict]:
    """Load query_log.json safely."""
    try:
        if not LOG_PATH.exists():
            return []
        import json
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


@router.post("/feedback")
def submit_feedback(
    request_id: str = Query(...),
    feedback: str = Query(...),
    source: str = Query("chat"),
):
    """
    Submit user feedback (positive/negative) for a response.
    Query params: request_id, feedback, source (optional).
    """
    if feedback not in ("positive", "negative"):
        raise HTTPException(400, "feedback must be 'positive' or 'negative'")
    if source not in ("chat", "image"):
        source = "chat"
    from backend.services.feedback_service import record_feedback
    record_feedback(request_id, feedback, source)
    return {"status": "recorded", "request_id": request_id}


@router.get("/usage")
def get_usage_metrics(days: int = Query(7, ge=1, le=365)) -> Dict[str, Any]:
    """
    Usage metrics from query_log.
    Returns agent distribution, query types, and daily counts.
    """
    logs = _load_query_log()
    if not logs:
        return {
            "total_requests": 0,
            "by_agent": {},
            "by_type": {},
            "by_day": {},
            "days": days,
        }

    cutoff_date = (datetime.utcnow() - timedelta(days=days)).date()
    agent_counts: Counter = Counter()
    type_counts: Counter = Counter()
    day_counts: Dict[str, int] = defaultdict(int)
    total = 0

    for entry in logs:
        ts_str = entry.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            ts_date = ts.date() if hasattr(ts, "date") else ts
            if ts_date < cutoff_date:
                continue
            day_key = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
        except Exception:
            continue

        agent = entry.get("agent", "unknown")
        agent_counts[agent] += 1

        qtype = entry.get("type", "text")
        type_counts[qtype] += 1

        day_counts[day_key] += 1
        total += 1

    return {
        "total_requests": total,
        "by_agent": dict(agent_counts),
        "by_type": dict(type_counts),
        "by_day": dict(sorted(day_counts.items())),
        "days": days,
    }


@router.get("/quality")
def get_quality_metrics(days: int = Query(30, ge=1, le=365)) -> Dict[str, Any]:
    """
    Quality metrics from feedback_log.
    Returns satisfaction rate and counts.
    """
    feedback = get_feedback_log()
    if not feedback:
        return {
            "total_responses": 0,
            "positive": 0,
            "negative": 0,
            "satisfaction_rate": None,
            "days": days,
        }

    cutoff_date = (datetime.utcnow() - timedelta(days=days)).date()
    positive = 0
    negative = 0

    for entry in feedback:
        ts_str = entry.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            ts_date = ts.date() if hasattr(ts, "date") else ts
            if ts_date < cutoff_date:
                continue
        except Exception:
            continue

        fb = entry.get("feedback", "")
        if fb == "positive":
            positive += 1
        elif fb == "negative":
            negative += 1

    total = positive + negative
    rate = round(100 * positive / total, 1) if total > 0 else None

    return {
        "total_responses": total,
        "positive": positive,
        "negative": negative,
        "satisfaction_rate": rate,
        "days": days,
    }
