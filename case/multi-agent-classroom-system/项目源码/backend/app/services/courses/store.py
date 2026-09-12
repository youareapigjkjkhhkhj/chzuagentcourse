"""课程与课程页的落库（P1 §3、§5，P1-C1 / P1-C4）。

三条贯穿全篇的约定：

1. **页号由服务端分配**，模型只管内容。模型排页码时会在删除、补页、重生成
   之后错位，而 `course_pages(course_id, page_no)` 上有唯一约束，
   错位就是一次写库失败。
2. **每次写页都追加一条版本**（`course_page_versions`），不覆盖。`rev` 就是
   「这页改过几次」的计数器，页面行上的 `rev` 与最新版本的 `rev` 永远相同。
3. **`dsl_json` 与 `course_pages` 必须能互相推出来**（P1-C1）：
   `dsl.chapters[].pages` 里的每个页号，都能在 `dsl.pages` 里找到同号的一页；
   反过来也一样。任何一次写页之后都由 `rebuild_dsl` 统一重算，
   不允许别处手改这个结构 —— 那是这份一致性唯一的破口。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from app.common.dbw import db_write
from app.common.logging import get_logger
from app.extensions import db
from app.models import PAGE_VERSION_REASONS, Course, CoursePage, CoursePageVersion
from app.services.generation.schema import estimate_sec

logger = get_logger("app.courses.store")

#: 「不属于任何一章」的章号。封面、大纲页、小结页都是全课级的：
#: 挂在第 1 章下会让「本章有几页」把它们算进去，而它们讲的并不是第 1 章的内容。
FRONT_MATTER = 0

#: 章号为 0 的页面里，哪些属于**开篇**（其余属于收尾）。
#: 两者都挂 0，但在工作台的大纲树上一个在上、一个在下，不能混在一起渲染。
FRONT_KINDS = ("cover", "outline")


# --- 课程 ---


def create_course(
    *,
    title: str,
    topic: str = "",
    options: Mapping[str, Any] | None = None,
    owner_id: str = "",
) -> Course:
    """建一门课。生成开始时课程就已经存在（状态 generating）——
    用户在生成过程中刷新页面要能看到它，而不是一个只活在内存里的任务。"""
    course = Course(
        title=title.strip()[:255] or "未命名课程",
        topic=(topic or title).strip()[:255],
        status="generating",
        owner_id=owner_id or None,
    )
    course.dsl = {"version": "", "mode": str((options or {}).get("mode") or "lecture")}
    db_write(lambda: db.session.add(course))
    return course


def get_course(course_id: str) -> Course | None:
    return db.session.get(Course, course_id)


def purge_course(course: Course) -> None:
    """**真删**一门课：页面、版本、任务、步骤、事件由外键级联带走（P1-C3）。

    不挂在接口上：`DELETE /api/courses/{id}` 是软删（§4），用户的手滑要能撤回。
    这里给的是运维用的那一把 —— 清归档、删测试数据、以及 P1-C3 那条
    「删完不留孤儿」的断言。级联靠的是 `ondelete="CASCADE"` 加
    `PRAGMA foreign_keys=ON`，本函数只发一条 `DELETE FROM courses`。
    """
    db_write(lambda: db.session.delete(course))


def pages_of(course: Course) -> list[CoursePage]:
    return list(CoursePage.query.filter_by(course_id=course.id).order_by(CoursePage.page_no).all())


def ready_pages(course: Course) -> list[CoursePage]:
    return [page for page in pages_of(course) if page.status == "ready" and page.dsl]


def page_by_no(course: Course, page_no: int) -> CoursePage | None:
    return CoursePage.query.filter_by(course_id=course.id, page_no=int(page_no)).first()


# --- 页面的分配与写入 ---


def allocate_pages(
    course: Course,
    outline: Mapping[str, Any],
    *,
    quiz_per_chapter: bool = True,
    debate: bool = False,
    extra_last: str = "summary",
) -> list[CoursePage]:
    """按大纲铺出全部页面行（`pending`），页号由这里定死。

    铺出来的顺序：封面 → 大纲页 → 各章[正文 → 研讨页 → 测验页] → 小结。

    为什么在**大纲阶段**就把页行建出来、而不是边写边建：
    工作台要显示「12 页里哪些还没生成」（四个状态），页行不存在就无从显示；
    页号也必须在这一刻定下来，否则每写一页都在改页码，前端的选中项会漂。

    测验页在章末、研讨页在测验页**之前**：一章的收尾动作是先辩后测 ——
    辩完才知道自己哪儿没想清楚，这时再去答题，测验才不只是背书名。
    """
    plan: list[dict[str, Any]] = [
        {"kind": "cover", "chapterNo": FRONT_MATTER, "title": outline.get("title") or course.title,
         "points": []},
        {"kind": "outline", "chapterNo": FRONT_MATTER, "title": "课程大纲", "points": []},
    ]
    for chapter in outline.get("chapters") or []:
        no = int(chapter.get("no") or 0)
        title = chapter.get("title") or f"第 {no} 章"
        for page in chapter.get("pages") or []:
            plan.append(
                {"kind": page["kind"], "chapterNo": no, "title": page["title"],
                 "points": page.get("points") or []}
            )
        if debate:
            plan.append(
                {"kind": "debate", "chapterNo": no, "title": f"{title} · 研讨议题",
                 "points": chapter.get("points") or []}
            )
        if quiz_per_chapter:
            plan.append(
                {"kind": "quiz", "chapterNo": no, "title": f"{title} · 随堂测验", "points": []}
            )
    if extra_last == "summary":
        # 小结挂在 FRONT_MATTER 而不是最后一章：它讲的是整门课，不是某一章；
        # 挂进最后一章还会让「每章最后一页是测验页」这条规则在末章失效。
        plan.append(
            {"kind": "summary", "chapterNo": FRONT_MATTER, "title": "课程小结", "points": []}
        )

    def _work() -> list[CoursePage]:
        for stale in pages_of(course):
            db.session.delete(stale)
        # 先删干净再插：页号是 (course_id, page_no) 上的唯一键，同一批 flush 里
        # 新旧行会撞在一起（确认大纲时按新大纲重铺，正是这条路径）。
        db.session.flush()
        rows = []
        for index, item in enumerate(plan, start=1):
            row = CoursePage(
                course_id=course.id,
                page_no=index,
                chapter_no=int(item["chapterNo"]),
                kind=item["kind"],
                title=str(item["title"])[:255],
                status="pending",
            )
            db.session.add(row)
            rows.append(row)
        db.session.flush()
        # 页数在这里就定下来，而不是等 assemble 收尾才写（与 `rebuild_dsl` 同口径：
        # 一门课有几页 = 它有几行页面）。等在收尾才写的话，从大纲确认点到写完
        # 这一整段里课程都是「0 页」：卡片与大纲树对不上，工作台点第 3 页还会
        # 被判成越界 —— 那 12 行明明就在那儿。
        course.page_count = len(rows)
        return rows

    rows = db_write(_work)
    _store_plan(course, outline, rows)
    return rows


def save_page(
    page: CoursePage,
    dsl: Mapping[str, Any],
    *,
    reason: str = "generate",
    model: str = "",
    tokens: int = 0,
    instruction: str = "",
    meta: Mapping[str, Any] | None = None,
) -> CoursePageVersion:
    """写一页的内容，并追加一条版本。

    `rev` 的推进规则：从没成功过就是 1，否则 +1。这样「第几次改的」一眼可见，
    而 P1-A7 的「重写后 rev+1」也就是这里自然的结果。
    """
    # 写库前先拦一道：CHECK 约束会拦得住，但它报的是「表 course_page_versions
    # 的第 N 行违反约束」，而这里报的是「你传了个什么」。手滑写错一个枚举值，
    # 该在调用点就断，而不是等到 commit 之后从日志里翻。
    if reason not in PAGE_VERSION_REASONS:
        raise ValueError(
            f"未知的版本来源：{reason!r}，可选：{'/'.join(PAGE_VERSION_REASONS)}"
        )
    next_rev = 1 if page.status != "ready" else int(page.rev or 1) + 1
    version_meta = dict(meta or {})

    def _work() -> CoursePageVersion:
        page.dsl = dict(dsl)
        page.title = str(dsl.get("title") or page.title or "")[:255]
        page.kind = str(dsl.get("kind") or page.kind)
        page.status = "ready"
        page.rev = next_rev
        version = CoursePageVersion(
            page_id=page.id,
            rev=next_rev,
            reason=reason,
            instruction=instruction or None,
            model=(model or "")[:64] or None,
            tokens=int(tokens or 0),
            meta_json=None,
        )
        version.dsl = dict(dsl)
        version.meta = version_meta
        db.session.add(version)
        db.session.flush()
        return version

    return db_write(_work)


def mark_page_failed(page: CoursePage, error: str) -> None:
    def _work() -> None:
        page.status = "failed"
        page.dsl = {**(page.dsl or {}), "error": error[:500]}

    db_write(_work)


# --- dsl_json 的重建（P1-C1）---


def rebuild_dsl(course: Course, *, meta: Mapping[str, Any] | None = None) -> dict:
    """按 `course_pages` 重算 `courses.dsl_json`。

    章节的标题/摘要来自大纲阶段存下的那一份；页号列表与页面内容**只认页面行**。
    两处都写着同一件事的时候，页面行是事实 —— 大纲只是一份计划。
    """
    stored = course.dsl or {}
    rows = ready_pages(course)
    by_no = {row.page_no: row for row in rows}
    chapters: list[dict[str, Any]] = []
    for chapter in stored.get("chapters") or []:
        numbers = sorted(
            row.page_no for row in rows if int(row.chapter_no or 0) == int(chapter.get("no") or 0)
        )
        chapters.append({**chapter, "pages": numbers})

    dsl = {
        "version": str(stored.get("version") or ""),
        "mode": str(stored.get("mode") or "lecture"),
        "title": course.title,
        "subtitle": str(stored.get("subtitle") or ""),
        "chapters": chapters,
        # 双向：chapters[].pages 里的每个号，这里都有一页同号的内容
        "pages": [by_no[number].dsl for number in sorted(by_no)],
        "meta": _meta(stored, rows, meta),
    }

    def _work() -> None:
        course.dsl = dsl
        course.page_count = len(pages_of(course))
        course.duration_min = _duration_min(by_no, rows)
        cover = by_no.get(1)
        if cover is not None and cover.kind == "cover":
            course.cover = {
                "title": cover.dsl.get("title") or course.title,
                "subtitle": cover.dsl.get("subtitle") or "",
                **(cover.dsl.get("meta") or {}),
            }

    db_write(_work)
    return dsl


def update_chapters(course: Course, chapters: Sequence[Mapping[str, Any]]) -> dict:
    """合并章节信息（大纲阶段写一次，quiz 阶段补 discussion）。"""
    stored = dict(course.dsl or {})
    merged: list[dict[str, Any]] = []
    incoming = {int(item.get("no") or 0): item for item in chapters}
    for chapter in stored.get("chapters") or []:
        extra = incoming.pop(int(chapter.get("no") or 0), None)
        merged.append({**chapter, **(dict(extra) if extra else {})})
    # 还没有过的章节（大纲重跑）：按传入的顺序补在后面
    for no in sorted(incoming):
        merged.append(dict(incoming[no]))

    def _work() -> None:
        course.dsl = {**stored, "chapters": merged}

    db_write(_work)
    return course.dsl


def set_dsl_meta(course: Course, meta: Mapping[str, Any]) -> None:
    """把受众画像这类课程级元信息并进 dsl。"""

    def _work() -> None:
        stored = dict(course.dsl or {})
        current = dict(stored.get("meta") or {})
        current.update(dict(meta))
        course.dsl = {**stored, "meta": current}

    db_write(_work)


def outline_tree(course: Course) -> dict:
    """工作台的大纲树：章节 → 页面（带四态：pending / ready / failed / generating）。"""
    stored = course.dsl or {}
    rows = pages_of(course)
    by_chapter: dict[int, list[CoursePage]] = {}
    for row in rows:
        by_chapter.setdefault(int(row.chapter_no or 0), []).append(row)

    def _page(row: CoursePage) -> dict:
        return {
            "pageNo": row.page_no,
            "kind": row.kind,
            "title": row.title or "",
            "status": row.status,
            "rev": row.rev,
        }

    chapters = [
        {
            "no": int(chapter.get("no") or 0),
            "title": str(chapter.get("title") or ""),
            "summary": str(chapter.get("summary") or ""),
            "points": list(chapter.get("points") or []),
            "discussion": list(chapter.get("discussion") or []),
            "pages": [_page(row) for row in by_chapter.get(int(chapter.get("no") or 0), [])],
        }
        for chapter in stored.get("chapters") or []
    ]
    loose = by_chapter.get(FRONT_MATTER, [])
    return {
        "courseId": course.id,
        "title": course.title,
        "subtitle": str(stored.get("subtitle") or ""),
        "status": course.status,
        "chapters": chapters,
        "front": [_page(row) for row in loose if row.kind in FRONT_KINDS],
        "back": [_page(row) for row in loose if row.kind not in FRONT_KINDS],
        "pageCount": len(rows),
    }


# --- 内部 ---


def _store_plan(course: Course, outline: Mapping[str, Any], rows: Iterable[CoursePage]) -> None:
    """把「计划」写进 dsl_json：章节树 + 每章的页号 + 大纲标题。"""
    page_nos: dict[int, list[int]] = {}
    for row in rows:
        page_nos.setdefault(int(row.chapter_no or 0), []).append(row.page_no)

    chapters = [
        {
            "no": int(chapter.get("no") or 0),
            "title": str(chapter.get("title") or ""),
            "summary": str(chapter.get("summary") or ""),
            "points": list(chapter.get("points") or []),
            "pages": page_nos.get(int(chapter.get("no") or 0), []),
        }
        for chapter in outline.get("chapters") or []
    ]
    stored = dict(course.dsl or {})

    def _work() -> None:
        course.dsl = {
            **stored,
            "title": outline.get("title") or course.title,
            "subtitle": outline.get("subtitle") or "",
            "chapters": chapters,
            "pages": [],
        }
        if outline.get("title"):
            course.title = str(outline["title"])[:255]

    db_write(_work)


def _meta(
    stored: Mapping[str, Any], rows: Sequence[CoursePage], extra: Mapping[str, Any] | None
) -> dict:
    current = dict(stored.get("meta") or {})
    if extra:
        current.update(dict(extra))
    current["pageCount"] = len(rows)
    current["narrationSec"] = _narration_sec(rows)
    return current


def _narration_sec(rows: Sequence[CoursePage]) -> int:
    """照着讲稿念完要多少秒。P2 的语音合成按它排时长。"""
    return sum(
        estimate_sec(beat.get("text", ""))
        for row in rows
        for beat in (row.dsl or {}).get("narration") or []
    )


def _duration_min(by_no: Mapping[int, CoursePage], rows: Sequence[CoursePage]) -> int:
    """课程时长（分钟）：优先用封面页写下的**设计时长**。

    两个候选值回答的是两个不同的问题：封面页 `meta.durationMin` 是「这节课排多长」
    （受众画像给的，也是课程卡上那个数），讲稿秒数是「照念一遍要多久」。
    卡片上写「12 页 · 25 分钟」，用后者会变成 4 分钟 —— 一节 25 分钟的课，
    讲稿本来就比课时短，中间还有提问、练习与讨论。讲稿时长另有去处：
    `dsl.meta.narrationSec` 一字不差地记着它。

    没有封面页（生成到一半、或大纲里没有它）时退回讲稿值，宁可给一个偏心
    偏小的数，也不给 0 —— 卡片上「0 分钟」比「4 分钟」更像坏了。
    """
    cover = by_no.get(1)
    if cover is not None and cover.kind == "cover":
        designed = int((cover.dsl or {}).get("meta", {}).get("durationMin") or 0)
        if designed > 0:
            return designed
    return _narration_sec(rows) // 60


__all__ = [
    "FRONT_MATTER",
    "allocate_pages",
    "create_course",
    "get_course",
    "mark_page_failed",
    "outline_tree",
    "page_by_no",
    "pages_of",
    "purge_course",
    "ready_pages",
    "rebuild_dsl",
    "save_page",
    "set_dsl_meta",
    "update_chapters",
]
