"""五种格式 → 同一串「块」（F4-2 / P4-A1）。

解析这一层的全部价值，是让**下游不必知道文件是什么格式**。分块、索引、检索、
溯源都只认 `Block`（一段文字 + 它在原文件里的位置），于是「换一种格式」
永远只是这一个文件里多加一个函数的事。

三件事在这里定下来：

1. **位置信息尽力而为，不假装精确**。PDF 有真页码，PPTX 的「页」是幻灯片序号，
   DOCX 与纯文本**没有页**（python-docx 不给页数，给了也是打印机排版出来的，
   与作者看到的不是一回事）→ `page_no=None`。溯源徽标显示「第 12 页」时用不上就
   显示章节名，而不是编一个页码出来。
2. **标题靠启发式认**（P4-A2 要求章节路径正确率 ≥ 90%，而标题检测是它的前提）。
   每种格式的启发式都写在对应函数上，共同点是不猜「长得像标题」的文字：
   Markdown 认 `#`、DOCX 认样式名、PPTX 认标题占位符 —— 这三种是**作者明确说过**
   「这是标题」的地方；只有 PDF 与纯文本要靠字号与编号去推。
3. **认不出来就不认**：一份没有标题信息的纯文本，`section_path` 是空串。
   空的章节路径只是「没有这段信息」，编一个「正文」出来反而会让前端以为抓到了。

重活都交给第三方库（PyMuPDF / python-docx / python-pptx），但它们都是**惰性导入**：
jieba 首次分词要建词典、PyMuPDF 是 C 扩展，而「材料功能关着」的部署与绝大多数
不解析材料的测试不该为它们付启动成本（`MATERIAL_ENABLED=false` 时一行都不 import）。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.common.logging import get_logger

logger = get_logger("app.materials.parsers")

#: 一段正文。`page_no` 是**原文件里的页码**（1 起），没有页的格式是 None。
#: `level` 0 = 正文，1~6 = 标题层级（与 Markdown 的 `#` 数同义）。
@dataclass(frozen=True)
class Block:
    text: str
    page_no: int | None = None
    section_path: str = ""
    level: int = 0

    @property
    def is_heading(self) -> bool:
        return self.level > 0


@dataclass
class ParsedDoc:
    """一次解析的产物：块序列 + 页数 + 需要告诉用户的话。"""

    blocks: list[Block] = field(default_factory=list)
    pages: int = 0
    #: 解析过程中值得说一句的事（如「已按 GBK 解码」）。会写进材料详情，
    #: 不写进 `error` —— 它们不是失败。
    notes: list[str] = field(default_factory=list)

    @property
    def chars(self) -> int:
        return sum(len(block.text) for block in self.blocks)


class ParseError(Exception):
    """解析失败，`str(exc)` 是**给用户看的那一句话**（P4-B2）。

    刻意不带堆栈、不带库的内部信息：用户在材料列表里看到的是
    「这份 PDF 打不开（文件损坏或格式不符）」，而不是 `mupdf: cannot open document`。
    真正的原因进服务端日志（`store.parse_material` 里记）。
    """


# --- 共用：章节栈 ---


class _Sections:
    """标题层级栈 → `第 3 章 > 3.2 检索` 这样的路径。"""

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []

    def push(self, level: int, title: str) -> None:
        title = title.strip()
        if not title:
            return
        while self._stack and self._stack[-1][0] >= level:
            self._stack.pop()
        self._stack.append((level, title))

    def path(self) -> str:
        return " > ".join(title for _, title in self._stack)


#: 中文编号标题：第一章 / 第二节 / 第 3 讲 / 第2部分。`第` 与数字之间常有一个空格。
_CN_HEADING = re.compile(r"^第\s*[一二三四五六七八九十百零〇0-9]+\s*[章节讲部分课篇]")

#: 阿拉伯数字编号：`1.2.3 标题`、`3、标题`、`3. 标题`。
_NUM_HEADING = re.compile(r"^(\d+(?:\.\d+){0,3})\s*[、.．)）]?\s+\S")

#: 中文顿号编号：`一、标题`（层级比「第 X 章」浅一层）。
_CN_DOT_HEADING = re.compile(r"^[一二三四五六七八九十]+\s*[、.．]\s*\S")


def _looks_like_heading(line: str) -> int:
    """文字像不像标题；像就返回层级（0 = 不像）。**只看文字，不看字号。**

    PDF 与纯文本共用它。三条约束缺一不可 —— 编号开头、足够短、不以句读结尾 ——
    少任何一条都会把「1. 我们先把问题简化一下，再考虑……」这样的正文认成标题。
    """
    text = line.strip()
    if not text or len(text) > 40:
        return 0
    if text.endswith(("。", "，", "；", "：", ",", ";", "!", "?", "！", "？")):
        return 0
    if _CN_HEADING.match(text):
        return 1
    if _CN_DOT_HEADING.match(text):
        return 2
    match = _NUM_HEADING.match(text)
    if match:
        # `1 标题` 是章、`1.1` 是节、`1.1.1` 是小节；深度即层级，但压到 3 以内
        return min(3, match.group(1).count(".") + 1)
    return 0


# --- 纯文本与 Markdown ---


#: 试编码的顺序。UTF-8 在前是因为它最可能；GBK 在后是因为中文 Windows 上
#: 用户从 Word/WPS 里导出的 txt 多半就是它。两个都不行才用替换字符硬解 ——
#: 「有几个乱码字」比「整份材料解析失败」好。
_ENCODINGS = ("utf-8-sig", "gbk")


def _read_text(path: Path) -> tuple[str, str | None]:
    """读文件 → (文本, 实际用的编码)。最后一种编码解不出来就替换非法字节。"""
    raw = path.read_bytes()
    for encoding in _ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), None


def parse_text(path: Path, ext: str) -> ParsedDoc:
    """`.md` / `.txt`：Markdown 认 `#`，纯文本靠编号启发式。"""
    text, encoding = _read_text(path)
    doc = ParsedDoc(pages=0)
    if encoding is None:
        doc.notes.append("文件不是标准的 UTF-8 或 GBK 编码，部分字符可能显示为乱码")
    elif encoding != "utf-8-sig":
        doc.notes.append(f"已按 {encoding.upper()} 解码")

    sections = _Sections()
    # Markdown 的 `#` 是作者写死的结构，优先用；没有就退回纯文本的启发式
    heading_re = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$") if ext == ".md" else None
    paragraph: list[str] = []

    def flush() -> None:
        if not paragraph:
            return
        body = "\n".join(paragraph).strip()
        if body:
            doc.blocks.append(Block(text=body, section_path=sections.path()))
        paragraph.clear()

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            flush()
            continue
        level = 0
        title = line.strip()
        if heading_re is not None:
            match = heading_re.match(title)
            if match:
                level = len(match.group(1))
                title = match.group(2).strip()
        else:
            level = _looks_like_heading(title)
        if level:
            flush()
            sections.push(level, title)
            doc.blocks.append(Block(text=title, section_path=sections.path(), level=level))
            continue
        paragraph.append(title)
    flush()
    return doc


# --- PDF ---


def parse_pdf(path: Path) -> ParsedDoc:
    """`.pdf`：按页取文字，按字号认标题，顺手去掉页眉页脚（F4-2 / 风险表）。

    页眉页脚必须去：一份 50 页的讲义里，「机器学习导论」这行会在 50 页的页顶各出现
    一次，于是它会被切成 50 个内容相同的块，把倒排索引里那个词的 df 拉到 50 ——
    检索时它看起来比「过拟合」这种真术语还重要。
    """
    import pymupdf

    try:
        document = pymupdf.open(path)
    except Exception as exc:  # PyMuPDF 抛什么都归成「打不开」
        logger.warning("PDF 打开失败：%s", type(exc).__name__)
        raise ParseError("这份 PDF 打不开（文件损坏或格式不符）") from exc

    with document:
        if document.needs_pass:
            raise ParseError("这份 PDF 有密码保护，请先解除密码再上传")
        # 按页号取页，而不是 `for page in document`：后者在 PyMuPDF 的类型
        # 存根里不是一个可迭代对象（运行期可以，但没必要为省一个 range 破例）
        pages = [
            _pdf_lines(document.load_page(index)) for index in range(document.page_count)
        ]

    _strip_running_heads(pages)

    body_size = _body_size(pages)
    sections = _Sections()
    doc = ParsedDoc(pages=len(pages))
    paragraph: list[str] = []
    paragraph_page: int | None = None

    def flush() -> None:
        if not paragraph:
            return
        body = _join_wrapped(paragraph)
        if body:
            doc.blocks.append(
                Block(text=body, page_no=paragraph_page, section_path=sections.path())
            )
        paragraph.clear()

    for page_no, lines in enumerate(pages, start=1):
        for text, size in lines:
            level = _pdf_heading_level(text, size, body_size)
            if level:
                flush()
                sections.push(level, text)
                doc.blocks.append(
                    Block(text=text, page_no=page_no, section_path=sections.path(), level=level)
                )
                continue
            if paragraph_page != page_no:
                flush()
                paragraph_page = page_no
            paragraph.append(text)
        flush()
        paragraph_page = None
    flush()

    if doc.pages and doc.chars < 20 * doc.pages:
        raise ParseError("这份 PDF 没有文本层（像是扫描件），需要 OCR，当前版本暂不支持")
    return doc


def _pdf_lines(page) -> list[tuple[str, float]]:
    """一页 → [(行文字, 该行最大字号)]。空行丢掉，空白块跳过。"""
    lines: list[tuple[str, float]] = []
    raw = page.get_text("dict")
    for block in raw.get("blocks", []):
        if block.get("type") != 0:  # 1 = 图片，没有文字可取
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(str(span.get("text", "")) for span in spans).strip()
            if not text:
                continue
            size = max(float(span.get("size", 0.0)) for span in spans)
            lines.append((text, size))
    return lines


def _body_size(pages: list[list[tuple[str, float]]]) -> float:
    """正文字号 = **按字符数加权**的众数。

    不加权的话，一份标题多、正文少的 PDF 会把标题字号当成正文 —— 于是所有正文
    都变成「比正文小」，一个标题也认不出来。按字符数算，「哪种字号占的篇幅最多」
    才等于「正文是多大」。
    """
    weight: dict[float, int] = {}
    for lines in pages:
        for text, size in lines:
            # 四舍五入到 0.5pt：同一级标题在 PDF 里常有 12.0/12.01 这种抖动
            key = round(size * 2) / 2
            weight[key] = weight.get(key, 0) + len(text)
    if not weight:
        return 0.0
    return max(weight.items(), key=lambda item: item[1])[0]


def _pdf_heading_level(text: str, size: float, body_size: float) -> int:
    """字号明显大于正文 → 标题；字号认不出来时，退回「编号 + 短」的文字启发式。"""
    if body_size > 0 and size >= body_size * 1.15 and len(text) <= 60:
        ratio = size / body_size
        if ratio >= 1.6:
            return 1
        if ratio >= 1.35:
            return 2
        return 3
    return _looks_like_heading(text)


def _join_wrapped(lines: list[str]) -> str:
    """把 PDF 的硬换行接回段落。

    规则只看**上一行怎么结束**：以句读结尾就是段落结束（换行保留），否则接上
    下一行（换行去掉）。中文几乎没有靠行尾空格断词的情况，所以这条例外的
    成本很低；而把半句话留在两个块里，是检索命中率最直接的损失。
    """
    out = ""
    for line in lines:
        if not out:
            out = line
        elif out.endswith(_SENTENCE_END):
            out += "\n" + line
        else:
            out += line
    return out.strip()


_SENTENCE_END = ("。", "！", "？", "；", "…", ".", "!", "?", ";", "：", ":")


def _strip_running_heads(pages: list[list[tuple[str, float]]]) -> None:
    """去掉每页重复出现的页眉页脚（就地修改）。

    只在**每页的头两行和末两行**里找重复 —— 正文中间重复出现某句话是正常的
    （「如图 3-1 所示」），不该被当成页眉。少于 3 页不做，那时候「重复」
    与「碰巧一样」分不开。
    """
    if len(pages) < 3:
        return
    counts: Counter[str] = Counter()
    for lines in pages:
        edge = {text for text, _ in lines[:2]} | {text for text, _ in lines[-2:]}
        counts.update(edge)
    threshold = max(2, int(len(pages) * 0.6))
    repeated = {text for text, count in counts.items() if count >= threshold}
    if not repeated:
        return
    for lines in pages:
        keep = [item for item in lines if item[0] not in repeated]
        lines[:] = keep


# --- DOCX ---


def parse_docx(path: Path) -> ParsedDoc:
    """`.docx`：按**正文顺序**遍历段落与表格，认 Word 的标题样式（F4-2）。

    为什么要按正文顺序：`document.paragraphs` 会把表格全部漏掉或全部挪到最后，
    于是「表 3-1 的结果」与它周围那段说明就被拆散了 —— 分块时它们本该挨在一起。
    """
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = docx.Document(str(path))
    except Exception as exc:  # python-docx 抛什么都归成「打不开」
        logger.warning("DOCX 打开失败：%s", type(exc).__name__)
        raise ParseError("这份 Word 文档打不开（文件损坏或格式不符）") from exc

    sections = _Sections()
    doc = ParsedDoc(pages=0)
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue
            level = _docx_heading_level(paragraph.style.name if paragraph.style else "")
            if level:
                sections.push(level, text)
                doc.blocks.append(Block(text=text, section_path=sections.path(), level=level))
            else:
                doc.blocks.append(Block(text=text, section_path=sections.path()))
        elif child.tag == qn("w:tbl"):
            text = _table_text(Table(child, document))
            if text:
                doc.blocks.append(Block(text=text, section_path=sections.path()))
    return doc


#: Word 的标题样式名。中文版 Word 写「标题 1」，英文版写「Heading 1」，
#: 而「标题」样式（不带数字）是这个文档的题目 —— 也算一级。
_DOCX_HEADING = re.compile(r"^(?:Heading|标题)\s*(\d+)?$", re.IGNORECASE)


def _docx_heading_level(style_name: str) -> int:
    name = str(style_name or "").strip()
    if not name:
        return 0
    if name in ("Title", "标题"):
        return 1
    match = _DOCX_HEADING.match(name)
    if not match:
        return 0
    return min(6, int(match.group(1) or 1))


def _table_text(table) -> str:
    """表格 → 一段文字，**不拆**（风险表：表格行合并为单块）。

    单元格之间用 ` | `：保留列的分界，人还能读，模型也能看出这是表格。
    空行去掉，否则跨页表格会带进来一串空行。
    """
    rows = []
    for row in table.rows:
        cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
        # 合并单元格会让同一段文字在相邻列重复出现，去重后保留顺序
        deduped = list(dict.fromkeys(cell for cell in cells if cell))
        if deduped:
            rows.append(" | ".join(deduped))
    return "\n".join(rows)


# --- PPTX ---


def parse_pptx(path: Path) -> ParsedDoc:
    """`.pptx`：一页幻灯片 = 一个 `page_no`，标题占位符 = 章节（F4-2）。

    PPT 的「页」就是幻灯片序号（而不是打印页），这正是作者与听众都认可的那种页码。
    """
    from pptx import Presentation

    try:
        presentation = Presentation(str(path))
    except Exception as exc:  # python-pptx 抛什么都归成「打不开」
        logger.warning("PPTX 打开失败：%s", type(exc).__name__)
        raise ParseError("这份 PPT 打不开（文件损坏或格式不符）") from exc

    doc = ParsedDoc(pages=len(presentation.slides))
    for index, slide in enumerate(presentation.slides, start=1):
        title = ""
        if slide.shapes.title is not None:
            title = str(slide.shapes.title.text or "").strip()
        section = title or f"第 {index} 页"
        if title:
            doc.blocks.append(
                Block(text=title, page_no=index, section_path=section, level=1)
            )
        for shape in slide.shapes:
            if shape == slide.shapes.title:
                continue
            if getattr(shape, "has_table", False):
                text = _table_text(shape.table)
            elif getattr(shape, "has_text_frame", False):
                text = "\n".join(
                    paragraph.text.strip()
                    for paragraph in shape.text_frame.paragraphs
                    if paragraph.text.strip()
                )
            else:
                continue
            if text.strip():
                doc.blocks.append(Block(text=text.strip(), page_no=index, section_path=section))
    return doc


# --- 入口 ---


#: 扩展名 → 解析函数。**不带扩展名的那两种单独走**（`parse_text` 要用它区分
#: Markdown 与纯文本），这样每个解析函数的签名都是「给一个路径」这一件事。
_PARSERS = {
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".pptx": parse_pptx,
}

#: 纯文本家族。它们共用一条实现，靠扩展名决定认不认 `#`。
_TEXT_EXTS = (".md", ".txt")


def parse(path: Path, ext: str) -> ParsedDoc:
    """解析入口。`ext` 必须已经过 `policy.ensure_supported`。"""
    if ext in _TEXT_EXTS:
        return parse_text(path, ext)
    parser = _PARSERS.get(ext)
    if parser is None:  # pragma: no cover - 白名单拦在前面
        raise ParseError(f"暂不支持 {ext} 格式")
    return parser(path)


def supported() -> tuple[str, ...]:
    return (*_TEXT_EXTS, *_PARSERS)


__all__ = [
    "Block",
    "ParseError",
    "ParsedDoc",
    "parse",
    "parse_docx",
    "parse_pdf",
    "parse_pptx",
    "parse_text",
    "supported",
]
