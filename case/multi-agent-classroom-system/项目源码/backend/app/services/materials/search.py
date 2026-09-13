"""BM25 检索（F4-5 / P4-A3/A4 / P4-D3）。

公式就是教科书上的那一份（`k1=1.5, b=0.75`，P4 §4 指定），实现上的三个决定
才是这个文件值得解释的地方：

1. **查不到的词不加分也不报错**。语料里没有它，它就无法区分任何两块 ——
   给它一个「凭空的高 IDF」（BM25 若按 `df=0` 代入，IDF 会趋向无穷）会让
   **每一个**块都得满分，等于把排序抹平。所以 `df=0` 的词直接跳过；
   一个查询里所有词都不在语料里 → 返回空列表，而不是硬凑一批结果出来（P4-A3）。
2. **归一化到 0~1 用的是「这个块覆盖了查询里多少信息量」**，不是「它比第一名
   差多少」。按第一名归一的话，拿一个毫不相关的词去查也总会有一个 1.0 的结果，
   前端就会在任何时候都显示「相关度 100%」。这里除以的是**查询词各自可能贡献
   的最大值之和**，于是「无关查询」得到的是接近 0 的分 —— 前端可以放心地
   把低分结果折叠掉。
3. **`score` 是相对语料的，不是绝对的**。同一段文字在两份材料里检索得到的分数
   会不同（df 不同）—— 这是 BM25 的本意，不是缺陷。它的用途是排序与「强弱」展示，
   正确性判定（引文对不对）由子串匹配负责（P4-C2），不看分。
4. **先打分、再取正文**。一次命中几千块是常态（「检索」这种词在整份讲义里到处
   都是），而用户只看得到前 8 条。所以打分只碰倒排表（词频 + 文档长度这两个整数），
   正文只对选出来的前 k 块查一次 —— 把几千块的正文读回内存再丢掉其中的 99.8%，
   正是 P4-D3 的 200ms 预算会被吃光的原因。
5. **打分在 SQL 里聚合，不在 Python 里循环**（P4-D3 实测）。命中几千块时，
   「把倒排行取回 Python」本身就要 100~200ms（12k 块的语料上），而 BM25 是
   `GROUP BY chunk_id` 上的一个 `SUM` —— 交给数据库做，回来的是**前 k 行**而不是
   几万行。`score_chunk()` 仍是**定义**（Python 版，最好读），`_rank()` 是它的
   SQL 镜像；`tests/unit/test_material_search.py` 里有一条差分用例逐位比对两者，
   所以「两边公式漂开了」会被测试拦住，而不是变成「排序莫名其妙」。

排序的最后一道保险是 `(-score, chunk_id)`：分数相同的两块顺序必须稳定，
否则「刷新一下结果换了个顺序」会被当成 bug 报上来，而它其实只是 set 的迭代顺序。
分档更严的一处是归一化截顶：几块都超过 1.0 时它们**并列满分**，此时按 `chunk_id`
排 —— SQL 那边也得照这个口径写（`min(score, 1.0)` 之后再排序），否则并列的两块
在两个实现里顺序不同。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

from sqlalchemy import case, func, literal, select

from app.extensions import db
from app.models import ChunkKeyword, MaterialChunk, MaterialStats
from app.services.materials import indexer

#: BM25 的两个自由参数（P4 §4 指定）。k1 控制词频的饱和速度，b 控制文档长度
#: 的惩罚力度 —— 0.75 是「长度归一化只做四分之三」的常见取值。
K1 = 1.5
B = 0.75

#: 单次检索最多返回多少块。接口层也会限制 `topK`，这里是最后一道：
#: 它挡的是「调用方把 topK 传成 100000」这种把整份材料读进内存的情况。
MAX_TOP_K = 50


@dataclass(frozen=True)
class Hit:
    """一条检索结果。`text` 是完整的一块 —— 溯源跳转要用它做高亮。"""

    chunk_id: str
    material_id: str
    material_name: str
    chunk_no: int
    page_no: int | None
    section_path: str
    text: str
    score: float
    matched: tuple[str, ...]

    def to_dict(self, *, with_text: bool = True) -> dict:
        data = {
            "chunkId": self.chunk_id,
            "fileId": self.material_id,
            "fileName": self.material_name,
            "chunkNo": self.chunk_no,
            "page": self.page_no,
            "section": self.section_path,
            "score": round(self.score, 4),
            "matched": list(self.matched),
        }
        if with_text:
            data["text"] = self.text
        return data


@dataclass(frozen=True)
class Corpus:
    """一次检索用到的语料统计。`doc_count == 0` 表示没有可检索的材料。"""

    doc_count: int
    avg_len: float
    df: dict[str, int]

    @property
    def empty(self) -> bool:
        return self.doc_count <= 0


def load_corpus(material_ids: Sequence[str]) -> Corpus:
    """取这几份材料的语料统计并合并（见 `indexer.merge_stats`）。"""
    ids = [str(item) for item in material_ids if item]
    if not ids:
        return Corpus(0, 0.0, {})
    rows = db.session.scalars(
        select(MaterialStats).where(MaterialStats.material_id.in_(ids))
    ).all()
    doc_count, avg_len, df = indexer.merge_stats(rows)
    return Corpus(doc_count, avg_len, df)


def build_query(terms: Sequence[str], corpus: Corpus) -> tuple[dict[str, float], float]:
    """查询词 → (每个词的 IDF, 归一化分母)。

    分母是「查询里每个词各自最多能贡献多少分」之和：tf 无穷大、文档长度正好等于
    平均长度时，一个词的贡献上限是 `idf * (K1 + 1)`。用它做分母，得分就落在 0~1，
    且**与第一名是谁无关**。
    """
    idfs: dict[str, float] = {}
    for term in terms:
        df = corpus.df.get(term, 0)
        if df <= 0:
            continue
        idfs[term] = math.log(1 + (corpus.doc_count - df + 0.5) / (df + 0.5))
    denom = sum(value * (K1 + 1) for value in idfs.values())
    return idfs, denom


def score_chunk(tf: dict[str, int], length: int, idfs: dict[str, float], corpus: Corpus) -> float:
    """一块的原始 BM25 分（未归一化）。"""
    dl = max(1, int(length or 0))
    avg = corpus.avg_len if corpus.avg_len > 0 else float(dl)
    total = 0.0
    for term, freq in tf.items():
        idf = idfs.get(term)
        if not idf:
            continue
        total += idf * freq * (K1 + 1) / (freq + K1 * (1 - B + B * dl / avg))
    return total


def search(
    query: str,
    *,
    material_ids: Sequence[str],
    top_k: int = 8,
) -> list[Hit]:
    """在指定的材料里检索。`material_ids` 为空 → 空结果（不跨用户搜）。"""
    ids = [str(item) for item in material_ids if item]
    terms = indexer.terms_of(query)
    if not ids or not terms:
        return []
    corpus = load_corpus(ids)
    if corpus.empty:
        return []
    idfs, denom = build_query(terms, corpus)
    if not idfs or denom <= 0:
        # 查询里的词一个都不在语料里：老实返回「没找到」（P4-A3）
        return []

    ranked = _rank(ids, idfs, denom, corpus, _clamp(top_k))
    if not ranked:
        return []

    # 到这里只剩前 k 块（≤50）：正文与命中词都只查这些块，不再碰倒排表的其余部分
    chunk_ids = [chunk_id for _score, chunk_id in ranked]
    chunks = {
        chunk.id: chunk
        for chunk in db.session.scalars(
            select(MaterialChunk).where(MaterialChunk.id.in_(chunk_ids))
        )
    }
    freqs_by_chunk = _matched_terms(chunk_ids, idfs)
    names = _material_names(ids)

    hits: list[Hit] = []
    for score, chunk_id in ranked:
        chunk = chunks.get(chunk_id)
        if chunk is None:  # pragma: no cover - 打分与取正文之间被删掉
            continue
        freqs = freqs_by_chunk.get(chunk_id, {})
        hits.append(
            Hit(
                chunk_id=chunk.id,
                material_id=chunk.material_id,
                material_name=names.get(chunk.material_id, ""),
                chunk_no=chunk.chunk_no,
                page_no=chunk.page_from,
                section_path=chunk.section_path,
                text=chunk.text,
                score=score,
                # 命中词按贡献从大到小 —— 前端要显示「命中：检索、索引」
                matched=tuple(
                    sorted(freqs, key=lambda term: (-idfs.get(term, 0.0) * freqs[term], term))
                ),
            )
        )
    return hits


def _rank(
    ids: Sequence[str],
    idfs: dict[str, float],
    denom: float,
    corpus: Corpus,
    limit: int,
) -> list[tuple[float, str]]:
    """`score_chunk` 的 SQL 版：在库里 `GROUP BY chunk_id` 聚合，只回前 `limit` 行。

    逐项对着 `score_chunk` 写，连**运算顺序**都一样（浮点加法不满足结合律，
    `(a+b)+c` 与 `a+(b+c)` 是可以差最后一位的）—— `SUM` 的加法顺序由数据库定，
    所以两者只保证到「排序一致、分数差在 1e-12 以内」，差分用例也是这么比的。

    三处值得解释的写法：

    - `CASE keyword WHEN ... THEN idf`：每个词的 IDF 是**算好的常数**（见
      `build_query`），把它当参数传进去，而不是在 SQL 里再算一遍 `log`。
    - `MAX(tokens, 1)` 用 `CASE` 写而不是 `max()`：SQLite 的 `max(a, b)` 是标量
      函数，但别的数据库里 `max` 只做聚合，`CASE` 两边都对。
    - `min(..., 1.0)` 截顶写在 SQL 里（不是取回来再截）：排序键必须是**截顶之后**
      的分数，否则并列满分的那几块在两边顺序不同（见模块头注释）。
    """
    doc_len = case((MaterialChunk.tokens > 1, MaterialChunk.tokens), else_=1)
    # `avg_len <= 0` 只在语料统计坏掉时才出现（`merge_stats` 除不出正数）；这时按
    # `score_chunk` 的口径退化成「拿这一块自己的长度当平均长度」。
    average: Any = literal(corpus.avg_len) if corpus.avg_len > 0 else doc_len
    idf = case(idfs, value=ChunkKeyword.keyword, else_=0.0)
    tf = ChunkKeyword.tf

    raw = func.sum(tf * idf * (K1 + 1) / (tf + K1 * (1 - B + B * doc_len / average)))
    score = func.min(raw / denom, 1.0).label("score")
    stmt = (
        select(score, MaterialChunk.id)
        .join(MaterialChunk, MaterialChunk.id == ChunkKeyword.chunk_id)
        .where(ChunkKeyword.keyword.in_(list(idfs)))
        .where(MaterialChunk.material_id.in_(list(ids)))
        .group_by(MaterialChunk.id)
        # 排序键就是 select 里的那个 `score` 别名（截顶后的），并列时按 id 兜底
        .order_by(score.desc(), MaterialChunk.id)
        .limit(limit)
    )
    # 没有 `HAVING > 0`：`idf` 恒为正（`df` 落在 1..doc_count 之间），每个分组都
    # 至少有一行命中，所以 SUM 必然为正 —— 与 `score_chunk` 的 `raw > 0` 等价。
    return [(float(value), chunk_id) for value, chunk_id in db.session.execute(stmt)]


def _matched_terms(chunk_ids: Sequence[str], idfs: dict[str, float]) -> dict[str, dict[str, int]]:
    """前 k 块各自命中了哪些词、命中几次（`Hit.matched` 要显示「命中：检索、索引」）。"""
    rows = db.session.execute(
        select(ChunkKeyword.chunk_id, ChunkKeyword.keyword, ChunkKeyword.tf).where(
            ChunkKeyword.chunk_id.in_(list(chunk_ids)),
            ChunkKeyword.keyword.in_(list(idfs)),
        )
    ).all()
    grouped: dict[str, dict[str, int]] = {}
    for chunk_id, keyword, tf in rows:
        grouped.setdefault(chunk_id, {})[keyword] = int(tf)
    return grouped


def _material_names(ids: Sequence[str]) -> dict[str, str]:
    """溯源徽标上要写「讲义第三章.pdf 第 12 页」，名字得跟着结果一起回来。"""
    from app.models import Material

    rows = db.session.execute(
        select(Material.id, Material.name).where(Material.id.in_(list(ids)))
    ).all()
    return {row[0]: row[1] for row in rows}


def _clamp(top_k: int) -> int:
    try:
        value = int(top_k)
    except (TypeError, ValueError):
        value = 8
    return max(1, min(value, MAX_TOP_K))


__all__ = [
    "K1",
    "MAX_TOP_K",
    "B",
    "Corpus",
    "Hit",
    "build_query",
    "load_corpus",
    "score_chunk",
    "search",
]
