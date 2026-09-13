"""生成链路里的材料注入与出处落定（P4-4 / F4-7 / F4-8 / P4-A7/A8）。

`services/materials/citations.py` 回答「哪些片段、引文对不对」，
`services/generation/prompts.py` 回答「怎么放进提示词」，
这个文件是中间那一层：**一次生成里材料该怎么用**。它被两条路复用 ——
管线里的写页（`pipeline._produce`）与工作台的同步重写（`courses.library.rewrite_page`），
两处要的规则一模一样，各写一份必然分叉。

三条规则在这里定死：

1. **查什么**：写一页用「标题 + 本页要点」，重写沿用这一页现在的标题与要点。
   检索不到就是空——生成照常进行，只是回到「只凭主题」那条路（P4-G3）。
2. **重试几次**：引文核对不过，带着**具体是哪一条不对**回喂一次（§5）。
   只重试一次：第二次还错说明这段材料里没有它想引的话，
   再试只是白花一次调用。
3. **仍不过怎么办**：保留内容、只留通过的出处、标 `sourceMissing`，
   并把失败原因写进日志。用户要的是能用的课件，不是一片空白；
   而「哪几条引文没对上」是排障时要看的东西，不是要给用户看的。
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from app.common.logging import get_logger
from app.services.generation import prompts
from app.services.materials import citations

logger = get_logger("app.generation.sourcing")

#: 一页最多问模型要几处出处。比注入的片段数略少：一页 3~5 条要点，
#: 每条一个出处刚好，多出来的多半是凑数。
MAX_SOURCES_PER_PAGE = 5


def inject(course_id: str, query: str, *, limit: int) -> dict[str, dict]:
    """检索这门课的材料，返回 `{chunkId: 片段}`（就是交给模型的那几片）。

    返回字典而不是列表：核对引文时要按 `chunkId` 反查，而且**注入集合 = 允许引用的
    集合**，用同一个对象表达最不容易漂。
    """
    return {hit["chunkId"]: hit for hit in citations.retrieve(course_id, query, limit=limit)}


def page_query(page: Mapping[str, Any]) -> str:
    """一页的检索词：标题 + 这一页的要点提示。

    不额外让模型产关键词：标题与要点本来就在这次调用的上下文里，
    再问一次只是多花一次调用去得到同样的东西。
    """
    parts = [str(page.get("title") or "")]
    parts.extend(str(item) for item in (page.get("points") or []))
    return " ".join(part for part in parts if part).strip()


def settle(
    dsl: dict,
    injected: Mapping[str, dict],
    *,
    regenerate: Callable[[str], tuple[dict, int]] | None = None,
) -> tuple[dict, dict]:
    """给一份刚生成的页面 DSL 定出处。返回 `(最终 dsl, 摘要)`。

    `regenerate(反馈)` 由调用方提供（它知道自己的 provider 与 messages），
    返回 `(新 dsl, 这一次花的 token)`。
    """
    raw = list(dsl.get("sources") or [])
    summary: dict[str, Any] = {"injected": len(injected), "sources": len(raw)}

    if not injected:
        # 没给材料就别留出处：它引的是模型自己的记忆，不是这门课的材料，
        # 界面上会显示成一个个点不开的徽标。
        if raw:
            dsl = {**dsl, "sources": []}
            summary["dropped"] = len(raw)
        dsl["sourceMissing"] = False
        return dsl, summary

    kept, problems = citations.verify(raw, injected)
    if problems and regenerate is not None:
        summary["retried"] = True
        try:
            again, tokens = regenerate(prompts.source_retry(problems))
        except Exception as exc:  # 重试失败不该把已经写好的一页丢掉
            logger.warning("出处重试失败：%s", type(exc).__name__)
        else:
            summary["retryTokens"] = tokens
            # 第二次的**全部**结论都作数：它可能删掉了一条编的、也可能换了个说法
            kept, problems = citations.verify(again.get("sources") or [], injected)
            if not problems:
                dsl = again

    dsl = {**dsl, "sources": kept[:MAX_SOURCES_PER_PAGE]}
    dsl["sourceMissing"] = bool(problems)
    if problems:
        # P4-A7 要的那条日志：用户看不到，排障时靠它分清
        # 「这一页本来就没材料」与「模型给了一条对不上的引文」
        logger.warning("source_mismatch problems=%s", "；".join(problems))
    summary["kept"] = len(dsl["sources"])
    summary["problems"] = problems
    return dsl, summary


def persist(page: Any, dsl: Mapping[str, Any]) -> int:
    """把定好的出处落到 `page_sources`（先删后写）。

    与 `save_page` 分两次写：这里不碰页面本身，而页面内容该由课程那条路负责。
    中间崩掉只会少一层溯源，重新生成即可 —— 两个写操作合成一个事务要付出的
    耦合（课程 store 认识材料表）比这层风险贵。
    """
    from app.common.dbw import db_write

    sources: Sequence[Mapping[str, Any]] = dsl.get("sources") or []
    written = 0

    def work() -> None:
        nonlocal written
        written = citations.replace_sources(page, sources)

    db_write(work)
    return written


__all__ = ["MAX_SOURCES_PER_PAGE", "inject", "page_query", "persist", "settle"]
