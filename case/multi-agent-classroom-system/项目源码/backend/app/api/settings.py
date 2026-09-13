"""设置页接口（§4.2）。

五个子域：
- providers  服务商卡片：列表 / 保存 / 测试连接 / 启用
- voice      音色与语速、ASR 开关
- generation 生成参数（页数 / 同学数 / 激烈度 / 详细度 / 三个开关）
- pricing    价目表（P5，F5-7）—— 只写，读在 `GET /api/usage/models`
- budget     预算上限与告警阈值（P5，F5-8）

预算挂在这里而不是 `/api/usage` 下，理由与其它三项相同：它是**设置**，
与「看用量」是两件事 —— 前者写、后者读，混在一个蓝图上，
某天想给「看用量」开只读权限时会发现分不开。

「测试连接」不叫「保存」——它真的会发一次 1-token 的请求（P0-A5）。
失败时返回 200 + `ok:false` + 原因，而不是 5xx：探活成功地探出了「连不上」，
这件事本身是成功的。唯一例外是**未配置**：那是 40201，
前端据此弹「去设置页填 Key」，与「填错了」是两条不同的引导（P0-B3）。
"""

from __future__ import annotations

from flask import Blueprint

from app.api import json_body
from app.common.response import ok
from app.services import audit, provider_admin, settings_service
from app.services.usage import budget, pricing

bp = Blueprint("settings", __name__, url_prefix="/api/settings")


# --- 服务商 ---


@bp.get("/providers")
def list_providers():
    """服务商卡片列表：配置状态、是否启用、掩码 Key、最近一次探活延迟。

    请求示例：
        GET /api/settings/providers

    ★ 只回掩码（`sk-****1234`）：明文与密文都不出服务端（P0-C1）。
    `missing` 字段说清这张卡还缺哪几栏 —— 「未配置」三个字没法告诉用户补什么。
    """
    return ok(provider_admin.list_cards())


@bp.put("/providers/<provider_id>")
def save_provider(provider_id: str):
    """保存某个服务商的 API Key / 接入地址 / 默认模型。

    请求示例：
        PUT /api/settings/providers/openai
        {"apiKey": "sk-…", "baseUrl": "https://api.example.com/v1", "defaultModel": "gpt-4o-mini"}

    字段缺省或空串 = **不改这一栏**（表单回显的是掩码，用户没动它就不该被覆盖）；
    想清空 Key 要用 `{"clearApiKey": true}`。
    """
    body = json_body()
    card = provider_admin.save_provider(provider_id, body)
    # 审计只记**改了哪几栏的名字**，一个值都不记 —— 这几栏里就有 API Key 原文
    #（AGENTS §19）。审计要回答的是「谁、什么时候、动过哪张卡」，
    # 而不是「配的是什么」：后者是取证时翻库才该看的东西。
    audit.record(
        audit.ACTION_PROVIDER_UPDATE,
        target=f"provider:{provider_id}",
        detail={"fields": sorted(k for k, v in body.items() if v not in (None, ""))},
    )
    return ok(card)


@bp.post("/providers/<provider_id>/test")
def test_provider(provider_id: str):
    """测试连接：真的发一次 1-token 请求，返回延迟或失败原因（P0-A5）。

    请求示例：
        POST /api/settings/providers/deepseek/test

    「连不上」不等于「接口失败」：这种情况返回 200 + `ok:false` + `error/errorCode`，
    让设置页显示 401 / 连不上 / 超时的**具体原因**。唯一会抛的是「还没配齐」——
    那是 40201（由 not_configured 抛出，走全局处理器），前端据此引导去填 Key。
    """
    result = provider_admin.probe_provider(provider_id)
    return ok(
        {
            "ok": result.ok,
            "latencyMs": result.latency_ms,
            "model": result.model,
            "error": result.error,
            "errorCode": result.error_code,
        }
    )


@bp.post("/providers/<provider_id>/enable")
def enable_provider(provider_id: str):
    """把某个服务商设为当前启用（全局唯一，其余自动置为未启用）。

    请求示例：
        POST /api/settings/providers/qwen/enable

    允许启用一张还没填 Key 的卡：用户的自然顺序是「先启用，再去填 Key」。
    """
    card = provider_admin.enable_provider(provider_id)
    # 启用是全局唯一的一次切换：它会把别的卡置为未启用，所以「什么时候换的、
    # 换成谁」要留痕 —— 上游账单对不上时，这是第一个要看的时间点。
    audit.record(audit.ACTION_PROVIDER_ENABLE, target=f"provider:{provider_id}")
    return ok(card)


# --- 语音 ---


@bp.get("/voice")
def get_voice():
    """语音设置：音色卡列表、当前音色、语速、语调起伏、ASR 开关。

    请求示例：
        GET /api/settings/voice

    `voices[].configured` 说这个音色在 .env 里有没有厂商音色 ID —— 没配就是
    `false`，绝不编一个占位 ID 出来（那会在调用时变成 `InvalidSpeaker`）。
    """
    return ok(settings_service.get_voice())


@bp.put("/voice")
def update_voice():
    """增量更新语音设置（音色 / 语速 / 起伏 / ASR 开关）。

    请求示例：
        PUT /api/settings/voice
        {"teacherVoiceId": "vp_teacher_gu", "speed": 1.2, "asrEnabled": true}

    只传要改的字段；字段名拼错会返回 40001，而不是被静默忽略。
    """
    return ok(settings_service.update_voice(json_body()))


# --- 生成参数 ---


@bp.get("/generation")
def get_generation():
    """生成参数：课件页数、AI 同学数量、讨论激烈程度、讲稿详细度与三个开关。

    请求示例：
        GET /api/settings/generation

    没写过的键返回默认值而不是 null（P0-C4）。
    """
    return ok(settings_service.get_generation())


@bp.put("/generation")
def update_generation():
    """增量更新生成参数。

    请求示例：
        PUT /api/settings/generation
        {"pageCount": 16, "classmateCount": 3, "intensity": "high"}

    取值范围以 `/api/capabilities` 的 `generation` 为准（前后端同一份常量）；
    越界返回 40001。
    """
    return ok(settings_service.update_generation(json_body()))


@bp.put("/pricing")
def update_pricing():
    """改价目表（P5 §4.2：价格表「可在设置页维护」）。

    请求示例：
        PUT /api/settings/pricing
        {"llm": {"deepseek-chat": {"promptPer1k": 1, "completionPer1k": 3}},
         "tts": {"perKChars": 0.2}}

    **读在 `/api/usage/models`，写在这里** —— 与预算同一套分法：看用量是读，
    改价目表是设置。传进来的整段覆盖 `settings_kv.pricing`，`.env` 里的
    `LLM_PRICE_*` / `VOICE_*_PRICE_*` 继续打底（见 `services/usage/pricing.py`）。

    负数与拼错的档位一律 40001：负单价会让账本出现负金额，
    而「花了 -3 元」会把别的链路花掉的钱抵掉一半。
    """
    return ok(pricing.update(json_body()))


# --- 预算（P5 §4.2 / F5-8）---


@bp.get("/budget")
def get_budget():
    """预算与当前用量：单课 token 上限、日预算、总额，各自用了多少（F5-8）。

    请求示例：
        GET /api/settings/budget

    `global` / `day` 各一条（没设过的补一条默认的：全部为 0 = 不限），
    加上每门配过预算的课各一条；`current` 里三个作用域都有位置
    （单课那一档说的是「哪门课都还没指定」）。
    每条都带着 `usedCost` / `usedTokens` / `alert`：设置页要显示
    「日预算 10 元，今天已用 3.2 元」，分两次请求去拼，两半数字会来自不同时刻。

    金额是**估算**（本机价目表乘出来的），每个响应都带 `note` 说明这件事。
    """
    return ok(budget.get_all())


@bp.put("/budget")
def update_budget():
    """改预算。按作用域增量更新，只认传了的字段。

    请求示例：
        PUT /api/settings/budget
        {"scope": "day", "limitCost": 20, "alertRatio": 0.8}
        {"budgets": [{"scope": "day", "limitTokens": 200000},
                     {"scope": "course", "refId": "c_01H…", "limitCost": 2}]}

    `limitTokens` / `limitCost` 的 **0 = 不限**（而不是「限额为零」）：
    用它把某一条关掉，比删行更好 —— 删行与「从没设过」在库里长得一样。
    单课预算必须带 `refId`，不带就报 40001（不带就是「所有课程」，
    那是 `global` 的意思，不能悄悄退化）。
    """
    return ok(budget.update(json_body()))
