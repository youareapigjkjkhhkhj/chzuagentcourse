"""分块测试（F4-3 / P4-A2）。

分块是纯函数，所以这里可以**只**谈分块：给一串块，看切出来的块对不对。
不建 app、不碰库、不解析文件 —— 分块的质量（P4-A2 要人工判定 ≥ 9/10 语义完整）
在这里被拆成能自动判的那几条：不跨标题、不在句子中间切、重叠是整句、
页码跟着内容走。
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from app.services.materials.chunking import split
from app.services.materials.parsers import Block

pytestmark = pytest.mark.unit

SENTENCE = "这是一句用来测试分块的中文句子。"


def _body(times: int = 3) -> str:
    return SENTENCE * times


def _numbered(count: int) -> str:
    """每句都不一样的一段话。

    重叠测试必须用它：句句相同的一段话是**周期性**的，「上一块的结尾」与
    「这一块的开头」随便截多长都能对上，于是「重叠从整句开始」这条断言
    在实现完全错位的情况下也会通过。
    """
    return "".join(f"第{index:03d}句话在这里。" for index in range(count))


def test_a_heading_starts_a_new_chunk():
    """标题是硬边界：一块里只有一个主题（`section_path` 准的前提）。"""
    blocks = [
        Block(text="第一章 检索", level=1, section_path="第一章 检索"),
        Block(text=_body(2), page_no=1),
        Block(text="1.1 倒排索引", level=2, section_path="第一章 检索 > 1.1 倒排索引"),
        Block(text=_body(2), page_no=2),
    ]
    chunks = split(blocks, target=600, overlap=60)

    assert [chunk.chunk_no for chunk in chunks] == [1, 2]
    assert chunks[0].section_path == "第一章 检索"
    assert chunks[1].section_path == "第一章 检索 > 1.1 倒排索引"
    # 标题跟着它下面的正文（检索时「1.1 倒排索引」这几个字拿得到分）
    assert chunks[0].text.startswith("第一章 检索")
    assert chunks[1].text.startswith("1.1 倒排索引")
    # 跨节不重叠：上一节的尾巴挂到这一节的开头，这一块的 section 就是错的
    assert SENTENCE not in chunks[1].text.split("\n")[0]


def test_chunks_never_cross_a_heading():
    """「第二章」不能出现在它前面的正文那一块里。"""
    blocks = [
        Block(text=_body(20)),
        Block(text="第二章 排序", level=1, section_path="第二章 排序"),
        Block(text=_body(20)),
    ]
    chunks = split(blocks, target=300, overlap=60)

    assert len(chunks) >= 3
    for chunk in chunks:
        if "第二章" in chunk.text and chunk.section_path != "第二章 排序":
            pytest.fail("标题落进了上一节的块里")


def test_every_chunk_stays_within_the_target():
    """每块都在目标长度内 —— 重叠算在内（`target` 是含重叠的长度）。"""
    chunks = split([Block(text=_body(40))], target=200, overlap=40)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.char_count <= 200, chunk.text


def _shared_suffix(previous: str, current: str) -> int:
    """相邻两块共享的那一段有多长（上一块的结尾 == 这一块的开头）。

    从长到短试：重叠段的**起点**会随着长度变化，「从短到长逐字符比」比的是
    错位的两个字符（上一块最后一个字 vs 这一块第一个字），永远算出 0。
    """
    for size in range(min(len(previous), len(current)), 0, -1):
        if previous[-size:] == current[:size]:
            return size
    return 0


def test_the_overlap_starts_at_a_sentence_boundary():
    """重叠从整句开始：否则下一块抬头就是半句话（P4-A2 的判据之一）。"""
    chunks = split([Block(text=_numbered(60))], target=200, overlap=60)

    assert len(chunks) >= 3
    for previous, current in pairwise(chunks):
        shared = _shared_suffix(previous.text, current.text)
        assert shared >= 8, "相邻两块之间没有重叠"
        # 重叠段的前一个字符是句读 —— 说明它是一整句的开头，不是半句话
        assert previous.text[-shared - 1] in "。！？；…"


def test_page_numbers_follow_the_content():
    """页码跟着内容走：跨页的一块两端页码都要留着（P4-A1）。"""
    blocks = [
        Block(text=_body(2), page_no=7),
        Block(text=_body(2), page_no=8),
    ]
    chunks = split(blocks, target=600, overlap=60)

    assert len(chunks) == 1
    assert (chunks[0].page_from, chunks[0].page_to) == (7, 8)


def test_a_chunk_without_pages_says_so():
    """没有页码的格式（纯文本/Word）不编页码：None 就是 None。"""
    chunks = split([Block(text=_body(2))], target=600)
    assert (chunks[0].page_from, chunks[0].page_to) == (None, None)


def test_a_sentence_longer_than_the_target_is_cut_hard():
    """一句话比目标还长（表格行、没有标点的清单）时硬切，而不是让它无限长。

    这是**例外**：正常长度的一段话永远切在句读上。硬切时不带重叠 —— 切口本来
    就没有语义，重叠一段同样没有语义的文字只会让两块看起来一样。
    """
    chunks = split([Block(text="无标点的长串" * 100)], target=100, overlap=20)

    assert len(chunks) >= 6
    for chunk in chunks:
        assert chunk.char_count <= 100


def test_splitting_is_deterministic():
    """同一份材料解析两次，块号与内容必须一模一样。

    不稳定的话，「重新解析」会让页面上已经记下的溯源指向别处 —— 而且是静默的。
    """
    blocks = [
        Block(text="第一章", level=1, section_path="第一章"),
        Block(text=_body(30)),
        Block(text="第二章", level=1, section_path="第二章"),
        Block(text=_body(30)),
    ]
    first = [(chunk.chunk_no, chunk.text) for chunk in split(blocks, target=200, overlap=40)]
    second = [(chunk.chunk_no, chunk.text) for chunk in split(blocks, target=200, overlap=40)]

    assert first == second
    assert [number for number, _ in first] == list(range(1, len(first) + 1))


def test_empty_and_blank_blocks_produce_nothing():
    """空白块不产生空块：一条空的 chunk 会在检索里变成一个永远命中的结果。"""
    assert split([]) == []
    assert split([Block(text="   "), Block(text="\n\n")]) == []


def test_the_tokens_field_is_left_to_the_indexer():
    """分块不碰分词：`tokens` 由索引器回填（换分词器时只动一处）。"""
    chunks = split([Block(text=_body(3))], target=600)
    assert chunks[0].tokens == 0
    assert chunks[0].char_count == len(_body(3))
