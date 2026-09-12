"""结构化日志 + 自动脱敏（AGENTS.md §4.1 / §24）。

红线：日志与异常栈里不得出现 API Key 原文；不记录完整提示词、材料正文、音频帧。
做法：在 logger 上挂 Filter，出站前统一改写 record —— 包括 traceback 文本。
"""

from __future__ import annotations

import contextlib
import logging
import re
import traceback

_LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s [%(process)d] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 关键词后的取值：key=xxx / "api_key": "xxx" / token: xxx
_KEYWORD_VALUE = re.compile(
    r"(?ix)"
    r"\b(api[_-]?key|access[_-]?token|secret[_-]?key|app[_-]?secret"
    r"|secret|password|passwd|token|key)"
    r"(\s*[\"']?\s*[:=]\s*[\"']?)"  # 分隔符，允许引号
    r"([^\s\"',;}\]\[]{6,})"  # 取值
    r"([\"']?)"  # 收尾引号
)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Authorization: Bearer xxx
    (re.compile(r"(?i)\b(Bearer)\s+([A-Za-z0-9\-._~+/]{8,}=*)"), r"\1 ****"),
    # key=value 形式
    (_KEYWORD_VALUE, r"\1\2****\4"),
    # 裸露的厂商 Key
    (re.compile(r"\bsk-[A-Za-z0-9\-_]{8,}"), "sk-****"),
    (re.compile(r"(?i)\bbearer-[A-Za-z0-9\-_]{6,}"), "bearer-****"),
    (re.compile(r"(?i)\bvolc-[A-Za-z0-9\-_]{6,}"), "volc-****"),
    (re.compile(r"(?i)\bark-[A-Za-z0-9\-_]{12,}"), "ark-****"),
)

REDACTED = "****"

#: 运行时登记过的凭据原文。形状匹配拦不住没有前缀的不透明令牌
#: （自建端点、部分厂商的 token 就是随机串），而这类凭据一旦被上游
#: 回显进错误体，就会跟着异常栈进日志 —— 所以除了「像不像 Key」，
#: 还要能按「是不是我知道的那把」来脱敏。
_KNOWN_SECRETS: set[str] = set()

#: 太短的值不登记：一个 3 字符的「凭据」会在正常文案里到处命中，
#: 把日志糊成一片 ****，反而看不出发生了什么。
_MIN_SECRET_LEN = 8


def register_secret(value: str | None) -> None:
    """登记一个凭据原文，之后所有出站文本都会把它换成 ****。

    由 Secret.reveal() 调用（见 providers/base.py）：凭据只有在真要
    发给上游的那一刻才会被登记，不会因为「加载了配置」就躺在全局表里。
    """
    if value and len(value) >= _MIN_SECRET_LEN:
        _KNOWN_SECRETS.add(value)


def redact(text: str) -> str:
    """把文本里所有疑似凭据替换成 ****。"""
    if not text:
        return text
    result = str(text)
    # 先按「已知原文」整串替换，再按形状兜底：整串替换是精确的，
    # 先做它，后面的正则就不会把一个已经被换掉的值再切一半。
    for secret in _KNOWN_SECRETS:
        if secret in result:
            result = result.replace(secret, REDACTED)
    for pattern, replacement in _PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def redact_mapping(data: dict) -> dict:
    """对字典值逐个脱敏，用于把配置 / headers 打进日志。"""
    return {k: redact(str(v)) for k, v in (data or {}).items()}


class RedactingFilter(logging.Filter):
    """出站前改写 record：脱敏消息、脱敏 traceback、带上 requestId。"""

    def filter(self, record: logging.LogRecord) -> bool:
        # 脱敏是「尽力而为」：它自己出错也绝不能反过来把业务打挂。
        # 所以这里显式吞掉异常，且不记日志（记日志会再次进入 filter → 递归）。
        with contextlib.suppress(Exception):  # pragma: no cover
            self._rewrite(record)
        return True

    @staticmethod
    def _rewrite(record: logging.LogRecord) -> None:
        # 先把 %s 参数渲染成完整文本，再脱敏；否则参数里的 Key 会绕过替换
        message = record.getMessage()
        record.msg = redact(message)
        record.args = ()

        request_id = _safe_request_id()
        if request_id and f"[{request_id}]" not in record.msg:
            record.msg = f"[{request_id}] {record.msg}"

        if record.exc_info:
            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None  # 交给 Formatter 用已脱敏的 exc_text

        if record.stack_info:
            record.stack_info = redact(record.stack_info)


def _safe_request_id() -> str:
    """取当前 requestId。不在请求上下文时返回空串，绝不抛异常。"""
    try:
        from app.common.response import current_request_id

        return current_request_id()
    except Exception:  # pragma: no cover - 日志路径必须无条件可用
        return ""


def get_logger(name: str = "eduagentx") -> logging.Logger:
    """取一个已挂脱敏 Filter 的 logger（重复调用不会叠加 Filter）。"""
    logger = logging.getLogger(name)
    if not any(isinstance(f, RedactingFilter) for f in logger.filters):
        logger.addFilter(RedactingFilter())
    return logger


def configure_logging(app) -> None:
    """给 root logger 装一个控制台 handler。可重复调用（幂等）。"""
    if app.extensions.get("eduagentx_logging_configured"):
        return
    app.extensions["eduagentx_logging_configured"] = True

    level_name = str(app.config.get("LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    handler.addFilter(RedactingFilter())

    root = logging.getLogger()
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)

    # Flask 自带的 logger 也走同一套过滤
    app.logger.addFilter(RedactingFilter())


__all__ = [
    "REDACTED",
    "RedactingFilter",
    "configure_logging",
    "get_logger",
    "redact",
    "redact_mapping",
    "register_secret",
]
