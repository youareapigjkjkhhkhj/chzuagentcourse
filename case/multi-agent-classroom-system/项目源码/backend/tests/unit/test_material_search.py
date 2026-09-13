"""分词与 BM25 检索测试（F4-4/F4-5 / P4-A3/A4 / P4-C5）。

检索的质量没法自动判（P4-E3 要人工看 10 个查询），能自动判的是**它的性质**：

- 命中要落在真正提到那个词的块上，且分数有区分度；
- 语料里没有的词不许凭空得分（否则每个块都「相关」，排序等于没有）；
- 分数与「第一名是谁」无关（否则任何查询都会有一个 1.0 的结果，前端只能显示
  「相关度 100%」，P4-A3 要的「无关词得分明显偏低」就永远不成立）；
- 跨材料检索时 `df` 与文档数是**合并**的（一份块只属于一份材料，相加正好对）。

写这些测试时用的都是真实管线：块落库、`indexer.build()` 建索引、`search.search()`
检索 —— 只有「造材料」这一步是直接写模型，因为这里要控制块的内容。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.extensions import db

pytestmark = pytest.mark.unit

RETRIEVAL = [
    "检索的第一步是把问题变成词。把问题变成词之后，才能在索引里找得到东西。",
    "倒排索引把词映射到文档。倒排索引是搜索引擎的基石，也是排序的前提。",
    "BM25 是一种经典的排序函数，它同时考虑词频与文档长度，是对倒排索引结果的打分。",
]
WEATHER = [
    "今天的天气很热，气温达到了三十五度，出门要记得带水。",
    "夏季的高温会持续到九月，气象台提醒注意防暑降温。",
]


def _publish(texts, *, name="讲义.txt", owner_id=None):
    """把几段文字当作一份已解析好的材料写进库（块与索引都走真实管线）。"""
    from app.common.timeutil import utcnow_iso
    from app.models import ChunkKeyword, Material, MaterialChunk, MaterialStats, new_id
    from app.services.materials import indexer
    from app.services.materials.chunking import Chunk

    material = Material(
        owner_id=owner_id,
        name=name,
        ext=".txt",
        size_bytes=sum(len(text) for text in texts),
        sha256=new_id(),
        status="ready",
    )
    db.session.add(material)
    db.session.commit()

    chunks = [Chunk(chunk_no=index + 1, text=text) for index, text in enumerate(texts)]
    result = indexer.build(chunks)
    stamp = utcnow_iso()
    rows = [
        {
            "id": new_id(),
            "material_id": material.id,
            "chunk_no": chunk.chunk_no,
            "section_path": "",
            "text": chunk.text,
            "char_count": chunk.char_count,
            "tokens": chunk.tokens,
            "created_at": stamp,
            "updated_at": stamp,
        }
        for chunk in chunks
    ]
    db.session.execute(MaterialChunk.__table__.insert(), rows)
    db.session.execute(
        ChunkKeyword.__table__.insert(),
        [
            {"chunk_id": row["id"], "keyword": word, "tf": tf}
            for row, keywords in zip(rows, result.keywords, strict=False)
            for word, tf in keywords
        ],
    )
    db.session.add(
        MaterialStats(
            material_id=material.id,
            doc_count=result.doc_count,
            avg_doc_len=result.avg_doc_len,
            keyword_df_json=_dump(result.df),
        )
    )
    db.session.commit()
    return material


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# --- 分词 ---


def test_tokens_drop_stopwords_and_punctuation(app):
    """「的」「是」这种词不进索引（它们在任何一块里都出现，区分不了任何东西）。"""
    from app.services.materials import indexer

    tokens = indexer.tokenize("倒排索引是搜索引擎的基石，也就是把词映射到文档。")

    assert "的" not in tokens
    assert "是" not in tokens
    assert "，" not in tokens
    assert "倒排" in tokens


def test_a_single_character_term_survives(app):
    """单字要留着：BM25 的 IDF 会把高频字压下去，而「熵」这种单字是真术语。"""
    from app.services.materials import indexer

    assert "熵" in indexer.tokenize("熵增")


def test_ascii_terms_are_lowercased(app):
    """英文大小写不该分成两个词（BM25 与 bm25 是同一个东西）。"""
    from app.services.materials import indexer

    assert "bm25" in indexer.tokenize("BM25 与 bm25")
    assert "BM25".lower() in indexer.tokenize("用 BM25 排序")


def test_a_repeated_word_in_the_query_counts_once(app):
    """查询里把一个词写两遍是强调，不是「重要两倍」。"""
    from app.services.materials import indexer

    assert indexer.terms_of("检索 检索 检索") == ["检索"]


# --- 检索 ---


def test_a_term_finds_the_chunk_that_actually_uses_it(app):
    """P4-A3：用语料里的术语检索，top-3 里要有真正的出处。"""
    from app.services.materials import search

    with app.app_context():
        material = _publish(RETRIEVAL)
        hits = search.search("倒排索引", material_ids=[material.id])

    assert hits, "术语检索不到任何东西"
    assert "倒排索引" in hits[0].text
    assert 0 < hits[0].score <= 1


def test_an_unrelated_query_does_not_pretend(app):
    """P4-A3：无关词要么没有结果，要么分数明显偏低 —— 不硬凑。"""
    from app.services.materials import search

    with app.app_context():
        material = _publish(RETRIEVAL)
        hits = search.search("量子纠缠与光合作用", material_ids=[material.id])

    assert hits == []


def test_a_query_of_stopwords_alone_is_empty(app):
    """「的是什么」这种查询没有信息量，返回空而不是把整份材料倒出来。"""
    from app.services.materials import search

    with app.app_context():
        material = _publish(RETRIEVAL)
        hits = search.search("的是 什么 一个", material_ids=[material.id])

    assert hits == []


def test_hits_carry_the_matched_terms(app):
    """P4-A4：每个结果要能说出「命中了哪几个词」，前端才讲得清为什么是它。"""
    from app.services.materials import search

    with app.app_context():
        material = _publish(RETRIEVAL)
        hits = search.search("倒排索引 排序", material_ids=[material.id])

    assert hits
    assert set(hits[0].matched) >= {"倒排", "索引"}


def test_a_rare_term_outweighs_a_common_one_in_the_same_query(app):
    """区分度来自 `df`：同一个查询里，「大半个语料都有的词」的贡献远小于「只有一块
    有的词」—— 所以只命中罕见词的那一块，排在只命中常见词的那几块前面。

    注意比的是**同一个查询内部**的两块，不是两个查询：分数按查询自己的信息量
    归一（见 `test_the_score_does_not_depend_on_who_won`），跨查询比大小没有意义。
    """
    from app.services.materials import search

    texts = [
        "机器学习的方法很多。",
        "机器学习的方法不少。",
        "统计学习的方法很稳。",
        "统计学习的方法很慢。",
        "梯度下降是一种算法。",
    ]
    with app.app_context():
        material = _publish(texts)
        hits = search.search("方法 梯度", material_ids=[material.id])

    assert hits
    assert hits[0].text == texts[4], "只命中罕见词的那一块没排到前面"
    assert hits[0].score > hits[1].score * 2


def test_the_score_does_not_depend_on_who_won(app):
    """第一名不一定满分：分数是「覆盖了查询里多少信息量」，不是「比第二名好多少」。

    按第一名归一的话，任何查询（包括完全无关的）都会有一个 1.0 的结果。
    """
    from app.services.materials import search

    with app.app_context():
        material = _publish(RETRIEVAL)
        # 两个词分属两块：谁都只覆盖了一半，于是谁都不是 1.0
        hits = search.search("倒排索引 气温", material_ids=[material.id])

    assert hits
    assert hits[0].score < 1.0


def test_search_is_limited_to_the_materials_it_is_given(app):
    """检索范围由调用方给定（工作台里选了哪几份就搜哪几份）。"""
    from app.services.materials import search

    with app.app_context():
        # id 要在上下文里取出来：退出时 session 被回收，实例上的属性就取不到了
        wanted = _publish(RETRIEVAL, name="检索讲义.txt").id
        other = _publish(WEATHER, name="天气.txt").id
        outside = search.search("气温", material_ids=[wanted])

    assert outside == []
    with app.app_context():
        inside = search.search("气温", material_ids=[other])
    assert inside and "气温" in inside[0].text


def test_no_materials_means_no_results(app):
    """没有指定材料就不搜（不能「顺手搜全库」——那会跨用户）。"""
    from app.services.materials import search

    with app.app_context():
        _publish(RETRIEVAL)
        assert search.search("倒排索引", material_ids=[]) == []


def test_top_k_is_clamped(app):
    """`topK` 传多大都只给上限那么多 —— 挡住「把整份材料读进内存」那种调用。"""
    from app.services.materials import search

    texts = [f"第 {index} 段都在说检索这件事。" for index in range(search.MAX_TOP_K + 10)]
    with app.app_context():
        material = _publish(texts)
        hits = search.search("检索", material_ids=[material.id], top_k=10_000)

    assert len(hits) == search.MAX_TOP_K


def test_the_df_is_merged_across_materials(app):
    """跨材料检索：两份材料各自的 df 相加就是合并语料上的 df。"""
    from app.services.materials import search

    with app.app_context():
        first = _publish(["倒排索引把词映射到文档。"], name="a.txt")
        second = _publish(["倒排索引是搜索引擎的基石。"], name="b.txt")
        hits = search.search("倒排索引", material_ids=[first.id, second.id])

    assert {hit.material_id for hit in hits} == {first.id, second.id}
    assert all(hit.score > 0 for hit in hits)


def test_the_order_is_stable(app):
    """同样的查询跑两次，顺序一样（分数相同时按 id 兜底，不看 set 的迭代顺序）。"""
    from app.services.materials import search

    with app.app_context():
        material = _publish(RETRIEVAL)
        first = [hit.chunk_id for hit in search.search("排序", material_ids=[material.id])]
        second = [hit.chunk_id for hit in search.search("排序", material_ids=[material.id])]

    assert first == second


MIXED = [
    "倒排索引把词映射到文档，倒排索引是检索的基石。",
    "倒排索引。",
    "检索的第一步是把问题变成词，然后才轮到排序。",
    "BM25 用词频与文档长度给倒排索引的结果打分，词频高的块不一定排前面，因为长度也要归一。",
    "梯度下降是一种优化方法，梯度下降每次沿着最陡的方向走一小步。",
    "今天气温三十五度。",
]
#: 最后一个是「只命中一块、且那块很短」的情形：它拿满分（截顶到 1.0），
#: 于是 SQL 与 Python 都得靠 `chunk_id` 兜底排序 —— 两边最容易写岔的地方。
MIXED_QUERIES = ["倒排索引", "检索 排序", "梯度下降 词频", "BM25 长度 检索", "气温"]


def _python_ranking(material_id, idfs, denom, corpus, *, limit):
    """`score_chunk()`（Python 的定义版）给出的排序 —— 就是 `search._rank()` 替掉的那段循环。

    测试里重新写一遍这段循环是有意的：直接从实现里抄的话，两处一起漂就等于没测。
    """
    from app.models import ChunkKeyword, MaterialChunk
    from app.services.materials import search

    rows = db.session.execute(
        select(ChunkKeyword.chunk_id, ChunkKeyword.keyword, ChunkKeyword.tf, MaterialChunk.tokens)
        .join(MaterialChunk, MaterialChunk.id == ChunkKeyword.chunk_id)
        .where(ChunkKeyword.keyword.in_(list(idfs)))
        .where(MaterialChunk.material_id == material_id)
    ).all()
    agg: dict[str, tuple[dict[str, int], int]] = {}
    for chunk_id, keyword, tf, tokens in rows:
        agg.setdefault(chunk_id, ({}, int(tokens or 0)))[0][keyword] = int(tf)

    scored = [
        (min(1.0, raw / denom), chunk_id)
        for chunk_id, (freqs, length) in agg.items()
        if (raw := search.score_chunk(freqs, length, idfs, corpus)) > 0
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[:limit]


def _compare(material_id, queries):
    """逐查询比对 SQL 排序与 Python 排序：顺序必须一样，分数必须一样（到浮点末位）。"""
    from app.services.materials import indexer, search

    ids = [material_id]
    compared = 0
    for query in queries:
        corpus = search.load_corpus(ids)
        idfs, denom = search.build_query(indexer.terms_of(query), corpus)
        assert idfs, f"查询 {query!r} 在语料里一个词都没有，这条差分比不了"
        expected = _python_ranking(material_id, idfs, denom, corpus, limit=search.MAX_TOP_K)
        got = search._rank(ids, idfs, denom, corpus, search.MAX_TOP_K)

        assert [chunk_id for _score, chunk_id in got] == [
            chunk_id for _score, chunk_id in expected
        ], f"查询 {query!r} 的两份排序不一致"
        assert got, f"查询 {query!r} 没有结果"
        # 浮点加法不满足结合律：`SUM` 的加法顺序由数据库定，所以比到 1e-12 而不是逐位相等
        for (mine, _), (theirs, _) in zip(got, expected, strict=True):
            assert abs(mine - theirs) < 1e-12, f"查询 {query!r} 的分数漂了：{mine} vs {theirs}"
        compared += 1
    return compared


def test_the_sql_ranking_agrees_with_the_python_one(app):
    """`_rank()`（SQL 聚合）与 `score_chunk()`（定义）给出同一份排序与同一个分数。

    两处公式漂开的表现是「排序莫名其妙」—— 页面上看不出错，所以只能在这里钉住：
    同一份语料、五个查询，逐块比分数与顺序。
    """
    with app.app_context():
        material = _publish(MIXED)
        assert _compare(material.id, MIXED_QUERIES) == len(MIXED_QUERIES)


def test_the_ranking_still_agrees_when_the_average_length_is_broken(app):
    """语料统计坏掉（`avg_doc_len = 0`）时两边仍要对得上。

    这时 `score_chunk()` 会退化成「拿这一块自己的长度当平均长度」，SQL 那侧的分母
    因此变成一个**逐行的表达式**而不是常数 —— 一个只在脏数据下才走到的分支，
    也正是最容易两边写岔的地方。
    """
    from app.models import MaterialStats
    from app.services.materials import search

    with app.app_context():
        material = _publish(MIXED)
        stats = db.session.scalars(
            select(MaterialStats).where(MaterialStats.material_id == material.id)
        ).one()
        stats.avg_doc_len = 0.0
        db.session.commit()

        corpus = search.load_corpus([material.id])
        assert corpus.avg_len == 0.0 and corpus.doc_count == len(MIXED)
        assert _compare(material.id, MIXED_QUERIES) == len(MIXED_QUERIES)


def test_corpus_stats_come_from_the_stored_df(app):
    """语料统计从 `material_stats` 读，不重算（P4-D3 的 200ms 靠这条）。"""
    from app.models import MaterialStats
    from app.services.materials import search

    with app.app_context():
        material = _publish(RETRIEVAL)
        stats = db.session.scalars(
            select(MaterialStats).where(MaterialStats.material_id == material.id)
        ).one()
        corpus = search.load_corpus([material.id])

    assert corpus.doc_count == stats.doc_count == len(RETRIEVAL)
    assert corpus.df.get("索引") == 3  # 三块里都提到了「索引」
    assert corpus.df.get("bm25") == 1
    assert corpus.avg_len > 0
