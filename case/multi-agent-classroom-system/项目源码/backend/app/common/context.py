"""取 LocalProxy 背后的真实对象。

Flask 的 `current_app` / `request` 在运行时是 LocalProxy：属性访问会转发到
当前上下文里的真对象，所以大多数时候直接用就行。而且从 Flask 3 起，它们
被**标注**成了 `Flask` / `Request`（标注撒了个小谎），于是 mypy 认为
`_get_current_object` 不存在 —— 明明运行时就在。

这里用一个 Protocol 把这个谎说破：先 cast 成「知道有这个方法」的形态再取，
就不用为了类型检查去写 `# type: ignore` 或 `getattr(x, "字面量")`。

为什么非要真对象，直接用代理不行：
- 往 `app.extensions` 里存东西再按对象身份取回来时，真对象更确定
- 往 request 上挂缓存（见 response.py 的 requestId）依赖 setattr 落在真对象上
"""

from __future__ import annotations

from typing import Any, Protocol, cast

from flask import Flask, Request, current_app, request


class _LocalProxy(Protocol):
    """只说一件事：代理能把背后的真对象交出来。"""

    def _get_current_object(self) -> Any: ...


def real_app() -> Flask:
    """当前 app 的真实对象。需在应用上下文里调用。"""
    return cast("Flask", cast("_LocalProxy", current_app)._get_current_object())


def real_request() -> Request:
    """当前请求的真实对象。需在请求上下文里调用（调用方自行确认）。"""
    return cast("Request", cast("_LocalProxy", request)._get_current_object())


__all__ = ["real_app", "real_request"]
