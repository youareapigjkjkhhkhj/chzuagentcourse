"""LLM 调用层：JSON 校验、失败重试、超时与记账（P1-F4 / P1-12 / AGENTS §4.5）。

这一层是「生成质量」与「账本完整」两条线的交汇点，所以断言分两类：

- 行为：合法输出一次过；不合法**恰好**重试一次并把错误回喂；仍不合法才算失败。
- 记账：无论成败，每一次真正发出去的调用都要在 model_calls 里留下一行 ——
  P5 的成本看板只认这张表，漏记就是系统性少报。
"""

from __future__ import annotations

import json

import pytest

from app.models import ModelCall
from app.providers.base import (
    LLMProvider,
    LLMResult,
    ProbeResult,
    ProviderError,
    ProviderTimeoutError,
)
from app.services.generation.llm import OutputInvalidError, call_json, call_page
from app.services.generation.schema import SchemaInvalid, parse_page, schema_for_kind

pytestmark = pytest.mark.unit


# --- 合法输出 ---


def test_valid_json_is_returned_in_one_attempt(app):
    provider = ScriptedLLM(json.dumps(_page(), ensure_ascii=False))

    call = call_json(provider, _messages(), schema=schema_for_kind("concept"))

    assert call.data["title"] == "3.2 梯度下降法"
    assert call.attempts == 1
    assert len(provider.calls) == 1


def test_tokens_and_model_are_reported_back(app):
    provider = ScriptedLLM(json.dumps(_page(), ensure_ascii=False))

    call = call_json(provider, _messages(), schema=schema_for_kind("concept"))

    assert call.tokens == 300
    assert call.model == "scripted-1"
    assert call.provider == "scripted"
    assert call.latency_ms >= 0


def test_tokens_are_reconstructed_when_upstream_omits_the_total(app):
    """上游只给 prompt/completion 时要自己加 —— 记账不能因为字段缺失就记 0。"""
    provider = ScriptedLLM(
        json.dumps(_page(), ensure_ascii=False),
        usage={"prompt_tokens": 120, "completion_tokens": 80},
    )

    assert call_json(provider, _messages(), schema=schema_for_kind("concept")).tokens == 200


# --- 失败重试（错误回喂）---


def test_invalid_output_is_retried_once_with_the_reason_fed_back(app):
    provider = ScriptedLLM(
        json.dumps({**_page(), "bullets": []}, ensure_ascii=False),
        json.dumps(_page(), ensure_ascii=False),
    )

    call = call_page(provider, _messages(), kind="concept", page_no=7)

    assert call.attempts == 2, "不合法必须重试一次"
    assert call.data["bullets"], "第二次的合法输出要被采用"

    # 回喂的内容：说清楚哪儿不对，并且要求重新输出完整 JSON
    feedback = provider.calls[1]["messages"][-1]["content"]
    assert "bullets" in feedback
    assert "JSON" in feedback


def test_still_invalid_after_one_retry_fails_the_page(app):
    provider = ScriptedLLM(json.dumps({**_page(), "bullets": []}, ensure_ascii=False))

    with pytest.raises(OutputInvalidError) as excinfo:
        call_page(provider, _messages(), kind="concept", page_no=7)

    assert len(provider.calls) == 2, "只重试一次，不是无限重试"
    assert "bullets" in str(excinfo.value)


def test_upstream_failure_is_not_retried(app):
    """上游 502/超时不走「重试一次」那条路 —— 那会平白多等一个超时周期。"""
    provider = ScriptedLLM(error=ProviderTimeoutError("上游超时"))

    with pytest.raises(ProviderTimeoutError):
        call_json(provider, _messages(), schema=schema_for_kind("concept"))

    assert len(provider.calls) == 1


def test_non_app_error_from_the_adapter_becomes_an_upstream_error(app):
    provider = ScriptedLLM(error=RuntimeError("socket exploded"))

    with pytest.raises(ProviderError):
        call_json(provider, _messages(), schema=schema_for_kind("concept"))


# --- 记账（AGENTS §4.5）---


def test_a_successful_call_is_recorded(app):
    provider = ScriptedLLM(json.dumps(_page(), ensure_ascii=False))

    call_json(
        provider,
        _messages(),
        schema=schema_for_kind("concept"),
        job_id="job-1",
        owner_id="user-1",
    )

    row = ModelCall.query.one()
    assert (row.kind, row.provider, row.model) == ("llm", "scripted", "scripted-1")
    assert row.tokens == 300
    assert row.ok is True
    assert row.error_code is None
    assert row.latency_ms >= 0
    assert row.job_id == "job-1"
    assert row.owner_id == "user-1"


def test_every_attempt_is_recorded(app):
    """重试的两次都要记账：第一次的 token 是**真的花掉了**的。"""
    provider = ScriptedLLM(
        json.dumps({**_page(), "bullets": []}, ensure_ascii=False),
        json.dumps(_page(), ensure_ascii=False),
    )

    call_page(provider, _messages(), kind="concept", page_no=7)

    rows = ModelCall.query.order_by(ModelCall.created_at).all()
    assert len(rows) == 2
    assert [row.ok for row in rows] == [False, True]
    assert rows[0].error_code == "schema_invalid"
    assert sum(row.tokens for row in rows) == 600


def test_a_timeout_is_recorded_with_its_own_error_code(app):
    provider = ScriptedLLM(error=ProviderTimeoutError("上游超时"))

    with pytest.raises(ProviderTimeoutError):
        call_json(provider, _messages(), schema=schema_for_kind("concept"))

    row = ModelCall.query.one()
    assert row.ok is False
    assert row.error_code == "timeout"


def test_accounting_failure_does_not_lose_the_page(app, monkeypatch):
    """记账写不进去（例如库被锁死）时，已经花掉的钱当然要报错，
    但不能把这一页**已经生成好的内容**一起丢掉 —— 两者不是一个优先级。

    打的是 `services/usage/ledger.py` 的 `db_write`：P5 起**账本的写入点只有那一处**
    （`generation/llm.py` 只是把数字交给它），所以「写库失败」这个仿真
    也只能打在那里 —— 打在这一层的旧名字上，测试会以「属性不存在」失败，
    而那看起来像是测试写错了，实际是账本换了一条路。
    """
    provider = ScriptedLLM(json.dumps(_page(), ensure_ascii=False))

    def boom(fn):
        raise RuntimeError("database is locked")

    monkeypatch.setattr("app.services.usage.ledger.db_write", boom)

    call = call_json(provider, _messages(), schema=schema_for_kind("concept"))

    assert call.data["title"] == "3.2 梯度下降法"
    assert ModelCall.query.count() == 0


def test_a_runaway_output_is_truncated_before_being_fed_back(app):
    """回喂上一次的输出有用，但一个跑题的 8k 输出会把上下文挤满，
    反而更容易再写错一次。"""
    runaway = "这不是 JSON。" + "废话连篇。" * 1000
    provider = ScriptedLLM(runaway, json.dumps(_page(), ensure_ascii=False))

    call_json(
        provider,
        _messages(),
        schema=schema_for_kind("concept"),
        parse=lambda text: parse_page("concept", text, page_no=7),
    )

    echoed = provider.calls[1]["messages"][-2]["content"]
    assert len(echoed) < 2000, "回喂的上一次输出没有被截断"
    assert "截断" in echoed


def test_the_adapters_error_code_wins_over_the_generic_one(app):
    """记账里的 error_code 是 P5 分组的依据：适配器已经分清是限流还是超时，
    这里就不要把它压成笼统的 upstream_error。"""
    provider = ScriptedLLM(
        error=ProviderError("限流了", details={"ok": False, "error": "rate_limit"})
    )

    with pytest.raises(ProviderError):
        call_json(provider, _messages(), schema=schema_for_kind("concept"))

    assert ModelCall.query.one().error_code == "rate_limit"


# --- 超时（P1-F4：60s 可配，每页独立）---


def test_page_timeout_defaults_to_60_seconds(app):
    provider = ScriptedLLM(json.dumps(_page(), ensure_ascii=False))

    call_json(provider, _messages(), schema=schema_for_kind("concept"))

    assert provider.calls[0]["timeout"] == 60.0


def test_page_timeout_is_configurable(app):
    app.config["GEN_PAGE_TIMEOUT"] = 12.5
    provider = ScriptedLLM(json.dumps(_page(), ensure_ascii=False))

    call_json(provider, _messages(), schema=schema_for_kind("concept"))

    assert provider.calls[0]["timeout"] == 12.5


def test_page_timeout_can_be_overridden_per_call(app):
    provider = ScriptedLLM(json.dumps(_page(), ensure_ascii=False))

    call_json(provider, _messages(), schema=schema_for_kind("concept"), timeout=3)

    assert provider.calls[0]["timeout"] == 3.0


def test_timeout_comes_from_the_environment(app_factory):
    from app.services.generation.llm import page_timeout

    app_factory(env={"GEN_PAGE_TIMEOUT": "45"})
    assert page_timeout() == 45.0


# --- 与页面校验的接合 ---


def test_parse_callback_is_what_decides_validity(app):
    """call_json 不自己解析页面 —— 校验规则只有一份，就在 schema.py。"""
    provider = ScriptedLLM(json.dumps(_page(), ensure_ascii=False))

    call = call_json(
        provider,
        _messages(),
        schema=schema_for_kind("concept"),
        parse=lambda text: parse_page("concept", text, page_no=7),
    )

    assert call.data["pageNo"] == 7
    assert [b["beatId"] for b in call.data["narration"]] == ["p7-b1", "p7-b2", "p7-b3"]


def test_parse_failure_message_reaches_the_model(app):
    provider = ScriptedLLM(
        "这不是 JSON",
        json.dumps(_page(), ensure_ascii=False),
    )

    call_json(
        provider,
        _messages(),
        schema=schema_for_kind("concept"),
        parse=lambda text: parse_page("concept", text, page_no=7),
    )

    assert "JSON" in provider.calls[1]["messages"][-1]["content"]


def test_custom_parse_error_is_not_swallowed(app):
    def parse(_text):
        raise SchemaInvalid("标题太长（超过 40 字）")

    provider = ScriptedLLM("{}", "{}")

    with pytest.raises(OutputInvalidError) as excinfo:
        call_json(provider, _messages(), schema={}, parse=parse)

    assert "标题太长" in str(excinfo.value)


# --- 桩 ---


class ScriptedLLM(LLMProvider):
    """按脚本逐次作答的文本模型。

    比 `MockLLM` 多的正是这一层要验的两件事：能按次序给出**不同**的输出
    （含非法输出），以及把每次调用收到的 `timeout` 记下来。
    """

    def __init__(
        self,
        *replies: str,
        error: Exception | None = None,
        usage: dict | None = None,
        name: str = "scripted",
        model: str = "scripted-1",
    ) -> None:
        super().__init__(name, default_model=model)
        self._replies = list(replies)
        self._error = error
        self._usage = usage or {
            "prompt_tokens": 100,
            "completion_tokens": 200,
            "total_tokens": 300,
        }
        self._index = 0
        self.calls: list[dict] = []

    def chat(
        self,
        messages,
        *,
        model=None,
        temperature=None,
        max_tokens=None,
        json_schema=None,
        timeout=None,
        **options,
    ) -> LLMResult:
        self.calls.append(
            {
                "messages": [dict(m) for m in messages],
                "model": model,
                "jsonSchema": json_schema,
                "timeout": timeout,
            }
        )
        if self._error is not None:
            raise self._error
        # 最后一个回复会被反复使用：测「重试之后仍然不合法」时不用写两遍同样的坏输出
        index = min(self._index, len(self._replies) - 1)
        self._index += 1
        return LLMResult(
            text=self._replies[index] if self._replies else "",
            model=model or self.default_model,
            provider=self.name,
            usage=self._usage,
            finish_reason="stop",
        )

    def test(self) -> ProbeResult:
        return ProbeResult(ok=True, provider=self.name)


def _messages() -> list[dict]:
    return [
        {"role": "system", "content": "你是课程设计专家。"},
        {"role": "user", "content": "为「机器学习入门」生成第 7 页（concept）。"},
    ]


def _page() -> dict:
    """一份**合法**的页面（含每一页都必须有的那一层，见 schema.UNIVERSAL_RULE）。"""
    return {
        "kind": "concept",
        "title": "3.2 梯度下降法",
        "subtitle": "GRADIENT DESCENT — 如何找到最低点",
        "visual": {"type": "diagram", "desc": "梯度下降曲线与最优点"},
        "bullets": [
            {"text": "梯度方向是最陡上升方向，取负即下降"},
            {"text": "学习率决定每一步走多远"},
            {"text": "步长过大会震荡，过小则收敛慢"},
        ],
        "narration": [
            {"text": "我们先看一个直觉：站在山坡上，往哪个方向走下降最快？"},
            {"text": "答案是把梯度取反。"},
            {"text": "学习率则决定了每一步迈多大。"},
        ],
    }
