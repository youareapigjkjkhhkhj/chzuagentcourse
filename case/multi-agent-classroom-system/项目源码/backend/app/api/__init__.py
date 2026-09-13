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
    from app.api.classroom import bp as classroom_bp
    from app.api.courses import bp as courses_bp
    from app.api.exports import bp as exports_bp
    from app.api.generation import bp as generation_bp
    from app.api.health import bp as health_bp
    from app.api.materials import bp as materials_bp
    from app.api.settings import bp as settings_bp
    from app.api.usage import bp as usage_bp
    from app.api.voice import bp as voice_bp
    from app.api.workbench import bp as workbench_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(settings_bp)
    # 用量蓝图带 url_prefix `/api/usage`：它三条路由同属一个只读子域，
    # 与课程/导出那种「一半挂课程下、一半挂自己下」的形状不同。
    # 预算那两条按 §4.2 留在设置蓝图里（改预算与改音色是同一类动作）。
    app.register_blueprint(usage_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(generation_bp)
    app.register_blueprint(courses_bp)
    # 导出蓝图同样写全路径：它一半挂在 `/api/courses/<id>/exports`
    # （课程详情页的导出面板），一半挂在 `/api/exports/<id>`（产物本身）
    app.register_blueprint(exports_bp)
    # 材料蓝图也没有 url_prefix：它有一条 `/api/courses/<id>/materials`
    # （课程关联），与课程蓝图的路由不重叠（课程那边没有 `/materials` 子路径）
    app.register_blueprint(materials_bp)
    # 工作台蓝图同样写全路径。它有一条 `/api/courses/<id>/chat/stream`，
    # 与课程的 `/api/courses/<id>/...` 不重叠（课程那边没有 `/chat` 子路径）。
    app.register_blueprint(workbench_bp)
    # 语音蓝图没有 url_prefix：路由写的是全路径，好让它的 errorhandler
    # 只圈住语音那几个端点（见 app/api/voice.py 顶部）
    app.register_blueprint(voice_bp)
    # 课堂蓝图同理没有 url_prefix：它的路由也写全路径。
    # **必须在语音之后注册**：两条 `websocket=True` 路由的路径前缀没有交集
    # （`/ws/voice/*` 与 `/ws/classroom/*`），顺序不影响匹配，但读路由表时
    # 两条推送通道挨着看更清楚（/ws 一共就这两条）
    app.register_blueprint(classroom_bp)


__all__ = ["json_body", "register_api"]
