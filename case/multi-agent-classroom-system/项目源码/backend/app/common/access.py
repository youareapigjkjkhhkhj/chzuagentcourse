"""站点访问码（P5 §6 / A13，可选开启）。

**这不是登录**。P0~P5 的归属仍是「单机本地会话」（见 common/identity.py），
访问码挡的是「这台机器被放到公网上之后，谁都能点进来」。所以它只要一件事：
**没带码的人看不到任何页面**，带了码的人一切照旧。

四个决定：

1. **默认关闭**（`SITE_ACCESS_CODE` 为空）。本地单机开发天天输密码是纯负担，
   而「默认开着但没人配」比默认关着危险得多 —— 后者只是没用上，前者会
   让所有人以为有保护。
2. **校验页由后端渲染**（`app/templates/access.html`，样式内联）。让前端 SPA
   来渲染这个页面就成了鸡生蛋：SPA 自己的 JS 也在门里，用户会看到一个转圈的
   白屏而不是一个输入框。这一页必须不依赖任何被它挡住的东西。
3. **凭据是签名过的 cookie，不是码本身**。值 = `HMAC(密钥, 码)`：拿到 cookie
   的人反推不出码，而改了码之后所有旧 cookie 立刻失效（HMAC 的密钥就是那个码）。
4. **API 与页面分开答复**。`/api/*`、`/ws/*` 直接 403 + 业务码 40304（前端据此
   跳校验页），其余走 302 跳到校验页并带 `next`。给 API 回 302 的话，fetch 会
   老老实实跟着跳，最后把一段 HTML 当成 JSON 解析 —— 那会变成一个「什么都对
   不上」的错误，而不是「你还没输访问码」。
"""

from __future__ import annotations

import hmac
import threading
import time
from hashlib import sha256
from urllib.parse import urlencode

from flask import Response, current_app, redirect, render_template, request

from app.common.logging import get_logger
from app.common.response import MESSAGES, fail

logger = get_logger("app.access")

#: 业务码：没通过访问码校验（403 段位的第四个，接在 40302 语音 / 40303 材料之后）。
CODE_ACCESS_REQUIRED = 40304

GATE_PATH = "/access"

#: 这些路径永远不挡。`/api/health` 是给容器与负载均衡的健康检查用的 ——
#: 它们没有浏览器、也拿不到 cookie，把它关在门内等于让「服务还活着吗」
#: 这个问题必须带上访问码才能问，于是健康检查永远失败，容器被反复重启。
EXEMPT_PATHS = frozenset({GATE_PATH, "/api/health"})

#: 前缀命中就按 API 答复（403 + 信封）而不是跳转。
_API_PREFIXES = ("/api/", "/ws/")

_COOKIE_PAYLOAD = b"eduagentx-access"


def _configured_code() -> str:
    return str(current_app.config.get("SITE_ACCESS_CODE") or "").strip()


def _token(code: str, secret: str) -> str:
    """cookie 里的值。密钥取 `SECRET_KEY`，没配就退回码本身。

    `SECRET_KEY` 缺省时并不比直接用码差：两边的输入都不是空的，而 HMAC
    的意义只是「别把码原样放进 cookie」。见模块 docstring 第 3 条。
    """
    key = (secret or code).encode("utf-8")
    return hmac.new(key, _COOKIE_PAYLOAD + code.encode("utf-8"), sha256).hexdigest()


def _cookie_name() -> str:
    return str(current_app.config.get("ACCESS_COOKIE_NAME") or "eduagentx_access")


def _passed() -> bool:
    """这次请求带没带一张对的 cookie。"""
    raw = request.cookies.get(_cookie_name()) or ""
    if not raw:
        return False
    code = _configured_code()
    expected = _token(code, str(current_app.config.get("SECRET_KEY") or ""))
    return hmac.compare_digest(raw, expected)


def check_code(value: str) -> bool:
    """用户提交的码对不对。定长比较，不因为「第几个字符开始不一样」泄露信息。"""
    code = _configured_code()
    return bool(code) and hmac.compare_digest(value.strip(), code)


def _safe_next(value: str) -> str:
    """`next` 只允许站内路径。

    必须挡 `//evil.com`（协议相对的绝对 URL）与 `\\evil.com`（部分浏览器把
    反斜杠当斜杠）—— 否则校验页会变成一个「输对码之后被送去任意站点」的跳板，
    而用户看到的是一闪而过的正常页面。
    """
    raw = (value or "").strip()
    if not raw.startswith("/") or raw.startswith("//") or raw.startswith("/\\"):
        return "/"
    return raw


# --- 尝试限流 ---
#
# 访问码就是一道口令，而公网上的口令输入框一定会被反复试。这里不引第三方
# 限流库：单进程内存里按 IP 记一串时间戳就够挡住「脚本每秒试一百次」——
# 真正要防的是爆破，不是精确的配额统计。
#
# **它不写库**：被拒的尝试一秒能来几百条，写进 audit_logs 就是拿攻击流量
# 打自己的库（同 services/audit.py 里那条口径）。
_attempts: dict[str, list[float]] = {}
_attempt_lock = threading.Lock()
#: 最多记这么多 IP，防止换来源刷爆内存
_ATTEMPT_MAX_KEYS = 4096


def _too_many_attempts() -> bool:
    count = int(current_app.config.get("ACCESS_RATE_LIMIT_COUNT") or 0)
    if count <= 0:
        return False
    window = float(current_app.config.get("ACCESS_RATE_LIMIT_WINDOW") or 60.0)
    now = time.monotonic()
    ip = request.remote_addr or "-"
    with _attempt_lock:
        hits = [t for t in _attempts.get(ip, []) if now - t < window]
        if len(_attempts) > _ATTEMPT_MAX_KEYS:
            # 粗暴清一遍过期的：正常流量下这一步几乎不会走到
            for key in [k for k, v in _attempts.items() if not v or now - v[-1] > window]:
                _attempts.pop(key, None)
        _attempts[ip] = hits
        if len(hits) >= count:
            return True
        hits.append(now)
        return False


def _wants_api() -> bool:
    return request.path.startswith(_API_PREFIXES)


def _deny():
    if _wants_api():
        return fail(CODE_ACCESS_REQUIRED, MESSAGES[CODE_ACCESS_REQUIRED], 403)
    target = _safe_next(request.full_path if request.query_string else request.path)
    return redirect(f"{GATE_PATH}?{urlencode({'next': target})}", code=302)


def install_access_gate(app) -> None:
    """装上门禁。没配访问码时**只注册 `/access` 的处理并直接放行**。

    `/access` 那条路径即使关着也注册：关掉门禁之后还留着一个 404 的
    `/access` 很合理，但前端在 40304 时跳的就是它 —— 少一个「未知路由」
    分支，省得排查时对不上。它此时回一句「访问码没开」而不是 404。
    """
    from app.services import audit

    @app.route(GATE_PATH, methods=["GET", "POST"], endpoint="access_gate")
    def _gate():  # pragma: no cover - 渲染路径靠验收脚本点
        """访问码校验页：GET 出表单，POST 收码、发 cookie、跳回 `next`。

        请求示例：
            GET  /access?next=/workbench    -> 表单页
            POST /access  code=...&next=... -> 302 跳 /workbench（带上 cookie）

        这一页由后端渲染（见模块 docstring 第 1 条），所以它用的是 `GET`/`POST`
        而不是 `fetch`；关掉访问码时它回一句纯文本说明，不会 404 —— 前端在
        40304 时跳的就是这个地址，少一个未知分支。
        """
        code = _configured_code()
        if not code:
            return Response("访问码未开启（SITE_ACCESS_CODE 为空）", mimetype="text/plain")
        if request.method == "GET":
            if _passed():
                return redirect(_safe_next(request.args.get("next") or "/"))
            return render_template(
                "access.html",
                next=_safe_next(request.args.get("next") or "/"),
                error="",
            )

        if _too_many_attempts():
            logger.warning("访问码尝试过于频繁 ip=%s", request.remote_addr or "-")
            return (
                render_template(
                    "access.html",
                    next=_safe_next(request.form.get("next") or "/"),
                    error="试得有点多，等一会儿再来",
                ),
                429,
            )

        if not check_code(request.form.get("code") or ""):
            logger.warning("访问码不正确 ip=%s", request.remote_addr or "-")
            return (
                render_template(
                    "access.html",
                    next=_safe_next(request.form.get("next") or "/"),
                    error="访问码不对",
                ),
                403,
            )

        target = _safe_next(request.form.get("next") or "/")
        response = redirect(target, code=302)
        # HttpOnly：这一页没有任何 JS 需要读它；SameSite=Lax：正常点击跳转能带上，
        # 跨站表单提交带不上。Secure 默认关 —— http 上开了它浏览器会直接丢掉这个
        # cookie，表现是「输对了码还是被弹回校验页」，那种问题很难往这儿想。
        response.set_cookie(
            _cookie_name(),
            _token(code, str(app.config.get("SECRET_KEY") or "")),
            max_age=int(app.config.get("ACCESS_TTL_SECONDS") or 7 * 24 * 3600),
            path="/",
            httponly=True,
            samesite="Lax",
            secure=bool(app.config.get("ACCESS_COOKIE_SECURE")),
        )
        audit.record(audit.ACTION_ACCESS_GRANT, target="site")
        logger.info("访问码通过 ip=%s", request.remote_addr or "-")
        return response

    @app.before_request
    def _guard():
        if not _configured_code():
            return None
        if request.path in EXEMPT_PATHS:
            return None
        if _passed():
            return None
        return _deny()

    # 这里读 app.config 而不是 _configured_code()：装门禁时还没有请求上下文，
    # 而 current_app 只在请求/应用上下文里才取得到。
    if str(app.config.get("SITE_ACCESS_CODE") or "").strip():
        logger.info("访问码已开启：所有页面与接口都需要先过 %s", GATE_PATH)
    else:
        logger.debug("访问码未开启（SITE_ACCESS_CODE 为空，本地单机模式）")


__all__ = ["CODE_ACCESS_REQUIRED", "GATE_PATH", "check_code", "install_access_gate"]
