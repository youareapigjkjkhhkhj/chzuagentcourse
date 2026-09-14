"""导出队列（P5-A5 / F5-6）。

一次导出的寿命：`queued → running → done | failed`。**状态只活在数据库里**，
队列本身不留任何内存状态 —— 这与 P1 生成管线是同一条约定（AGENTS §4.3），
理由也一样：服务重启之后，`running` 的那些行会被收拾成 `failed`（可重跑），
而不用指望某个内存队列还在。

对外就四个动作：

- `create()` —— 建一行 `queued`。**不渲染**，接口层要立刻返回。
- `submit()` —— 丢进后台线程池。同一次导出只会有一个线程在跑。
- `run()` —— 真正干活：DSL（或课堂记录）→ IR → 字节 → 落盘 → 改行。同步执行，
  所以测试能直接驱动它，不必为「等一个后台线程」在断言里塞 sleep。
- `cleanup()` —— 删过期产物与行。**没有 `expired` 状态**：留着点不动的条目
  只会把导出历史弄脏（`models/export.py` 的模块注释第 3 条）。

### 为什么导出要走后台

渲染 12 页 PPTX 大约几百毫秒、PDF 要一两秒，听起来「同步做也行」。但：

1. 并发几个导出一起排队时，请求线程会被占住，而线程池是有界的（`GEN_WORKERS`）。
2. 进度（`progress` 那一列）**必须有人来更新**，请求线程返回之后没人更新它了。
3. 一次导出失败要留下原因 —— 同步做的话，那个原因只能变成一个 500。

### 每种格式走哪条路

| 格式 | 课件（`scope=course`） | 课堂记录（`scope=record`） |
|------|----------------------|--------------------------|
| pptx | `pptx.render` | 不支持 |
| html | `html.document` | 不支持 |
| pdf  | `pdf.render` | `record.to_deck` → `pdf.render` |
| md   | 不支持 | `record.to_markdown` |

不支持的那几格在 `create()` 就挡住了（40001），不留到渲染时才发现 ——
用户等 3 秒拿到一句「这个格式不支持」，比当场告诉他糟得多。
"""

from __future__ import annotations

from typing import Any, Mapping

from app.common.dbw import db_write
from app.common.errors import NotFoundError, StateError, ValidationError
from app.common.logging import get_logger
from app.common.tasks import get_runner
from app.common.timeutil import parse_iso, to_iso, utcnow, utcnow_iso
from app.extensions import db
from app.models import Course, CoursePage, Export, Material, PageSource
from app.services.exports import html as html_renderer
from app.services.exports import pdf as pdf_renderer
from app.services.exports import pptx as pptx_renderer
from app.services.exports import record as record_renderer
from app.services.exports import store
from app.services.exports import theme as theme_registry
from app.services.exports.ir import Deck, RenderOptions, Source, from_dsl

logger = get_logger("app.exports.queue")

#: 后台任务的 key 前缀。与生成任务（直接用 job_id）分开，
#: 免得某次导出的 id 撞上一个任务 id 就把对方挡在门外。
KEY_PREFIX = "export:"

#: 渲染选项的缺省值（§4.1 的 `options`）。三项都是「给出去的东西」的开关：
#: 关掉水印的那一份**不能**再当成合规产物（P5 的水印项），所以原样记进
#: `options_json`，看到一份没水印的 PDF 时能说清它是从哪来的。
DEFAULT_OPTIONS: dict[str, Any] = {
    "watermark": True,
    "withNotes": True,
    "withQuiz": True,
}

#: 进度条：起步 5、封顶 95，中间 90 由「画完几页 / 共几页」填满。
#: 剩下的 5% 留给落盘 —— 大文件写盘不是瞬时的，进度条卡在 95 不动比停在 100 诚实。
_START = 5
_SPAN = 90

#: 支持哪些 (scope, format) 组合。见模块 docstring 那张表。
_SUPPORTED: dict[str, tuple[str, ...]] = {
    "course": ("pptx", "html", "pdf"),
    "record": ("md", "pdf"),
}


# --------------------------------------------------------------------------
# 建
# --------------------------------------------------------------------------


def supported_formats(scope: str) -> tuple[str, ...]:
    return _SUPPORTED.get(str(scope or ""), ())


def create(
    course: Course,
    *,
    fmt: str,
    scope: str = "course",
    session_id: str = "",
    options: Mapping[str, Any] | None = None,
    owner_id: str = "",
) -> Export:
    """建一行 `queued` 的导出。**不渲染**（P5-A5：接口层立即返回）。

    Raises:
        ValidationError: 格式与范围不匹配（40001）。
        StateError: 这门课还没有可导出的页面（40902）。
        NotFoundError: `scope=record` 但那堂课不存在或不属于请求方（404）。
    """
    scope = str(scope or "course")
    fmt = str(fmt or "").lower()
    if fmt not in supported_formats(scope):
        allowed = "、".join(supported_formats(scope)) or "（无）"
        raise ValidationError(
            f"{'课堂记录' if scope == 'record' else '课件'}不支持导出为 {fmt or '（空）'}，"
            f"可选：{allowed}",
            details={"scope": scope, "format": fmt, "allowed": list(supported_formats(scope))},
        )
    if scope == "record":
        if not session_id:
            raise ValidationError("课堂记录导出必须指定 sessionId", details={"scope": scope})
        # 归属在这里判，不留给后台线程：一次「导出别人的课堂记录」的请求
        # 不该先排上队、再在几秒后变成一个失败行 —— 那是把越权写进了导出历史。
        _require_visible_session(session_id, owner_id or course.owner_id or "")
    else:
        # 走到这里 scope 一定是 `course`：别的取值在上一道格式检查里就已经被挡了
        # （`supported_formats` 对不认识的 scope 返回空元组，任何 fmt 都过不了）。
        _require_ready(course)

    merged = _clean_options(options, default_template=course.template)
    row = Export(
        course_id=course.id,
        session_id=session_id or None,
        owner_id=owner_id or course.owner_id or "",
        format=fmt,
        scope=scope,
        status="queued",
        progress=0,
    )
    row.options = merged

    def _work() -> Export:
        db.session.add(row)
        db.session.flush()
        return row

    return db_write(_work)


def _as_list(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _clean_options(
    options: Mapping[str, Any] | None, *, default_template: str = ""
) -> dict[str, Any]:
    """补上缺省的渲染选项。

    三个认识的键**必须是布尔**：`options_json` 是原样留档的（模型注释第 1 条），
    所以这里不丢键、不做类型转换 —— 但 `"false"` 这种字符串必须当场报错。
    `bool("false")` 是 `True`，一路放行下去的结果是**用户关了水印却拿到带水印的
    产物**，而这一点只有打开文件才看得出来。

    不认识的键原样留着（`_render_options` 会忽略它们）：留档是为了回答
    「这份产物是怎么跑出来的」，多存的那些前端参数不影响这个问题的答案。
    """
    merged: dict[str, Any] = {**DEFAULT_OPTIONS, **dict(options or {})}
    for key in DEFAULT_OPTIONS:
        if not isinstance(merged[key], bool):
            raise ValidationError(
                f"options.{key} 必须是布尔值", details={"option": key}
            )
    _clean_template(merged, default_template=default_template)
    return merged


def _clean_template(merged: dict[str, Any], *, default_template: str = "") -> None:
    """补上并校验 `template`（PPT 模板）。

    与三个布尔开关分开处理：它是**字符串**。没给就退回**课程级的那一套**
    （`courses.template`，首页开始生成时选的）—— 于是导出默认跟着课程走，
    面板上再选一次则是单次覆盖；两者都没给才退回 `default`。给了但认不出就
    当场 40001 —— 与其让渲染时 `theme.get` 悄悄退回默认（用户选了「瑞士」却拿到
    「品牌蓝」，只有打开文件才看得出），不如在建任务时就把话说清楚。
    """
    fallback = str(default_template or "").strip() or theme_registry.DEFAULT_KEY
    raw = merged.get("template")
    if raw is None or not str(raw).strip():
        merged["template"] = fallback
        return
    key = str(raw).strip()
    if key not in theme_registry.THEMES:
        raise ValidationError(
            f"未知的模板 {key}",
            details={"template": key, "allowed": list(theme_registry.THEMES)},
        )
    merged["template"] = key


def _require_visible_session(session_id: str, owner_id: str) -> None:
    """这堂课看得见吗。看不见与不存在给同一句话（P3-F4：404 不是 403）。"""
    from app.services.classroom import sessions as classroom_sessions

    classroom_sessions.require_visible(classroom_sessions.require(session_id), owner_id)


def _require_ready(course: Course, *, dsl: Mapping[str, Any] | None = None) -> None:
    """课程得先有可讲的页面，否则导出来是一份空册子。

    用 `StateError`（40902）而不是 `ValidationError`：请求本身没问题，
    是**课程还没到那一步**（`errors.py` 里 `StateError` 的注释就是照这个场景写的）。

    **两个判据都要过，因为它们是两份数据**：
    - `course_pages` 里有就绪的页 → 这门课生成完了（P1 的收尾信号）。
    - `courses.dsl` 里有一页页的正文 → 渲染时真读得到东西（`_deck_of` 读的是它）。

    只看前者会漏：`rebuild_dsl` 没跑过、或跑在页面写进去之前时，
    `course_pages` 满着而 `courses.dsl_json` 里的 `pages` 是空的。此时导出来的是
    一份空产物 —— PPTX 与 HTML 会安静地给出一个没有内容的文件，PDF 则会在
    `DocumentWriter.close()` 上抛一句 `cannot save with zero pages`，
    最后变成「导出失败，请重试」，谁也看不出真正的原因。
    """
    ready = (
        CoursePage.query.filter_by(course_id=course.id, status="ready")
        .filter(CoursePage.dsl_json.isnot(None))
        .count()
    )
    if not ready:
        raise StateError(
            "这门课还没有生成好的页面，先生成完再导出",
            details={"courseId": course.id},
        )

    source = course.dsl if dsl is None else dsl
    if not [item for item in _as_list(_as_mapping(source).get("pages")) if _as_mapping(item)]:
        raise StateError(
            "这门课的课件内容还是空的，重新生成一次再导出",
            details={"courseId": course.id},
        )


def submit(export_id: str) -> bool:
    """把一次导出丢到后台。返回 False 表示它已经在跑了。"""
    return get_runner().submit(KEY_PREFIX + export_id, lambda: run(export_id))


# --------------------------------------------------------------------------
# 读
# --------------------------------------------------------------------------


def require(export_id: str) -> Export:
    """按 id 取一行，取不到抛 404。**不判归属** —— 归属是 `owned_by` 的事，
    而下载那条路上「谁」是从票据里来的（见 `api/exports.py`）。"""
    row = db.session.get(Export, str(export_id or ""))
    if row is None:
        raise NotFoundError("导出任务不存在")
    return row


def list_of_course(course_id: str, *, limit: int = 20, offset: int = 0) -> list[Export]:
    """一门课的导出历史，**新的在前**。

    按 `created_at` 倒序：用户打开导出面板想找的是「刚刚点的那一次」，
    而它一定在最新的一头。同一秒建出来的两行用 id 兜底排序，
    否则 SQLite 给不出稳定顺序、翻页时会看到同一行出现两次。
    """
    return list(
        Export.query.filter_by(course_id=str(course_id or ""))
        .order_by(Export.created_at.desc(), Export.id.desc())
        .limit(max(1, int(limit)))
        .offset(max(0, int(offset)))
        .all()
    )


def expired(row: Export, *, now: Any = None) -> bool:
    """这份产物过没过期（`expires_at` 是我们自己写下的承诺）。

    清理任务与下载接口都走它：判据只有一处，才不会出现「清理说没到期、
    下载说已过期」这种自相矛盾的答复。
    """
    parsed = parse_iso(getattr(row, "expires_at", ""))
    return parsed is not None and parsed <= (now or utcnow())


# --------------------------------------------------------------------------
# 跑
# --------------------------------------------------------------------------


def run(export_id: str) -> Export:
    """同步跑完一次导出。**不抛异常** —— 失败写进 `export.error`。

    抛出去的话，唯一会看到它的是线程池的日志，而用户那边只会看到一行
    永远停在 `running` 的记录（`common/tasks.py` 的 `_guard` 把异常关在线程里）。
    导出失败是**用户要看到的事**，所以它必须落到库里。
    """
    row = db.session.get(Export, export_id)
    if row is None:
        raise NotFoundError(f"导出任务 {export_id} 不存在")

    try:
        _mark(row, status="running", progress=_START, error="")
        deck = _deck_of(row)
        payload = _render(row, deck)
        _finish(row, payload)
    except Exception as exc:
        _fail(row, exc)
    return row


def _deck_of(row: Export) -> Deck:
    if row.scope == "record":
        deck = record_renderer.to_deck(_record_of(row))
    else:
        course = db.session.get(Course, row.course_id)
        if course is None:
            raise NotFoundError("课程不存在或已被删除")
        deck = from_dsl(course.dsl or {}, sources_by_page=_sources_of(course))

    if not deck.pages:
        # `create()` 已经挡过一道（`_require_ready`）。这里是两道之间的兜底 ——
        # 排队期间有人重生成、把 DSL 清空了。空册子不该被当成一份成功的产物
        # 发出去：PPTX/HTML 会安静地给出一个没内容的文件，PDF 更会在落盘时
        # 抛「cannot save with zero pages」，对用户等于什么都没说。
        raise StateError(
            "这门课的课件内容还是空的，重新生成一次再导出",
            details={"courseId": row.course_id},
        )
    return deck


def _sources_of(course: Course) -> dict[int, list[Source]]:
    """页号 → 给人看的出处（P4）。

    DSL 里那份 `sources` 只有 `chunkId` 与引文，人要看的是「《机器学习讲义》第 3 页」。
    展示名在 `materials.name`、页码在 `page_sources.page_no`，所以要**查一次库**：
    `from_dsl` 明说了自己不碰 DB，这个旁路只能由调用方铺。

    两张表各查一次（不是每页查一遍）：12 页的课查 24 次库和查 2 次库，
    差别在导出这种「一次几百毫秒」的操作里看得见。
    """
    pages = (
        CoursePage.query.filter_by(course_id=course.id, status="ready")
        .filter(CoursePage.dsl_json.isnot(None))
        .all()
    )
    if not pages:
        return {}

    by_id = {page.id: int(page.page_no or 0) for page in pages}
    rows = PageSource.query.filter(PageSource.page_id.in_(list(by_id))).all()
    if not rows:
        return {}

    material_ids = {item.material_id for item in rows if item.material_id}
    titles = {
        item.id: item.name
        for item in Material.query.filter(Material.id.in_(list(material_ids))).all()
    } if material_ids else {}

    out: dict[int, list[Source]] = {}
    for item in rows:
        page_no = by_id.get(item.page_id)
        if not page_no:
            continue
        out.setdefault(page_no, []).append(
            Source(label=_label(titles.get(item.material_id, ""), item.page_no), quote=item.quote or "")
        )
    return out


def _label(material_name: str, page_no: Any) -> str:
    """`《机器学习讲义》第 3 页`。材料被删掉时退化成「材料已删除」。

    书名号只在真拿到名字时加 —— `《》第 3 页` 这种空壳比不显示更难看。
    """
    name = str(material_name or "").strip()
    number = int(page_no or 0)
    if not name:
        return "材料已删除" + (f"（原第 {number} 页）" if number else "")
    return f"《{name}》" + (f"第 {number} 页" if number else "")


def _render(row: Export, deck: Deck) -> bytes | str:
    """按格式渲染。进度回调**节流**成「百分比变了才写库」。

    12 页的课每页写一次库是 12 次写；而进度条的刻度只有 100 格 ——
    每页都写并不会让它更准，只会让导出慢一点、SQLite 多一批事务。
    """
    options = RenderOptions(**_render_options(row))
    generated_at = utcnow().strftime("%Y-%m-%d")

    last = [_START]

    def on_page(done: int, total: int) -> None:
        if total <= 0:
            return
        percent = _START + int(_SPAN * done / total)
        if percent != last[0]:
            last[0] = percent
            _mark(row, progress=percent)

    if row.format == "md":
        text = record_renderer.to_markdown(_record_of(row))
        _mark(row, progress=_START + _SPAN)
        return text

    if row.format == "pptx":
        return pptx_renderer.render(deck, options, generated_at=generated_at, on_page=on_page)
    if row.format == "pdf":
        return pdf_renderer.render(deck, options, generated_at=generated_at, on_page=on_page)
    if row.format == "html":
        text = html_renderer.document(deck, options, generated_at=generated_at, on_page=on_page)
        _mark(row, progress=_START + _SPAN)
        return text

    # create() 已经挡过一道，这里是「有人直接往库里插了一行」的兜底
    raise ValidationError(f"不认识的导出格式：{row.format}")


def _record_of(row: Export) -> Mapping[str, Any]:
    """这次导出的课堂记录。Markdown 与 IR 两条路都从它出发（不各查一遍库）。"""
    from app.services.classroom import record as classroom_record
    from app.services.classroom import sessions as classroom_sessions

    if not row.session_id:
        raise ValidationError("这次导出没有记下 sessionId，无法重建课堂记录")
    session = classroom_sessions.require(str(row.session_id))
    return classroom_record.build(session)


def _render_options(row: Export) -> dict[str, Any]:
    """`options_json` → `RenderOptions` 的字段。

    **只取认识的那几个键**：`options_json` 是原样留档的，里面可能有前端多传的
    东西（比如 `format`），而 `RenderOptions` 是 frozen dataclass，
    多一个键就是 TypeError。
    """
    raw = row.options or {}
    return {
        "watermark": bool(raw.get("watermark", True)),
        "with_notes": bool(raw.get("withNotes", True)),
        "with_quiz": bool(raw.get("withQuiz", True)),
        # 老记录没有这一项，退回缺省主题（`theme.get` 也会再兜一次底）。
        "template": str(raw.get("template") or theme_registry.DEFAULT_KEY),
    }


# --------------------------------------------------------------------------
# 收尾
# --------------------------------------------------------------------------


def _finish(row: Export, payload: bytes | str) -> None:
    """落盘 + 改行。

    先量体积再落盘：超过上限的产物**根本不写**（写了一半再删是白花一次 IO，
    而 `EXPORT_MAX_BYTES` 挡的是「把磁盘写满」这件事本身）。
    """
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    limit = store.max_bytes()
    if len(data) > limit:
        raise StateError(
            f"导出内容过大（{len(data) / 1048576:.1f} MB，上限 {limit / 1048576:.0f} MB），"
            "试试少带讲稿或改用其他格式",
            details={"sizeBytes": len(data), "maxBytes": limit},
        )

    rel, size = store.write(row.course_id, row.id, row.format, data)
    expires = _expires_at()

    def _work() -> None:
        row.file_path = rel
        row.size_bytes = size
        row.progress = 100
        row.status = "done"
        row.error = ""
        row.finished_at = utcnow_iso()
        row.expires_at = expires
        db.session.add(row)

    db_write(_work)
    logger.info(
        "导出完成 id=%s format=%s size=%dB scope=%s",
        row.id, row.format, size, row.scope,
    )


def _fail(row: Export, exc: Exception) -> None:
    """失败写进 `error` 并标记 `failed`。

    消息取**给人看的那一句**（`AppError.message`），不取类名 —— 「这门课还没有
    生成好的页面」能直接指导用户下一步，`StateError` 不能。
    非 AppError 的意外（编码错误、库表结构变了）给一句泛化的，细节进服务端日志：
    堆栈与路径不该出现在一个会给用户看的字段里（AGENTS §19）。
    """
    from app.common.errors import AppError

    if isinstance(exc, AppError):
        message = str(exc.message)
    else:
        message = "导出失败，请重试；若反复失败请联系管理员"
        logger.exception("导出失败 id=%s", row.id)

    def _work() -> None:
        row.status = "failed"
        row.error = message[:500]
        row.finished_at = utcnow_iso()
        row.file_path = None
        row.size_bytes = 0
        db.session.add(row)

    try:
        db_write(_work)
    except Exception:  # pragma: no cover - 连失败都写不进去，只能记日志
        logger.exception("写导出失败状态时出错 id=%s", row.id)


def _mark(row: Export, *, status: str | None = None, progress: int | None = None,
          error: str | None = None) -> None:
    """改状态 / 进度。**单独提交**，不等渲染结束。

    进度条的意义就是「现在进行到哪了」，攒到最后一起写等于没有进度条。
    """

    def _work() -> None:
        if status is not None:
            row.status = status
        if progress is not None:
            row.progress = max(0, min(100, int(progress)))
        if error is not None:
            row.error = error
        db.session.add(row)

    try:
        db_write(_work)
    except Exception as exc:  # pragma: no cover - 进度写不进去不该中断渲染
        logger.warning("更新导出进度失败 id=%s：%s", row.id, type(exc).__name__)


def _expires_at() -> str:
    from datetime import timedelta

    hours = store.ttl_hours()
    return to_iso(utcnow() + timedelta(hours=hours))


# --------------------------------------------------------------------------
# 清理
# --------------------------------------------------------------------------


def cleanup(*, now: Any = None) -> dict[str, int]:
    """删掉到期的产物与行（P5-A6 / P5-C1）。

    判定用**行上的 `expires_at`**，不是「文件的 mtime 有多老」：前者是我们自己
    写下的承诺，后者会被一次 `cp -p`、一次备份还原改得面目全非。

    `expires_at` 为空的行**不删**：那是还没跑完或失败的行，它们没有承诺期限，
    删掉就等于把「上次为什么失败」一起删了。

    除了删行，还会扫一遍**无主产物**（`store.sweep_orphans`）：上一次崩在
    「写完文件」与「改库」之间的那些，`cleanup` 顺着行是找不到的。

    返回 `{"exports": 删了几行, "files": 删了几个文件, "orphans": 清掉几个无主产物}`。
    """
    moment = now or utcnow()
    due = [row for row in Export.query.filter(Export.expires_at != "").all() if expired(row, now=moment)]
    if not due:
        alive = [str(row.file_path) for row in Export.query.all() if row.file_path]
        return {"exports": 0, "files": 0, "orphans": store.sweep_orphans(alive)}

    files = 0
    for row in due:
        files += store.purge(row)

    ids = [row.id for row in due]

    def _work() -> None:
        for row in due:
            db.session.delete(row)

    db_write(_work)

    # 剩下那些还活着的行的产物**不能被当成孤儿** —— 先查出来再扫盘。
    # 这一步要在 db_write 之后：刚删掉的行不该再算「活着」。
    alive = [str(row.file_path) for row in Export.query.all() if row.file_path]
    orphans = store.sweep_orphans(alive)
    store.clean_tmp()

    logger.info("清理了 %d 份过期导出（%d 个文件），另清 %d 个无主产物", len(ids), files, orphans)
    return {"exports": len(ids), "files": files, "orphans": orphans}


def remove(row: Export) -> dict[str, Any]:
    """删掉一次导出：先删盘上的产物，再删那一行。

    **先文件后行**（与 `courses.store.purge_course` 同一条顺序）：反过来的话，
    删文件失败时这一行已经没了，那份文件就再也没人指得到 —— 只能等
    `sweep_orphans` 的宽限期过去才被清掉。

    调用方负责挡住「还在跑的那一次」（`api/exports.py` 回 40902）：
    后台线程手里攥着这一行的对象，删了行它照样会写文件、再把行插回去。
    """
    files = store.purge(row)
    export_id = row.id
    course_id = row.course_id

    def _work() -> None:
        db.session.delete(row)

    db_write(_work)
    logger.info("删除导出 id=%s（%d 个文件）", export_id, files)
    return {"id": export_id, "courseId": course_id, "deletedFiles": files}


def purge_course(course_id: str) -> int:
    """删课时的收尾：把盘上的导出目录端掉。库里的行由外键 CASCADE 带走。"""
    return store.purge_course(course_id)


def register_cli(app) -> None:
    """注册 `flask exports-cleanup`（P5-C1 那个「清理任务」的入口）。

    这个仓库没有常驻调度器（P2 的音频、P4 的临时文件都是**顺手**清的），
    所以过期产物的收尾交给外面：部署方挂一条 cron / 定时任务，
    或由验收脚本显式调一次。命令只负责让 `cleanup()` 有个能被调到的入口。
    """

    @app.cli.command("exports-cleanup")
    def exports_cleanup_command() -> None:  # pragma: no cover - 通过 CLI 触发
        """删掉过期的导出产物与记录，并清扫无主文件。"""
        import click

        report = cleanup()
        # 只用中文与 ASCII：Windows 控制台默认 GBK，打符号会直接崩掉命令
        click.echo(
            f"清理完成：过期导出 {report['exports']} 条、文件 {report['files']} 个，"
            f"另清无主产物 {report['orphans']} 个"
        )
        click.echo(f"导出目录当前占用 {store.used_bytes() / 1048576:.1f} MB")


__all__ = [
    "DEFAULT_OPTIONS",
    "KEY_PREFIX",
    "cleanup",
    "create",
    "expired",
    "list_of_course",
    "purge_course",
    "remove",
    "require",
    "run",
    "submit",
    "supported_formats",
]
