"""导出接口（P5-4 / §4.1 那五条路由）。

接口层还是那三件事（取参数 → 调 service → 包信封），但这个域有四处只有接口层能决定：

1. **下载地址是签出来的**（`_file_url`）。`GET /api/exports/{id}/download` 会被
   **浏览器直接打开** —— 而浏览器跟链接时不会带 `X-Owner-Id` 请求头。
   所以归属必须写在 URL 里：签发一张一次性的票据（`voice/tickets.py`，
   与语音/课堂共用一套，只是 `scope` 换成 `export:{id}`），下载时核销它换出归属人。
   票据是**一次性**的：链接被抄走（浏览器历史、聊天记录、日志）也只能用一次。

2. **不可见的资源是 404**（AGENTS §4.1）。导出、课程、课堂记录都走这一条 ——
   403 等于承认「这个 id 存在，只是不给你看」。课堂记录的归属在
   `queue.create` 里就判了（越权请求不该先排上队再变成一个失败行）。

3. **`fileUrl` 只在能下载时出现**，而且**每次轮询都会换一张新票**。前端因此
   必须在**点下载前重新问一次状态**，不要缓存上一次拿到的链接：
   票是一次性的，用过即废，而缓存下来的那张票在几分钟后也会自己过期。

4. **删产物不打断正在跑的导出**（40902）。后台线程手里攥着那一行的对象，
   删了行它照样会写出文件、再把行插回去 —— 一个「删了又回来」的幽灵记录。

蓝图不带 `url_prefix`（同 `materials.py` / `voice.py` / `classroom.py`）：
课程下面那两条路由写全路径，才看得出它们是这个域的东西。
"""

from __future__ import annotations

import re

from flask import Blueprint, request, send_file

from app.api import json_body
from app.common.errors import NotFoundError, StateError, ValidationError
from app.common.identity import current_owner_id, owned_by
from app.common.response import ok
from app.extensions import db
from app.models import Course, Export
from app.services import audit
from app.services.courses import library as courses
from app.services.exports import queue, store
from app.services.voice import tickets

bp = Blueprint("exports", __name__)

#: 产物格式 → MIME。`html` 那份给 `text/html`，但下载一律走
#: `as_attachment=True`，所以它只会被存成文件、不会在标签页里被渲染出来。
MIMETYPES = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
    "html": "text/html; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
}

#: 列表的默认条数与上限。导出历史比材料列表还短（同一门课导几次就到头了），
#: 默认 20 够铺满一屏。
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

#: 下载票据的有效期。比语音那张 60 秒的票长得多，因为这两张票的用法不一样：
#: 语音的票是「拿到就立刻建连」，中间隔不下人；下载链接是**给人点的**，
#: 用户可能开着导出历史那一页、过几分钟才去点它。十分钟仍然远短于产物
#: 自己的 24 小时（`expires_at`）—— 票据不该比它保护的东西活得久。
DOWNLOAD_TTL_SECONDS = 600

#: 核销失败时告诉前端**退到哪条路**（`tickets.consume` 的 `fallback`）。
#: 语音退到文字问答、课堂退到手动翻页，下载没有第二形态可退 ——
#: 它能做的是「回去重新问一次状态」，拿一张新票再来。
_FALLBACK = "refetch"

#: 文件名里不能出现的东西。`send_file` 会把中文名编成 RFC 5987（`filename*=UTF-8''…`），
#: 但它**不负责**把这些拿掉 —— 那是我们的事：这个名字来自课程标题，而标题是用户输入。
#:
#: 除了 `\ / : * ? " < > |` 与控制字符，还要压掉**连续的点**：`../..` 这种片段
#: 放进文件名里，一半的客户端会把它解释成往上跳一级，另一半会显示成
#: 一串看不懂的点。两边都不该发生。
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]+|\.{2,}')

#: 文件名里课程标题的截断长度。留出后缀与「-课件」的位置，别让一个长标题
#: 把整个文件名顶到操作系统的上限上。
_TITLE_LIMIT = 60


# --- 建 ---


@bp.post("/api/courses/<course_id>/exports")
def create_export(course_id: str):
    """创建一次导出并立刻返回（P5-A5 / F5-6）。

    请求示例：
        POST /api/courses/c_01H…/exports
        {"format": "pptx", "scope": "course",
         "options": {"watermark": true, "withNotes": true, "withQuiz": true}}

        POST /api/courses/c_01H…/exports
        {"format": "md", "scope": "record", "sessionId": "s_01H…"}

    返回 201 与 `{exportId, status, progress, …}`。**渲染不在这里发生**：
    PDF 要一两秒、PPTX 几百毫秒，同步做就是把用户按在一个转圈的页面上，
    而进度（`progress`）也必须在请求返回之后还有人更新它。

    格式与范围对不上（比如课件导 `md`）当场回 40001，不留到渲染时才发现 ——
    用户等三秒拿到一句「这个格式不支持」，比当场告诉他糟得多。
    """
    course = courses.course_or_404(course_id, current_owner_id())
    body = json_body()
    options = body.get("options")
    row = queue.create(
        course,
        fmt=str(body.get("format") or ""),
        scope=str(body.get("scope") or "course"),
        session_id=str(body.get("sessionId") or ""),
        options=options if isinstance(options, dict) else None,
        owner_id=current_owner_id(),
    )
    queue.submit(row.id)
    # 导出是「把课程内容带出这台机器」的动作，P5-A14 点名要留痕。
    # 记格式与范围（决定了产物里有什么），**不记产物内容**。
    audit.record(
        audit.ACTION_EXPORT_CREATE,
        target=f"export:{row.id}",
        owner_id=current_owner_id(),
        detail={"courseId": course.id, "format": row.format, "scope": row.scope},
    )
    return ok(_payload(row), http_status=201)


# --- 读 ---


@bp.get("/api/exports/<export_id>")
def get_export(export_id: str):
    """任务状态：进度、产物大小、到期时间、`error`（F5-6）。

    请求示例：
        GET /api/exports/e_01H…

    前端拿它做两件事：渲染进度条（`status` + `progress`），以及**下载前取链接**
    （`fileUrl`）。后者每次都会换一张新票，所以别把它缓存起来复用。

    `progress` 是「画完几页 / 共几页」算出来的（`queue._render`），不是估的。
    """
    # 轮询读的是后台线程**刚写进去**的值，而会话缓存里的那份副本不会自己过期：
    # 不读到最新的，进度条就会一直停在打开页面那一刻的格子上。
    db.session.expire_all()
    row = _visible_or_404(export_id, current_owner_id())
    return ok(_payload(row))


@bp.get("/api/courses/<course_id>/exports")
def list_exports(course_id: str):
    """这门课的导出历史（新的在前）。

    请求示例：
        GET /api/courses/c_01H…/exports?page=1&size=20

    多取一条判断 `hasMore`，与材料列表同一个口径 —— 列表页要知道的是
    「还有没有下一页」，不是「总共有多少条」。

    `items[].fileUrl` 在这里**是空的**：列表只回答「哪些能下」（`downloadable`），
    链接由点击前那一次单条查询现签。理由见 `_payload` 的 `signed`。
    """
    course = courses.course_or_404(course_id, current_owner_id())
    page = max(1, _int_arg("page", 1))
    size = max(1, min(_int_arg("size", DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))
    rows = queue.list_of_course(course.id, limit=size + 1, offset=(page - 1) * size)
    return ok(
        {
            "items": [_payload(row, signed=False) for row in rows[:size]],
            "page": page,
            "size": size,
            "hasMore": len(rows) > size,
            "supported": {
                scope: list(queue.supported_formats(scope))
                for scope in ("course", "record")
            },
        }
    )


@bp.get("/api/exports/<export_id>/download")
def download_export(export_id: str):
    """取走产物文件（F5-6）。

    请求示例：
        GET /api/exports/e_01H…/download?token=<一次性票据>

    这条路由**不带 JSON 信封**：响应体是文件本身，`Content-Disposition`
    带着一个能看懂的中文文件名（`机器学习入门-课件.pptx`，走 RFC 5987）。

    没带票据时退回请求头里的归属（本机部署下就是那位老师），带了票据就
    **只认票据**：它已经说明「这张票是给谁的」，再去比一次请求头只会在
    浏览器不带头的正常路径上把一次合法下载判成越权。
    """
    token = str(request.args.get("token") or "").strip()
    if token:
        owner_id = tickets.consume(token, scope=_scope_of(export_id), fallback=_FALLBACK)
    else:
        owner_id = current_owner_id()

    row = _visible_or_404(export_id, owner_id)
    if not row.downloadable:
        raise StateError(_not_ready_reason(row), details={"status": row.status})
    if queue.expired(row):
        # 行还在、文件也还在，只是过了我们承诺的那 24 小时（清理任务还没扫到它）。
        # 照发出去等于把 `expires_at` 变成一句装饰 —— 这份产物随时会消失，
        # 不如现在就说清楚，让人去重导一次。
        raise StateError(
            "这份产物已过期（产物只保留 24 小时），重新导出一次",
            details={"expiresAt": row.expires_at},
        )

    path = store.file_of(row)
    if path is None:
        # 行在而文件不在是正常会发生的：有人清了 data/ 或清理任务刚删了文件。
        # 给的不是 500 —— 库没坏，是产物没了。
        raise NotFoundError("导出文件不存在或已被清理，重新导出一次")

    return send_file(
        path,
        mimetype=MIMETYPES.get(row.format, "application/octet-stream"),
        as_attachment=True,
        download_name=_filename(row, _course_title(row)),
        # 支持 Range：断点续传、以及看 PDF 时直接翻页
        conditional=True,
        max_age=0,
    )


# --- 删 ---


@bp.delete("/api/exports/<export_id>")
def delete_export(export_id: str):
    """删掉一次导出：产物文件与那一行（F5-6）。

    请求示例：
        DELETE /api/exports/e_01H…

    正在跑的那一次**不删**（40902）：后台线程手里攥着这一行的对象，
    删了行它照样把文件写出来、再把行插回去 —— 用户会看到一份刚删掉的记录
    自己回来了。等它跑完再删（几秒钟的事），或者干脆让它失败。
    """
    row = _visible_or_404(export_id, current_owner_id())
    if row.status in {"queued", "running"}:
        raise StateError(
            "这次导出还在进行中，等它结束再删",
            details={"status": row.status, "progress": row.progress},
        )
    return ok(queue.remove(row))


# --- 组装 ---


def _payload(row: Export, *, signed: bool = True) -> dict:
    """一行导出 → 接口载荷。存储事实来自 `Export.to_dict()`，这里只加两样：

    - `downloadable`：前端据此决定「下载」按钮亮不亮（比让前端自己拼
      `status == "done" && filePath` 强 —— 那条件改一次就要改两处）。
    - `fileUrl`：签过票的下载地址，见模块 docstring 第 3 条。

    `signed=False` 给**列表**用：那里一串二十行，每行签一张票就是二十张没人用的票
    （票据是内存表，一张活十分钟）。列表只回答「哪些能下」，链接由点击前那一次
    单条查询现签 —— 于是「别缓存下载链接」这件事从一句劝告变成了结构上做不到。
    """
    data = row.to_dict()
    # 主键在这份载荷里叫 `exportId`（§4.1）。模型那边叫 `id` 是因为它描述的是
    # 一行记录，而这里描述的是一个**资源** —— 换个名字比让前端记住「导出的
    # id 字段跟别处不一样」便宜。
    data["exportId"] = data.pop("id")
    data["downloadable"] = bool(row.downloadable) and not queue.expired(row)
    data["fileUrl"] = _file_url(row) if signed else ""
    data.pop("filePath", None)  # 盘上路径不出去：它回答不了用户的任何问题
    return data


def _file_url(row: Export) -> str:
    """给这一行签一个下载地址。**只在真能下载时才签**。

    别的状态下签出来的票没人会用，而票据存在内存里（`tickets` 是一张表）——
    一个每 3 秒轮询一次、连查 10 分钟的页面会白攒 200 张废票。
    前端拉到最后一次状态时正好拿到链接，点下载就走。
    """
    if not row.downloadable or queue.expired(row):
        return ""
    owner = row.owner_id or current_owner_id()
    ticket = tickets.issue(owner, ttl=DOWNLOAD_TTL_SECONDS, scope=_scope_of(row.id))
    return f"/api/exports/{row.id}/download?token={ticket['ticket']}"


def _scope_of(export_id: str) -> str:
    """下载票的用途：**一张票只对一次导出有效**。

    不带 `scope` 的话，为 A 签的票改一下 URL 就能下载 B —— 而这两份产物
    的归属本来可以不一样（同一个人导的，也该各是一次一票）。
    """
    return f"export:{export_id}"


def _visible_or_404(export_id: str, owner_id: str) -> Export:
    """取一行并判归属。不存在与越权都回 404（AGENTS §4.1）。"""
    row = queue.require(export_id)
    if not owned_by(row, owner_id):
        raise NotFoundError("导出任务不存在")
    return row


def _not_ready_reason(row: Export) -> str:
    """「还不能下载」要说清是为什么 —— 三种状态，用户要做的事各不相同。"""
    if row.status == "failed":
        return row.error or "这次导出失败了，重新导出一次"
    if row.status in {"queued", "running"}:
        return "这次导出还在进行中，稍等一下"
    return "这次导出没有可下载的产物，重新导出一次"


def _course_title(row: Export) -> str:
    """下载文件名前缀用的课程名。课程没了就退成 id，不编一个名字出来。"""
    course = db.session.get(Course, row.course_id)
    return str(getattr(course, "title", "") or row.course_id)


def _filename(row: Export, course_title: str) -> str:
    """`机器学习入门-课件.pptx`。

    后缀取**枚举里的那个值**（`row.format`），不是从 `file_path` 尾巴上割的 ——
    后者在有人手改过库里那一列时会把一个奇怪的扩展名送给浏览器。

    课程标题只留一层：路径分隔符、引号与连续的点全部换成下划线，两头的点去掉
    （`.` 开头在类 Unix 上是隐藏文件，而 `-课件.pptx` 这种名字看着像没名字）。
    """
    what = "课堂记录" if row.scope == "record" else "课件"
    base = _UNSAFE_NAME.sub("_", str(course_title or "")).strip()[: _TITLE_LIMIT]
    stem = f"{base.strip().strip('.') or '导出'}-{what}"
    return f"{stem}.{row.format}"


def _int_arg(name: str, default: int) -> int:
    """取一个整数查询参数。给了但不合法报 40001，而不是悄悄用默认值
    （同 `materials._int_arg`）。"""
    raw = request.args.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError as exc:
        raise ValidationError(f"{name} 必须是一个整数") from exc


__all__ = ["DEFAULT_PAGE_SIZE", "DOWNLOAD_TTL_SECONDS", "MIMETYPES", "bp"]
