"""IR → PPTX（P5 §3 的 `renderPptx`，F5-2）。

产物是**可二次编辑的课件**，不是一页一张图：每页的标题、要点、代码都是真的
文本框与段落，老师在 PowerPoint / WPS 里改字、挪框、删条目都行（P5-A2）。
这也是当初选 python-pptx 而不是「把 HTML 截图塞进幻灯片」的唯一理由 ——
后者快得多，也好看得多，但它交出去的东西改不了一个字。

讲稿进**备注页**（`notes_slide`）：放映时看不到，备课时正好；导出时不进正文，
因为讲稿是「讲」的、要点是「看」的，混在一起两边都不好用。

中文字体：每条 run 都同时设 `latin` 与 `ea` 两个字型（`_set_font`）。只设 latin
的话，中文按主题字体渲染 —— 在一台没装那个主题字体的机器上就是一堆方框，
而 PPTX 与 PDF 不一样，它**不在我们机器上渲染**，是要拿到别人电脑上打开的。

**示意图**是唯一不走文本框的内容：`add_picture` 置入的是位图（PPTX 只收
png/jpeg），所以要先把 DSL 里那段 SVG 栅格化（`exports/svg.py`）。它不是
「一页一张截图」—— 其余每一个字仍然是可编辑的文本框，图也只是能替换、能挪动
的图片对象，这一页该改的字一个都没锁住。
"""

from __future__ import annotations

import io
from typing import Callable, Iterable

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Length, Pt

from app.services.exports import svg as svg_export
from app.services.exports.ir import Deck, Page, RenderOptions

__all__ = ["render"]

#: 品牌色（与 `frontend/src/styles/tokens.css` 同源）。
_BRAND = RGBColor.from_string("0052D9")
_INK = RGBColor.from_string("181818")
_MUTED = RGBColor.from_string("6B7280")
_WARN = RGBColor.from_string("92400E")
_LINE = RGBColor.from_string("E7E7E7")

#: 幻灯片尺寸：16:9（13.333in × 7.5in）。
_WIDTH = Inches(13.333)
_HEIGHT = Inches(7.5)

_FONT = "Microsoft YaHei"  # 中文机器上基本都有；没有时由 PowerPoint 兜底替换
_MONO = "Consolas"

_WATERMARK = "AI 生成 · EduAgentX"

#: 正文区：整幅的左右边界，以及「有图也有文字」时左边那一栏图的宽度。
#: 16:9 的幻灯片是横的，图占满 12.1in 宽会被正文区的高度顶住（只有 4.35in 高），
#: 最后缩得比要点还小；分两栏之后图能用上 7in 宽，图里的字在投影上也看得清。
_BODY_LEFT = Inches(0.62)
_BODY_WIDTH = Inches(12.1)
_IMAGE_COLUMN_WIDTH = Inches(7.0)
_RIGHT_COLUMN_LEFT = Inches(7.85)
_RIGHT_COLUMN_WIDTH = Inches(4.87)
#: 图注：图与它之间、它与下一条内容之间的缝，以及它自己占的高度。
_CAPTION_GAP = int(Inches(0.06))
_CAPTION_HEIGHT = int(Inches(0.32))
_FIGURE_GAP = int(Inches(0.16))


def render(
    deck: Deck,
    options: RenderOptions,
    *,
    generated_at: str = "",
    on_page: Callable[[int, int], None] | None = None,
) -> bytes:
    """整门课 → `.pptx` 字节。

    `on_page(已画完, 共几页)` 每画完一页调一次。导出任务靠它报**真进度**：
    「画完几页 / 共几页」是这一层唯一知道的事实，编一个「大概快好了」的数字
    比不报还糟（`models/export.py` 的 `progress` 一列同一条理由）。
    计算快，可以在渲染线程里直接调 —— 但**别在里面做慢 IO**，它会把渲染拖慢。
    """
    prs = Presentation()
    prs.slide_width = _WIDTH
    prs.slide_height = _HEIGHT

    pages = list(deck.pages)
    for index, page in enumerate(pages):
        slide = prs.slides.add_slide(prs.slide_layouts[6])  # 6 = 空白版式
        _paint(slide, deck, page, options, index=index, total=len(pages), generated_at=generated_at)
        if on_page is not None:
            on_page(index + 1, len(pages))

    buffer = io.BytesIO()
    prs.save(buffer)
    return buffer.getvalue()


def _paint(
    slide, deck: Deck, page: Page, options: RenderOptions, *, index: int, total: int, generated_at: str
) -> None:
    """一页 → 一张幻灯片。"""
    _text_box(
        slide,
        Inches(0.6),
        Inches(0.42),
        Inches(12.1),
        Inches(0.95),
        [_run_spec(page.title, size=30, bold=True, color=_BRAND)],
    )
    if page.subtitle:
        _text_box(
            slide,
            Inches(0.62),
            Inches(1.32),
            Inches(12.1),
            Inches(0.5),
            [_run_spec(page.subtitle, size=15, color=_MUTED)],
        )

    top = Inches(1.95)
    body_height = Inches(4.35)
    _body(slide, page, options, top=top, height=body_height)

    footer = f"{index + 1} / {total}"
    if page.sources:
        labels = "；".join(item.label for item in page.sources if item.label)
        footer = f"{footer}　出处：{labels}"
    _text_box(
        slide,
        Inches(0.62),
        Inches(6.92),
        Inches(9.6),
        Inches(0.4),
        [_run_spec(footer, size=10, color=_MUTED)],
    )
    if options.watermark:
        mark = _WATERMARK + (f" · {generated_at}" if generated_at else "")
        _text_box(
            slide,
            Inches(10.4),
            Inches(6.92),
            Inches(2.3),
            Inches(0.4),
            [_run_spec(mark, size=10, color=_LINE)],
            align=PP_ALIGN.RIGHT,
        )

    notes = _notes_text(page, options)
    if notes:
        slide.notes_slide.notes_text_frame.text = notes


def _notes_text(page: Page, options: RenderOptions) -> str:
    """备注页的内容：讲稿 + 板书 + 缺口。

    缺口（材料没写到的地方，P4-A8）也写进备注页：导出之后**页面上**看不到这个
    提示了，而讲课的人应当在讲这一页之前就知道「这块材料里没有」。
    """
    parts: list[str] = []
    if options.with_notes and page.notes:
        parts.append(f"【讲稿】{page.notes}")
    if page.board:
        descs = "；".join(item.desc for item in page.board if item.desc)
        if descs:
            parts.append(f"【板书】{descs}")
    if page.gaps:
        parts.append("【材料未涉及】" + "；".join(page.gaps))
    return "\n".join(parts)


def _body(  # noqa: PLR0912 —— 块型分派天然这么多分支，见 _blocks_html 的同款说明
    slide, page: Page, options: RenderOptions, *, top: Length, height: Length
) -> None:
    """正文区。按块型摆 —— 每一种块型在这里出现一次（与 HTML 渲染器一一对应）。

    示意图单独拎出来（`figures`）：别的块都是段落，攒进一个文本框；图得用
    `add_picture` 真画上去。图与文字**分左右两栏**，与 HTML 渲染器的先后顺序
    可以不同 —— PPT 一页是一次铺开的，概念页的图排在要点前面（DSL 里在后）
    不是丢内容，是为了别把一段话从中间切开。
    """
    specs: list[list[tuple]] = []
    figures: list[tuple[bytes, str]] = []  # (png 字节, 图注)
    for block in page.blocks:
        if block.kind == "heading":
            specs.append([_run_spec(block.text, size=20, bold=True, color=_INK)])
        elif block.kind == "paragraph":
            specs.append([_run_spec(_with_caption(block.caption, block.text), size=16)])
        elif block.kind == "bullets":
            for item in block.items:
                specs.append([_run_spec(item.text, size=16)])
        elif block.kind == "steps":
            for number, item in enumerate(block.items, start=1):
                specs.append([_run_spec(f"{number}. {item.text}", size=16)])
        elif block.kind == "code":
            code = block.code
            if code is not None:
                for line in (code.content or "").splitlines() or [""]:
                    specs.append([_run_spec(line, size=13, mono=True)])
            explain = [item.text for item in block.items if item.text]
            for line in explain:
                specs.append([_run_spec(f"· {line}", size=14, color=_MUTED)])
        elif block.kind == "image":
            png = svg_export.render_png(block.svg)
            if png:
                figures.append((png, block.text))
            else:
                # 老课程的这一页没有 svg（P1 只出描述），或这段 svg 没画出来：
                # 维持原样的灰色占位行，不假装有图。
                specs.append([_run_spec(f"［图示］{block.text}", size=15, color=_MUTED)])
        elif block.kind == "quote":
            specs.append([_run_spec(block.text, size=16, italic=True)])
            for item in block.items:
                specs.append([_run_spec(f"· {item.text}", size=15, color=_MUTED)])
        elif block.kind == "quiz" and block.quiz is not None and options.with_quiz:
            quiz = block.quiz
            specs.append([_run_spec(quiz.stem, size=18, bold=True)])
            for index, option in enumerate(quiz.options):
                mark = "√ " if option == quiz.answer else f"{_letter(index)}. "
                specs.append([_run_spec(f"{mark}{option}", size=16)])
            if quiz.answer:
                line = f"答案：{quiz.answer}"
                if quiz.explain:
                    line += f"　解析：{quiz.explain}"
                specs.append([_run_spec(line, size=14, color=_WARN)])

    if not specs and not figures:
        return
    if figures and specs:
        # 图和文字都有的页（figure / concept / example 都是这样）：左边图、右边字。
        _place_figures(
            slide, figures, left=_BODY_LEFT, width=_IMAGE_COLUMN_WIDTH, top=top, limit=height
        )
        _text_box(
            slide,
            _RIGHT_COLUMN_LEFT,
            top,
            _RIGHT_COLUMN_WIDTH,
            height,
            _flatten(specs),
            bullet_from=1,
        )
    elif figures:
        # 整页只有一张图：它可以把整幅正文区用起来。
        _place_figures(slide, figures, left=_BODY_LEFT, width=_BODY_WIDTH, top=top, limit=height)
    else:
        _text_box(slide, _BODY_LEFT, top, _BODY_WIDTH, height, _flatten(specs), bullet_from=1)


def _place_figures(
    slide,
    figures: list[tuple[bytes, str]],
    *,
    left: Length,
    width: Length,
    top: Length,
    limit: Length,
) -> Length:
    """把示意图依次放进 `left`/`width` 这一栏，返回最后一张图（含图注）下方的 y。

    尺寸按像素比例算（`_fit_image`），图与图注都在这一栏里**居中** ——
    图多是 16:9 的，被栏高顶住之后两边会留空，贴着左边比居中更显歪。
    """
    box = int(width)
    each = int(limit) // max(len(figures), 1)
    cursor = int(top)
    for png, caption in figures:
        # 图注也占高度，先把它从这一张图的份额里扣掉 —— 否则图会把图注挤出去。
        room = each - (_CAPTION_GAP + _CAPTION_HEIGHT + _FIGURE_GAP if caption else 0)
        height, fitted = _fit_image(png, box_width=box, max_height=room)
        if not height:
            continue
        slide.shapes.add_picture(
            io.BytesIO(png),
            int(left) + (box - fitted) // 2,
            cursor,
            width=fitted,
            height=height,
        )
        cursor += height
        if caption:
            cursor += _CAPTION_GAP
            _text_box(
                slide,
                left,
                Emu(cursor),
                width,
                Emu(_CAPTION_HEIGHT),
                [_run_spec(caption, size=12, color=_MUTED)],
                align=PP_ALIGN.CENTER,
            )
            cursor += _CAPTION_HEIGHT
        cursor += _FIGURE_GAP
    return Emu(cursor)


def _fit_image(png: bytes, *, box_width: int, max_height: int) -> tuple[int, int]:
    """等比缩放到 (box_width, max_height) 之内，返回 EMU 的 (高, 宽)。

    必须自己算尺寸：`add_picture` 不给 width/height 时按 72dpi 置入，一张
    1920px 宽的图会占掉 26 英寸 —— 整张幻灯片都装不下。认不出图片返回 (0, 0)。
    """
    px_w, px_h = svg_export.pixel_size(png)
    if px_w <= 0 or px_h <= 0:
        return 0, 0
    width = box_width
    height = round(width * px_h / px_w)
    if height > max_height:
        height = max_height
        width = round(max_height * px_w / px_h)
    return height, width


def _letter(index: int) -> str:
    return "ABCD"[index] if 0 <= index < 4 else str(index + 1)


def _with_caption(caption: str, text: str) -> str:
    return f"{caption}　{text}" if caption else text


def _flatten(groups: Iterable[Iterable[tuple]]) -> list[tuple]:
    out: list[tuple] = []
    for group in groups:
        out.extend(group)
    return out


def _run_spec(
    text: str, *, size: int, bold: bool = False, italic: bool = False, color=None, mono: bool = False
) -> tuple:
    return (text, size, bold, italic, color, mono)


def _text_box(  # noqa: PLR0917 —— 四个坐标跟 `add_textbox` 自己的签名同序，按位置读最顺
    slide,
    left: Length,
    top: Length,
    width: Length,
    height: Length,
    paragraphs: list[tuple],
    *,
    align=PP_ALIGN.LEFT,
    bullet_from: int | None = None,
):
    """一个文本框，`paragraphs` 里每个元组是一段。

    `bullet_from` 指定从第几段起加项目符号 —— 小标题与首段不该有圆点，
    而「这一段是不是要点」在上面的 `_body` 里已经分清了：那里决定的是**内容**，
    这里只管**样子**。
    """
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.word_wrap = True

    for index, (text, size, bold, italic, color, mono) in enumerate(paragraphs):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.alignment = align
        paragraph.space_after = Pt(6)
        run = paragraph.add_run()
        run.text = text
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.italic = italic
        run.font.color.rgb = color or _INK
        _set_font(run, _MONO if mono else _FONT)
        if bullet_from is not None and index >= bullet_from:
            _bullet(paragraph)
    return box


def _set_font(run, name: str) -> None:
    """同时设 latin 与 ea 两个字型。

    `run.font.name` 只写 `<a:latin>`，中文走的是 `<a:ea>`（东亚字型）那一支 ——
    不写它，中文就会按主题字体渲染，在没装那个主题字体的机器上变成方框。
    这是「PPTX 在别人电脑上打开」这类问题的常见来源，所以在这里一次性处理掉。
    """
    run.font.name = name
    rpr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        element = rpr.find(qn(tag))
        if element is None:
            element = etree.SubElement(rpr, qn(tag))
        element.set("typeface", name)


def _bullet(paragraph, char: str = "•") -> None:
    """给段落加真项目符号（`<a:buChar>`）。

    不用「在文字前面手打一个 •」：那样符号会跟着文字一起被选中、被删掉，
    换行也不会缩进 —— 交出去的课件要经得起别人编辑。
    """
    ppr = paragraph._p.get_or_add_pPr()
    for tag in ("a:buNone", "a:buChar", "a:buAutoNum", "a:buFont"):
        for element in ppr.findall(qn(tag)):
            ppr.remove(element)
    font = etree.SubElement(ppr, qn("a:buFont"))
    font.set("typeface", "Arial")
    mark = etree.SubElement(ppr, qn("a:buChar"))
    mark.set("char", char)
