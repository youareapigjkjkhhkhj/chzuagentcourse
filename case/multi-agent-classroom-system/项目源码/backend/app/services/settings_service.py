"""设置项读写（P0 §4.2）。

设置分两类，形状不同但都是「读要能容忍缺失、写要能拒绝脏值」：
- **单项**（当前服务商、语音、生成参数）存在 `settings_kv`，值是 JSON
- **清单**（音色、角色）来自各自的表

为什么把默认值与取值范围集中在这里，而不是散在接口层：
- P0-C4 要求「读取缺失键时返回默认值而非 null」—— 只有一处知道默认值才做得到
- 前端也要显示范围（滑杆的 min/max），走 /api/capabilities 拿的是同一份常量
- 校验与默认值放在一起，才不会出现「默认值 12 但范围是 8~20，改天有人把默认改成 25」
"""

from __future__ import annotations

from typing import Any

from flask import current_app

from app.common.dbw import db_write
from app.common.errors import ValidationError
from app.extensions import db
from app.models import SettingsKV
from app.models.settings_kv import KEY_ACTIVE_PROVIDER, KEY_ASR, KEY_GENERATION, KEY_VOICE
from app.models.voice_profile import VoiceProfile

# --- 默认值（来自原型 settings.html）---

DEFAULT_VOICE: dict[str, Any] = {
    "teacherVoiceId": "vp_teacher_shen",
    "speed": 1.0,
    "intonation": "natural",
}

#: ASR 开关单独存一份（settings_kv 的 asr 键）：
#: 它管的是「学生能不能用语音发言」，与音色/语速是两件事 ——
#: P2 接语音识别时要读的是它，不该从音色配置里刨。
#: 接口层仍然把两者合成一个对象返回（§4.2 把 ASR 开关挂在 voice 端点下）。
DEFAULT_ASR: dict[str, Any] = {
    "asrEnabled": True,
    "asrBrowserLocal": True,
}

DEFAULT_GENERATION: dict[str, Any] = {
    "pageCount": 12,
    "classmateCount": 3,
    "intensity": "medium",
    "scriptDetail": "detailed",
    "autoIllustration": True,
    "quizPerChapter": True,
    "whiteboard": True,
}

#: 语速：0.5x 慢速朗读 ~ 2.0x 快速复习。超出这个区间听着就不像人话了。
MIN_SPEED = 0.5
MAX_SPEED = 2.0

#: 语调起伏。火山 TTS 的 emotion / pitch 取值映射到这三个档。
INTONATIONS = ("flat", "natural", "expressive")

#: 讨论激烈程度。轮次映射见 P3（低:1 / 适中:2 / 高:3 轮）。
INTENSITIES = ("low", "medium", "high")

#: 讲稿详细程度：影响每页讲稿的字数预算。
SCRIPT_DETAILS = ("concise", "normal", "detailed")


# --- 底层读写 ---


def _read_json(key: str) -> Any:
    row = db.session.get(SettingsKV, key)
    return None if row is None else row.value


def _write_json(key: str, value: Any) -> None:
    """写一项设置。整段替换 —— 调用方负责先合并默认值。"""

    def _work() -> None:
        row = db.session.get(SettingsKV, key)
        if row is None:
            row = SettingsKV(key=key)
            db.session.add(row)
        row.value = value

    db_write(_work)


def _merged(defaults: dict, stored: Any) -> dict:
    """默认值打底、已存的覆盖。

    打底而不是整段替换：规格加了一个新参数之后，老库里没有这个键，
    读出来也该是默认值而不是 null（P0-C4）。
    """
    result = dict(defaults)
    if isinstance(stored, dict):
        result.update({k: v for k, v in stored.items() if k in defaults})
    return result


# --- 生成参数 ---


def get_generation() -> dict:
    return _merged(DEFAULT_GENERATION, _read_json(KEY_GENERATION))


def page_count_limits() -> tuple[int, int]:
    cfg = current_app.config
    return int(cfg.get("MIN_PAGE_COUNT", 8)), int(cfg.get("MAX_PAGE_COUNT", 20))


def classmate_limits() -> tuple[int, int]:
    cfg = current_app.config
    return int(cfg.get("MIN_CLASSMATE_COUNT", 0)), int(cfg.get("MAX_CLASSMATE_COUNT", 5))


def update_generation(payload: Any) -> dict:
    """按字段增量更新生成参数。只认已知字段 —— 拼错的键必须报错。"""
    current = get_generation()
    changes = _validate_generation_payload(payload)

    # 先全部校验再落库：一半字段生效比整段失败更难排查
    current.update(changes)
    _write_json(KEY_GENERATION, current)
    return current


def _validate_generation_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError("请求体必须是一个 JSON 对象")
    if not payload:
        raise ValidationError("请求体为空，没有要修改的设置")

    known = set(DEFAULT_GENERATION)
    unknown = sorted(set(payload) - known)
    if unknown:
        raise ValidationError(
            f"不认识的设置项：{'、'.join(unknown)}；可选：{'、'.join(sorted(known))}"
        )

    changes: dict[str, Any] = {}
    if "pageCount" in payload:
        low, high = page_count_limits()
        changes["pageCount"] = as_int(payload["pageCount"], "课件页数", low, high)
    if "classmateCount" in payload:
        low, high = classmate_limits()
        changes["classmateCount"] = as_int(payload["classmateCount"], "AI 同学数量", low, high)
    if "intensity" in payload:
        changes["intensity"] = _as_choice(payload["intensity"], "讨论激烈程度", INTENSITIES)
    if "scriptDetail" in payload:
        changes["scriptDetail"] = _as_choice(payload["scriptDetail"], "讲稿详细程度", SCRIPT_DETAILS)
    for field in ("autoIllustration", "quizPerChapter", "whiteboard"):
        if field in payload:
            changes[field] = _as_bool(payload[field], field)
    return changes


def generation_limits() -> dict:
    """给 /api/capabilities：前端滑杆的 min/max 与后端校验用的是同一份常量。"""
    page_low, page_high = page_count_limits()
    mate_low, mate_high = classmate_limits()
    return {
        "minPageCount": page_low,
        "maxPageCount": page_high,
        "minClassmateCount": mate_low,
        "maxClassmateCount": mate_high,
        "minSpeed": MIN_SPEED,
        "maxSpeed": MAX_SPEED,
        "intonations": list(INTONATIONS),
        "intensities": list(INTENSITIES),
        "scriptDetails": list(SCRIPT_DETAILS),
    }


# --- 语音 ---


def get_voice() -> dict:
    settings = _merged(DEFAULT_VOICE, _read_json(KEY_VOICE))
    asr = _merged(DEFAULT_ASR, _read_json(KEY_ASR))
    voices = list_voices()
    # 选中的音色被删掉（或库被换过）时回落到默认值，
    # 否则前端会显示「已选中一个不存在的音色」
    known = {voice["id"] for voice in voices}
    if settings["teacherVoiceId"] not in known and voices:
        settings["teacherVoiceId"] = (
            DEFAULT_VOICE["teacherVoiceId"]
            if DEFAULT_VOICE["teacherVoiceId"] in known
            else voices[0]["id"]
        )
    result = {"voices": voices, **settings}
    result.update(asr)
    return result


def update_voice(payload: Any) -> dict:
    """一次请求可能同时改音色与 ASR 开关，落库时按归属拆成两份存。"""
    changes = _validate_voice_payload(payload)

    voice_changes = {k: v for k, v in changes.items() if k in DEFAULT_VOICE}
    asr_changes = {k: v for k, v in changes.items() if k in DEFAULT_ASR}

    if voice_changes:
        voice = _merged(DEFAULT_VOICE, _read_json(KEY_VOICE))
        voice.update(voice_changes)
        _write_json(KEY_VOICE, voice)
    if asr_changes:
        asr = _merged(DEFAULT_ASR, _read_json(KEY_ASR))
        asr.update(asr_changes)
        _write_json(KEY_ASR, asr)

    return get_voice()


def _validate_voice_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError("请求体必须是一个 JSON 对象")
    if not payload:
        raise ValidationError("请求体为空，没有要修改的设置")

    known = set(DEFAULT_VOICE) | set(DEFAULT_ASR)
    unknown = sorted(set(payload) - known)
    if unknown:
        raise ValidationError(
            f"不认识的设置项：{'、'.join(unknown)}；可选：{'、'.join(sorted(known))}"
        )

    changes: dict[str, Any] = {}
    if "teacherVoiceId" in payload:
        voice_id = str(payload["teacherVoiceId"] or "").strip()
        if db.session.get(VoiceProfile, voice_id) is None:
            raise ValidationError(f"音色 {voice_id} 不存在")
        changes["teacherVoiceId"] = voice_id
    if "speed" in payload:
        changes["speed"] = _as_float(payload["speed"], "语速", MIN_SPEED, MAX_SPEED)
    if "intonation" in payload:
        changes["intonation"] = _as_choice(payload["intonation"], "语调起伏", INTONATIONS)
    for field in ("asrEnabled", "asrBrowserLocal"):
        if field in payload:
            changes[field] = _as_bool(payload[field], field)
    return changes


def list_voices() -> list[dict]:
    return [voice.to_dict() for voice in VoiceProfile.query.order_by(VoiceProfile.id).all()]


# --- 当前服务商 ---


def get_active_provider() -> str:
    value = _read_json(KEY_ACTIVE_PROVIDER)
    return value.strip() if isinstance(value, str) else ""


def set_active_provider(provider_id: str) -> None:
    _write_json(KEY_ACTIVE_PROVIDER, provider_id)


# --- 校验小工具 ---


def as_int(value: Any, label: str, low: int, high: int) -> int:
    # bool 是 int 的子类：True 会被当成 1 悄悄通过，这里明确拒掉
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValidationError(f"{label}必须是 {low}~{high} 之间的整数")
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label}必须是 {low}~{high} 之间的整数") from exc
    if not low <= number <= high:
        raise ValidationError(f"{label}必须在 {low}~{high} 之间，收到的是 {number}")
    return number


def _as_float(value: Any, label: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValidationError(f"{label}必须是 {low}~{high} 之间的数字")
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label}必须是 {low}~{high} 之间的数字") from exc
    if not low <= number <= high:
        raise ValidationError(f"{label}必须在 {low}~{high} 之间，收到的是 {number}")
    return number


def _as_choice(value: Any, label: str, choices: tuple[str, ...]) -> str:
    text = str(value or "").strip()
    if text not in choices:
        raise ValidationError(f"{label}只能是 {'、'.join(choices)} 之一，收到的是 {text!r}")
    return text


def _as_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValidationError(f"{field} 必须是布尔值")


__all__ = [
    "DEFAULT_ASR",
    "DEFAULT_GENERATION",
    "DEFAULT_VOICE",
    "INTENSITIES",
    "INTONATIONS",
    "MAX_SPEED",
    "MIN_SPEED",
    "SCRIPT_DETAILS",
    "as_int",
    "classmate_limits",
    "generation_limits",
    "get_active_provider",
    "get_generation",
    "get_voice",
    "list_voices",
    "page_count_limits",
    "set_active_provider",
    "update_generation",
    "update_voice",
]
