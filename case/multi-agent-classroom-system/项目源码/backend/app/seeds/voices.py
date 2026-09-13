"""内置音色种子（F0-11）。

3 个音色对应原型设置页的 3 张音色卡。

★ 厂商音色 ID 一律从环境变量读取，代码里零字面量（AGENTS.md §4.1）：
换一个火山账号只需要改 .env，不需要改代码，也不会把 A 账号的音色
带进 B 账号（那会直接 InvalidSpeaker）。

**每位老师要配两个 ID**：TTS 2.0 音色池（`_uranus_bigtts`，课件旁白用）与
实时语音音色池（`_jupiter_bigtts`，全双工对话用）。两个池子互不通用，
拿 TTS 的 ID 去建实时会话会直接 InvalidSpeaker —— 所以这里成对登记，
让「同一个人的两种声音」在同一处可见。
"""

from __future__ import annotations

from typing import Any

from flask import current_app

# env_key 指向承载厂商音色 ID 的环境变量；没配就是空串（诚实留空，不塞占位值）
BUILTIN_VOICES: tuple[dict[str, Any], ...] = (
    {
        "id": "vp_teacher_shen",
        "name": "沈老师",
        "env_key": "VOLC_TTS_VOICE_TEACHER",
        "realtime_env_key": "VOLC_REALTIME_VOICE_TEACHER",
        "gender": "male",
        "style": "沉稳男声 · 适合理工课程",
        "speech_rate": 0,
    },
    {
        "id": "vp_teacher_gu",
        "name": "顾老师",
        "env_key": "VOLC_TTS_VOICE_HISTORY",
        "realtime_env_key": "VOLC_REALTIME_VOICE_HISTORY",
        "gender": "female",
        "style": "知性女声 · 适合文史课程",
        "speech_rate": 0,
    },
    {
        "id": "vp_teacher_lu",
        "name": "陆老师",
        "env_key": "VOLC_TTS_VOICE_SCIENCE",
        "realtime_env_key": "VOLC_REALTIME_VOICE_SCIENCE",
        "gender": "male",
        "style": "活力青年音 · 适合入门科普",
        "speech_rate": 8,
    },
)

VOICE_PROVIDER = "volc_tts"
VOICE_PROVIDER_REALTIME = "volc_realtime"


def voice_pool(kind: str = "tts") -> dict[str, str]:
    """`{显示名: 厂商音色 ID}`，从当前配置里取。

    Provider 的 `list_voices()` 只报「本项目配了哪些」，不报上游全部 ——
    上游没有列音色的接口，而且选音色是教学设计，不是接口能力。
    """
    env_key = "env_key" if kind != "realtime" else "realtime_env_key"
    return {
        str(item["name"]): str(current_app.config.get(item[env_key], "") or "").strip()
        for item in BUILTIN_VOICES
    }


def voice_specs() -> list[dict]:
    """把内置音色展开成可直接落库的字段（音色 ID 取自当前配置）。"""
    specs = []
    for item in BUILTIN_VOICES:
        specs.append(
            {
                "id": item["id"],
                "name": item["name"],
                "provider": VOICE_PROVIDER,
                "voice_type": str(current_app.config.get(item["env_key"], "") or "").strip(),
                "gender": item["gender"],
                "style": item["style"],
                "speech_rate": item["speech_rate"],
                "builtin": True,
            }
        )
    return specs


def voice_id_for(name: str) -> str:
    """按显示名取音色主键，供角色种子引用。"""
    for item in BUILTIN_VOICES:
        if item["name"] == name:
            return item["id"]
    raise KeyError(f"未知内置音色：{name}")


def missing_voice_ids() -> dict[str, list[str]]:
    """还缺厂商音色 ID 的音色，**按两条链路分开报**。

    分开是因为后果不同：缺 TTS ID 是讲稿没人念；缺实时 ID 只是不能语音对话
    （还能打字问答）。合成一句「有 2 个音色未配置」会让人以为整个语音都不能用，
    然后去重配一个本来没问题的东西。
    """
    return {
        kind: [name for name, voice_id in voice_pool(kind).items() if not voice_id]
        for kind in ("tts", "realtime")
    }


__all__ = [
    "BUILTIN_VOICES",
    "VOICE_PROVIDER",
    "VOICE_PROVIDER_REALTIME",
    "missing_voice_ids",
    "voice_id_for",
    "voice_pool",
    "voice_specs",
]
