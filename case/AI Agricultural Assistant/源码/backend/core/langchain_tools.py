"""Agent registry - cached to avoid repeated instantiation."""
from __future__ import annotations

from typing import Dict, List, TypeAlias

from backend.agents.crop_agent import CropAgent
from backend.agents.irrigation_agent import IrrigationAgent
from backend.agents.pest_agent import PestAgent
from backend.agents.subsidy_agent import SubsidyAgent
from backend.agents.yield_agent import YieldAgent
from backend.agents.formatter_agent import FormatterAgent

AgentRegistry: TypeAlias = Dict[str, object]

# FormatterAgent must never be selected by router
NON_ROUTABLE_AGENTS = {"FormatterAgent"}

_AGENT_REGISTRY_CACHE: AgentRegistry | None = None


def get_agent_registry() -> AgentRegistry:
    """Return cached agent registry - single instance per process."""
    global _AGENT_REGISTRY_CACHE
    if _AGENT_REGISTRY_CACHE is None:
        _AGENT_REGISTRY_CACHE = {
            "CropAgent": CropAgent(),
            "PestAgent": PestAgent(),
            "IrrigationAgent": IrrigationAgent(),
            "SubsidyAgent": SubsidyAgent(),
            "YieldAgent": YieldAgent(),
            "FormatterAgent": FormatterAgent(),
        }
    return _AGENT_REGISTRY_CACHE

# Router Metadata
AGENT_DESCRIPTIONS: List[dict] = [
    {
        "name": "CropAgent",
        "description": (
            "General crop management and cultivation advice. "
            "Use for fertilizer selection and dosage, soil preparation, "
            "planting methods, crop growth stages, crop rotation, "
            "and overall best farming practices. "
            "Also use if the query is broad or unclear and needs general guidance."
        ),
    },
    {
        "name": "PestAgent",
        "description": (
            "Pest, disease, or nutrient deficiency diagnosis. "
            "Use when the farmer reports insects, worms, larvae, "
            "leaf spots, fungal or bacterial infection, "
            "yellowing, curling, wilting, discoloration, or damage symptoms. "
            "This agent MUST be selected for image-based crop problems."
        ),
    },
    {
        "name": "IrrigationAgent",
        "description": (
            "Irrigation and water management expert. "
            "Use for watering frequency, irrigation scheduling, "
            "water stress (overwatering or drought), soil moisture, "
            "drip or sprinkler systems, and water-saving practices."
        ),
    },
    {
        "name": "YieldAgent",
        "description": (
            "Yield improvement and productivity analysis. "
            "Use when the farmer mentions low yield, poor harvest, "
            "reduced output, small fruits, fewer tillers, "
            "or asks how to increase crop productivity."
        ),
    },
    {
        "name": "SubsidyAgent",
        "description": (
            "Government subsidy and agricultural scheme information (India-focused). "
            "Use for PM-Kisan, loan support, crop insurance, "
            "drip irrigation subsidy, equipment or machinery grants, "
            "and eligibility for government financial assistance."
        ),
    },
]
