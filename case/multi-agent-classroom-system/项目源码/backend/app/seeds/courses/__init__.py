"""预置「官方示例课」（P1-7，交付物清单第 4 条）。

为什么要有它：P2 接语音、P3 开课堂，两件事都要在有模型、有网络的环境里
才能演示得起来 —— 而演示现场最常见的意外就是没有网、没有 Key。
这两门课是**离线素材**：装好就有一门完整的课可以翻、可以讲、可以导出。

三条约定：

1. **内容和真实生成的课长得一样**。页面 DSL 走的是同一个
   `schema.validate_page()` —— 生成链路怎么写，这里就怎么写。
   少走这一步的代价很具体：种子课的 `narration` 是一整段字符串、
   生成课的是 beat 数组，前端就得为「两种讲稿」各写一套渲染。
2. **作者只写文本**。`beats` 的编号、每句的秒数、缺省字段的收敛
   都由校验器算（`normalize_beats` / `_to_dsl`），写种子的人不该
   手工维护 `p7-b3` 这种编号 —— 那是排一次序就能对上的东西。
3. **手写，不用桩**。离线桩（`providers/llm/fixture.py`）造出来的课是
   「结构合格」，用来验收管线；这两门课是给人看的，讲稿要能直接念。

新增一门课 = 在这个包里加一个模块，然后登记到 `_MODULES`。
"""

from __future__ import annotations

from typing import Any

from app.seeds.courses import ml_intro, photosynthesis
from app.services.generation import schema

#: 示例课的归属用户。与角色、音色同属「演示教师」这一套种子。
OWNER_ID = "user_demo_teacher"

#: 两门课的模块。顺序就是列表页的顺序 —— 模型课在前（原型里的样板课）。
_MODULES = (ml_intro, photosynthesis)


def course_specs() -> list[dict]:
    """两门课的**课程级**字段（不含页面）。"""
    return [_course_spec(module) for module in _MODULES]


def page_specs_of(course_id: str) -> list[dict]:
    """某门课的页面（已经是规范化后的 DSL）。"""
    module = _module_of(course_id)
    return [_page_spec(module, page) for page in module.PAGES]


def dsl_of(course_id: str) -> dict:
    """课程级 `dsl_json` 的骨架。

    只写「页面行里没有的那部分」：版本、形式、副标题、章节的标题与讨论点。
    页号列表与页面正文由 `store.rebuild_dsl()` 从页面行重算（P1-C1）——
    在这里再写一份页号，第一次删页就会与页面行对不上。
    """
    module = _module_of(course_id)
    return {
        "version": module.VERSION,
        "mode": module.COURSE["mode"],
        "subtitle": module.COURSE["subtitle"],
        "chapters": [
            {
                "no": chapter["no"],
                "title": chapter["title"],
                "summary": chapter["summary"],
                "points": list(chapter["points"]),
                "discussion": list(chapter["discussion"]),
                "pages": [],
            }
            for chapter in module.CHAPTERS
        ],
    }


def meta_of(course_id: str) -> dict:
    """课程级 meta：受众画像与生成信息。

    生成课在 parse 步会写一份 `audienceProfile`，示例课没有那一步，
    所以这里补一份同形的 —— P3 的课堂要照着受众调语气，缺了就得特判。
    """
    module = _module_of(course_id)
    return {
        "audienceProfile": dict(module.PROFILE),
        "source": "seed",
        "title": module.COURSE["title"],
        "topic": module.COURSE["topic"],
    }


# --- 内部 ---


def _module_of(course_id: str) -> Any:
    for module in _MODULES:
        if module.COURSE["id"] == course_id:
            return module
    raise KeyError(f"没有这门示例课：{course_id}")


def _course_spec(module: Any) -> dict:
    """课程级字段 = 作者写死的那些。

    没有 `cover`：封面卡上的讲师/时长/受众都在**封面页**的 `meta` 里，
    而 `store.rebuild_dsl()` 每次都会用那一页重算 `courses.cover_json`。
    在这里再写一份，只会在下一次重算时被悄悄改掉 —— 两份真相里活下来的
    是页面行，于是这里那份就成了误导。
    """
    course = module.COURSE
    return {
        "id": course["id"],
        "title": course["title"],
        "topic": course["topic"],
        "status": course["status"],
        "duration_min": course["duration_min"],
    }


def _texts_of(dsl: dict) -> dict:
    """把 `bullets` / `narration` 里的裸字符串补成对象。

    DSL 里这两项是对象数组（带 `emphasis` / `beatId` / `estSec`），但作者只该写
    `"水的光解产生氧气"` 这样一句文本：编号与秒数是 `normalize_beats` 按页号算的，
    写进作者稿只会两边对不上。补齐放在这里，样板课才不至于变成一份 JSON 练习。
    """
    payload = dict(dsl)
    for key in ("bullets", "narration"):
        rows = payload.get(key)
        if isinstance(rows, list):
            payload[key] = [
                {"text": row} if isinstance(row, str) else dict(row) for row in rows
            ]
    return payload


def _page_spec(module: Any, page: dict) -> dict:
    """一页的作者稿 → 落库形状。字段全走校验器，作者只写文本。"""
    dsl = schema.validate_page(
        page["kind"],
        _texts_of(page["dsl"]),
        page_no=page["page_no"],
        chapter_no=page["chapter_no"],
    )
    return {
        "page_no": page["page_no"],
        "chapter_no": page["chapter_no"],
        "kind": page["kind"],
        "title": dsl["title"] or page["title"],
        "dsl": dsl,
    }


__all__ = [
    "OWNER_ID",
    "course_specs",
    "dsl_of",
    "meta_of",
    "page_specs_of",
]
