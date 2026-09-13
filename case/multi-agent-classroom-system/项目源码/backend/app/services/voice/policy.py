"""语音开关与降级口径（P2-B2 / P2-G3）。

一条规则：**降级路径由服务端说了算**。

前端在语音失败时该做什么，答案只有一个来源 —— 服务端在错误里给出的
`fallback` 字段。让前端自己判断「这个错是不是没配 Key、要不要改成打字」，
判断逻辑就会有两份，而且两份会在不同的时间点过期：后端加了一种失败原因，
前端的判断还是旧的，于是它按旧逻辑弹了一个「服务器错误」的弹窗 ——
一节课中间弹一次，这节课就断了。所以这里把「退回哪条路」定成枚举，
由 `fallback_for()` 一处映射，任何 error 都必须带上它。

三条路（P2 §2.1 的切换规则）：
- `text`：纯文字 —— 讲稿、字幕、打字问答都还在。总开关关掉、或上游彻底不可用时走这条；
- `browser`：浏览器自带合成（`speechSynthesis`）—— 服务端没有声音，但设备有；
- `none`：没有退路。目前只有「连文字都没有」的场景才会用到，预留给将来。
"""

from __future__ import annotations

from typing import Any, Mapping

from flask import current_app

from app.common.errors import AppError
from app.common.response import MESSAGES

#: 退化为纯文字：内容全在，只是没有声音。
FALLBACK_TEXT = "text"
#: 退化为浏览器本地合成。
FALLBACK_BROWSER = "browser"
#: 无路可退。
FALLBACK_NONE = "none"

FALLBACKS = (FALLBACK_TEXT, FALLBACK_BROWSER, FALLBACK_NONE)

#: 业务码。40302 归在 4xxxx 段：这是**部署方的一个决定**（开关关着），
#: 不是服务端故障 —— 前端据此显示黄色提示条，而不是红色错误弹窗。
VOICE_DISABLED_CODE = 40302


class VoiceDisabledError(AppError):
    """语音总开关关着（`VOICE_ENABLED=false`）。

    `data` 的形状跟 40201 对齐（平铺的 `ok/error/fallback`，不套 details）：
    这两个错误在前端是同一段代码处理的 —— 都是「没有声音，退到某条路上去」，
    如果形状不一样，那段代码就得写两个分支去读同一个语义。
    """

    code = VOICE_DISABLED_CODE
    http_status = 403

    def __init__(self, message: str | None = None, *, fallback: str = FALLBACK_TEXT) -> None:
        super().__init__(message or MESSAGES[VOICE_DISABLED_CODE], details={"fallback": fallback})

    def to_envelope(self):
        from app.common.response import fail_with_data

        return fail_with_data(
            self.code,
            {"ok": False, "error": "voice_disabled", "fallback": self.details["fallback"]},
            self.message,
            self.http_status,
        )


def voice_enabled() -> bool:
    """语音总开关（P2-G3）。缺配置时按**开**处理：没配这个键的老部署不该突然没声音。"""
    return bool(current_app.config.get("VOICE_ENABLED", True))


def disabled(*, fallback: str = FALLBACK_TEXT) -> VoiceDisabledError:
    """统一的 40302 构造点：文案与 fallback 只在这里写一次。"""
    return VoiceDisabledError(fallback=fallback)


def fallback_for(exc: BaseException) -> str:
    """这个异常该退到哪条路。

    顺序有讲究：先看「是不是我们主动关的」，再看「是不是配置缺失」。
    `VoiceDisabledError` 是 AppError 的子孙，而 Provider 那类错误也是 ——
    反过来判会把开关关闭误报成「去设置页填 Key」。
    """
    from app.providers.base import ProviderError, ProviderNotConfiguredError

    if isinstance(exc, VoiceDisabledError):
        return FALLBACK_TEXT
    if isinstance(exc, ProviderNotConfiguredError):
        # 服务端没声音但设备有：让前端用浏览器合成，体验上比「静音」接近课堂
        return FALLBACK_BROWSER
    if isinstance(exc, ProviderError):
        return FALLBACK_BROWSER
    return FALLBACK_TEXT


def with_fallback(exc: AppError) -> AppError:
    """把 `fallback` 写进异常的信封（P2-B2：「任何 error 事件都必须携带 fallback」）。

    只加一个键，不改形状：40201 的 `data` 是 P0 §4.2 钉死的平铺结构，
    这里往它的 details 里补一个键，`to_envelope` 会把它一起平铺出去。
    前端读 `data.fallback`，读不到再退到 `data.details.fallback`。
    """
    current = exc.details if isinstance(exc.details, Mapping) else {}
    details: dict[str, Any] = dict(current)
    details.setdefault("fallback", fallback_for(exc))
    exc.details = details
    return exc


__all__ = [
    "FALLBACKS",
    "FALLBACK_BROWSER",
    "FALLBACK_NONE",
    "FALLBACK_TEXT",
    "VOICE_DISABLED_CODE",
    "VoiceDisabledError",
    "disabled",
    "fallback_for",
    "voice_enabled",
    "with_fallback",
]
