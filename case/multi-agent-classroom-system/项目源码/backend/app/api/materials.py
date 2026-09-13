"""材料接口（P4-3 / F4-1~F4-9）。

九个端点分四组：上传与列表、详情与分块（抽屉）、检索（工作台）、删改与课程关联。
接口层还是那三件事（取参数 → 调 service → 包信封），但有三处**只有接口层**能决定：

1. **404 与 403 不分家**（AGENTS §4.1）。材料的归属判断全在 `store.get_material()`
   里，接口层不再自己查一遍 —— 两处判断迟早分叉，而分叉的那一份会漏。
2. **删除要二次确认**：被课程引用过（`impact.pages > 0`）时先回 40901 与影响面
   （「3 页引用将失效」），用户确认后带 `?force=1` 再来一次。这条不能放在 service
   里：service 只答「删了会怎样」，要不要拦是接口的取舍。
3. **检索不到就算了**：`q` 为空或没有一份可搜的材料 → 空列表而不是报错。
   工作台的搜索框是**边打边搜**的，中间态（刚清空、只打了半个词）报错会把
   一次正常输入变成一串错误提示。
4. **总开关关着时怎么答**（P4-G3），见 `_require_enabled()` 上面那段 ——
   清单类读接口回 200 + 空，单个对象的读写回 40303。

蓝图不带 `url_prefix`（同 `voice.py` / `classroom.py`）：课程关联那两条路由在
`/api/courses/…` 下面，写全路径才看得出来它们是这个域的东西。
"""

from __future__ import annotations

from flask import Blueprint, request

from app.api import json_body
from app.common.errors import ConflictError, ValidationError
from app.common.identity import current_owner_id
from app.common.response import ok
from app.services.courses import library as courses
from app.services.materials import policy, store

bp = Blueprint("materials", __name__)

#: 列表与分块分页的默认条数。材料列表比课程列表短得多（一个人几十份顶天），
#: 所以默认给 50；分块动辄几百条，默认 50 一页刚好是抽屉里滚一屏。
DEFAULT_PAGE_SIZE = 50


# --- 总开关（P4-G3）---


def _require_enabled() -> None:
    """材料总开关关着 → 40303。**单个对象**的读写都走这里。

    清单类读接口（`GET /api/materials`、`/materials/search`、
    `/courses/{id}/materials`）刻意**不**走这里，它们回 200 + 空清单 +
    `enabled: false`：

    - 这三条在前端是**渲染路径**（列表挂载、抽屉打开、检索边打边搜），
      报错会把「这个部署没开材料」变成用户面前的一串红色提示。
    - 空清单本身就是准确的答案 —— 没开材料，就一份材料都没有。
    - 前端要判断「该不该显示材料入口」看的是 `/api/capabilities` 里的
      `materials.enabled`，而不是靠这里的错误码去猜。

    单个对象的读（详情、分块）与所有写操作则一律 40303：它们只会在入口
    可见时才被调到，真被调到就是**一个不该发生的动作**，那里说清原因。
    """
    if not policy.enabled():
        raise policy.disabled()


# --- 上传与列表 ---


@bp.post("/api/materials")
def upload_material():
    """上传一份材料并异步解析（F4-1 / P4-A1）。

    请求示例：
        POST /api/materials        (multipart/form-data, 字段名 file)

    返回 201 与 `{fileId, name, sizeBytes, pages, chunkCount, status, duplicated}`。
    `status` 回来就是 `parsing`（解析在后台线程里跑），前端据此显示进度并轮询
    详情；`duplicated=1` 表示这份内容已经在库里了（P4-C4），**不会再解析一次**，
    此时是 200 而不是 201 —— 前端据此提示「这份材料已经在库里」而不是「上传成功」。

    开关关着 → 40303（`store.create_from_upload` 里也拦了一道，那是给不经接口层
    的调用方留的）。
    """
    _require_enabled()
    upload = request.files.get("file")
    if upload is None:
        raise ValidationError("没有收到文件：请用 multipart/form-data 的 file 字段上传")

    material, existed = store.create_from_upload(upload, owner_id=current_owner_id())
    data = material.to_dict()
    data["duplicated"] = existed
    return ok(data, http_status=200 if existed else 201)


@bp.get("/api/materials")
def list_materials():
    """材料列表（F4-2）。

    请求示例：
        GET /api/materials?status=ready&page=1&size=50

    多取一条来判断 `hasMore`（`size + 1`），省掉一次 `count(*)` ——
    列表页只需要知道「还有没有下一页」，数总共有多少条是另一件事。

    `enabled` 是材料总开关（P4-G3）。关着时回 200 + 空清单而不是 40303，
    理由见 `_require_enabled()`。
    """
    page = max(1, _int_arg("page", 1))
    size = max(1, min(_int_arg("size", DEFAULT_PAGE_SIZE), 200))
    if not policy.enabled():
        return ok({"enabled": False, "items": [], "page": page, "size": size, "hasMore": False})
    rows = store.list_materials(
        owner_id=current_owner_id(),
        status=str(request.args.get("status") or "").strip(),
        limit=size + 1,
        offset=(page - 1) * size,
    )
    return ok(
        {
            "enabled": True,
            "items": [row.to_dict() for row in rows[:size]],
            "page": page,
            "size": size,
            "hasMore": len(rows) > size,
        }
    )


@bp.get("/api/materials/search")
def search_materials():
    """BM25 检索（F4-5 / P4-A3/A4）。

    请求示例：
        GET /api/materials/search?q=倒排索引&fileIds=m_1,m_2&topK=8

    `fileIds` 给了就只搜这几份（工作台里勾了哪几份就搜哪几份），没给就搜当前
    用户的全部已就绪材料 —— 两种情况都在 service 里收敛到「他确实能搜的」。

    开关关着时回空（P4-G3）：检索是边打边搜的，这里报错等于用户每敲一个字
    挨一次提示；而「搜不到」与「没开材料」在界面上本来就是同一个样子。
    """
    query = str(request.args.get("q") or "").strip()
    hits = (
        store.search_materials(
            query,
            owner_id=current_owner_id(),
            file_ids=_ids_arg("fileIds"),
            top_k=_int_arg("topK", 8),
        )
        if query and policy.enabled()
        else []
    )
    return ok({"enabled": policy.enabled(), "query": query, "items": [hit.to_dict() for hit in hits]})


# --- 详情与分块 ---


@bp.get("/api/materials/<material_id>")
def get_material(material_id: str):
    """详情：元信息 + 目录树 + 影响面（F4-6 / P4-A13）。

    请求示例：
        GET /api/materials/m_01H…

    `impact`（有几页引用它、关联在几门课里）跟着详情一起回来，于是删除确认框
    一打开就是填好的 —— 用户点「删除」之前那次请求已经把这些数字取到了。
    """
    _require_enabled()
    material = store.get_material(material_id, owner_id=current_owner_id())
    data = store.detail(material.id, owner_id=current_owner_id())
    data["impact"] = store.impact(material.id, owner_id=current_owner_id())
    return ok(data)


@bp.get("/api/materials/<material_id>/chunks")
def list_chunks(material_id: str):
    """分块分页（F4-6）。

    请求示例：
        GET /api/materials/m_01H…/chunks?page=1&size=50&section=第一章 检索
    """
    _require_enabled()
    return ok(
        store.list_chunks(
            material_id,
            owner_id=current_owner_id(),
            page=_int_arg("page", 1),
            size=_int_arg("size", DEFAULT_PAGE_SIZE),
            section=str(request.args.get("section") or "").strip(),
        )
    )


@bp.get("/api/materials/<material_id>/chunks/<chunk_id>")
def get_chunk(material_id: str, chunk_id: str):
    """单个分块的原文（溯源徽标跳过来看的那一段，P4-A6）。

    请求示例：
        GET /api/materials/m_01H…/chunks/k_01H…
    """
    _require_enabled()
    chunk = store.get_chunk(material_id, chunk_id, owner_id=current_owner_id())
    return ok(chunk.to_dict())


# --- 删除 ---


@bp.delete("/api/materials/<material_id>")
def delete_material(material_id: str):
    """删除材料及其分块与索引（F4-9 / P4-C1）。

    请求示例：
        DELETE /api/materials/m_01H…
        DELETE /api/materials/m_01H…?force=1      # 确认过了

    被课程引用着（有页面把它的片段当出处）时，第一次回 40901 与影响面；
    前端把 `details.impact` 显示成「3 页引用将失效，确定删除？」。
    """
    _require_enabled()
    owner = current_owner_id()
    impact = store.impact(material_id, owner_id=owner)
    if impact["pages"] > 0 and not _flag_arg("force"):
        raise ConflictError(
            f"有 {impact['pages']} 页引用了这份材料，删除后这些引用会失效",
            details={"needConfirm": True, "impact": impact},
        )
    return ok(store.delete_material(material_id, owner_id=owner))


# --- 与课程的关联（P4-7 / F4-7 / F4-14）---


@bp.get("/api/courses/<course_id>/materials")
def list_course_materials(course_id: str):
    """一门课已经关联了哪些材料（抽屉里标「已加入」）。

    请求示例：
        GET /api/courses/c_01H…/materials

    课程不存在或不属于当前用户 → 404（与课程接口同一个口径）。开关关着 → 空清单
    （同 `GET /api/materials`）—— 课程的 404 仍照判，课程本身与材料开关无关。
    """
    courses.course_or_404(course_id, current_owner_id())
    if not policy.enabled():
        return ok({"enabled": False, "items": []})
    rows = store.materials_of_course(course_id, owner_id=current_owner_id())
    return ok({"enabled": True, "items": [row.to_dict() for row in rows]})


@bp.post("/api/courses/<course_id>/materials")
def attach_materials(course_id: str):
    """把材料关联到课程（F4-7）。

    请求示例：
        POST /api/courses/c_01H…/materials
        {"fileIds": ["m_01H…", "m_02H…"]}

    关联之后生成链路就会在生成/重写时检索这些材料（P4-4）。
    已经在课里的返回在 `skipped` 里，不算失败 —— 重复点「加入」不该报错。
    """
    _require_enabled()
    body = json_body()
    file_ids = body.get("fileIds")
    if not isinstance(file_ids, list) or not [item for item in file_ids if item]:
        raise ValidationError("fileIds 必须是一个非空的材料 id 列表")
    return ok(store.attach_to_course(course_id, file_ids, owner_id=current_owner_id()))


@bp.delete("/api/courses/<course_id>/materials/<material_id>")
def detach_material(course_id: str, material_id: str):
    """从课程里移除一份材料（F4-14）。材料本身留着 —— 它属于用户，不属于这门课。

    请求示例：
        DELETE /api/courses/c_01H…/materials/m_01H…


    返回 `affectedCitations`：这门课里有多少处溯源引用了它。移除**不删**已生成的
    页面（那要用户明确去改内容），所以前端把「N 处引用将失效」显示成提示，
    而不是当成一次删除的后果。
    """
    _require_enabled()
    return ok(
        store.detach_from_course(course_id, material_id, owner_id=current_owner_id())
    )


# --- 参数 ---


def _int_arg(name: str, default: int) -> int:
    """取一个整数查询参数。给了但不合法报 40001，而不是悄悄用默认值
    （同 `courses._int_arg`：默认值会让「我明明传了 size=100」变成查不出的问题）。"""
    raw = request.args.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError as exc:
        raise ValidationError(f"{name} 必须是一个整数") from exc


def _flag_arg(name: str) -> bool:
    """`?force=1` / `?force=true` 都算真；不传或空算假。"""
    raw = str(request.args.get(name) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _ids_arg(name: str) -> list[str]:
    """id 列表参数：`?fileIds=a,b` 与 `?fileIds=a&fileIds=b` 都收。

    两种写法在前端各有各的自然写法（拼串 vs `URLSearchParams.append`），
    让接口两种都认，比让调用方记住「本接口只认逗号」便宜。
    """
    values: list[str] = []
    for raw in request.args.getlist(name):
        values.extend(part.strip() for part in str(raw).split(","))
    return [value for value in values if value]


__all__ = ["DEFAULT_PAGE_SIZE", "bp"]
