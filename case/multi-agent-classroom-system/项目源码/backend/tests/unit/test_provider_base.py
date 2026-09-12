"""Provider 抽象基类测试（F0-8）。

接口一旦定下来，P1~P6 的所有能力都长在上面，所以这里把契约钉死：
- 抽象方法必须齐全，漏实现要在实例化时就报错，而不是调用时才炸
- 返回值一律是不可变 dataclass，避免调用方意外改到 Provider 的内部状态
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# --- 抽象基类不能被直接实例化 ---


def test_llm_provider_is_abstract():
    from app.providers.base import LLMProvider

    with pytest.raises(TypeError):
        LLMProvider()


def test_tts_provider_is_abstract():
    from app.providers.base import TTSProvider

    with pytest.raises(TypeError):
        TTSProvider()


def test_asr_provider_is_abstract():
    from app.providers.base import ASRProvider

    with pytest.raises(TypeError):
        ASRProvider()


def test_realtime_provider_is_abstract():
    from app.providers.base import RealtimeProvider

    with pytest.raises(TypeError):
        RealtimeProvider()


@pytest.mark.parametrize(
    ("base_name", "missing"),
    [
        ("LLMProvider", "chat"),
        ("LLMProvider", "test"),
        ("TTSProvider", "synthesize"),
        ("TTSProvider", "stream"),
        ("TTSProvider", "list_voices"),
        ("ASRProvider", "transcribe"),
        ("ASRProvider", "stream"),
    ],
)
def test_partial_subclass_cannot_be_instantiated(base_name, missing):
    """只实现了部分抽象方法的子类，必须在实例化时就失败。"""
    from app.providers import base

    parent = getattr(base, base_name)
    methods = {
        name: (lambda self, *a, **kw: None)
        for name in parent.__abstractmethods__
        if name != missing
    }
    partial = type(f"Partial{base_name}{missing}", (parent,), methods)

    with pytest.raises(TypeError):
        partial()


def test_provider_base_exposes_identity_fields():
    """每个 Provider 都要能说清自己是谁 —— 日志与 /api/health 都依赖它。"""
    from app.providers.base import LLMProvider

    for attr in ("name", "kind", "configured"):
        assert hasattr(LLMProvider, attr) or attr in getattr(LLMProvider, "__annotations__", {})


# --- 结果类型 ---


def test_llm_result_is_immutable():
    from dataclasses import FrozenInstanceError

    from app.providers.base import LLMResult

    result = LLMResult(text="光合作用发生在叶绿体", model="m", provider="p")
    with pytest.raises(FrozenInstanceError):
        result.text = "改不了"


def test_llm_result_defaults_are_sane():
    from app.providers.base import LLMResult

    result = LLMResult(text="x")
    assert result.model == ""
    assert result.provider == ""
    assert result.usage == {}
    assert result.finish_reason == ""


def test_probe_result_reports_success():
    from app.providers.base import ProbeResult

    ok = ProbeResult(ok=True, latency_ms=320, model="deepseek-chat", provider="deepseek")
    assert ok.ok is True
    assert ok.error == ""
    assert ok.latency_ms == 320


def test_probe_result_reports_failure():
    from app.providers.base import ProbeResult

    bad = ProbeResult(ok=False, error="401 invalid api key", error_code="unauthorized")
    assert bad.ok is False
    assert bad.latency_ms == 0


def test_tts_result_shape():
    from app.providers.base import TTSResult

    result = TTSResult(audio=b"\x00\x01", fmt="mp3", duration_ms=1200, provider="volc_tts")
    assert result.audio == b"\x00\x01"
    # 默认是空元组而不是空列表：结果对象一旦发出就该是只读的
    assert result.subtitles == ()


def test_voice_shape():
    from app.providers.base import Voice

    voice = Voice(id="zh_male_x", name="沈老师", gender="male", style="沉稳", provider="volc_tts")
    assert voice.gender == "male"
    assert voice.sample_url == ""


def test_asr_segment_shape():
    from app.providers.base import ASRSegment

    seg = ASRSegment(text="光合作用", start_ms=0, end_ms=800, final=True)
    assert seg.final is True
    assert ASRSegment(text="半句").final is False


def test_asr_result_shape():
    from app.providers.base import ASRResult, ASRSegment

    result = ASRResult(text="光合作用是什么", segments=[ASRSegment(text="光合作用", final=True)])
    assert result.text == "光合作用是什么"
    assert len(result.segments) == 1
    assert result.duration_ms == 0


def test_provider_error_hierarchy():
    """Provider 层的异常必须能被上层按类捕获，而不是靠字符串匹配。"""
    from app.common.errors import AppError, UpstreamError
    from app.providers.base import ProviderError, ProviderNotConfiguredError, ProviderTimeoutError

    assert issubclass(ProviderError, AppError)
    assert issubclass(ProviderNotConfiguredError, ProviderError)
    assert issubclass(ProviderTimeoutError, ProviderError)
    assert issubclass(ProviderTimeoutError, UpstreamError)

    assert ProviderNotConfiguredError().code == 40201
    assert ProviderNotConfiguredError().http_status == 400
    assert ProviderTimeoutError().code == 50401
    assert ProviderError().code == 50201
