"""工作台的七个内置技能（F4-12 / P4-A10）。

**Agent 能动课程的唯一入口就在这个文件里**。它不直接改库、不自己拼提示词去改课：
每个技能落到别的域已经写好的那条路上 ——

    rewrite_page / change_tone ──► courses.library.rewrite_page（带材料注入与溯源）
    add_page / remove_page     ──► courses.store.insert_page / delete_page（页号重排）
    revise_outline             ──► courses.store.update_chapters + rebuild_dsl
    add_quiz / summarize_material ──► generation.llm.call_json（一次结构化调用）

这一层守两条：

1. **每次调用都要有结果**（P4-A10）。成功给 `result`，失败给一句能照着修的话 ——
   前端那张操作卡上写的就是它，而不是一个「失败了」。
2. **参数写宽松、缺省要合理**。「把这一页改口语点」常常不带页号（用户正看着第 5 页），
   所以页号缺省取 `ref_page_no`；章号缺省取这一页所在的章。让模型去猜这些，
   不如让每个技能自己按上下文补。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

from app.common.errors import AppError, ValidationError
from app.common.logging import get_logger
from app.models import SKILL_NAMES, ChatSession, Course
from app.services.courses import library, store
from app.services.generation import prompts
from app.services.generation.llm import call_json, call_page
from app.services.generation.schema import load_json
from app.services.materials import citations, search
from app.services.workbench import REF_TYPE_CHAT

logger = get_logger("app.workbench.skills")

#: 换语气最多重写几页。语气是**整课**的属性，但一次调用三页已经够表达；
#: 再多就是几十次模型调用，而用户要的只是「听着不一样」。
MAX_TONE_PAGES = 3

#: `summarize_material` 取几片材料。与写页的 top-K 同一个量级：
#: 再多的片段对一次摘要没有增益，只是把上下文撑满。
SUMMARY_TOP_K = 6

#: 摘要出处里带回多少字原文（鼠标停在徽标上先看这一眼）。
#: 60 与 P4 §5「`quote` 可截断至 60 字」同一把尺子。
QUOTE_CHARS = 60


@dataclass
class SkillContext:
    """一次技能调用能看到的全部东西。"""

    course: Course
    session: ChatSession | None = None
    owner_id: str = ""
    #: 用户当时看着哪一页（消息上的 `ref_page_no`）。参数缺省时取它。
    ref_page_no: int = 0
    #: 用户那句话。技能按需要把它当指令或当作检索词。
    instruction: str = ""
    #: 文本模型。None 表示这一步不用模型（纯数据改动的技能本来就不需要）。
    provider: Any = None
    #: 技能往消息流里补的额外说明（由 runner 收集，进操作卡的详情）。
    notes: list[str] = field(default_factory=list)

    def page_or_fail(self, page_no: int):
        page = store.page_by_no(self.course, int(page_no or 0))
        if page is None:
            raise ValidationError(f"这门课没有第 {int(page_no or 0)} 页")
        return page

    def number(self, args: Mapping[str, Any], *keys: str) -> int:
        """从参数里取一个页号/章号：先看显式参数，再看用户正看着的那一页。"""
        for key in keys:
            value = args.get(key)
            if value not in (None, "", 0):
                return int(value)
        return int(self.ref_page_no or 0)


@dataclass(frozen=True)
class Skill:
    name: str
    title: str
    description: str
    #: 参数表：名字 → 「类型，说明」。前端渲染提示、提示词里给模型看的都是它。
    params: Mapping[str, str]
    fn: Callable[[SkillContext, Mapping[str, Any]], dict]


# --- 大纲 ---


def _revise_outline(ctx: SkillContext, args: Mapping[str, Any]) -> dict:
    """改一章的标题/摘要/要点（`revise_outline`）。

    只改大纲，不动页面内容：章节标题改了，页面的归属与页号都不变
    （页行上的 `chapter_no` 才是归属，`update_chapters` 不碰它）。
    想顺手把这一章重讲一遍是另一个技能的事 —— 合成一个的话，
    用户说「第三章叫排序算法」也会连带重写五页内容。
    """
    chapter_no = ctx.number(args, "chapterNo")
    chapters = (ctx.course.dsl or {}).get("chapters") or []
    if not chapters:
        raise ValidationError("这门课还没有大纲")
    target = next(
        (item for item in chapters if int(item.get("no") or 0) == chapter_no),
        None,
    )
    if target is None:
        # 没给章号（用户也没在看某一页）：默认改第一章，而不是报错 ——
        # 「把第一章改成…… 」比「请指定章号」更像是用户会说的话
        target = chapters[0]
        chapter_no = int(target.get("no") or 0)

    patch = {
        key: value
        for key, value in (
            ("title", str(args.get("title") or "").strip()),
            ("summary", str(args.get("summary") or "").strip()),
            ("points", [str(item) for item in (args.get("points") or [])]),
        )
        if value
    }
    if not patch:
        raise ValidationError("要改什么？请给出 title / summary / points 里的至少一项")

    store.update_chapters(ctx.course, [{"no": chapter_no, **patch}])
    store.rebuild_dsl(ctx.course)
    pages = [row.page_no for row in store.pages_of(ctx.course) if int(row.chapter_no or 0) == chapter_no]
    return {"chapterNo": chapter_no, "changed": sorted(patch), "changedPages": pages}


# --- 页面 ---


def _rewrite_page(ctx: SkillContext, args: Mapping[str, Any]) -> dict:
    """重写一页（`rewrite_page`）。走的是工作台「重写」按钮同一条路。"""
    page_no = ctx.number(args, "pageNo")
    instruction = str(args.get("instruction") or ctx.instruction or "").strip()
    if not instruction:
        raise ValidationError("要改成什么样？请给出 instruction")
    page = ctx.page_or_fail(page_no)
    result = library.rewrite_page(ctx.course, page, instruction, llm=ctx.provider)
    return {
        "pageNo": page.page_no,
        "rev": page.rev,
        "tokens": result.get("tokens") or 0,
        "sources": len((page.dsl or {}).get("sources") or []),
    }


def _change_tone(ctx: SkillContext, args: Mapping[str, Any]) -> dict:
    """换语气（`change_tone`）：把几页的讲稿改一个说法，知识点不动。

    一次最多 `MAX_TONE_PAGES` 页（默认前三页正文），每页一次调用。
    语气是整课的事，但用户说「讲得口语一点」时，先改前几页让他看看效果，
    比一口气重写十二页（十二次调用、几分钟）更合算 —— 不合适的话，
    他一句话就能把这几页再改回来。
    """
    tone = str(args.get("tone") or ctx.instruction or "").strip()
    if not tone:
        raise ValidationError("要换成什么语气？请给出 tone")
    wanted = [int(item) for item in (args.get("pageNos") or []) if int(item or 0) > 0]
    if not wanted:
        wanted = [
            row.page_no
            for row in store.ready_pages(ctx.course)
            if row.kind not in store.FRONT_KINDS
        ][:MAX_TONE_PAGES]
    changed = []
    tokens = 0
    for page_no in wanted[:MAX_TONE_PAGES]:
        page = ctx.page_or_fail(page_no)
        result = library.rewrite_page(
            ctx.course, page, f"把这一页的语气改成「{tone}」，讲稿与要点都改，知识点不要变",
            llm=ctx.provider,
        )
        tokens += int(result.get("tokens") or 0)
        changed.append({"pageNo": page.page_no, "rev": page.rev})
    if not changed:
        raise ValidationError("这门课还没有写好内容的页面可以改语气")
    return {"tone": tone, "pages": changed, "tokens": tokens}


def _add_quiz(ctx: SkillContext, args: Mapping[str, Any]) -> dict:
    """出一题随堂测验（`add_quiz`）：写进这一章的测验页。

    章末没有测验页时**顺手补一页**（`kind=quiz`）—— 「给第三章加一道题」这个
    诉求里，「第三章还没有测验页」是实现细节，不该变成用户要处理的一个错误。
    """
    if ctx.provider is None:
        raise ValidationError("这次对话没有可用的文本模型，出不了题")
    chapter_no = ctx.number(args, "chapterNo")
    topic = str(args.get("topic") or ctx.instruction or "").strip()
    page = _quiz_page(ctx, chapter_no)
    call = call_json(
        ctx.provider,
        _quiz_messages(ctx, page, topic),
        schema=_QUIZ_SCHEMA,
        parse=_parse_quiz,
        job_id="",
        owner_id=ctx.owner_id,
        ref_type=REF_TYPE_CHAT,
        ref_id=ctx.course.id,
    )
    dsl = {**(page.dsl or {}), "quiz": call.data}
    store.save_page(
        page, dsl, reason="rewrite", model=call.model, tokens=call.tokens,
        instruction=f"add_quiz：{topic}"[:200], meta={"skill": "add_quiz"},
    )
    return {"pageNo": page.page_no, "chapterNo": chapter_no, "stem": call.data["stem"],
            "tokens": call.tokens}


def _add_page(ctx: SkillContext, args: Mapping[str, Any]) -> dict:
    """加一页（`add_page`）：插在指定位置，并**顺手把它写出来**。

    只插一个空页的话，用户还得自己去找「生成」按钮 —— 而他在对话里说的是
    「加一页讲讲 X」，那句话本身就是写作要求。所以有了标题就直接写内容
    （失败则留一个空页，页还在、内容可以再让他重写一次）。
    """
    chapter_no = ctx.number(args, "chapterNo")
    title = str(args.get("title") or "").strip() or "补充内容"
    kind = str(args.get("kind") or "concept")
    after = int(args.get("afterPageNo") or 0)
    if after <= 0 and ctx.ref_page_no:
        after = int(ctx.ref_page_no)
    page = store.insert_page(
        ctx.course, chapter_no=chapter_no, after_page_no=after, kind=kind, title=title[:120]
    )
    result: dict[str, Any] = {"pageNo": page.page_no, "chapterNo": chapter_no, "title": title}
    try:
        written, tokens = _write_new_page(
            ctx, page, str(args.get("instruction") or ctx.instruction or title)
        )
    except AppError as exc:
        # 页已经在了：告诉用户「页加好了但没写成」，比整条技能判失败有用
        ctx.notes.append(f"第 {page.page_no} 页已加上，但内容没写出来：{exc.message}")
        result["error"] = exc.message
        return result
    result.update(
        {"written": True, "rev": page.rev, "tokens": tokens,
         "sources": len(written.get("sources") or [])}
    )
    return result


def _remove_page(ctx: SkillContext, args: Mapping[str, Any]) -> dict:
    """删一页（`remove_page`）：后面的页号顺延，版本与溯源跟着走。"""
    page_no = ctx.number(args, "pageNo")
    if not page_no:
        raise ValidationError("要删哪一页？请给出 pageNo")
    removed = store.delete_page(ctx.course, page_no)
    return {**removed, "pageCount": int(ctx.course.page_count or 0)}


# --- 材料 ---


def _summarize_material(ctx: SkillContext, args: Mapping[str, Any]) -> dict:
    """把材料里相关的一段讲清楚（`summarize_material`）。

    不写页面、不改课程：它回答的是用户的一个问题（「讲义里第三章讲了什么」），
    答案进消息流，**同时带回出处** —— 材料模式下的每一句结论都该指得回去。
    """
    query = str(args.get("query") or ctx.instruction or "").strip()
    material_ids = citations.material_ids_of(ctx.course.id)
    if not material_ids:
        return {"summary": [], "sources": [], "reason": "这门课还没有关联材料"}
    hits = search.search(query or ctx.course.topic, material_ids=material_ids, top_k=SUMMARY_TOP_K)
    if not hits:
        return {"summary": [], "sources": [], "reason": f"材料里没找到和「{query}」相关的片段"}
    if ctx.provider is None:
        raise ValidationError("这次对话没有可用的文本模型，做不了摘要")
    call = call_json(
        ctx.provider,
        _summary_messages(ctx, query, hits),
        schema=_SUMMARY_SCHEMA,
        parse=_parse_summary,
        job_id="",
        owner_id=ctx.owner_id,
        ref_type=REF_TYPE_CHAT,
        ref_id=ctx.course.id,
    )
    return {
        "summary": call.data["points"],
        "tokens": call.tokens,
        # 出处的字段与页面溯源**逐字一致**（`citations.verify` 定的那套）：
        # `materialId` + `chunkId` 是抽屉定位那一段的两个坐标，`quote` 是鼠标
        # 停上去先看的那几十字。前端因此只需要认一种出处，多一个 `fileName`
        # 是摘要卡要显示「哪份材料」。
        "sources": [
            {"materialId": hit.material_id, "chunkId": hit.chunk_id,
             "fileName": hit.material_name, "pageNo": hit.page_no,
             "sectionPath": hit.section_path, "score": round(hit.score, 4),
             "quote": hit.text[:QUOTE_CHARS]}
            for hit in hits
        ],
    }


# --- 注册表 ---


SKILLS: dict[str, Skill] = {
    skill.name: skill
    for skill in (
        Skill("revise_outline", "改大纲",
              "改某一章的标题、摘要或要点（不动页面内容）",
              {"chapterNo": "int，可选（缺省：当前页所在章，再缺省第一章）",
               "title": "string，可选", "summary": "string，可选",
               "points": "string[]，可选（整章要点，会整批替换）"},
              _revise_outline),
        Skill("rewrite_page", "重写某页",
              "按一句改写要求重写一页的内容与讲稿（带材料溯源）",
              {"pageNo": "int，可选（缺省：当前页）", "instruction": "string，必填"},
              _rewrite_page),
        Skill("add_quiz", "加随堂测验",
              "给某一章出一道选择题，写进章末的测验页（没有就补一页）",
              {"chapterNo": "int，可选（缺省：当前页所在章）", "topic": "string，可选"},
              _add_quiz),
        Skill("add_page", "加一页",
              "在某一章插一页并写入内容",
              {"chapterNo": "int，可选", "afterPageNo": "int，可选（缺省：当前页之后）",
               "title": "string，可选", "kind": "string，可选（concept/example/figure/code）",
               "instruction": "string，可选（这一页要讲什么）"},
              _add_page),
        Skill("remove_page", "删一页",
              "删掉一页，后面的页号顺延",
              {"pageNo": "int，可选（缺省：当前页）"},
              _remove_page),
        Skill("change_tone", "换语气",
              f"把若干页的语气换成指定风格（一次最多 {MAX_TONE_PAGES} 页）",
              {"tone": "string，必填（如「更口语」「更学术」）",
               "pageNos": "int[]，可选（缺省：前三页正文）"},
              _change_tone),
        Skill("summarize_material", "讲材料",
              "从关联材料里找出相关片段并总结，答案带出处",
              {"query": "string，可选（缺省：用户这句话）"},
              _summarize_material),
    )
}

#: 注册表与模型的枚举必须一字不差（`SKILL_NAMES` 是两张表共同的定义处）。
assert set(SKILLS) == set(SKILL_NAMES), "技能注册表与 models.SKILL_NAMES 对不上"


def catalogue() -> list[dict]:
    """`GET /api/courses/{id}/skills` 的清单，也是提示词里给模型看的那份。"""
    return [
        {
            "name": skill.name,
            "title": skill.title,
            "description": skill.description,
            "params": [{"name": name, "desc": desc} for name, desc in skill.params.items()],
        }
        for skill in SKILLS.values()
    ]


def run(ctx: SkillContext, name: str, args: Mapping[str, Any] | None = None) -> dict:
    """跑一个技能。**不抛异常**：失败也是一次调用，要落进操作卡（P4-A10）。"""
    skill = SKILLS.get(str(name or ""))
    started = perf_counter()
    if skill is None:
        return {"skill": name, "status": "failed", "result": None, "durationMs": 0,
                "error": f"没有「{name}」这个技能"}
    try:
        result = skill.fn(ctx, dict(args or {}))
    except AppError as exc:
        return {"skill": name, "status": "failed", "result": None,
                "durationMs": _ms(started), "error": exc.message}
    except Exception as exc:  # 技能内部出意外：记日志、给用户一句人话
        logger.warning("技能 %s 执行失败：%s", name, type(exc).__name__, exc_info=True)
        return {"skill": name, "status": "failed", "result": None,
                "durationMs": _ms(started), "error": f"技能执行失败（{type(exc).__name__}）"}
    return {"skill": name, "status": "ok", "result": result, "durationMs": _ms(started), "error": ""}


# --- 内部 ---


def _quiz_page(ctx: SkillContext, chapter_no: int):
    rows = [row for row in store.pages_of(ctx.course) if int(row.chapter_no or 0) == chapter_no]
    quiz = next((row for row in reversed(rows) if row.kind == "quiz"), None)
    if quiz is not None:
        return quiz
    if not rows:
        raise ValidationError(f"这门课没有第 {chapter_no} 章")
    return store.insert_page(
        ctx.course, chapter_no=chapter_no, after_page_no=rows[-1].page_no,
        kind="quiz", title=f"第 {chapter_no} 章 · 随堂测验",
    )


def _write_new_page(ctx: SkillContext, page, instruction: str) -> tuple[dict, int]:
    """给刚插进来的空页写内容，返回 `(dsl, 花的 token)`。

    与管线写页同一个套路（注入材料 + 定出处），只是**不带大纲与上一页**：
    这一页是对话里临时加的，它要贴着用户那句话写，而不是贴着课程计划写。
    """
    from app.services.generation import sourcing

    target = {
        "pageNo": page.page_no, "chapterNo": page.chapter_no, "kind": page.kind,
        "title": page.title or "", "points": [instruction] if instruction else [],
    }
    injected = sourcing.inject(
        ctx.course.id, sourcing.page_query(target),
        limit=citations.config_int("MATERIAL_PAGE_TOP_K", 8),
    )
    call = call_page(
        ctx.provider,
        prompts.page_messages(target, profile={}, materials=list(injected.values())),
        kind=page.kind, page_no=page.page_no, chapter_no=page.chapter_no,
        job_id="", owner_id=ctx.owner_id,
        ref_type=REF_TYPE_CHAT, ref_id=ctx.course.id,
    )
    dsl, summary = sourcing.settle(call.data, injected)
    store.save_page(page, dsl, reason="generate", model=call.model, tokens=call.tokens,
                    meta={"skill": "add_page", "sources": summary})
    sourcing.persist(page, dsl)
    return dsl, int(call.tokens or 0)


def _quiz_messages(ctx: SkillContext, page, topic: str) -> list[dict]:
    dsl = ctx.course.dsl or {}
    chapter: dict[str, Any] = next(
        (item for item in dsl.get("chapters") or []
         if int(item.get("no") or 0) == int(page.chapter_no or 0)),
        {},
    )
    body = [
        prompts.task_header(task="quiz_skill"),
        f"【课程】{ctx.course.title}",
        f"【章节】第 {chapter.get('no')} 章 · {chapter.get('title') or ''}",
        f"【本章要点】{'；'.join(str(item) for item in chapter.get('points') or [])}",
        f"【出题范围】{topic}" if topic else "",
        "",
        "请按上面的范围出一道单选题：题干要问「为什么」或「怎么用」，"
        "四个选项里只有一个是错的/对的，`answer` 写选项字母，`explain` 用两句话说清原因。",
    ]
    return [
        {"role": "system", "content": "你是一位命题老师，出的题考理解而不是记背。"},
        {"role": "user", "content": "\n".join(part for part in body if part)},
    ]


def _summary_messages(ctx: SkillContext, query: str, hits: Sequence[Any]) -> list[dict]:
    material = "\n".join(
        f"<<<MATERIAL chunk:{hit.chunk_id}>>>\n（出处：{hit.material_name} · 第 {hit.page_no} 页）\n"
        f"{hit.text}\n<<<END>>>"
        for hit in hits
    )
    body = [
        prompts.task_header(task="summarize_material"),
        f"【课程】{ctx.course.title}",
        f"【问题】{query}",
        "",
        "【参考资料】",
        material,
        "",
        "只依据上面的材料回答，3~5 条要点，每条一句话；材料里没有的不要写。",
    ]
    return [
        {"role": "system", "content": "你是一位助教，回答课程问题时只依据给到的材料。"},
        {"role": "user", "content": "\n".join(body)},
    ]


_QUIZ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "stem": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
        "answer": {"type": "string"},
        "explain": {"type": "string"},
        "conceptTag": {"type": "string"},
    },
    "required": ["stem", "options", "answer", "explain"],
}

_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"points": {"type": "array", "items": {"type": "string"}}},
    "required": ["points"],
}


def _parse_quiz(text: str) -> dict:
    """出题的校验：四个选项、答案得是其中之一 —— 不合格就让模型重来一次。"""
    data = load_json(text)
    options = [str(item).strip() for item in (data.get("options") or []) if str(item).strip()]
    answer = str(data.get("answer") or "").strip().upper()[:1]
    if len(options) < 4 or answer[:1] not in ("A", "B", "C", "D"):
        raise ValidationError("题目要四个选项、答案是 A/B/C/D 之一")
    return {
        "stem": str(data.get("stem") or "").strip() or "（题干缺失）",
        "options": options[:4],
        "answer": answer,
        "explain": str(data.get("explain") or "").strip(),
        "conceptTag": str(data.get("conceptTag") or "").strip(),
    }


def _parse_summary(text: str) -> dict:
    data = load_json(text)
    points = [str(item).strip() for item in (data.get("points") or []) if str(item).strip()]
    if not points:
        raise ValidationError("要点不能是空的")
    return {"points": points[:5]}


def _ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


__all__ = [
    "MAX_TONE_PAGES",
    "QUOTE_CHARS",
    "SKILLS",
    "SUMMARY_TOP_K",
    "Skill",
    "SkillContext",
    "catalogue",
    "run",
]
