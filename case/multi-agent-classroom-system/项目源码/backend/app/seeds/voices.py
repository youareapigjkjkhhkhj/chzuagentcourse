"""内置音色种子（F0-11）。

3 个音色对应原型设置页的 3 张音色卡。

★ 厂商音色 ID 一律从环境变量读取，代码里零字面量（AGENTS.md §4.1）：
换一个火山账号只需要改 .env，不需要改代码，也不会把 A 账号的音色
带进 B 账号（那会直接 InvalidSpeaker）。
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
        "gender": "male",
        "style": "沉稳男声 · 适合理工课程",
        "speech_rate": 0,
    },
    {
        "id": "vp_teacher_gu",
        "name": "顾老师",
        "env_key": "VOLC_TTS_VOICE_HISTORY",
        "gender": "female",
        "style": "知性女声 · 适合文史课程",
        "speech_rate": 0,
    },
    {
        "id": "vp_teacher_lu",
        "name": "陆老师",
        "env_key": "VOLC_TTS_VOICE_SCIENCE",
        "gender": "male",
        "style": "活力青年音 · 适合入门科普",
        "speech_rate": 8,
    },
)

VOICE_PROVIDER = "volc_tts"


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


__all__ = ["BUILTIN_VOICES", "VOICE_PROVIDER", "voice_id_for", "voice_specs"]
