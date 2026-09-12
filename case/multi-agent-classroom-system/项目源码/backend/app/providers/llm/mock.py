"""离线文本模型（AGENTS.md §23：无网络、无密钥也必须能跑通全流程）。

它不是「占位符」而是正经的测试替身：
- 完全确定性 —— 同一个输入永远同一个输出，测试不需要宽恕随机性；
- 支持 json_schema —— P1 的课程生成是「一次生成结构化 JSON」，
  没有这条，离线测试就只能测到「调用了」而不是「产出能被解析」；
- 记录调用 —— 上游测试可以直接断言「提示词里有没有带上材料分隔符」。

**要结构化输出时有两条路**（见 `chat`）：
认得出任务的走 `fixture`（造一门完整的课，P1-G2 的离线验收靠它）；
认不出的仍走 `_fill`（照着 Schema 填样例值，P0 的老用例走这条）。
"""

from __future__ import annotations

import json
from typing import Any, Iterator, Mapping, Sequence

from app.providers.base import LLMProvider, LLMResult, ProbeResult
from app.providers.llm import fixture

#: 生成的假文本长度上限，避免离线用例把内存写爆。
_MAX_ECHO = 200

#: 流式分块的最小粒度（字）。短回复也要切成几块，见 chat_stream。
CHUNK_CHARS = 8

_TYPE_SAMPLES: dict[str, Any] = {
    "string": "示例文本",
    "number": 1,
    "integer": 1,
    "boolean": True,
    "null": None,
}


class MockLLM(LLMProvider):
    """确定性文本模型。"""

    def __init__(
        self, name: str = "mock", *, default_model: str = "mock-model", **options: Any
    ) -> None:
        super().__init__(name, configured=True, default_model=default_model, **options)
        #: 最近 N 次调用（messages / model / json_schema），供测试断言提示词
        self.calls: list[dict] = []

    # --- 对话 ---

    def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_schema: Mapping[str, Any] | None = None,
        **options: Any,
    ) -> LLMResult:
        self._record(messages, model, json_schema)
        text = _compose(messages, json_schema)
        return LLMResult(
            text=text,
            model=model or self.default_model,
            provider=self.name,
            usage={
                "prompt_tokens": sum(len(str(m.get("content", ""))) for m in messages),
                "completion_tokens": len(text),
                "total_tokens": 0,
            },
            finish_reason="stop",
        )

    def chat_stream(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_schema: Mapping[str, Any] | None = None,
        **options: Any,
    ) -> Iterator[str]:
        """切成多块吐出。

        它模拟的是「多块」这个**形状**，不是真实 TTS 的分句策略 ——
        所以按长度均分而不是按标点：短回复也必须能分成几块，
        否则流式渲染的测试会退化成「一块到底」而测不出东西。
        """
        text = self.chat(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_schema=json_schema,
            **options,
        ).text
        step = max(len(text) // 4, CHUNK_CHARS)
        for start in range(0, len(text), step):
            yield text[start : start + step]

    def test(self) -> ProbeResult:
        return ProbeResult(
            ok=True,
            latency_ms=0,
            model=self.default_model,
            provider=self.name,
        )

    # --- 内部 ---

    def _record(
        self,
        messages: Sequence[Mapping[str, Any]],
        model: str | None,
        json_schema: Mapping[str, Any] | None,
    ) -> None:
        self.calls.append(
            {
                "messages": [dict(m) for m in messages],
                "model": model or self.default_model,
                "jsonSchema": dict(json_schema) if json_schema else None,
            }
        )

    def describe(self) -> dict:
        info = super().describe()
        info["offline"] = True
        return info


def _compose(
    messages: Sequence[Mapping[str, Any]], json_schema: Mapping[str, Any] | None
) -> str:
    """这次该回什么。

    要 JSON 时先问 `fixture` 认不认得这次调用（认得出的说明是课程生成的某一步，
    它给的是一门像样的课）；认不出再退回 `_fill`（照着 Schema 填样例值）。
    两层都在，是因为「合法 JSON」与「能当课用」是两件事：
    P0 的用例只要前者，P1 的离线验收要后者。
    """
    if json_schema is None:
        return _reply_for(messages)
    data = fixture.answer(messages, json_schema)
    return json.dumps(data if data is not None else _fill(json_schema), ensure_ascii=False)


def _reply_for(messages: Sequence[Mapping[str, Any]]) -> str:
    """把最后一条用户消息回显成一句像样的中文，方便肉眼确认链路。"""
    last = ""
    for message in reversed(list(messages)):
        if message.get("role") == "user":
            last = str(message.get("content", ""))
            break
    head = last.strip().splitlines()[0] if last.strip() else "（空提问）"
    return f"[离线示例] 关于「{head[:_MAX_ECHO]}」的讲解。"


def _fill(schema: Mapping[str, Any] | None) -> Any:
    """按 JSON Schema 造一个合法的样例值。

    P0 只保证「结构合法、能被 json.loads 解析、必填字段齐全」——
    足够让 P1 的生成链路在没有网络时也能端到端跑通。
    """
    if not schema:
        return {}
    if schema.get("enum"):
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        properties = schema.get("properties") or {}
        return {key: _fill(value) for key, value in properties.items()}
    if kind == "array":
        items = schema.get("items")
        count = max(int(schema.get("minItems", 1) or 1), 1)
        return [_fill(items) for _ in range(count)]
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "string")
    return _TYPE_SAMPLES.get(str(kind), "示例文本")


__all__ = ["MockLLM"]
