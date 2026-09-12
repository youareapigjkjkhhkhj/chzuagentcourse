"""离线 Provider 的行为测试（AGENTS.md §23）。

Mock 不是「随便返回点什么」——P1~P6 的离线测试全都长在它上面，
所以它的输出必须**结构合法且确定**：JSON 能被解析、WAV 能被播放、
中间结果与终稿的语义清楚地分开。这些性质一旦破了，
后面每个阶段的测试都会跟着变得不可信。
"""

from __future__ import annotations

import json
import struct

import pytest

pytestmark = pytest.mark.unit


# --- 文本 ---


def test_mock_llm_is_deterministic(app):
    from app.providers.llm.mock import MockLLM

    with app.app_context():
        provider = MockLLM()
        messages = [{"role": "user", "content": "光合作用是什么"}]
        first = provider.chat(messages)
        second = provider.chat(messages)

    assert first.text == second.text
    assert provider.configured is True
    assert first.provider == "mock"


def test_mock_llm_fills_json_schema(app):
    """P1 的课程生成是「一次生成结构化 JSON」，Mock 必须真的能产出合法 JSON。"""
    from app.providers.llm.mock import MockLLM

    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "pages": {
                "type": "array",
                "minItems": 3,
                "items": {
                    "type": "object",
                    "properties": {"heading": {"type": "string"}, "index": {"type": "integer"}},
                },
            },
            "level": {"type": "string", "enum": ["入门", "进阶"]},
        },
    }

    with app.app_context():
        result = MockLLM().chat([{"role": "user", "content": "出个大纲"}], json_schema=schema)

    payload = json.loads(result.text)
    assert isinstance(payload["title"], str)
    assert len(payload["pages"]) == 3
    assert isinstance(payload["pages"][0]["index"], int)
    assert payload["level"] == "入门"


def test_mock_llm_stream_splits_into_multiple_chunks(app):
    from app.providers.llm.mock import MockLLM

    with app.app_context():
        chunks = list(MockLLM().chat_stream([{"role": "user", "content": "讲一下光合作用"}]))

    assert len(chunks) > 1, "流式演示需要「多块」，一块到底等于没流"
    assert "".join(chunks)


def test_mock_llm_records_calls_for_assertions(app):
    """上游测试要能断言「提示词里有没有带上材料分隔符」。"""
    from app.providers.llm.mock import MockLLM

    with app.app_context():
        provider = MockLLM()
        provider.chat([{"role": "user", "content": "你好"}])

    assert provider.calls[-1]["messages"][-1]["content"] == "你好"


# --- 语音合成 ---


def test_mock_tts_returns_a_playable_wav(app):
    """浏览器要能真的把它播出来，前端才不用为 Mock 模式写特例。"""
    from app.providers.tts.mock import MockTTS

    with app.app_context():
        result = MockTTS().synthesize("光合作用发生在叶绿体。")

    assert result.audio[:4] == b"RIFF"
    assert result.audio[8:12] == b"WAVE"
    # data 块的声明长度必须和真实字节数一致，否则播放器会当成坏文件
    declared = struct.unpack("<I", result.audio[40:44])[0]
    assert declared == len(result.audio) - 44
    assert result.duration_ms > 0
    assert result.fmt == "wav"


def test_mock_tts_duration_follows_text_length(app):
    from app.providers.tts.mock import MockTTS

    with app.app_context():
        provider = MockTTS()
        short = provider.synthesize("短句。")
        long = provider.synthesize("这是一段明显更长的讲解文本，用来验证时长随字数增长。")

    assert long.duration_ms > short.duration_ms


def test_mock_tts_speed_changes_duration(app):
    from app.providers.tts.mock import MockTTS

    with app.app_context():
        provider = MockTTS()
        normal = provider.synthesize("同样的文本，不同的语速。")
        faster = provider.synthesize("同样的文本，不同的语速。", speed=2.0)

    assert faster.duration_ms < normal.duration_ms


def test_mock_tts_stream_yields_more_than_one_chunk(app):
    from app.providers.tts.mock import MockTTS

    with app.app_context():
        chunks = list(MockTTS().stream("逐块吐出，才能边合成边播。"))

    assert len(chunks) > 1
    assert b"".join(chunks)[:4] == b"RIFF"


def test_mock_tts_lists_offline_voices(app):
    from app.providers.tts.mock import MockTTS

    with app.app_context():
        voices = MockTTS().list_voices()

    assert len(voices) >= 3
    for voice in voices:
        assert voice.id and voice.name
        assert voice.provider == "mock"
        # 音色 ID 必须是明显的假值，不能长得像真的厂商音色
        assert voice.id.startswith("mock-")


def test_mock_tts_never_estimates_a_marathon(app):
    """离线用例不该因为一段长讲稿产出几十兆静音。"""
    from app.providers.tts.mock import MAX_MOCK_MS, MockTTS

    with app.app_context():
        result = MockTTS().synthesize("很长的讲稿。" * 5000)

    assert result.duration_ms <= MAX_MOCK_MS


# --- 语音识别 ---


def test_mock_asr_transcribes(app):
    from app.providers.asr.mock import MockASR

    with app.app_context():
        provider = MockASR()
        result = provider.transcribe(b"\x00" * 1600)

    assert result.text
    assert result.segments[-1].final is True
    assert provider.calls[-1]["bytes"] == 1600


def test_mock_asr_stream_emits_interim_then_final(app):
    """中间结果的存在，是前端「边听边显示」的前提。"""
    from app.providers.asr.mock import MockASR

    with app.app_context():
        segments = list(MockASR().stream([b"\x00" * 800, b"\x00" * 800]))

    assert segments, "流式识别至少要给出一条结果"
    assert segments[0].final is False, "第一条应当是中间结果"
    assert segments[-1].final is True, "最后一条必须是终稿"
    assert segments[-1].text


# --- 实时语音 ---


def test_mock_realtime_starts_and_closes_a_session(app):
    from app.providers.tts.mock import MockRealtime

    with app.app_context():
        provider = MockRealtime()
        session = provider.start_session(role="student")
        session.send_audio(b"\x00\x01")
        session.send_text("你好")
        session.close()

    assert session.sent == [b"\x00\x01", "你好"]
    assert session.closed is True
    assert provider.sessions == [session]


def test_mock_realtime_lists_its_own_voice_pool(app):
    """实时语音的音色池与 TTS 不通用，Mock 也要体现这一点（名字不同即可）。"""
    from app.providers.tts.mock import MockRealtime

    with app.app_context():
        voices = MockRealtime().list_voices()

    assert len(voices) >= 1
    assert all(v.id.startswith("mock-") for v in voices)
