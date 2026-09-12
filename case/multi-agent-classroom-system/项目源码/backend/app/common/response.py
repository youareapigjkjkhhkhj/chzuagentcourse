"""统一响应信封：{code, message, data, requestId}。

前端只需处理一种响应形状（P0-F2）。业务码分段：
    0        成功
    4xxxx    客户端错误（4 位是 HTTP 状态，末位是序号）
    5xxxx    服务端错误
"""

from __future__ import annotations

import uuid
from typing import Any

from flask import has_request_context, jsonify, request

from app.common.context import real_request

SUCCESS_CODE = 0

#: requestId 在 request 对象上的缓存属性名。挂私有属性而不是用 g：
#: g 属于 app context，多个请求复用一个 app context 时会串号（测试里就是如此）。
_REQUEST_ID_ATTR = "_eduagentx_request_id"

# 业务码 → 默认文案
MESSAGES = {
    SUCCESS_CODE: "成功",
    40001: "参数不合法",
    40101: "未授权或缺少凭据",
    40301: "无权访问该资源",
    40401: "资源不存在",
    40501: "请求方法不被允许",
    40901: "资源当前状态冲突",
    40902: "当前状态不允许该操作",
    # 40201 是配置问题不是故障：前端据此引导去设置页，而不是弹「服务器错误」
    40201: "未配置 API Key",
    42901: "请求过于频繁，请稍后重试",
    50001: "服务器内部错误",
    50201: "上游服务调用失败",
    50401: "上游服务响应超时",
}

REQUEST_ID_HEADER = "X-Request-Id"

# 允许上游透传的 requestId 字符（防止日志注入）
_MAX_REQUEST_ID_LEN = 128


def new_request_id() -> str:
    return uuid.uuid4().hex


def current_request_id() -> str:
    """取当前请求的 requestId：优先上游透传，其次本次生成。

    缓存在 request 对象上而不是 g 上 —— g 属于 app context，
    多个 request context 复用一个 app context 时会串号（测试里就是如此）。
    """
    if not has_request_context():
        return ""

    # 拿真实对象而不是代理：LocalProxy 会转发读写，但挂缓存这件事
    # 依赖 setattr 一定落在真对象上，取真的更稳（见 common/context.py）。
    req = real_request()

    cached = getattr(req, _REQUEST_ID_ATTR, None)
    if cached:
        return cached

    incoming = (request.headers.get(REQUEST_ID_HEADER) or "").strip()
    if incoming and len(incoming) <= _MAX_REQUEST_ID_LEN:
        # 只保留可打印 ASCII，避免把换行塞进日志（日志注入）
        cleaned = "".join(ch for ch in incoming if 0x20 <= ord(ch) < 0x7F)
        rid = cleaned or new_request_id()
    else:
        rid = new_request_id()

    setattr(req, _REQUEST_ID_ATTR, rid)
    return rid


def _envelope(code: int, message: str | None, data: Any) -> dict:
    return {
        "code": code,
        "message": message if message is not None else MESSAGES.get(code, "未知状态"),
        "data": data,
        "requestId": current_request_id(),
    }


def ok(data: Any = None, message: str | None = None, http_status: int = 200):
    """成功响应。返回 (dict, status)，由 Flask 自动转 JSON。"""
    return _envelope(SUCCESS_CODE, message, data), http_status


def fail(
    code: int,
    message: str | None = None,
    http_status: int = 400,
    details: Any = None,
):
    """失败响应。details 放进 data.details，保持 4 键信封不变。"""
    data = {"details": details} if details is not None else None
    return _envelope(code, message, data), http_status


def fail_with_data(
    code: int,
    data: Any,
    message: str | None = None,
    http_status: int = 400,
):
    """失败响应，data **原样**作为 data（不再套一层 details）。

    只给被契约定死形状的场景用：P0 §4.2 规定 40201 的 data 就是
    `{ok: false, error: "missing_api_key"}`，前端照着它写判断。
    除此之外一律用 fail(details=...)，让字段级错误有统一的归处。
    """
    return _envelope(code, message, data), http_status


def is_success(code: int) -> bool:
    return code == SUCCESS_CODE


def is_client_error(code: int) -> bool:
    return 40000 <= code < 50000


def is_server_error(code: int) -> bool:
    return 50000 <= code < 60000


def json_response(payload: dict, http_status: int = 200):
    """需要显式构造 Response 时使用。"""
    return jsonify(payload), http_status
