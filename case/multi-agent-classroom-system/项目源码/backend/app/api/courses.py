"""课程库与工作台接口（P1 §4）。

接口层只做三件事：取参数 → 调 service → 包信封（P0 §4）。校验规则、默认值、
归属判断都在 service / common 里，这里不重复一遍 —— 重复的规则一定会分叉，
而分叉的那一份迟早是错的那份。

有一条规矩贯穿全部九个端点：**课程不存在、已删除、属于别人，一律 404**
（AGENTS §4.1）。403 等于告诉对方「这个 id 是存在的，只是不给你看」，
那就是一个可以用来枚举别人课程的信息口子。
"""

from __future__ import annotations

from flask import Blueprint, request

from app.api import json_body
from app.common import tasks
from app.common.errors import ValidationError
from app.common.identity import current_owner_id
from app.common.response import ok
from app.services.courses import library
from app.services.generation import intake

bp = Blueprint("courses", __name__, url_prefix="/api/courses")


@bp.get("")
def list_courses():
    """课程列表（P1-A10）。

    请求示例：
        GET /api/courses?status=ready&page=1&size=12

    返回 `data.items[]`，每项是首页卡片要的字段：页数、时长、状态、角色数，
    外加生成进度与 `jobId`（生成中的卡片据此订阅 SSE 进度环，§6）。
    """
    return ok(
        library.list_courses(
            owner_id=current_owner_id(),
            status=str(request.args.get("status") or "").strip(),
            page=_int_arg("page", 1),
            size=_int_arg("size", library.DEFAULT_PAGE_SIZE),
        )
    )


@bp.get("/<course_id>")
def get_course(course_id: str):
    """课程详情：meta + chapters（+ 可选 pages）。

    请求示例：
        GET /api/courses/c_01H…?withPages=1
    """
    course = library.course_or_404(course_id, current_owner_id())
    return ok(library.course_detail(course, with_pages=_flag_arg("withPages")))


@bp.delete("/<course_id>")
def delete_course(course_id: str):
    """删除课程（软删，置 `deleted_at`，§4）。

    请求示例：
        DELETE /api/courses/c_01H…

    删掉之后这门课在列表与详情里都消失，页面与版本留在库里 ——
    用户点错了还能捞回来，复盘那次生成也还有依据。
    """
    course = library.course_or_404(course_id, current_owner_id())
    return ok(library.delete_course(course))


# --- 大纲 ---


@bp.get("/<course_id>/outline")
def get_outline(course_id: str):
    """工作台左侧的大纲树（四态由页面行的状态直接给出，P1-A4）。

    请求示例：
        GET /api/courses/c_01H…/outline

    四态里只有三个来自这里（`pending` 待生成 / `ready` 已完成 / `failed` 失败）：
    「生成中」是**正在写的那一小批**，由 SSE 的 `step.progress` 实时给，
    树本身不动 —— 每逢一页写就改一次树，只会让前端反复重排。
    同一个响应里还带 `confirmable`：「确认大纲」按钮亮不亮由服务端说了算
    （AGENTS §4.3），前端自己数页数会在重连、重试之后判错。
    """
    course = library.course_or_404(course_id, current_owner_id())
    return ok(library.outline_payload(course))


@bp.post("/<course_id>/outline")
def confirm_outline(course_id: str):
    """确认/修改大纲后提交，触发后续的写页（P1-A3）。

    请求示例：
        POST /api/courses/c_01H…/outline
        {"chapters": [{"no": 1, "title": "…", "pages": [{"kind": "concept", "title": "…"}]}]}

    重复确认返回 409（P1-B3）：任务已经过了这个点，再按新大纲重铺会把
    正在写、或者已经写好的页面推倒，那不是「确认」，是「重来一遍」。
    """
    course = library.course_or_404(course_id, current_owner_id())
    job = library.ensure_confirmable(course)

    outline = intake.clean_outline(json_body(), options=dict(job.options or {}))
    result = library.confirm_outline(course, outline)
    submitted = tasks.submit_job(job.id, resume=True)
    return ok({**library.outline_payload(course), "pageCount": result["pageCount"],
               "resumed": submitted})


# --- 页面 ---


@bp.get("/<course_id>/pages/<int:page_no>")
def get_page(course_id: str, page_no: int):
    """单页详情（工作台右侧编辑区）。

    请求示例：
        GET /api/courses/c_01H…/pages/5

    返回该页的 `dsl`（讲稿 / 要点 / 图示按页型而定）、页型、`status` 与 `rev`。
    页号越界是 40001（P1-B3）：页号由服务端分配，编号对不上说明前端拿的是
    旧的大纲，报错比返回一个空页有用。
    """
    course = library.course_or_404(course_id, current_owner_id())
    page = library.page_or_400(course, page_no)
    return ok(page.to_dict(include_dsl=True))


@bp.put("/<course_id>/pages/<int:page_no>")
def update_page(course_id: str, page_no: int):
    """人工编辑页面字段（P1-A11）。

    请求示例：
        PUT /api/courses/c_01H…/pages/5
        {"narration": [{"text": "这一句换个说法。"}]}

    改完落一条 `reason=manual` 的版本记录，`rev` +1 —— 编辑也是版本，
    和生成、重写一样可以回溯。
    """
    course = library.course_or_404(course_id, current_owner_id())
    page = library.page_or_400(course, page_no)
    return ok(library.update_page(page, json_body()))


@bp.post("/<course_id>/pages/<int:page_no>/rewrite")
def rewrite_page(course_id: str, page_no: int):
    """AI 重写一页（P1-A7）。

    请求示例：
        POST /api/courses/c_01H…/pages/7/rewrite
        {"instruction": "更通俗"}

    同步返回新版本：用户点「重写」就等着看结果，再套一层任务与轮询
    只会多出一套要维护的状态。
    """
    course = library.course_or_404(course_id, current_owner_id())
    page = library.page_or_400(course, page_no)
    body = json_body(required=False)
    instruction = intake.clean_instruction(body.get("instruction")) or "更通俗"
    return ok(library.rewrite_page(course, page, instruction))


@bp.get("/<course_id>/pages/<int:page_no>/versions")
def list_versions(course_id: str, page_no: int):
    """一页的版本链，新的在前（§4，为 P6.4 的回滚预留）。

    请求示例：
        GET /api/courses/c_01H…/pages/7/versions?withDsl=1
    """
    course = library.course_or_404(course_id, current_owner_id())
    page = library.page_or_400(course, page_no)
    return ok({"items": library.versions_of(page, with_dsl=_flag_arg("withDsl"))})


# --- 参数 ---


def _int_arg(name: str, default: int) -> int:
    """取一个整数查询参数。给了但不合法要报 40001，而不是悄悄用默认值 ——
    「我明明传了 size=100，怎么还是 12 条」是比报错更难查的一类问题。"""
    raw = request.args.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError as exc:
        raise ValidationError(f"{name} 必须是一个整数") from exc


def _flag_arg(name: str) -> bool:
    raw = str(request.args.get(name) or "").strip().lower()
    return raw not in {"", "0", "false", "no", "off"}


__all__ = ["bp"]
