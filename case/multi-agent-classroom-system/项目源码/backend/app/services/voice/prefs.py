"""一次合成/一次会话要用哪套参数（P2-A5 / F2-11「选中的音色全局生效」）。

**音色是谁定的**，优先级从高到低 —— 每一级都有它存在的理由：

1. 调用方显式给的 `voiceId`（接口的 body / 查询参数）—— 试听某一张卡片时用；
2. 设置页的 `teacherVoiceId` —— 用户刚刚点下的决定，覆盖它是不可接受的；
3. 老师角色绑定的音色（`agent_roles.voice_profile_id`）—— 种子里绑的那一个，
   设置页从没被打开过时（以及换过库、设置被清掉时）由它说了算；
4. 库里第一个配好音色 ID 的音色 —— 兜底，免得上面三级全落空时整个语音不可用。

**第 1 级与第 2~4 级的判据不同**，这是刻意的：显式指定的音色即使还没配上游
音色 ID 也原样返回（让 `synthesize_beat` 报「这个音色还没有配置上游音色 ID」），
而**推导**出来的候选必须已经配好 —— 用户没说要用哪个，那就不能替他挑一个
用不了的回来，然后报一句他看不懂的错。

两个音色池的桥接也在这里（`realtime_voice_id`）：TTS 2.0 池与实时语音池
互不通用（见 models/voice_profile.py），而设置页里选的是**老师**、不是音色 ID。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from flask import current_app

from app.extensions import db
from app.models import AgentRole, VoiceProfile
from app.services.voice.assets import VoiceSettings, glossary_for, settings_for

#: 「语调起伏」三档 → 合成参数里的 tone 标签。
#:
#: `natural` 映射成空串而不是 `"natural"`：空是「不调整」，也正是 P2 之前所有
#: 资产的默认值。这样默认档位算出来的缓存键与历史资产一致，不会凭空重合成一遍。
TONE_BY_INTONATION: dict[str, str] = {
    "flat": "flat",
    "natural": "",
    "expressive": "expressive",
}

#: 默认（未调整）倍速。等于它时按「用户没动过滑杆」处理，见 `narration_settings`。
DEFAULT_SPEED = 1.0

#: 读不到设置时的兜底档位。
_FALLBACK_INTONATION = "natural"


@dataclass(frozen=True)
class VoicePrefs:
    """设置页上与语音有关的几项，**一次读齐**。

    拆成几个函数各读一次的话，一次整课合成会对 settings_kv 与 voice_profiles
    各查好几遍（`narration_settings` 里三处都要用），而它们在同一次合成里必须是
    同一份快照 —— 中间被设置页改了，这一课的每句话就会是不同的参数。
    """

    voice_id: str = ""
    speed: float = DEFAULT_SPEED
    intonation: str = _FALLBACK_INTONATION
    asr_enabled: bool = True

    @property
    def tone(self) -> str:
        return TONE_BY_INTONATION.get(self.intonation, "")


def current_prefs() -> VoicePrefs:
    """当前设置页上的语音偏好。

    **局部 import 设置服务**：它会拉进模型层，而本模块要在 WS 线程、
    后台合成线程里被反复调到，导入链浅一点好排查。
    """
    from app.services import settings_service

    data: Mapping[str, Any] = settings_service.get_voice()
    try:
        speed = float(data.get("speed") or DEFAULT_SPEED)
    except (TypeError, ValueError):  # pragma: no cover - 写入侧已经校验过
        speed = DEFAULT_SPEED
    return VoicePrefs(
        voice_id=str(data.get("teacherVoiceId") or "").strip(),
        speed=speed,
        intonation=str(data.get("intonation") or _FALLBACK_INTONATION),
        asr_enabled=bool(data.get("asrEnabled", True)),
    )


# --- 音色 ---


def tone_of(value: str) -> str:
    """前端给的「语调起伏」档位 → 合成参数。

    认不出来的档位原样传下去（上游不认就当没调整），但 `natural` **必须**
    换成空串：接口的 `tone` 字段与设置页的 `intonation` 说的是同一件事，
    同一个档位算出两个不同的缓存键，就会把同一段话合成两遍。
    """
    text = str(value or "").strip()
    if not text:
        return ""
    return TONE_BY_INTONATION.get(text, text)


def teacher_voice_id() -> str:
    """老师角色绑定的音色 ID。角色种子里写着，没有就空串。"""
    role = (
        AgentRole.query.filter_by(role="teacher")
        .order_by(AgentRole.sort_order, AgentRole.id)
        .first()
    )
    return str(role.voice_profile_id or "") if role is not None else ""


def voice_profile(voice_id: str = "") -> VoiceProfile | None:
    """定下这一次用哪个音色档。找不到返回 None（调用方据此走降级）。

    返回类型是「可能没有」而不是抛异常：语音是下游能力，
    一个音色都没配好不该让接口 500，而该让清单/播放器显示「未合成」。
    """
    explicit = str(voice_id or "").strip()
    if explicit:
        # 显式指定的：**不检查 configured**，理由见模块 docstring
        return db.session.get(VoiceProfile, explicit)

    for candidate in (current_prefs().voice_id, teacher_voice_id()):
        profile = db.session.get(VoiceProfile, candidate) if candidate else None
        if profile is not None and _server_side(profile):
            return profile

    return (
        VoiceProfile.query.filter(
            VoiceProfile.provider != "browser", VoiceProfile.voice_type != ""
        )
        .order_by(VoiceProfile.id)
        .first()
    )


def _server_side(profile: VoiceProfile) -> bool:
    """这个音色能不能在服务端合成。

    `browser` 是「设备自己发声」那一档（F2-8 的降级路），合成要交给前端
    `speechSynthesis`，服务端拿着它的 id 去调 TTS 只会得到 InvalidSpeaker。
    """
    return profile.provider != "browser" and bool(profile.voice_type)


def narration_settings(
    course: Any = None,
    *,
    voice_id: str = "",
    speed: float | None = None,
    tone: str | None = None,
    glossary: bool = True,
) -> VoiceSettings:
    """合成一段讲稿要的那套参数：音色 + 语速 + 语调 + 课程纠音表。

    `speed` 的三个来源要说清楚，否则「我明明在设置里调到 1.2，怎么没变」：

    - 调用方传了就用它（接口支持 `?speed=`）；
    - 没传时读设置页；**读到的正好是 1.0 就当作「没调过」**，
      把语速交给音色自己的 `speech_rate`（陆老师讲得快、顾老师慢一点，
      那是音色的属性）。否则默认值 1.0 会把每个音色的个性抹平。
    - 音色不存在时返回**空壳** `VoiceSettings()`：`usable` 为假，
      调用方据此走降级，而不是拿一个假音色去合成。
    """
    profile = voice_profile(voice_id)
    if profile is None:
        return VoiceSettings()

    prefs = current_prefs()
    resolved: float | None = prefs.speed if speed is None else float(speed)
    if resolved == DEFAULT_SPEED:
        resolved = None  # 见 docstring 的第二条

    pronunciation: dict[str, str] = {}
    if glossary and course is not None:
        pronunciation = dict(glossary_for(course).get("pronunciation") or {})

    return settings_for(
        profile,
        speed=resolved,
        tone=prefs.tone if tone is None else tone_of(tone),
        pronunciation=pronunciation,
    )


# --- 实时语音 ---


def realtime_voice_id(voice_id: str = "", *, role_code: str = "teacher") -> str:
    """实时语音池里的音色 ID。

    两个池子不通用，而设置页选的是**老师**（TTS 池的音色档），
    所以这里拿音色档的名字回查种子表，换出同一个人的实时池音色 ID
    （`VOLC_REALTIME_VOICE_*`）。换不出来返回空串，由调用方决定怎么办。
    """
    from app.seeds.voices import BUILTIN_VOICES

    profile = db.session.get(VoiceProfile, str(voice_id or "").strip() or _role_profile_id(role_code))
    name = profile.name if profile is not None else ""
    for item in BUILTIN_VOICES:
        if str(item["name"]) == name:
            return str(current_app.config.get(str(item["realtime_env_key"]), "") or "").strip()
    return ""


def _role_profile_id(role_code: str) -> str:
    """这个角色该用哪个音色档。老师听设置页的，其他角色听自己绑的。"""
    code = str(role_code or "").strip()
    if not code or code == "teacher":
        return current_prefs().voice_id or teacher_voice_id()
    role = AgentRole.query.filter_by(code=code).first()
    return str(role.voice_profile_id or "") if role is not None else ""


def realtime_pool() -> dict[str, str]:
    """实时池里本项目认得的全部音色 `{显示名: 音色 ID}`（配置注入）。"""
    from app.seeds.voices import voice_pool

    return {name: voice_id for name, voice_id in voice_pool("realtime").items() if voice_id}


def pick_realtime_voice(requested: str = "", *, role_code: str = "teacher") -> str:
    """前端传的音色 ID 要**在配置认得的那几个里**才认。

    浏览器可以随便填一个字符串上来。它不是凭据（拿不到别人的账号），
    但让客户端指定任意上游资源 ID 是没必要的口子 —— 认不出来就退回默认音色。
    """
    wanted = str(requested or "").strip()
    if wanted and wanted in set(realtime_pool().values()):
        return wanted
    return realtime_voice_id(role_code=role_code)


def asr_enabled() -> bool:
    """设置页的「允许语音发言」开关（P0 就有的那一项，P2 起才真的管用）。

    缺这个键按**开**处理：它是随 P0 一起落的设置，老库里没有也不该突然禁言。
    """
    value = current_prefs().asr_enabled
    return bool(value)


# --- Provider ---


def tts_provider(name: str = ""):
    """当前该用的合成服务商。没配好会抛 40201（业务层用 current_* 那一组）。"""
    from app.services.provider_registry import get_registry

    return get_registry().current_tts(name or None)


def tts_provider_or_none(name: str = ""):
    """同上，但没配好时返回 None 而不是抛异常。

    给**清单**用：播放器要知道「这一句现在有没有声音」，答案里本来就包含
    「压根没配 TTS」这一种。抛 40201 的话，前端连清单都拿不到，
    只能显示一个空白播放器 —— 而它恰恰要在这种时候显示纯文字。"""
    from app.common.errors import AppError

    try:
        return tts_provider(name)
    except AppError:
        return None


def asr_provider(name: str = ""):
    from app.services.provider_registry import get_registry

    return get_registry().current_asr(name or None)


def realtime_provider(name: str = ""):
    from app.services.provider_registry import get_registry

    return get_registry().current_realtime(name or None)


__all__ = [
    "DEFAULT_SPEED",
    "TONE_BY_INTONATION",
    "VoicePrefs",
    "asr_enabled",
    "current_prefs",
    "narration_settings",
    "pick_realtime_voice",
    "realtime_pool",
    "realtime_voice_id",
    "teacher_voice_id",
    "tone_of",
    "tts_provider",
    "tts_provider_or_none",
    "voice_profile",
]
