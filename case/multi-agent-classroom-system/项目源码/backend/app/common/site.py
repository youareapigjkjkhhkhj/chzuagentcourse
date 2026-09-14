

"""托管前端产物（P5 §6「app 容器同时托管 frontend/dist」）。

开发态是 Vite 在 5173 上服务页面、后端只管 `/api`（README 的两条命令）。
生产把这个顺序反过来：一个容器、一个端口就是完整站点，浏览器只跟 Flask 说话。

三件事：

1. **目录不存在就不注册任何路由**。开发机上根本没跑过 `npm run build`，
   注册了也只会多出一堆 404；而不注册时 `/` 走 Flask 自己的 404，
   与「这里本来就没有页面」是一回事。
2. **`/api/*`、`/ws/*` 的未知路径不落到 SPA 上**。通配路由会把它们接住，
   于是 `GET /api/typo` 会返回一份 HTML —— 前端的 axios 会把它当 JSON 解析，
   报出一句与真实原因毫无关系的话（同 common/access.py 第 4 条）。
   这里直接给 404 信封，让它和别的「没这个接口」长得一样。
3. **带扩展名又找不到的文件就是 404，不带扩展名的交给 index.html**。
   前端是 history 路由（`createWebHistory`），`/workbench` 这种地址在盘上
   没有对应文件，必须由 SPA 自己解析；而 `/assets/foo.js` 找不到就是找不到，
   给它回一份 HTML 只会让浏览器报「语法错误」，把真正的原因盖掉。
4. **兜底只给「浏览器导航」**（`Accept` 首选 `text/html`）。不带这个头的
   请求（curl、探针、XHR）走第 3 条之外的 404 信封 —— 否则 Flask 自带的
   404 在这台服务上会凭空消失，`/_definitely_not_here` 也会回 200。
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, request, send_from_directory
from werkzeug.exceptions import NotFound

from app.common.logging import get_logger

logger = get_logger("app.site")

#: 这些前缀是后端的，永远不该由前端产物接管
_BACKEND_PREFIXES = ("api/", "ws/")

#: 构建产物里的静态文件名带内容哈希，改内容必改名字 —— 可以放心长缓存。
#: index.html 反过来必须每次问一次，否则用户会一直拿着旧版本、指着一个
#: 早就修好的 bug 说没修（这条比省下的那点带宽值钱得多）。
_IMMUTABLE_CACHE = "public, max-age=31536000, immutable"


def install_frontend(app: Flask) -> None:
    dist = Path(str(app.config.get("FRONTEND_DIST") or ""))
    index = dist / "index.html"
    if not index.is_file():
        logger.debug("前端产物不存在（%s），只提供 API", dist)
        return

    logger.info("托管前端产物：%s", dist)

    @app.route("/", defaults={"path": ""}, endpoint="site_root")
    @app.route("/<path:path>", endpoint="site_path")
    def _serve(path: str):
        """托管前端页面：盘上有这个文件就给文件，没有就交给 index.html 走前端路由。

        请求示例：
            GET /workbench   -> index.html（history 路由由前端自己解析）
            GET /assets/x.js -> 文件本身；盘上没有这个文件就是 404

        只有「浏览器在导航」（Accept 首选 text/html）才落到 SPA 上 —— 见 `_wants_html`。
        """
        if path.startswith(_BACKEND_PREFIXES):
            # 交给统一的 404 信封（install_error_handlers 那条），
            # 而不是让这里编一句自己的话
            raise NotFound

        # 解析之后再比一次父目录：`..` 与符号链接都不能跑到 dist 外面去
        # （send_from_directory 自己也会挡，这里多一道是因为**判断**也要挡：
        # 用 `Path.exists()` 判过再交给 send_from_directory，等于给了它一个
        # 能区分「存在但越界」与「不存在」的旁路）。
        target = (dist / path).resolve() if path else index
        try:
            inside = target.is_relative_to(dist.resolve())
        except OSError:  # pragma: no cover - 路径异常（超长/权限）一律当没有
            inside = False

        if path and inside and target.is_file():
            response = send_from_directory(dist, path)
            if path.startswith("assets/"):
                response.headers["Cache-Control"] = _IMMUTABLE_CACHE
            return response

        if path and Path(path).suffix:
            raise NotFound
        if not _wants_html():
            # 不是浏览器在导航（XHR / curl / 探针）。它要的不是一份页面，
            # 而把「这个地址没有内容」回成 200 + HTML，比 404 难查得多：
            # 前端拿到一坨 HTML 去 `JSON.parse`，报出来的错和真实原因隔着三层。
            raise NotFound
        return _index(index)

    def _index(index_path: Path):
        response = send_from_directory(index_path.parent, index_path.name)
        response.headers["Cache-Control"] = "no-cache"
        return response


def _wants_html() -> bool:
    """这次请求是「浏览器在导航」吗？

    浏览器导航一定带 `Accept: text/html,...`，而 axios 默认是
    `application/json, text/plain, */*`。两者都会命中 `*/*`，所以要比的是
    **text/html 的质量值高于 JSON**，而不是「能不能接受 HTML」——
    后者对任何 `*/*` 都成立，等于没判。

    没有 Accept 头（curl、容器探针）的一概不算：它们要的从来不是页面。
    """
    accept = request.accept_mimetypes
    html = accept["text/html"]
    return bool(html) and html > accept["application/json"]


__all__ = ["install_frontend"]
