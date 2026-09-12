"""响应信封测试（P0-A1 / P0-F2）。

约定：{code, message, data, requestId}；code=0 成功，4xxxx 客户端错误，5xxxx 服务端错误。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_success_envelope_shape(app):
    """成功响应必须恰好包含 4 个顶层键，不多不少。"""
    from app.common.response import ok

    with app.test_request_context("/api/health"):
        body, status = ok({"pong": True})

    assert status == 200
    assert set(body.keys()) == {"code", "message", "data", "requestId"}
    assert body["code"] == 0
    assert body["data"] == {"pong": True}
    assert isinstance(body["message"], str)


def test_success_envelope_request_id_is_uuid_like(app):
    """requestId 非空且全局唯一。"""
    from app.common.response import ok

    ids = set()
    for _ in range(20):
        with app.test_request_context("/api/health"):
            body, _ = ok(None)
        ids.add(body["requestId"])
        assert len(body["requestId"]) >= 8

    assert len(ids) == 20, "requestId 必须每次不同"


def test_success_envelope_default_data_is_none(app):
    from app.common.response import ok

    with app.test_request_context("/api/health"):
        body, status = ok()

    assert status == 200
    assert body["data"] is None


def test_fail_envelope_shape(app):
    """失败响应同样遵守 4 键信封。"""
    from app.common.response import fail

    with app.test_request_context("/api/health"):
        body, status = fail(40001, "参数不合法", http_status=400)

    assert status == 400
    assert set(body.keys()) == {"code", "message", "data", "requestId"}
    assert body["code"] == 40001
    assert body["message"] == "参数不合法"
    assert body["data"] is None


def test_fail_envelope_carries_details(app):
    """字段级错误明细放在 data.details，仍是 4 键信封。"""
    from app.common.response import fail

    with app.test_request_context("/api/health"):
        body, _ = fail(40001, "参数不合法", details={"field": "page_count"})

    assert body["data"] == {"details": {"field": "page_count"}}


def test_request_id_propagates_from_incoming_header(app):
    """上游传 X-Request-Id 时必须沿用，便于跨服务串联日志。"""
    from app.common.response import ok

    with app.test_request_context("/api/health", headers={"X-Request-Id": "trace-abc-123"}):
        body, _ = ok()

    assert body["requestId"] == "trace-abc-123"


def test_envelope_is_json_serializable(app):
    """信封必须能被 json.dumps 直接序列化（中文不转义）。"""
    import json

    from app.common.response import ok

    with app.test_request_context("/api/health"):
        body, _ = ok({"课程": "光合作用"})

    text = json.dumps(body, ensure_ascii=False)
    assert "光合作用" in text


def test_error_code_ranges_are_documented():
    """错误码分段：0 成功 / 4xxxx 客户端 / 5xxxx 服务端。"""
    from app.common.response import is_client_error, is_server_error, is_success

    assert is_success(0)
    assert not is_success(40001)

    assert is_client_error(40001)
    assert is_client_error(40101)
    assert is_client_error(40401)
    assert is_client_error(42901)
    assert not is_client_error(50001)
    assert not is_client_error(0)

    assert is_server_error(50001)
    assert is_server_error(50201)
    assert is_server_error(50401)
    assert not is_server_error(40001)
