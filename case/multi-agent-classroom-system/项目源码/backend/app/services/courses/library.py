"""课程库与工作台的读写（P1 §4 的课程面）。

接口层把 HTTP 参数交到这里，这里只管三件事：**看不见的课程不返回**、
**改一门课就追加一条版本**、**改完让 `dsl_json` 跟上**。

两个贯穿全篇的口径：

1. **列表与详情是同一份数据**（P1-A10）。卡片上的页数/时长/状态直接读
   `courses` 行的三个列，而不是「卡片算一遍、详情算一遍」—— 两处各算一次，
   迟早会在某一处先更新、另一处没跟上，而那种不一致正是 A10 要防的。
2. **删除是软删**（§4）。`deleted_at` 一置，列表与详情都看不见它，页面、
   版本、事件却都还在 —— 用户点错了要找回来，或者要复盘那次生成，都还查得到。
   真删（级联）留给部署方，见 `store.purge_course`。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.common.dbw import db_write
from app.common.errors import NotFoundError, StateError, ValidationError
from app.common.timeutil import utcnow_iso
from app.extensions import db
from app.models import COURSE_STATUSES, AgentRole, Course, CoursePage, CoursePageVersion, GenJob
from app.services.courses import store
from app.services.generation import events, prompts, sourcing
from app.services.generation.llm import call_page, clip_feedback
from app.services.generation.schema import EDITABLE_FIELDS, SchemaInvalid, validate_page
from app.services.materials import citations

#: 列表默认一页 12 张卡片（首页「最近课堂」一屏正好三行）。
DEFAULT_PAGE_SIZE = 12
#: 单页上限。前端要一次拉很多时才调大，但总得有个头 —— 否则一个 `size=100000`
#: 就能让 SQLite 把整库课程读进内存。
MAX_PAGE_SIZE = 50

#: 任务还在跑的状态。这几个状态下才值得往前端推事件。
LIVE_JOB_STATUSES = ("queued", "running", "paused")

#: 由服务端决定、人工编辑改不了的三个字段。原样发回来不算改（见 `_check_patch`）。
STRUCTURAL_FIELDS = ("pageNo", "chapterNo", "kind")


# --- 列表与详情 ---


def list_courses(
    *, owner_id: str = "", status: str = "", page: int = 1, size: int = DEFAULT_PAGE_SIZE
) -> dict[str, Any]:
    """课程列表（P1 §4 / P1-A10）。按更新时间倒序 —— 刚动过的那门课在最上面。"""
    if status and status not in COURSE_STATUSES:
        raise ValidationError(f"课程状态只能是 {' / '.join(COURSE_STATUSES)}")
    if page < 1:
        raise ValidationError("页码从 1 开始")
    if not 1 <= size <= MAX_PAGE_SIZE:
        raise ValidationError(f"每页条数要在 1 到 {MAX_PAGE_SIZE} 之间")

    query = _visible(Course.query, owner_id)
    if status:
        query = query.filter(Course.status == status)

    total = query.count()
    rows = (
        query.order_by(Course.updated_at.desc(), Course.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    course_ids = [row.id for row in rows]
    jobs = _latest_jobs(course_ids)
    ready = _ready_counts(course_ids)
    role_count = AgentRole.query.count()

    return {
        "items": [
            card_of(row, job=jobs.get(row.id), role_count=role_count, ready=ready.get(row.id, 0))
            for row in rows
        ],
        "total": total,
        "page": page,
        "size": size,
    }


def card_of(
    course: Course, *, job: GenJob | None = None, role_count: int = 0, ready: int = 0
) -> dict[str, Any]:
    """首页卡片要的字段：页数、时长、状态、角色数，外加生成进度（§6）。"""
    return {
        "id": course.id,
        "title": course.title,
        "topic": course.topic or "",
        "status": course.status,
        "pageCount": int(course.page_count or 0),
        "readyPages": int(ready),
        "durationMin": int(course.duration_min or 0),
        "roleCount": int(role_count),
        "cover": course.cover or {},
        "progress": progress_of(course, job),
        "jobId": job.id if job is not None else "",
        "createdAt": course.created_at,
        "updatedAt": course.updated_at,
    }


def progress_of(course: Course, job: GenJob | None) -> int:
    """卡片的进度环读什么。

    没有任务（P1-7 的示例课）就看课程状态：ready 即 100%。有任务时以任务为准，
    但**不能拿一个失败任务的 37% 去覆盖一门已经 ready 的课** —— 卡片会显示
    「就绪但进度 37%」，用户只能理解为「卡住了」。
    """
    if job is not None and job.status in LIVE_JOB_STATUSES:
        return int(job.progress or 0)
    return 100 if course.status == "ready" else int(job.progress or 0) if job else 0


def course_detail(course: Course, *, with_pages: bool = False) -> dict[str, Any]:
    """课程详情：meta + chapters + pages（§4）。"""
    dsl = course.dsl or {}
    job = latest_job_of(course)
    payload = course.to_dict()
    payload.update(
        {
            "subtitle": str(dsl.get("subtitle") or ""),
            "chapters": list(dsl.get("chapters") or []),
            "meta": dict(dsl.get("meta") or {}),
            "cover": course.cover or {},
            "progress": progress_of(course, job),
            "jobId": job.id if job is not None else "",
            "roleCount": AgentRole.query.count(),
        }
    )
    if with_pages:
        payload["pages"] = [row.to_dict(include_dsl=True) for row in store.pages_of(course)]
    return payload


def outline_of(course: Course) -> dict[str, Any]:
    """工作台左侧的大纲树（§4）。四态由页面行的 status 直接给出。"""
    return store.outline_tree(course)


def outline_payload(course: Course) -> dict[str, Any]:
    """大纲树 + 「现在能不能确认」。

    工作台的「确认大纲」按钮什么时候亮，只能由服务端说了算（AGENTS §4.3）：
    前端自己判断「是不是 12 页都齐了」，就会在重连、重试、取消之后判错。
    """
    job = latest_job_of(course)
    payload = store.outline_tree(course)
    payload["jobId"] = job.id if job is not None else ""
    payload["jobStatus"] = job.status if job is not None else ""
    payload["progress"] = progress_of(course, job)
    payload["confirmable"] = bool(job is not None and job.status == "paused")
    return payload


# --- 任务 ---


def latest_job_of(course: Course) -> GenJob | None:
    return (
        GenJob.query.filter(GenJob.course_id == course.id)
        .order_by(GenJob.created_at.desc(), GenJob.id.desc())
        .first()
    )


def live_job_of(course: Course) -> GenJob | None:
    """还在跑（或停在大纲确认点）的任务。只有它值得继续往前端推事件。"""
    return (
        GenJob.query.filter(GenJob.course_id == course.id, GenJob.status.in_(LIVE_JOB_STATUSES))
        .order_by(GenJob.created_at.desc(), GenJob.id.desc())
        .first()
    )


def step_payload(job: GenJob) -> dict[str, Any]:
    """轮询兜底用的任务视图（P1 §4 的 `GET /api/jobs/{jobId}`）。

    SSE 断了、或者前端压根没用 SSE 时，靠它把「现在到哪了」问出来。
    """
    payload = job.to_dict(with_steps=True)
    payload["currentStep"] = next(
        (step for step in payload.get("steps", []) if step["status"] == "running"), None
    )
    failed = [step for step in payload.get("steps", []) if step["status"] == "failed"]
    payload["failedSteps"] = [step["id"] for step in failed]
    payload["retryable"] = bool(failed) and job.status in {"failed", "done"}
    # 能不能「继续生成」（P5-F5-9）：任务停下了、而且还有没做完的步骤。
    # 判据放在服务端而不是前端去数 steps：前面那两条（failed / canceled）
    # 各自的条件以后会变（比如多一种终态），散在 JS 里的判断不会跟着变。
    payload["resumable"] = job.status in {"failed", "canceled"} and any(
        step["status"] not in {"done", "skipped"} for step in payload.get("steps", [])
    )
    return payload


# --- 大纲确认 ---


def confirm_outline(course: Course, outline: Mapping[str, Any]) -> dict[str, Any]:
    """用户确认/修改大纲：按新大纲重铺页行（P1-A3）。

    在大纲确认点，页面**全部还是 pending** —— 一页内容都还没生成。所以这里
    可以放心地按新大纲重铺：删除、调整、换页型都不会丢东西。真到了写页之后
    还想改结构，那是「重新生成」，不是「确认大纲」。

    重铺之后页号由 `store.allocate_pages` 重新连续分配（P1-A3 的 12 页删一页
    变成 11 页，就是这一步的自然结果）。
    """
    rows = store.pages_of(course)
    written = [row for row in rows if row.status == "ready"]
    if written:
        # 兜底：确认点跑到了写页之后（改过管线顺序、手工造过数据），
        # 重铺就等于把已经花钱生成的页面删掉。宁可报错也不静默烧钱。
        raise StateError("已经有生成好的页面，不能再按新大纲重铺")

    job = latest_job_of(course)
    options = dict(job.options) if job is not None else {}
    rows = store.allocate_pages(
        course,
        outline,
        quiz_per_chapter=bool(options.get("quizPerChapter", True)),
        debate=str(options.get("mode") or "lecture") == "seminar",
    )
    if job is not None:
        # 确认过了就不再是「等你确认」：状态**在这里**就推到 queued，而不是
        # 等后台线程醒来再推。不推的话，用户双击的那一下会落在「还是 paused」
        # 的几十毫秒里，于是同一份大纲被重铺两遍（`ensure_confirmable` 拦的就是
        # 这件事，它得先看得见状态变了）。与 `retry_step` 同一个做法。
        db_write(lambda: setattr(job, "status", "queued"))

    return {
        "courseId": course.id,
        "pageCount": len(rows),
        "outline": store.outline_tree(course),
    }


def ensure_confirmable(course: Course) -> GenJob:
    """确认大纲的前置：必须**正好**停在大纲确认点（P1-B3 的 409）。"""
    job = latest_job_of(course)
    if job is None:
        raise StateError("这门课没有可确认的生成任务")
    if job.status == "paused":
        return job
    if job.status in {"queued", "running"}:
        raise StateError("大纲还在生成中，稍后再确认")
    raise StateError("这次生成已经结束，大纲不能再改")


# --- 页面编辑 ---


def page_or_400(course: Course, page_no: int) -> CoursePage:
    """按页号取页。页号是服务端分配的，越界就是参数不对（P1-B3 要求 400）。"""
    if page_no < 1 or page_no > int(course.page_count or 0):
        raise ValidationError(f"页码超出范围（这门课共 {int(course.page_count or 0)} 页）")
    page = store.page_by_no(course, page_no)
    if page is None:
        raise ValidationError(f"第 {page_no} 页不存在")
    return page


def update_page(page: CoursePage, patch: Mapping[str, Any]) -> dict[str, Any]:
    """人工编辑一页（P1-A11）。改完追加一条 `reason=manual` 的版本。"""
    clean = _check_patch(page, patch)
    if not clean:
        # 空保存会白白推一个 rev 上去，把「改过几次」这个数字变成噪音
        raise ValidationError("请求体里没有要修改的字段")
    merged = {**dict(page.dsl or {}), **clean}
    dsl = _revalidate(page, merged)
    store.save_page(page, dsl, reason="manual", meta={"editedAt": utcnow_iso()})
    store.rebuild_dsl(_course_of(page))
    return page.to_dict(include_dsl=True)


def rewrite_page(
    course: Course, page: CoursePage, instruction: str, *, llm: Any = None
) -> dict[str, Any]:
    """AI 重写一页（P1-A7）：追加一条 `reason=rewrite` 的版本，`rev` +1。

    这是**同步**调用（P1-D2 要求单页重写 P95 ≤ 15s）：用户点「重写」就等着
    看结果，把它丢进后台再让前端轮询，反而要多写一套状态。
    """
    if page.status != "ready" or not page.dsl:
        raise StateError("这一页还没有内容，不能重写")

    dsl = course.dsl or {}
    # 材料注入（F4-7）：重写沿用这一页现在的标题与要点去检索 ——
    # 用户给的那句改写要求是「换个说法」，不是「换个知识点」，
    # 拿它当检索词会让这一页的出处跟着漂（P4-A5）。
    injected = sourcing.inject(
        course.id,
        sourcing.page_query(page.dsl or {}),
        limit=citations.config_int("MATERIAL_PAGE_TOP_K", 8),
    )
    messages = prompts.rewrite_messages(
        page.dsl,
        instruction,
        profile=dict((dsl.get("meta") or {}).get("audienceProfile") or {}),
        outline={"title": course.title, "chapters": list(dsl.get("chapters") or [])},
        materials=list(injected.values()),
    )
    call = call_page_for_rewrite(
        llm,
        messages,
        kind=page.kind,
        page_no=page.page_no,
        chapter_no=page.chapter_no,
        owner_id=course.owner_id or "",
    )

    def _regenerate(feedback: str) -> tuple[dict, int]:
        again = call_page_for_rewrite(
            llm,
            [*messages, {"role": "assistant", "content": clip_feedback(call.text)},
             {"role": "user", "content": feedback}],
            kind=page.kind,
            page_no=page.page_no,
            chapter_no=page.chapter_no,
            owner_id=course.owner_id or "",
        )
        return again.data, again.tokens

    dsl_out, summary = sourcing.settle(call.data, injected, regenerate=_regenerate)
    store.save_page(
        page,
        dsl_out,
        reason="rewrite",
        model=call.model,
        tokens=call.tokens + int(summary.get("retryTokens") or 0),
        instruction=instruction,
        meta={"rewrittenAt": utcnow_iso(), "attempts": call.attempts, "sources": summary},
    )
    sourcing.persist(page, dsl_out)
    store.rebuild_dsl(course)

    job = live_job_of(course)
    if job is not None:
        # 只有还在生成的任务才推事件：给它发一帧，工作台上看着这一页的人
        # 能立刻看到新版本。任务已经结束时这条流早就关了，发出去也没人收。
        events.emit(job.id, "page.ready", {
            "pageNo": page.page_no, "kind": page.kind, "title": page.title or "",
            "rev": page.rev, "reason": "rewrite",
        })
    return {"page": page.to_dict(include_dsl=True), "tokens": call.tokens, "model": call.model}


def call_page_for_rewrite(llm: Any, messages: Sequence[Mapping[str, Any]], **kwargs: Any):
    """取模型并要一页内容。单独抽出来是为了测试能塞一个桩进去。

    记账**不挂在某个 job 上**：重写发生在生成任务之外，把它算进那次生成，
    P1-D4 的对账（任务 token 与各步之和）就会多出一笔对不上的账。
    """
    if llm is None:
        from app.services.provider_registry import get_registry

        llm = get_registry().current_llm()
    return call_page(llm, messages, **kwargs)


def versions_of(page: CoursePage, *, with_dsl: bool = False) -> list[dict[str, Any]]:
    """一页的版本链，新的在前（§4，为 P6.4 的回滚预留）。"""
    rows = (
        CoursePageVersion.query.filter(CoursePageVersion.page_id == page.id)
        .order_by(CoursePageVersion.rev.desc())
        .all()
    )
    return [row.to_dict(include_dsl=with_dsl) for row in rows]


# --- 删除 ---


def delete_course(course: Course) -> dict[str, Any]:
    """软删一门课（§4）。

    生成中的课先叫停：用户已经不要它了，继续跑就是继续花钱。
    """
    from app.services.generation.pipeline import request_cancel

    job = live_job_of(course)
    if job is not None:
        request_cancel(job.id)

    def _work() -> None:
        course.deleted_at = utcnow_iso()

    db_write(_work)
    return {"id": course.id, "deletedAt": course.deleted_at}


def course_or_404(course_id: str, owner_id: str) -> Course:
    """取课程并判归属。不存在、已删除、不属于当前用户 —— 都返回 404（AGENTS §4.1）。

    已删除的课程与不存在的课程给同一个答复是有意的：软删之后再访问，
    与访问一个从没存在过的 id 不该有分别。
    """
    from app.common.identity import owned_by

    course = db.session.get(Course, course_id)
    if course is None or course.deleted_at or not owned_by(course, owner_id):
        raise NotFoundError("课程不存在")
    return course


# --- 内部 ---


def _visible(query, owner_id: str):
    """只看没删的、以及当前用户的。

    归属判断与 `identity.owned_by` 同一口径：`owner_id` 为空（还没有用户，
    或调用方没给）时不过滤，否则「自己的」加「没主的」—— 老数据没有 owner，
    不该因为后加的这个字段就对所有人消失。
    """
    query = query.filter(Course.deleted_at.is_(None))
    if not owner_id:
        return query
    return query.filter(db.or_(Course.owner_id == owner_id, Course.owner_id.is_(None)))


def _latest_jobs(course_ids: Sequence[str]) -> dict[str, GenJob]:
    if not course_ids:
        return {}
    rows = (
        GenJob.query.filter(GenJob.course_id.in_(list(course_ids)))
        .order_by(GenJob.created_at.desc(), GenJob.id.desc())
        .all()
    )
    latest: dict[str, GenJob] = {}
    for row in rows:
        latest.setdefault(row.course_id, row)
    return latest


def _ready_counts(course_ids: Sequence[str]) -> dict[str, int]:
    if not course_ids:
        return {}
    rows = (
        db.session.query(CoursePage.course_id, db.func.count(CoursePage.id))
        .filter(CoursePage.course_id.in_(list(course_ids)), CoursePage.status == "ready")
        .group_by(CoursePage.course_id)
        .all()
    )
    return {str(course_id): int(count) for course_id, count in rows}


def _check_patch(page: CoursePage, patch: Mapping[str, Any]) -> dict[str, Any]:
    """只收允许改的字段，其余一律 40001。

    「悄悄忽略」比报错更糟：前端发了 `pageNo` 想调整页号，看起来保存成功了，
    刷新之后却没变 —— 用户会以为保存功能坏了。

    结构性的三个字段（pageNo / chapterNo / kind）**原样发回来是允许的**：
    编辑区绑定的是整份 dsl，前端把整页存回去是最自然的写法。改它们的值才拦。
    """
    unknown = sorted(set(patch) - set(EDITABLE_FIELDS) - set(STRUCTURAL_FIELDS))
    if unknown:
        raise ValidationError(f"不能修改这些字段：{'、'.join(unknown)}")

    actual = {"pageNo": page.page_no, "chapterNo": page.chapter_no, "kind": page.kind}
    for key in STRUCTURAL_FIELDS:
        if key in patch and patch[key] != actual[key]:
            raise ValidationError(f"不能修改 {key}：页号与页型由服务端决定")
    return {key: value for key, value in patch.items() if key in EDITABLE_FIELDS}


def _revalidate(page: CoursePage, merged: Mapping[str, Any]) -> dict[str, Any]:
    """把改过的内容按页型规则重新校验一遍，返回规范化后的 DSL。

    人工编辑也要过 Schema：编辑区里少删一个引号、把 bullets 写成字符串，
    都会让这一页在 P3 课堂运行时崩掉 —— 而那时没人会想到问题出在一次
    「只是改了标题」的保存上。
    """
    try:
        return validate_page(
            page.kind, merged, page_no=page.page_no, chapter_no=page.chapter_no
        )
    except SchemaInvalid as exc:
        raise ValidationError(f"这一页的内容不符合 {page.kind} 页的要求：{exc.reason}") from exc


def _course_of(page: CoursePage) -> Course:
    course = db.session.get(Course, page.course_id)
    if course is None:  # pragma: no cover - 外键保证不会发生
        raise NotFoundError("课程不存在")
    return course


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "LIVE_JOB_STATUSES",
    "MAX_PAGE_SIZE",
    "card_of",
    "confirm_outline",
    "course_detail",
    "course_or_404",
    "delete_course",
    "ensure_confirmable",
    "latest_job_of",
    "list_courses",
    "live_job_of",
    "outline_of",
    "outline_payload",
    "page_or_400",
    "progress_of",
    "rewrite_page",
    "step_payload",
    "update_page",
    "versions_of",
]
