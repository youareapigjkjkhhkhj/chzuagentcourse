"""统一异常体系 + 全局异常处理器。

两条硬要求：
1. 所有失败都走 4 键信封，前端不需要区分形状。
2. 未捕获异常绝不把堆栈 / 文件路径 / 上游原文泄露给客户端（AGENTS.md §4.1）。
"""

from __future__ import annotations

from typing import Any

from werkzeug.exceptions import HTTPException

from app.common.response import MESSAGES, fail

# HTTP 状态 → 业务码。404 一律 40401，不区分「不存在」与「越权」，
# 避免通过错误码探测资源是否存在（AGENTS.md §4.1 越权返回 404）。
HTTP_STATUS_TO_CODE = {
    400: 40001,
    401: 40101,
    403: 40301,
    404: 40401,
    405: 40501,
    409: 40901,
    413: 40002,
    415: 40003,
    422: 40001,
    429: 42901,
    500: 50001,
    502: 50201,
    503: 50201,
    504: 50401,
}


class AppError(Exception):
    """所有业务异常的基类。"""

    code: int = 50001
    http_status: int = 500

    def __init__(
        self,
        message: str | None = None,
        *,
        code: int | None = None,
        http_status: int | None = None,
        details: Any = None,
    ) -> None:
        self.message = message or MESSAGES.get(self.code, "未知错误")
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        self.details = details
        super().__init__(self.message)

    def to_envelope(self):
        return fail(self.code, self.message, self.http_status, self.details)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<{type(self).__name__} code={self.code} msg={self.message!r}>"


class ValidationError(AppError):
    """入参不合法。"""

    code = 40001
    http_status = 400


class UnauthorizedError(AppError):
    """缺少或无效凭据（例如未配置 API Key）。"""

    code = 40101
    http_status = 401


class PayloadTooLargeError(AppError):
    """请求体（上传的文件）超过上限（P4-B3 的 413）。

    单独一个类是因为它必须与「参数不合法」分开：材料 50MB 的上限是按端点
    放开的（`MATERIAL_MAX_BYTES`），前端要据此提示「换个小的/拆开来传」，
    而不是提示「文件名不合法」。
    """

    code = 40002
    http_status = 413


class UnsupportedMediaError(AppError):
    """文件类型不在白名单里、或内容与扩展名不符（P4-B3 的 415）。

    「内容与扩展名不符」（改了后缀的伪装文件，P4-F1）也走这个码：
    对用户来说这两件事是同一件 —— 这个文件我们不吃。
    """

    code = 40003
    http_status = 415


class ForbiddenError(AppError):
    code = 40301
    http_status = 403


class NotFoundError(AppError):
    """资源不存在 —— 越权时同样返回它，不泄露资源存在性。"""

    code = 40401
    http_status = 404


class ConflictError(AppError):
    code = 40901
    http_status = 409


class StateError(AppError):
    """状态机不允许的操作（例如课程未生成完就导出）。"""

    code = 40902
    http_status = 409


class RateLimitError(AppError):
    code = 42901
    http_status = 429


class UpstreamError(AppError):
    """上游 Provider（LLM / TTS / ASR / 实时语音）失败。"""

    code = 50201
    http_status = 502


class UpstreamTimeoutError(UpstreamError):
    code = 50401
    http_status = 504


def _code_for_http_status(status: int) -> int:
    if status in HTTP_STATUS_TO_CODE:
        return HTTP_STATUS_TO_CODE[status]
    if 400 <= status < 500:
        return 40000 + status % 100 * 100 + 1
    return 50001


def install_error_handlers(app) -> None:
    """把异常处理器挂到 app 上。可重复调用（Flask 的注册是覆盖语义）。"""
    from app.common.logging import get_logger

    logger = get_logger("app.errors")

    @app.errorhandler(AppError)
    def _handle_app_error(exc: AppError):
        # 业务异常是预期内的，用 warning；不打印堆栈，避免噪音
        logger.warning("业务异常 code=%s msg=%s", exc.code, exc.message)
        return exc.to_envelope()

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc: HTTPException):
        status = exc.code or 500
        code = _code_for_http_status(status)
        # 405 等由框架给出；404 统一文案，不透露路由是否存在
        message = MESSAGES.get(code) or exc.description or "请求失败"
        if status == 404:
            message = MESSAGES[40401]
        return fail(code, message, status)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc: Exception):
        # 这里才是真正的「未知」。堆栈只进服务端日志，客户端只拿到一句话。
        logger.exception("未捕获异常 type=%s", type(exc).__name__)
        return fail(50001, MESSAGES[50001], 500)

