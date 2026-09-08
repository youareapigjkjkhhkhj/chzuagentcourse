"""Centralized prompt loader for versioning and auditability."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parent.parent
PROMPTS_PATH = BASE_DIR / "prompts" / "prompts.yaml"

_cached_prompts: Dict[str, Any] | None = None


def _load_prompts() -> Dict[str, Any]:
    """Load prompts from YAML file."""
    global _cached_prompts
    if _cached_prompts is not None:
        return _cached_prompts

    try:
        import yaml
    except ImportError:
        raise ImportError("PyYAML is required for prompt loading. pip install pyyaml")

    if not PROMPTS_PATH.exists():
        raise FileNotFoundError(f"Prompts file not found: {PROMPTS_PATH}")

    with open(PROMPTS_PATH, "r", encoding="utf-8") as f:
        _cached_prompts = yaml.safe_load(f)

    return _cached_prompts


def get_prompt(key: str, **kwargs: Any) -> str:
    """
    Get a prompt template by key and optionally format with kwargs.
    Keys use dot notation: e.g. 'router.template', 'crop_agent.template'
    """
    data = _load_prompts()
    keys = key.split(".")
    cursor: Any = data
    for k in keys:
        cursor = cursor.get(k)
        if cursor is None:
            raise KeyError(f"Prompt key not found: {key}")

    if not isinstance(cursor, str):
        raise ValueError(f"Prompt value for '{key}' is not a string")

    if kwargs:
        return cursor.format(**kwargs)
    return cursor


def get_prompt_version() -> str:
    """Return the current prompts version for audit."""
    data = _load_prompts()
    return str(data.get("version", "unknown"))
