"""语音服务层（P2）。

六个模块，按「谁依赖谁」排列 —— **导入顺序不能改**：
`assets` 里有一句 `from app.services.voice import usage`，那要求包里
已经把 `usage` 这个属性挂上（见下面 import 的先后）。

| 模块 | 管什么 |
|------|--------|
| `policy`   | 开关与降级口径：关掉语音算不算失败、失败退到哪条路（P2-B2/G3） |
| `usage`    | 记账与汇总：一次合成/识别/对话花了多少（P2-A11/C3） |
| `glossary` | 术语表：一份数据投出纠音表与热词表（P2-A20） |
| `assets`   | 音频资产管线：合成、缓存、失效、清单、清理（P2-A2/A5/A6/C1/C2/C4） |
| `prefs`    | 参数解析：这一次该用哪个音色、什么语速语调（P2-A5/F2-11） |
| `realtime` | 实时语音的语义层：上行/下行那套自己的词，与传输无关（P2-B1/§4.2） |
| `jobs`     | 整课预合成的后台任务：入队、去重、进度从清单推（P2-A2） |

分层的方向是单向的：`assets` 可以用前三个，反过来不行。
`usage` 不认识 `assets`，所以「记一笔账」这件事可以被实时语音、
ASR 这些与音频文件无关的链路复用。

导入顺序的两条约束（都在上面的表里自上而下）：`assets` 依赖 `usage`/`policy`/
`glossary`，`prefs` 依赖 `assets`，`realtime` 依赖 `prefs`，`jobs` 依赖 `prefs`。
"""

from __future__ import annotations

# 子模块之间不互相 `from 本包 import`（见 assets.py 顶部那句），所以这里的顺序无所谓 ——
# 排成这样只是因为 isort 会这么排。
from app.services.voice import assets, glossary, jobs, policy, prefs, realtime, usage
from app.services.voice.assets import (
    Beat,
    VoiceSettings,
    manifest,
    mark_stale,
    narrate,
    preview,
    purge_course,
    settings_for,
    synthesize_beat,
)
from app.services.voice.glossary import glossary_of, glossary_terms, hotwords, pronunciation
from app.services.voice.policy import VoiceDisabledError, voice_enabled
from app.services.voice.prefs import (
    VoicePrefs,
    narration_settings,
    realtime_voice_id,
    voice_profile,
)
from app.services.voice.realtime import MODE_MAP, RealtimeChannel
from app.services.voice.usage import record, summary

__all__ = [
    "MODE_MAP",
    "Beat",
    "RealtimeChannel",
    "VoiceDisabledError",
    "VoicePrefs",
    "VoiceSettings",
    "assets",
    "glossary",
    "glossary_of",
    "glossary_terms",
    "hotwords",
    "jobs",
    "manifest",
    "mark_stale",
    "narrate",
    "narration_settings",
    "policy",
    "prefs",
    "preview",
    "pronunciation",
    "purge_course",
    "realtime",
    "realtime_voice_id",
    "record",
    "settings_for",
    "summary",
    "synthesize_beat",
    "usage",
    "voice_enabled",
    "voice_profile",
]
