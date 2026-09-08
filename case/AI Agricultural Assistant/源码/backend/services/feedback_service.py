"""Feedback service - stores user quality ratings for metrics."""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
FEEDBACK_PATH = DATA_DIR / "feedback_log.json"
FEEDBACK_TMP = DATA_DIR / "feedback_log_tmp.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
_lock = threading.Lock()


def record_feedback(request_id: str, feedback: str, source: str = "chat") -> None:
    """
    Record user feedback (positive/negative) for a request.
    source: "chat" | "image"
    """
    entry = {
        "request_id": request_id,
        "feedback": feedback,  # "positive" | "negative"
        "source": source,
        "timestamp": datetime.utcnow().isoformat(),
    }
    with _lock:
        try:
            data = []
            if FEEDBACK_PATH.exists():
                with open(FEEDBACK_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if not isinstance(data, list):
                        data = []
            data.append(entry)
            with open(FEEDBACK_TMP, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            FEEDBACK_TMP.replace(FEEDBACK_PATH)
        except Exception as e:
            print(f"[FEEDBACK] Failed to write: {e}")


def get_feedback_log() -> List[dict]:
    """Read all feedback entries."""
    with _lock:
        try:
            if not FEEDBACK_PATH.exists():
                return []
            with open(FEEDBACK_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []
