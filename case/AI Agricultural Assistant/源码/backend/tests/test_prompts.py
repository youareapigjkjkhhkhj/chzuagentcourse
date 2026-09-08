"""Tests for prompt loader."""
import pytest


def test_get_prompt_version():
    from backend.core.prompt_loader import get_prompt_version
    v = get_prompt_version()
    assert v in ("1.0", "unknown")


def test_get_prompt_router():
    from backend.core.prompt_loader import get_prompt
    p = get_prompt(
        "router.template",
        agent_map="- CropAgent: test",
        chat_history="None",
        query="What fertilizer for rice?",
    )
    assert "CropAgent" in p
    assert "What fertilizer for rice?" in p


def test_get_prompt_crop():
    from backend.core.prompt_loader import get_prompt
    p = get_prompt(
        "crop_agent.template",
        chat_history="None",
        query="tomato fertilizer",
    )
    assert "CropAgent" in p
    assert "tomato fertilizer" in p
