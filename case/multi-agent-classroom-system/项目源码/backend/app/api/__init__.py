"""API 蓝图（P0 §4）。

约定：**所有接口以 /api 开头**（§3）。业务码与 HTTP 状态分离：
HTTP 状态给浏览器/代理看，`code` 给前端业务逻辑看（P0-B1）。

接口层只做三件事：取参数 → 调 service → 包信封。
校验规则、默认值、加解密都在 service / common 里，接口层不重复一遍 ——
重复的规则一定会分叉，而分叉的那一份迟早是错的那份。
"""

from __future__ import annotations

from flask import Flask

from app.common.errors import ValidationError

#: 上游没给 content_type 时 request.get_json() 会抛 415。
#: 这里统一放宽成「body 不是 JSON 对象就报 40001」，前端只需处理一种错。
_JSON_KWARGS = {"silent": True}


def json_body(required: bool = True) -> dict:
    """取请求体。不是 JSON 对象就抛 40001。

    silent=True 让解析失败返回 None 而不是抛 werkzeug 的 415 ——
    415 会绕过我们对「请求体不合法」的统一文案。
    """
    from flask import request

    payload = request.get_json(**_JSON_KWARGS)
    if payload is None:
        if not required:
            return {}
        raise ValidationError("请求体必须是 JSON 格式")
    if not isinstance(payload, dict):
        raise ValidationError("请求体必须是一个 JSON 对象")
    return payload


def register_api(app: Flask) -> None:
    """注册全部蓝图。前缀统一在各自蓝图里写全，便于直接看路由表。"""
    from app.api.agents import bp as agents_bp
    from app.api.courses import bp as courses_bp
    from app.api.generation import bp as generation_bp
    from app.api.health import bp as health_bp
    from app.api.settings import bp as settings_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(generation_bp)
    app.register_blueprint(courses_bp)


__all__ = ["json_body", "register_api"]
