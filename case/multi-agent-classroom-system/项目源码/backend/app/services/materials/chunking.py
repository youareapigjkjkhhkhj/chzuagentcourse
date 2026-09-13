"""块序列 → 检索与溯源的最小单位（F4-3 / P4-A2）。

分块是这一阶段最容易被做坏的一步：切得太碎，检索回来的都是半句话；切得太大，
一块里混着三四个主题，注入提示词时等于没筛。所以这里的三条规则都围绕
**「一块 = 一个完整的意思」**：

1. **标题是硬边界**。一段正文永远不会跨过它上面的那个标题 —— 于是「一块里
   有几个主题」这件事从结构上被消掉了，`section_path` 也就准了（P4-A2 要 ≥ 90%）。
2. **切在句读上，不切在字上**。整句放不下就换一块；只有「一句话本身就超过目标
   长度」时才硬切（表格行、没有标点的长清单）—— 那时候没有更好的选择，
   但它是例外而不是常规。
3. **重叠从整句开头起算**（`MATERIAL_CHUNK_OVERLAP`，默认 60 字）。这一段的用处
   只有一个：一句话正好横跨切口时，它在前一块的结尾和后一块的开头都能被检索到。
   所以重叠必须**从句子的开头**开始 —— 从字符中间截出来的 60 字，两头都是半句话，
   检索命中了也没法读。

块号从 1 开始且**由本模块自己发**（`chunk_no`），它是「这份材料里的第几块」，
与页码无关，也与解析顺序无关 —— 同一份材料解析两次得到的编号必须一样，
否则「重新解析」会让页面上已经记下的溯源指向别处。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.services.materials.parsers import Block

#: 句读。中文的四种 + 英文的三种 + 换行 —— 换行也算，因为解析器已经用它
#: 标出了段落与 PDF 的硬换行结束。
_SENTENCE_END = "。！？；…!?;\n"

#: 重叠短于这么多字就不值得留：抬头就是半句话，还会让两块看起来几乎一样。
_MIN_OVERLAP = 8


@dataclass
class Chunk:
    """一块。`tokens` 留 0，由索引器回填 —— 分块不该知道 jieba 的存在
    （换分词器时只动 `indexer` 一处，块号与切分结果都不受影响）。"""

    chunk_no: int
    text: str
    section_path: str = ""
    page_from: int | None = None
    page_to: int | None = None
    tokens: int = 0

    @property
    def char_count(self) -> int:
        return len(self.text)


def split(
    blocks: Sequence[Block],
    *,
    target: int = 600,
    overlap: int = 60,
) -> list[Chunk]:
    """块序列 → 分块序列。`target` 是目标长度（不是硬上限，见下）。"""
    target = max(50, int(target or 600))
    overlap = max(0, min(int(overlap or 0), target // 2))
    chunks: list[Chunk] = []
    buffer: list[Block] = []
    #: 上一块结尾的重叠文字。只在**同一节内部**传递：跨过标题的重叠会把上一节的
    #: 尾巴挂到这一节的开头，那块内容的 section_path 就是错的。
    carry = ""

    def pending() -> int:
        return len(carry) + sum(len(item.text) for item in buffer)

    def flush(*, keep_overlap: bool) -> None:
        nonlocal buffer, carry
        if not buffer:
            carry = ""
            return
        body = "\n".join(item.text for item in buffer)
        # 重叠直接接在正文前面、不加分隔符：它就是「上一块的结尾」，加一个换行
        # 会让人以为这里原本就断了行，而检索与高亮都只关心文字本身
        text = f"{carry}{body}"
        pages = [item.page_no for item in buffer if item.page_no is not None]
        chunks.append(
            Chunk(
                chunk_no=len(chunks) + 1,
                text=text,
                section_path=buffer[0].section_path,
                page_from=min(pages) if pages else None,
                page_to=max(pages) if pages else None,
            )
        )
        carry = _tail(body, overlap) if keep_overlap else ""
        buffer = []

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        if block.is_heading:
            # 先落上一块，再从标题开新的一块：标题跟着它下面的正文走，
            # 这样「3.2 检索的步骤」这几个字在检索里是拿得到分的
            flush(keep_overlap=False)
            buffer.append(block)
            continue
        if len(text) > target:
            flush(keep_overlap=False)
            pieces = _split_long(text, target=target, overlap=overlap)
            for piece in pieces[:-1]:
                buffer.append(_copy(block, piece))
                flush(keep_overlap=False)
            # 最后一片留在缓冲区：后面的短段落能接着它，不至于又多出一个尾巴块
            buffer.append(_copy(block, pieces[-1]))
            continue
        if buffer and pending() + len(text) > target:
            flush(keep_overlap=True)
        buffer.append(block)

    flush(keep_overlap=False)
    return chunks


def _copy(block: Block, text: str) -> Block:
    return Block(text=text, page_no=block.page_no, section_path=block.section_path)


def _split_long(text: str, *, target: int, overlap: int) -> list[str]:
    """一段超长文字 → 若干片，每片尽量不超过 `target`。"""
    pieces: list[str] = []
    current = ""
    for sentence in _sentences(text):
        if len(sentence) > target:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_hard_cut(sentence, target))
            continue
        if current and len(current) + len(sentence) > target:
            pieces.append(current)
            current = _tail(current, overlap) + sentence
        else:
            current += sentence
    if current:
        pieces.append(current)
    return pieces or [text]


def _sentences(text: str) -> list[str]:
    """按句读切开，标点留在句尾。结果里没有空串。"""
    out: list[str] = []
    current = ""
    for char in text:
        current += char
        if char in _SENTENCE_END:
            if current.strip():
                out.append(current.strip())
            current = ""
    if current.strip():
        out.append(current.strip())
    return out


def _hard_cut(sentence: str, target: int) -> list[str]:
    """硬切。只在「一句话比目标长度还长」时发生 —— 表格行、无标点的长清单。

    这里不做重叠：硬切的切口本来就没有语义，重叠一段同样没有语义的文字，
    只会让两块看起来一样。
    """
    return [sentence[index : index + target] for index in range(0, len(sentence), target)]


def _tail(text: str, overlap: int) -> str:
    """取结尾一段**从整句开始**的文字，作为下一块的开头。"""
    if overlap < _MIN_OVERLAP or len(text) <= overlap:
        return ""
    window = text[-overlap:]
    for index, char in enumerate(window):
        if char in _SENTENCE_END:
            tail = window[index + 1 :].strip()
            # 只切出一个标点（或只剩换行）时不要 —— 那不是一段话
            return tail if len(tail) >= _MIN_OVERLAP else ""
    # 这 60 字里一个句读都没有（长清单/表格）：退回按字符截，
    # 但至少保证不是「一个字的重叠」
    return window.strip()


__all__ = ["Chunk", "split"]
