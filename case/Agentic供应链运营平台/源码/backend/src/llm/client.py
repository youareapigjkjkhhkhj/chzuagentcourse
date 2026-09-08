import json
import re
from typing import Optional, Any
from openai import OpenAI
from config import config


class LLMClient:
    def __init__(self):
        self.client = None
        self.model = config.LLM_MODEL

    def _get_client(self) -> OpenAI:
        if self.client is None:
            self.client = OpenAI(
                base_url=config.LLM_BASE_URL,
                api_key=config.NEBIUS_API_KEY,
            )
        return self.client

    def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        response = self._get_client().chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"} if json_mode else None,
        )
        content = response.choices[0].message.content or ""
        return self._extract_json_content(content) if json_mode else content

    def stream_complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ):
        stream = self._get_client().chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def _extract_json_content(self, content: str) -> str:
        cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        if cleaned.startswith("{") and cleaned.endswith("}"):
            return cleaned

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = cleaned[start : end + 1]
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass
        return cleaned


llm_client = LLMClient()
