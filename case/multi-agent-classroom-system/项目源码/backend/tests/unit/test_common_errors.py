"""统一异常体系测试（P0-A1 / P0-F2）。

要求：
- 业务异常携带 (code, http_status, message)
- 未捕获异常绝不把堆栈泄露给客户端
- 所有失败都走 4 键信封
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_business_exceptions_carry_code_and_http_status(app):
    from app.common.errors import (
        ConflictError,
        NotFoundError,
        RateLimitError,
        StateError,
        UnauthorizedError,
        UpstreamError,
        UpstreamTimeoutError,
        ValidationError,
    )

    cases = [
        (ValidationError("页数必须是整数"), 40001, 400),
        (UnauthorizedError("未配置 API Key"), 40101, 401),
        (NotFoundError("课程不存在"), 40401, 404),
        (ConflictError("课程正在生成中"), 40901, 409),
        (RateLimitError("请求过于频繁"), 42901, 429),
        (StateError("当前状态不允许该操作"), 40902, 409),
        (UpstreamError("上游返回 500"), 50201, 502),
        (UpstreamTimeoutError("上游超时"), 50401, 504),
    ]

    for exc, expected_code, expected_http in cases:
        assert exc.code == expected_code, exc
        assert exc.http_status == expected_http, exc
        assert isinstance(exc.message, str) and exc.message
        assert isinstance(exc, Exception)


def test_not_found_default_message():
    from app.common.errors import NotFoundError

    assert NotFoundError().message


def test_validation_error_carries_details():
    """字段级错误要能带出，供前端定位表单。"""
    from app.common.errors import ValidationError

    exc = ValidationError("参数不合法", details={"page_count": "必须在 8~20 之间"})
    assert exc.details == {"page_count": "必须在 8~20 之间"}


def test_app_error_to_envelope(app):
    """异常 → 信封，http 状态码同步。"""
    from app.common.errors import NotFoundError, ValidationError

    with app.test_request_context("/api/courses/nope"):
        body, status = ValidationError("页数超范围").to_envelope()

    assert status == 400
    assert body["code"] == 40001
    assert body["data"] is None
    assert set(body.keys()) == {"code", "message", "data", "requestId"}

    with app.test_request_context("/api/courses/nope"):
        _, status = NotFoundError("课程不存在").to_envelope()
    assert status == 404


def test_unhandled_exception_returns_500_envelope_without_traceback(app):
    """未捕获异常 → 50001 信封，且响应体不得出现堆栈/文件路径/异常类名。"""
    from app.common.errors import install_error_handlers

    install_error_handlers(app)

    @app.route("/_boom")
    def _boom():
        raise RuntimeError("secret internal detail: /etc/passwd")

    resp = app.test_client().get("/_boom")
    assert resp.status_code == 500

    body = resp.get_json()
    assert set(body.keys()) == {"code", "message", "data", "requestId"}
    assert body["code"] == 50001

    raw = resp.get_data(as_text=True)
    assert "RuntimeError" not in raw
    assert "Traceback" not in raw
    assert "/etc/passwd" not in raw
    assert "secret internal detail" not in raw


def test_http_exception_returns_envelope(app):
    """Flask 自带的 404 也要包成信封，前端只需处理一种形状。"""
    from app.common.errors import install_error_handlers

    install_error_handlers(app)
    resp = app.test_client().get("/_definitely_not_here")

    assert resp.status_code == 404
    body = resp.get_json()
    assert set(body.keys()) == {"code", "message", "data", "requestId"}
    assert body["code"] == 40401


def test_error_handlers_are_installed_by_factory(app):
    """create_app 必须自动装上异常处理器，不能依赖各蓝图自觉。"""
    resp = app.test_client().get("/api/_no_such_route_")
    assert resp.status_code == 404
    body = resp.get_json()
    assert body is not None and body["code"] == 40401


def test_bad_json_body_is_40001_not_500(app):
    """畸形 JSON 属于客户端错误，不能算服务端 500。"""
    @app.route("/_echo", methods=["POST"])
    def _echo():
        from flask import request

        return {"got": request.get_json()}

    resp = app.test_client().post(
        "/_echo", data="{not json", content_type="application/json"
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["code"] == 40001
