from abc import ABC, abstractmethod
from typing import Any, TypedDict
from llm.client import llm_client


class AgentState(TypedDict):
    sku: str
    risk_alerts: list[Any]
    demand_forecast: dict | None
    purchase_requisition: dict | None
    negotiation_result: dict | None
    negotiation_transcript: list[Any] | None
    logistics_plan: dict | None
    final_recommendation: dict | None
    preferred_vendor_id: int | None
    requested_quantity: int | None
    initial_message: str | None
    messages: list[dict[str, str]]


class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name
        self.llm = llm_client

    @abstractmethod
    def run(self, state: AgentState) -> AgentState:
        pass

    def _create_messages(
        self, system_prompt: str, user_prompt: str
    ) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _call_llm(self, messages: list[dict[str, str]], json_mode: bool = False) -> str:
        return self.llm.complete(
            messages,
            temperature=0.2,
            max_tokens=900,
            json_mode=json_mode,
        )
