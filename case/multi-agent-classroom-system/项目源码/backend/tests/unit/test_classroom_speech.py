"""课堂里「非讲稿」发言的语音（P3-A5）。

这一层要防的错**全是静默的**：合成失败不抛的话没人知道为什么这一句突然没声，
抛了的话一条答疑就把整堂课顶掉。所以断言分两半写：

- **成了的时候**：真的给出一段能播的音频（不是空串、不是「清单里有这一条」
  却没有文件），并且同一句话不合成第二遍（老师把同一句话答两遍是常事）。
- **不成的时候**：一个空 dict、不抛、不留半截状态 —— 调用方拿它就知道
  「这条按纯文字走」。上游挂了、没配音色、压根没配 TTS，三种都得走到这里。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.providers.base import UpstreamError
from app.providers.tts.mock import MockTTS

pytestmark = pytest.mark.unit

VOICE_ENV = {
    "VOLC_TTS_VOICE_TEACHER": "vendor-teacher-voice-id",
    "VOLC_TTS_VOICE_HISTORY": "vendor-history-voice-id",
    "VOLC_TTS_VOICE_SCIENCE": "vendor-science-voice-id",
}

#: 一句像样的答疑（长度要够长，短句在 Mock 下会撞上时长上限）。
ANSWER = "归一化是为了让每个特征的尺度一致，否则梯度的方向会被量纲大的特征带偏。"


@pytest.fixture()
def seeded(app_factory):
    """一台灌过种子的机器 + 三个音色（音色 ID 走配置注入）。"""
    return app_factory(seed=True, env=VOICE_ENV)


def _teacher_voice_id(app) -> str:
    from app.models import VoiceProfile

    with app.app_context():
        return VoiceProfile.query.filter_by(name="沈老师").one().id


# --- 配得上声音 ---


def test_an_answer_gets_a_playable_url_and_its_length(seeded):
    """答疑当场合成一段音频：给出 URL，也给出**时长**。

    时长不是附带信息：课堂的节奏按它计时（`runtime._speak_ms`），少一个数
    就会按字数估 —— 估出来的值和真音频差得越多，老师的话被截得越早。
    """
    from app.services.classroom import speech

    with seeded.app_context():
        entry = speech.answer_audio(ANSWER)

        voice_id = _teacher_voice_id(seeded)
        assert entry["url"].startswith(f"/api/voice/voices/{voice_id}/preview")
        assert "?v=" in entry["url"], "换句话合成之后要能刷新浏览器缓存"
        assert entry["durationMs"] > 0


def test_the_audio_is_really_there_and_is_not_a_lecture_asset(seeded):
    """音频要**真的落在盘上**，而且不落 `audio_assets`。

    前半句防的是「返回了一个 404 的 URL」—— Mock 只给结构，磁盘才是真相。
    后半句是这一层的取舍：那张表的 `course_id` 指向真课，而一次答疑属于
    这一堂课，挂不进任何一门课的行里。
    """
    from app.models import AudioAsset
    from app.services.classroom import speech
    from app.services.voice import assets

    with seeded.app_context():
        speech.answer_audio(ANSWER)

        directory = Path(seeded.config["AUDIO_DIR"]) / assets.PREVIEW_OWNER
        assert list(directory.glob("*.wav")), "答疑音频应该和试听放在同一个目录下"
        assert AudioAsset.query.count() == 0


def test_the_same_sentence_is_only_synthesized_once(seeded):
    """同一句话答两遍（两个学生问同一个问题）只花一次的钱。

    记账口径就是判据：`record_usage` 只在**真的调了上游**那一次写。
    命中缓存还记一笔的话，「花了多少钱」与「合成过几次」从此对不上。
    """
    from app.models import UsageRecord
    from app.services.classroom import speech

    with seeded.app_context():
        first = speech.answer_audio(ANSWER)
        second = speech.answer_audio(ANSWER)

        assert first["url"] == second["url"]
        assert UsageRecord.query.filter_by(ref_id=f"classroom:{_teacher_voice_id(seeded)}").count() == 1


# --- 配不上就退到纯文字 ---


def test_a_blank_line_costs_nothing(seeded):
    """空白文本不合成：合成一段空音频只会得到一段静音，还要按次计费。"""
    from app.services.classroom import speech

    with seeded.app_context():
        assert speech.answer_audio("   \n  ") == {}
        assert speech.answer_audio("") == {}
        assert speech.answer_audio(None) == {}


def test_a_broken_upstream_degrades_instead_of_raising(seeded, monkeypatch):
    """上游挂了 → 空 dict，**不抛**。

    答疑已经在一次 LLM 调用上花掉几秒，上游 TTS 再抖一次不该把答案本身弄没：
    `runtime._answer` 拿到空 dict 就按「这条没有音频」走，话照说、记录照留。
    """
    from app.services.classroom import speech
    from app.services.voice import prefs

    def _boom(*args, **kwargs):
        raise UpstreamError("上游挂了")

    with seeded.app_context():
        monkeypatch.setattr(prefs, "tts_provider", _boom)

        assert speech.answer_audio(ANSWER) == {}


def test_no_voice_at_all_degrades_instead_of_raising(app_factory):
    """一个音色都没配好的机器上（没灌种子）：也是空 dict。

    这条不是重复上一条：上面走的是「上游挂了」，这条走的是「压根没有嗓子可借」，
    连 Provider 都不该被碰到 —— 抛 40201 出来的话，第一次部署的人开一堂课，
    教师答疑会整条失败，而他只是还没选音色。
    """
    from app.services.classroom import speech

    app = app_factory()
    with app.app_context():
        assert speech.answer_audio(ANSWER) == {}


def test_voice_disabled_by_config_degrades_instead_of_raising(app_factory):
    """`VOICE_ENABLED=false`（P2-G3 的那条开关）：同样是空 dict。

    课堂**不因为语音关掉就不能上** —— 退到纯文字讲稿与文字答疑，
    与 `CLASSROOM_WS=false` 退到手动翻页是同一条口径。
    """
    from app.services.classroom import speech

    app = app_factory(seed=True, env={**VOICE_ENV, "VOICE_ENABLED": "false"})
    with app.app_context():
        assert speech.answer_audio(ANSWER) == {}


def test_a_very_long_answer_is_cut_before_it_reaches_the_upstream(seeded, monkeypatch):
    """超长文本在出门前就截断：上游有长度上限，而它按字计费。"""
    from app.services.classroom import speech
    from app.services.voice import prefs

    seen: list[str] = []
    provider = MockTTS()

    def _spy(text, **options):
        seen.append(text)
        return provider.synthesize(text, **options)

    monkeypatch.setattr(provider, "synthesize", _spy)

    with seeded.app_context():
        monkeypatch.setattr(prefs, "tts_provider", lambda *a, **k: provider)

        speech.answer_audio("很长的答疑。" * 500)

        assert seen and len(seen[0]) <= speech.MAX_CHARS


def test_the_answer_is_spoken_with_the_teachers_voice(seeded):
    """答疑用的必须是**讲稿那把嗓子**。

    判据落在文件名上：试听音频是按 `{音色档 id}_{规格哈希}` 命名的，
    叫得上号才说明借的是老师那一个音色档。对不上就会变成「上课一个声音、
    答疑另一个声音」，而且不报错 —— 这正是这一层最该拦住的一类错。
    """
    from app.services.classroom import speech
    from app.services.voice import assets

    with seeded.app_context():
        speech.answer_audio(ANSWER)

        directory = Path(seeded.config["AUDIO_DIR"]) / assets.PREVIEW_OWNER
        names = [item.name for item in directory.glob("*.wav")]
        assert names and all(name.startswith(f"{_teacher_voice_id(seeded)}_") for name in names)
