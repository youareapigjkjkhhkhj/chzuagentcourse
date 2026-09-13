"""生成时的材料注入与溯源校验（P4-4 / F4-7 / F4-8 / P4-C2 / P4-A7/A8）。

生成链路与材料域的交界就在这个文件里，它只做四件事：

    取这门课的材料 → 按这一页要讲的东西检索 → 校验模型给的引文 → 落 `page_sources`

**检索词从哪来**：写一页时用「页标题 + 本页的要点提示」，出大纲时用课程主题。
不额外让模型先产关键词 —— 那是一次多余调用，而标题与要点本来就是这一步已经在
提示词里的东西。

**为什么引文要逐字校验**（P4-C2）：模型的转述与原文长得几乎一样，只有逐字比对
才分得清「引用了材料」与「讲得像材料」。所以 `quote` 必须是 chunk 正文的连续
子串（去掉空白与标点后比 —— 模型重排一下换行不该算不匹配）。

**校验不过怎么办**（§5）：带着失败原因**重生成一次**；仍不过就把这一页标成
`source_missing` 但**保留内容**（用户要的是能用的课件，不是一片空白），
同时在 `page_sources` 里只留通过的那些 —— 宁缺毋滥，前端标黄提示比标错出处好。
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from flask import current_app
from sqlalchemy import select

from app.common.logging import get_logger
from app.extensions import db
from app.models import PageSource
from app.services.materials import policy, search, store

logger = get_logger("app.materials.citations")

#: 比对引文时先去掉的字符：空白与常见的全半角标点。
#: 只去掉这些，中文与字母数字一个不动 —— 「BM25」与「bm25」是两回事，
#: 这里不做大小写归一（那会让「引文对不对」变成另一件事）。
_NOISE = re.compile(r"[\s，。、；：？！「」『』（）()《》〈〉“”‘’\"'`,.;:?!\[\]【】—–\-…·]+")


def enabled() -> bool:
    """材料链路的总开关（P4-G3）。关掉时生成回到「只凭主题」那条路。"""
    return policy.enabled()


def material_ids_of(course_id: str) -> list[str]:
    """这门课关联的材料 id。没关材料也没关联任何材料时是空表。"""
    if not enabled() or not course_id:
        return []
    return store.material_ids_of_course(course_id)


def config_int(name: str, default: int) -> int:
    """读一个材料相关的整数配置（`MATERIAL_PAGE_TOP_K` 这类）。

    没有应用上下文时返回默认值：检索注入要在生成线程里跑，
    那里有上下文；但「用几个词试一下检索」这种离线调用没有。
    """
    from flask import has_app_context

    if not has_app_context():
        return default
    return int(current_app.config.get(name) or default)


def retrieve(course_id: str, query: str, *, limit: int) -> list[dict]:
    """给生成阶段检索材料片段。返回空表 = 「这门课没有可用的材料」。

    每一步都退得回去：材料关着、没关联、检索不到、查询词是空的 ——
    结果都是空表，调用方据此走原来那条只凭主题的路（P4-G3）。
    """
    ids = material_ids_of(course_id)
    text = str(query or "").strip()
    if not ids or not text or limit <= 0:
        return []
    hits = search.search(text, material_ids=ids, top_k=limit)
    return [hit.to_dict() for hit in hits]


def verify(sources: Sequence[Any], injected: Mapping[str, dict]) -> tuple[list[dict], list[str]]:
    """把模型给的 `sources` 逐条核对，返回 `(通过的, 不通过的原因)`。

    `injected` 是这次**真的交给模型**的那几块（chunk_id → 片段）。只在里面找：
    模型编一个没给它看过的 chunkId，或者引用一块它在别的页见过的材料，
    都算不通过 —— 「出处」必须是这次检索得到的那个集合里的东西。
    """
    kept: list[dict] = []
    problems: list[str] = []
    minimum = config_int("MATERIAL_QUOTE_MIN_CHARS", 20)
    for index, item in enumerate(sources, start=1):
        chunk_id = str(_field(item, "chunkId") or "").strip()
        quote = str(_field(item, "quote") or "").strip()
        if not chunk_id or not quote:
            problems.append(f"第 {index} 条出处缺少 chunkId 或 quote")
            continue
        chunk = injected.get(chunk_id)
        if chunk is None:
            problems.append(f"第 {index} 条出处引用了未提供给它的片段 {chunk_id}")
            continue
        body = _squeeze(quote)
        if len(body) < minimum:
            problems.append(f"第 {index} 条引文太短（不足 {minimum} 字），无法核对")
            continue
        if body not in _squeeze(str(chunk.get("text") or "")):
            problems.append(f"第 {index} 条引文在材料原文里找不到：{quote[:30]}")
            continue
        kept.append(
            {
                "materialId": str(chunk.get("fileId") or chunk.get("materialId") or ""),
                "chunkId": chunk_id,
                "pageNo": chunk.get("page"),
                "sectionPath": str(chunk.get("section") or ""),
                "quote": quote,
                "score": float(chunk.get("score") or 0.0),
            }
        )
    return kept, problems


def replace_sources(page, sources: Sequence[Mapping[str, Any]]) -> int:
    """把一页的溯源整批换掉（先删后写，P4-C5 同一条口径）。返回写入的条数。

    重新生成一页时旧引文必须先清掉：留着的话，页面上会出现「这一版已经不存在
    的出处」，而徽标仍然点得动 —— 那种错比没有出处更难发现。
    """
    page_id = str(getattr(page, "id", "") or "")
    if not page_id:
        return 0
    db.session.execute(PageSource.__table__.delete().where(PageSource.page_id == page_id))
    rows = [
        PageSource(
            page_id=page_id,
            material_id=str(item.get("materialId") or ""),
            chunk_id=str(item.get("chunkId") or ""),
            page_no=item.get("pageNo"),
            section_path=str(item.get("sectionPath") or "")[:255],
            quote=str(item.get("quote") or ""),
            score=float(item.get("score") or 0.0),
        )
        for item in sources
        if item.get("materialId") and item.get("chunkId")
    ]
    if rows:
        db.session.add_all(rows)
    db.session.flush()
    return len(rows)


def sources_of(page_id: str) -> list[dict]:
    """一页的溯源（按写入顺序）。前端徽标读的是它，不是 DSL 里那份。"""
    rows = db.session.scalars(
        select(PageSource).where(PageSource.page_id == str(page_id or ""))
    ).all()
    return [row.to_dict() for row in rows]


def _field(item: Any, name: str) -> Any:
    """`sources` 里的一项 —— 模型可能给对象（正常），也可能给字符串（P1 的老形态）。"""
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


def _squeeze(text: str) -> str:
    """去掉空白与标点，只留字。大小写**不**归一：`BM25` 与 `bm25` 是两个词。"""
    return _NOISE.sub("", str(text or ""))


__all__ = [
    "config_int",
    "enabled",
    "material_ids_of",
    "replace_sources",
    "retrieve",
    "sources_of",
    "verify",
]
