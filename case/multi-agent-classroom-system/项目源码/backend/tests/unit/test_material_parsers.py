"""解析测试（F4-2 / P4-A1 / P4-A2 的前半段）。

四种格式各写各的，所以这里**就地造真文件**（PyMuPDF / python-docx / python-pptx
都能写，也能读），而不是塞几个二进制桩：桩只能证明「我们的代码调了库」，
真文件才能证明「库吐出来的东西我们接住了」。

三种格式的标题判据不一样，各测各的：

| | 标题从哪来 | 页码 |
|---|---|---|
| Markdown | `#`（作者写死的） | 无 |
| 纯文本 | 编号 + 短 + 不以句读结尾（推的） | 无 |
| PDF | 字号 ≥ 1.15×正文（推的） | **真页码** |
| DOCX | 样式名（作者写死的） | 无（不编） |
| PPTX | 标题占位符（作者写死的） | 幻灯片序号 |

PDF 那两件重活单独测：**页眉页脚剔除**（不去掉的话，50 页讲义会把页眉切成 50 个
相同块，把它的 df 拉到 50）与**扫描件报错**（没有文本层的 PDF 必须明说需要 OCR，
而不是解析出一份空材料）。
"""

from __future__ import annotations

import pytest

from app.services.materials import parsers
from app.services.materials.parsers import ParseError

pytestmark = pytest.mark.unit

#: 页面上的坐标。字号不同才认得出标题，所以三个字号固定写死。
BODY_SIZE = 10.0
H1_SIZE = 20.0  # 2.0 倍 → 一级
H2_SIZE = 14.0  # 1.4 倍 → 二级

SENTENCE = "检索的第一步是把问题变成词，然后在索引里找得到东西。"


# --- 造文件（都是真文件，不是桩）---


def _pdf(path, pages: list[list[tuple[str, float]]], *, password: str = ""):
    """写一份 PDF：`pages` 是每页的 [(行文字, 字号)]。"""
    import pymupdf

    document = pymupdf.open()
    for lines in pages:
        page = document.new_page()
        top = 72.0
        for text, size in lines:
            page.insert_text((72, top), text, fontsize=size, fontname="china-s")
            top += size * 1.6
    if password:
        document.save(
            str(path),
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw=password,
            user_pw=password,
        )
    else:
        document.save(str(path))
    document.close()
    return path


# --- 入口 ---


def test_the_parser_list_matches_the_upload_whitelist():
    """解析器认识的扩展名与白名单必须**一模一样**（P4-A1）。

    两边分开写是刻意的（一个是「收不收」，一个是「拆不拆得开」），
    但一旦对不上，用户就会遇到「收下了却解析不了」这种最没道理的状态。
    """
    from app.models import MATERIAL_EXTS

    assert set(parsers.supported()) == set(MATERIAL_EXTS)


def test_parse_dispatches_by_extension(tmp_path):
    """`parse()` 按扩展名分派；`.md` 与 `.txt` 走同一条实现（认不认 `#` 的区别）。"""
    markdown = tmp_path / "a.md"
    markdown.write_text("# 第一章 检索\n\n正文。\n", encoding="utf-8")
    plain = tmp_path / "a.txt"
    plain.write_text("# 第一章 检索\n\n正文。\n", encoding="utf-8")

    md_doc = parsers.parse(markdown, ".md")
    txt_doc = parsers.parse(plain, ".txt")

    assert md_doc.blocks[0].is_heading  # `#` 是 Markdown 的标题
    assert not txt_doc.blocks[0].is_heading  # `.txt` 里的 `#` 只是一个井号


def test_an_unknown_extension_is_a_parse_error(tmp_path):
    """白名单之外的格式走到这里要报错，而不是抛 NotImplementedError 之类的库异常。"""
    path = tmp_path / "a.doc"
    path.write_bytes(b"whatever")
    with pytest.raises(ParseError):
        parsers.parse(path, ".doc")


# --- 纯文本与 Markdown ---


def test_a_gbk_file_says_which_encoding_it_used(tmp_path):
    """中文 Windows 上导出的 txt 多半是 GBK。解得开就解，但要说一句。"""
    path = tmp_path / "讲义.txt"
    path.write_bytes("第一章 检索\n\n第一步是把问题变成词。".encode("gbk"))

    doc = parsers.parse(path, ".txt")

    assert any("GBK" in note for note in doc.notes)
    assert doc.chars > 0


def test_a_numbered_plain_text_line_is_a_heading(tmp_path):
    """纯文本靠编号推标题：`第一章` 是章、`1.2` 是节。"""
    path = tmp_path / "讲义.txt"
    path.write_text(
        "第一章 检索\n\n正文一段。\n\n1.2 倒排索引\n\n正文另一段。\n", encoding="utf-8"
    )

    doc = parsers.parse(path, ".txt")

    assert doc.blocks[0].text == "第一章 检索" and doc.blocks[0].level == 1
    assert doc.blocks[-1].section_path == "第一章 检索 > 1.2 倒排索引"


def test_a_long_numbered_sentence_is_not_a_heading(tmp_path):
    """「1. 我们先把问题简化一下，再考虑……」是正文 —— 三条约束缺一不可。"""
    path = tmp_path / "讲义.txt"
    path.write_text("1. 我们先把问题简化一下，再考虑后面那些更麻烦的情况。\n", encoding="utf-8")

    doc = parsers.parse(path, ".txt")

    assert not doc.blocks[0].is_heading
    assert doc.blocks[0].section_path == ""


def test_plain_text_has_no_page_numbers(tmp_path):
    """没有页的格式不编页码（`page_no=None`，而不是「第 1 页」）。"""
    path = tmp_path / "讲义.txt"
    path.write_text("正文一段。\n", encoding="utf-8")

    doc = parsers.parse(path, ".txt")
    assert doc.pages == 0
    assert all(block.page_no is None for block in doc.blocks)


# --- PDF ---


def test_pdf_blocks_carry_the_real_page_number(tmp_path):
    """PDF 有真页码：溯源徽标上那个「第 12 页」就是它（P4-A6）。"""
    path = _pdf(
        tmp_path / "讲义.pdf",
        [
            [("第一章 检索", H1_SIZE), (SENTENCE, BODY_SIZE)],
            [("第二章 排序", H1_SIZE), ("排序决定谁排在最前面。", BODY_SIZE)],
        ],
    )

    doc = parsers.parse(path, ".pdf")

    assert doc.pages == 2
    by_text = {block.text: block.page_no for block in doc.blocks}
    assert by_text["第一章 检索"] == 1
    assert by_text["排序决定谁排在最前面。"] == 2


def test_a_bigger_font_line_becomes_a_heading(tmp_path):
    """字号明显大于正文就是标题；倍率决定层级（2.0 → 一级，1.4 → 二级）。"""
    path = _pdf(
        tmp_path / "讲义.pdf",
        [[("第一章 检索", H1_SIZE), ("1.1 倒排索引", H2_SIZE), (SENTENCE, BODY_SIZE)]],
    )

    doc = parsers.parse(path, ".pdf")
    levels = {block.text: block.level for block in doc.blocks}

    assert levels["第一章 检索"] == 1
    assert levels["1.1 倒排索引"] == 2
    assert levels[SENTENCE] == 0
    assert doc.blocks[-1].section_path == "第一章 检索 > 1.1 倒排索引"


def test_the_body_size_is_weighed_by_characters(tmp_path):
    """正文的字号要按**字符数**认：标题多、正文少的那一页不能把标题字号当正文。

    不加权的话（按行数取众数）这里会认成 20pt，于是正文全部变成「比正文小」，
    一个标题也认不出来。
    """
    path = _pdf(
        tmp_path / "讲义.pdf",
        [
            [
                ("第一章 检索", H1_SIZE),
                ("第二章 排序", H1_SIZE),
                ("第三章 索引", H1_SIZE),
                (SENTENCE, BODY_SIZE),
                ("再补一句同样长的正文，让正文的字数超过上面三行标题。", BODY_SIZE),
            ]
        ],
    )

    doc = parsers.parse(path, ".pdf")

    assert [block.level for block in doc.blocks[:3]] == [1, 1, 1]
    assert doc.blocks[-1].level == 0


def test_wrapped_lines_are_joined_into_one_paragraph(tmp_path):
    """PDF 的硬换行不是段落结束：上一行没以句读收尾就接上下一行。

    半句话留在两个块里，是检索命中率最直接的损失。
    """
    path = _pdf(
        tmp_path / "讲义.pdf",
        [[("检索的第一步是把问题变成词，", BODY_SIZE), ("然后在索引里找得到东西。", BODY_SIZE)]],
    )

    doc = parsers.parse(path, ".pdf")

    assert len(doc.blocks) == 1
    assert doc.blocks[0].text == "检索的第一步是把问题变成词，然后在索引里找得到东西。"


def test_a_new_sentence_starts_a_new_line_inside_the_block(tmp_path):
    """上一行以句号收尾 = 段落结束：换行留着（两句话不该粘成一句）。"""
    first = "第一句到此结束。后面再接一句，把这一页的字数撑过二十个字。"
    path = _pdf(tmp_path / "讲义.pdf", [[(first, BODY_SIZE), ("第二句另起一行。", BODY_SIZE)]])

    doc = parsers.parse(path, ".pdf")
    assert doc.blocks[0].text == f"{first}\n第二句另起一行。"


def test_running_headers_and_footers_are_dropped(tmp_path):
    """页眉在每页顶上重复出现 —— 不剔除的话，它会被切成一堆相同的块，
    把倒排索引里的 df 拉到页数那么大（F4-2 的风险表）。"""
    pages = [
        [("机器学习导论", BODY_SIZE), (f"第 {no} 页的正文，写够二十个字才不会被当成扫描件。", BODY_SIZE), ("第 1 章", BODY_SIZE)]
        for no in range(1, 4)
    ]
    path = _pdf(tmp_path / "讲义.pdf", pages)

    doc = parsers.parse(path, ".pdf")
    text = "\n".join(block.text for block in doc.blocks)

    assert "机器学习导论" not in text
    assert "第 1 章" not in text
    assert doc.pages == 3


def test_a_scanned_pdf_is_reported_as_needing_ocr(tmp_path):
    """没有文本层的 PDF 要明说「需要 OCR」，而不是解析出一份空材料。"""
    path = _pdf(
        tmp_path / "扫描件.pdf",
        [[("图", BODY_SIZE)], [("图", BODY_SIZE)]],
    )

    with pytest.raises(ParseError) as info:
        parsers.parse(path, ".pdf")
    assert "OCR" in str(info.value)


def test_a_password_protected_pdf_says_so(tmp_path):
    """有密码的 PDF 要说「先解除密码」，而不是「文件损坏」。"""
    path = _pdf(tmp_path / "加密.pdf", [[(SENTENCE, BODY_SIZE)]], password="secret")

    with pytest.raises(ParseError) as info:
        parsers.parse(path, ".pdf")
    assert "密码" in str(info.value)


def test_a_broken_pdf_fails_with_a_readable_message(tmp_path):
    """打不开的文件给一句人话，堆栈只进服务端日志（P4-B2）。"""
    path = tmp_path / "坏的.pdf"
    path.write_bytes(b"%PDF-1.7\nthis is not really a pdf")

    with pytest.raises(ParseError) as info:
        parsers.parse(path, ".pdf")
    assert "打不开" in str(info.value)


# --- DOCX ---


def test_docx_headings_come_from_the_style_name(tmp_path):
    """Word 的标题是**作者写死的样式**，不用猜字号。"""
    import docx

    path = tmp_path / "讲义.docx"
    document = docx.Document()
    document.add_heading("第一章 检索", level=1)
    document.add_paragraph(SENTENCE)
    document.add_heading("1.1 倒排索引", level=2)
    document.add_paragraph("每一个词都指向含有它的那些文档。")
    document.save(str(path))

    doc = parsers.parse(path, ".docx")

    assert doc.blocks[0].level == 1
    assert doc.blocks[2].level == 2
    assert doc.blocks[-1].section_path == "第一章 检索 > 1.1 倒排索引"
    assert all(block.page_no is None for block in doc.blocks)  # python-docx 不给真页码


def test_docx_recognizes_the_chinese_style_name(tmp_path):
    """中文版 Word 写的样式名是「标题 1」而不是「Heading 1」。"""
    import docx
    from docx.enum.style import WD_STYLE_TYPE

    path = tmp_path / "讲义.docx"
    document = docx.Document()
    document.styles.add_style("标题 1", WD_STYLE_TYPE.PARAGRAPH)
    paragraph = document.add_paragraph("第二章 排序")
    paragraph.style = document.styles["标题 1"]
    document.add_paragraph(SENTENCE)
    document.save(str(path))

    doc = parsers.parse(path, ".docx")

    assert doc.blocks[0].is_heading
    assert doc.blocks[0].text == "第二章 排序"


def test_a_docx_table_stays_in_one_block_and_in_reading_order(tmp_path):
    """表格合为一块（风险表）：拆成一行一块的话，表头与数据会散开。"""
    import docx

    path = tmp_path / "讲义.docx"
    document = docx.Document()
    document.add_paragraph("下表列出三种方法的差别。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "方法"
    table.cell(0, 1).text = "特点"
    table.cell(1, 0).text = "倒排索引"
    table.cell(1, 1).text = "快"
    document.add_paragraph("结束语一段。")
    document.save(str(path))

    doc = parsers.parse(path, ".docx")
    texts = [block.text for block in doc.blocks]

    assert texts[0] == "下表列出三种方法的差别。"
    assert texts[1] == "方法 | 特点\n倒排索引 | 快"  # 表格在它原来的位置上
    assert texts[2] == "结束语一段。"


def test_a_broken_docx_fails_with_a_readable_message(tmp_path):
    path = tmp_path / "坏的.docx"
    path.write_bytes(b"not a zip at all")

    with pytest.raises(ParseError) as info:
        parsers.parse(path, ".docx")
    assert "打不开" in str(info.value)


# --- PPTX ---


def test_each_slide_is_a_page_and_its_title_is_a_heading(tmp_path):
    """PPT 的「页」= 幻灯片序号（作者与听众都认的那种页码）。"""
    from pptx import Presentation

    path = tmp_path / "讲义.pptx"
    presentation = Presentation()
    for title, body in (
        ("第一章 检索", SENTENCE),
        ("第二章 排序", "排序决定谁排在最前面。"),
    ):
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text_frame.text = body
    presentation.save(str(path))

    doc = parsers.parse(path, ".pptx")

    assert doc.pages == 2
    titles = [block for block in doc.blocks if block.is_heading]
    assert [block.text for block in titles] == ["第一章 检索", "第二章 排序"]
    assert [block.page_no for block in titles] == [1, 2]
    body = [block for block in doc.blocks if not block.is_heading]
    assert body[0].section_path == "第一章 检索"
    assert body[1].page_no == 2


def test_a_slide_without_a_title_still_gets_a_section(tmp_path):
    """没有标题占位符的幻灯片用「第 N 页」当章节名 —— 不能是空串，
    否则那块内容在目录树里无处安放。"""
    from pptx import Presentation

    path = tmp_path / "讲义.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])  # 空白版式
    box = slide.shapes.add_textbox(0, 0, 4000000, 1000000)
    box.text_frame.text = SENTENCE
    presentation.save(str(path))

    doc = parsers.parse(path, ".pptx")

    assert doc.pages == 1
    assert doc.blocks[0].section_path == "第 1 页"


def test_a_pptx_table_becomes_one_block(tmp_path):
    """PPT 里的表格与 Word 里的一样处理（同一份 `_table_text`）。"""
    from pptx import Presentation

    path = tmp_path / "讲义.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "方法对比"
    table = slide.shapes.add_table(2, 2, 0, 1000000, 4000000, 1000000).table
    table.cell(0, 0).text = "方法"
    table.cell(0, 1).text = "特点"
    table.cell(1, 0).text = "倒排索引"
    table.cell(1, 1).text = "快"
    presentation.save(str(path))

    doc = parsers.parse(path, ".pptx")

    assert "方法 | 特点\n倒排索引 | 快" in [block.text for block in doc.blocks]


def test_a_broken_pptx_fails_with_a_readable_message(tmp_path):
    path = tmp_path / "坏的.pptx"
    path.write_bytes(b"not a zip at all")

    with pytest.raises(ParseError) as info:
        parsers.parse(path, ".pptx")
    assert "打不开" in str(info.value)
