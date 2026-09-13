"""语音参数解析测试（P2-A5 / F2-11 / P2-G3）。

这一层回答的是「这一次合成/会话用哪个音色、什么语速语调」。它出的错全是
**静默**的，所以断言都往「错了会不会有人发现」上写：

- 挑到一个用不了的音色 → 每句话都合成失败，而界面上只是「没有声音」；
- 语速被默认值抹平 → 用户拖了滑杆，听到的还是原速（陆老师和顾老师的
  默认语速本来就不同，抹平之后三个音色听起来一样快）；
- 参数变了却命中旧缓存 → 换了语调，学生听到的还是上一版的声音。

音色 ID 一律走配置注入（AGENTS §4.1）：这里的 `VOICE_ENV` 就是「换了一个
火山账号」的样子 —— 顾老师两个池子都留空，用来验「推导出来的候选必须能用」。
"""

from __future__ import annotations

import pytest

from app.providers.tts.mock import MockTTS

pytestmark = pytest.mark.unit

VOICE_ENV = {
    "VOLC_TTS_VOICE_TEACHER": "vendor-teacher",
    "VOLC_TTS_VOICE_HISTORY": "",
    "VOLC_TTS_VOICE_SCIENCE": "vendor-science",
    "VOLC_REALTIME_VOICE_TEACHER": "rt-teacher",
    "VOLC_REALTIME_VOICE_HISTORY": "",
    "VOLC_REALTIME_VOICE_SCIENCE": "rt-science",
}

SHEN, GU, LU = "vp_teacher_shen", "vp_teacher_gu", "vp_teacher_lu"


@pytest.fixture()
def seeded(app_factory):
    """一台刚部署好的机器：三个音色 + 教师/学生角色 + 示例课程。"""
    return app_factory(seed=True, env=VOICE_ENV)


def _course(app, course_id: str = "course_demo_ml"):
    from app.extensions import db
    from app.models import Course

    with app.app_context():
        return db.session.get(Course, course_id)


def _glossary_course():
    """一门带补录读音的课 —— 纠音表就是从 `dsl.meta.glossary` 来的（P2-A20）。"""
    from app.extensions import db
    from app.models import Course

    course = Course(title="术语表测试课", topic="卷积", status="ready")
    db.session.add(course)
    db.session.flush()
    course.dsl = {"meta": {"glossary": {"卷积": "juǎn jī"}}}
    db.session.commit()
    return course


# --- 音色四级链路 ---


def test_settings_choice_decides_the_default_voice(seeded):
    """设置页没被打开过时，默认音色就是设置里的那一个（种子：沈老师）。"""
    from app.services.voice import prefs

    with seeded.app_context():
        profile = prefs.voice_profile()

    assert profile is not None and profile.id == SHEN


def test_settings_change_moves_the_voice(seeded):
    """用户在设置页点下陆老师 → 合成必须换嗓子。"""
    from app.services import settings_service
    from app.services.voice import prefs

    with seeded.app_context():
        settings_service.update_voice({"teacherVoiceId": LU})
        assert prefs.voice_profile().id == LU


def test_explicit_voice_wins_over_settings(seeded):
    """显式指定的音色优先于设置页 —— 试听某一张卡片就是这条（P2-A5）。"""
    from app.services.voice import prefs

    with seeded.app_context():
        assert prefs.voice_profile(GU).id == GU


def test_explicit_unconfigured_voice_is_still_returned(seeded):
    """显式指定的音色即使没配上游 ID 也**原样返回**。

    这一条与下面那条是刻意相反的：用户点的是这张卡片，就该让这次合成报
    「这个音色还没有配置上游音色 ID」，而不是悄悄换成另一个人的声音 ——
    那会让人以为「我选了，只是听不出来」。
    """
    from app.services.voice import prefs

    with seeded.app_context():
        profile = prefs.voice_profile(GU)
        assert profile.id == GU
        assert not profile.voice_type, "顾老师在这套配置里没有上游音色 ID"


def test_derived_candidates_skip_unusable_profiles(seeded):
    """设置页选中的音色用不了时，退回老师角色绑定的那一个（沈老师）。

    推导出来的候选**必须已经配好上游 ID**：用户没说要用哪个，就不能替他挑
    一个用不了的回来，然后报一句他看不懂的错。
    """
    from app.services import settings_service
    from app.services.voice import prefs

    with seeded.app_context():
        settings_service.update_voice({"teacherVoiceId": GU})
        profile = prefs.voice_profile()

    assert profile.id == SHEN, "不能停在没配 ID 的顾老师身上"


def test_no_usable_voice_at_all_yields_an_empty_spec(app_factory):
    """一个音色都没配上游 ID：返回空壳，而不是拿一个假音色去合成。"""
    from app.services.voice import prefs

    app = app_factory(
        seed=True,
        env={
            "VOLC_TTS_VOICE_TEACHER": "",
            "VOLC_TTS_VOICE_HISTORY": "",
            "VOLC_TTS_VOICE_SCIENCE": "",
        },
    )
    with app.app_context():
        settings = prefs.narration_settings()

    assert settings.voice_id == ""
    assert not settings.usable


# --- 语速与语调 ---


def test_default_speed_keeps_the_voices_own_rate(seeded):
    """没动过滑杆（1.0）时用音色自己的 `speech_rate`，不把个性抹平。

    陆老师种子里是 8（略快），沈老师是 0 —— 如果 1.0 被当成真语速往下传，
    两个人听起来会一样快。
    """
    from app.services.voice import prefs

    with seeded.app_context():
        lu = prefs.narration_settings(voice_id=LU)
        shen = prefs.narration_settings(voice_id=SHEN)

    assert (lu.rate, lu.speed) == (8, None), "默认档要交给音色自己的语速"
    assert (shen.rate, shen.speed) == (0, None)


def test_explicit_speed_overrides_the_voice(seeded):
    """滑杆动过就按滑杆来：1.5 倍速 → 上游语速 50（量程 ±100）。"""
    from app.services.voice import prefs

    with seeded.app_context():
        settings = prefs.narration_settings(voice_id=SHEN, speed=1.5)

    assert (settings.rate, settings.speed) == (50, 1.5)


def test_settings_speed_is_used_when_the_caller_is_silent(seeded):
    from app.services import settings_service
    from app.services.voice import prefs

    with seeded.app_context():
        settings_service.update_voice({"speed": 1.2})
        settings = prefs.narration_settings(voice_id=SHEN)

    assert (settings.rate, settings.speed) == (20, 1.2)


@pytest.mark.parametrize(
    ("intonation", "tone"),
    [("flat", "flat"), ("natural", ""), ("expressive", "expressive")],
)
def test_intonation_maps_to_the_synthesis_tone(seeded, intonation: str, tone: str):
    """三档语调 → 合成参数。`natural` 映射成空串，历史缓存键因此不变。"""
    from app.services import settings_service
    from app.services.voice import prefs

    with seeded.app_context():
        settings_service.update_voice({"intonation": intonation})
        assert prefs.narration_settings(voice_id=SHEN).tone == tone
        assert prefs.tone_of(intonation) == tone


def test_tone_and_speed_change_the_cache_key(seeded):
    """参数解析的结果必须真的进缓存键 —— 否则调完滑杆听到的是同一段音频。

    这一条把「解析」与「缓存」接在一起验：两处各改各的，正好是那个静默的错。
    """
    from app.services.voice import assets, prefs

    with seeded.app_context():
        beat = assets.Beat(page_no=1, beat_id="p1-b1", text="学习率决定了每一步走多远")
        provider = MockTTS()
        base = assets.spec_hash_of(beat, prefs.narration_settings(voice_id=SHEN), provider=provider)
        faster = assets.spec_hash_of(
            beat, prefs.narration_settings(voice_id=SHEN, speed=1.5), provider=provider
        )
        flatter = assets.spec_hash_of(
            beat, prefs.narration_settings(voice_id=SHEN, tone="flat"), provider=provider
        )

    assert len({base, faster, flatter}) == 3


def test_course_glossary_reaches_the_spec(seeded):
    """课程术语表里的读音要进合成参数与缓存键（P2-A20）。"""
    from app.services.voice import assets, prefs

    with seeded.app_context():
        course = _glossary_course()
        beat = assets.Beat(page_no=1, beat_id="p1-b1", text="卷积是什么")
        with_terms = prefs.narration_settings(course, voice_id=SHEN)
        without = prefs.narration_settings(course, voice_id=SHEN, glossary=False)
        provider = MockTTS()
        hashes = {
            assets.spec_hash_of(beat, with_terms, provider=provider),
            assets.spec_hash_of(beat, without, provider=provider),
        }

    assert with_terms.pronunciation == {"卷积": "juǎn jī"}
    assert without.pronunciation == {}
    assert len(hashes) == 2, "纠音表变了就是另一段音频"


# --- 开关 ---


def test_asr_enabled_follows_the_setting(seeded):
    """设置页的「允许语音发言」开关（P0 就有的那一项，P2 起真的管用）。"""
    from app.services import settings_service
    from app.services.voice import prefs

    with seeded.app_context():
        assert prefs.asr_enabled() is True
        settings_service.update_voice({"asrEnabled": False})
        assert prefs.asr_enabled() is False


def test_asr_enabled_defaults_to_on_when_the_key_is_missing(seeded):
    """老库里没有这个键时按**开**处理：不能因为缺一个设置就把学生禁言。"""
    from app.extensions import db
    from app.models.settings_kv import KEY_ASR, SettingsKV
    from app.services import settings_service
    from app.services.voice import prefs

    with seeded.app_context():
        settings_service.update_voice({"asrEnabled": False})
        assert prefs.asr_enabled() is False, "先确认这个开关真的关得上"

        row = SettingsKV.query.filter_by(key=KEY_ASR).one()
        db.session.delete(row)
        db.session.commit()
        assert prefs.asr_enabled() is True


# --- 实时语音音色 ---


def test_realtime_voice_follows_the_teacher_pick(seeded):
    """TTS 池与实时语音池不通用：设置页选的是老师，这里换出**同一个人的**实时音色。"""
    from app.services import settings_service
    from app.services.voice import prefs

    with seeded.app_context():
        assert prefs.realtime_voice_id(role_code="teacher") == "rt-teacher"
        settings_service.update_voice({"teacherVoiceId": LU})
        assert prefs.realtime_voice_id(role_code="teacher") == "rt-science"


def test_realtime_voice_for_a_student_role(seeded):
    """学生角色说自己的话，用**它自己**绑的音色，而不是老师那一个。"""
    from app.models import AgentRole
    from app.services.voice import prefs

    with seeded.app_context():
        role = AgentRole.query.filter_by(code="xiaoxiao").one()
        assert role.voice_profile_id == GU, "种子把林晓绑在顾老师上"
        assert prefs.realtime_voice_id(role_code="xiaoxiao") == "", "顾老师没配实时音色 ID"


def test_client_supplied_realtime_voice_must_be_in_the_pool(seeded):
    """前端传的音色 ID 要在配置认得的那几个里才认，认不出来就退回默认。"""
    from app.services.voice import prefs

    with seeded.app_context():
        assert prefs.pick_realtime_voice("rt-science") == "rt-science"
        assert prefs.pick_realtime_voice("volc-some-other-account-voice") == "rt-teacher"
        assert prefs.pick_realtime_voice("") == "rt-teacher"


# --- Provider 解析 ---


def test_tts_provider_or_none_swallows_the_missing_key(app_factory):
    """没配 Key 的 List 版返回 None 而不是抛 40201。

    清单要能回答「这一句现在有没有声音」，而「压根没配 TTS」正是答案之一；
    抛异常会让前端连清单都拿不到，只剩一个空白播放器。
    """
    from app.providers.base import ProviderNotConfiguredError
    from app.services.provider_registry import get_registry
    from app.services.voice import prefs

    # 配了 Key 但缺别的字段 —— 真服务商在这台机器上就是「用不了」
    app = app_factory(seed=True, env={**VOICE_ENV, "VOLC_TTS_API_KEY": "half-configured"})
    with app.app_context():
        get_registry().register(_UnconfiguredTTS())
        assert prefs.tts_provider_or_none() is None
        with pytest.raises(ProviderNotConfiguredError) as excinfo:
            prefs.tts_provider()
    assert excinfo.value.code == 40201


def test_mock_tts_is_the_default_when_nothing_is_configured(seeded):
    """一个 Key 都没配时落到离线替身：无网络也起得来（AGENTS §23）。"""
    from app.services.voice import prefs

    with seeded.app_context():
        provider = prefs.tts_provider_or_none()

    assert provider is not None and provider.name == "mock"


class _UnconfiguredTTS(MockTTS):
    """占住真服务商的名字，但没配好 —— 用来验 40201 那条路。"""

    name = "volc_tts"

    @property
    def configured(self) -> bool:
        return False

    def missing_config(self) -> list[str]:
        return ["API Key"]
