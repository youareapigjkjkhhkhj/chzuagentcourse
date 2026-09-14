"""IR → PDF 讲义（P5 §3 的 `renderPdf`，F5-4）。

用 **PyMuPDF 的 `Story`**（HTML → 排版 → PDF），不是无头浏览器：仓库里本来就有
PyMuPDF（P4 的解析器用它读 PDF），而 Playwright 要背一个 Chromium（P5 §8 的风险
表里写着「镜像大」）。少一个几百 MB 的运行时，换来的代价是排版器只认 CSS 的
一个子集 —— 所以 PDF 那份 HTML 是**另写的一份**（`html.print_pages`），
只留最简的流式结构。内容同源、排版各表，理由写在 `html.py` 的头注释里。

### 一页课程 = 一个 Story

`Story` 不认 `break-after: page`（实测：三页 HTML 排出来是一页）。想让每页课程
从新的一页开始，只能在**调用侧**控制：一页课程新建一个 Story，放进一张新纸。
这比「一份大 HTML 配分页 CSS」笨，但它是**确定的** —— 不依赖排版器对某个 CSS
属性的支持程度。

内容长到一页纸放不下时**接着排下一张纸**，不截断：PDF 是拿去打印的讲义，
少一段要点比多一页纸糟糕得多。所以一张课程页可能对应两张 PDF 纸。

### 页码与落款是**盖**上去的，不是排出来的

正文里不写页码。`DocumentWriter` 排完得到字节后，重新打开这份 PDF，用
`insert_text(fontname="china-s")` 在每张纸上盖页脚（课程名 + `第 i / N 页`）
与水印。两个好处：页码是**真的纸页码**（不受排版影响），中文走 PyMuPDF 自带的
简体字库（`china-s`），不依赖系统装了什么字体。

### 体积

PyMuPDF 排版时会嵌一份完整的 CJK 兜底字库（约 3.5MB），所以最后一步调
`doc.subset_fonts()` 只留用到的那些字 —— 12 页的讲义因此从 3.5MB 落到几百 KB。
"""

from __future__ import annotations

import contextlib
import io
from typing import Callable

import pymupdf

from app.services.exports import html as html_renderer
from app.services.exports import theme as themes
from app.services.exports.ir import Deck, RenderOptions

__all__ = ["A4", "render"]

#: 纸型与页边距。A4 竖版 —— 讲义是打印出来看的，不是投影。
A4 = "a4"
_MARGIN_X = 46.0
_MARGIN_TOP = 50.0
_MARGIN_BOTTOM = 52.0  # 比上边距大一点：页脚要盖在空白里

#: 页脚与水印的字号 / 颜色。
_FOOT_SIZE = 8.5
_FOOT_GRAY = (0.42, 0.45, 0.50)
_WM_GRAY = (0.72, 0.74, 0.78)

#: PyMuPDF 自带的简体中文字库。用它盖页脚，**不读系统字体** ——
#: 镜像里没装中文字体时，系统字体这条路会安静地退化成方框。
_CJK_FONT = "china-s"


def _pdf_css(theme: themes.Theme) -> str:
    """按主题生成排版样式。颜色与 PPTX / HTML 同源（都从 `theme` 取）；
    字体保持 `sans-serif` / `monospace` —— MuPDF 的排版器用自带的字库，
    指定具体字体名未必能解析，而中文无论如何都走它内嵌的 CJK 字库
    （`_stamp` 那一步同理），所以 PDF 这一份的主题差异体现在**配色**上，字体不强求。
    """
    brand = theme.css(theme.brand)
    ink = theme.css(theme.ink)
    muted = theme.css(theme.muted)
    warn = theme.css(theme.warn)
    # 版式微调：三档 layout 给标题一道不同的装饰（瑞士下划线、科技左竖条）。
    # MuPDF 的排版器只认 CSS 的一个子集，border 是它排得出来的那一样。
    layout = theme.layout if theme.layout in ("swiss", "tech") else "classic"
    if layout == "swiss":
        decor = f"h1 {{ border-bottom: 2pt solid {brand}; padding-bottom: 4pt; }}"
    elif layout == "tech":
        decor = f"h1 {{ border-left: 3pt solid {brand}; padding-left: 8pt; }}"
    else:
        decor = ""
    return f"""
body {{ font-family: sans-serif; font-size: 10.5pt; line-height: 1.65; color: {ink}; }}
h1 {{ font-size: 17pt; color: {brand}; margin: 0 0 8pt 0; }}
h2 {{ font-size: 12.5pt; margin: 10pt 0 4pt 0; }}
p {{ margin: 4pt 0; }}
ul, ol {{ margin: 4pt 0 4pt 16pt; }}
li {{ margin: 2pt 0; }}
strong {{ color: {brand}; }}
pre {{ font-family: monospace; font-size: 8.5pt; background-color: #f3f4f6; padding: 6pt; }}
blockquote {{ margin: 6pt 0; padding: 2pt 8pt; border-left: 2pt solid {brand}; color: #374151; }}
figure {{ margin: 6pt 0; }}
/* 示意图是栅格化后的位图（`html._image_html` 的 rasterize 那条路）。
   不给它限宽的话，一张 1920px 宽的图会顶出版心。 */
img {{ max-width: 100%; }}
figcaption {{ color: {muted}; font-size: 8.5pt; }}
.cap {{ color: {muted}; font-size: 8.5pt; }}
.notes {{ color: #4b5563; font-size: 9pt; }}
.gap {{ color: {warn}; }}
.quiz__answer {{ color: {warn}; }}
.note {{ color: {warn}; }}
{decor}
"""


def render(
    deck: Deck,
    options: RenderOptions,
    *,
    generated_at: str = "",
    on_page: Callable[[int, int], None] | None = None,
) -> bytes:
    """整门课 → `.pdf` 字节。

    `on_page(已排完, 共几页)` 按**课程页**报进度，不是纸页 —— 一页课程排成两张纸
    时仍然只算走完一页，因为「还剩几页要排」问的是课程还剩几页。
    """
    fragments = html_renderer.print_pages(deck, options)
    css = _pdf_css(themes.get(options.template))
    buffer = io.BytesIO()
    body = pymupdf.DocumentWriter(buffer)
    mediabox = pymupdf.paper_rect(A4)
    # 这不是元组拼接：`Rect.__add__` 收一个四元组是**逐个坐标加减**——
    # 正的两个把左上推进来、负的两个把右下推进来，得到的就是版心。
    # ruff 只看得见一个 `+`。
    where = mediabox + (_MARGIN_X, _MARGIN_TOP, -_MARGIN_X, -_MARGIN_BOTTOM)  # noqa: RUF005

    for index, fragment in enumerate(fragments):
        story = pymupdf.Story(html=f"<html><body>{fragment}</body></html>", user_css=css)
        more = 1
        while more:
            device = body.begin_page(mediabox)
            more, _filled = story.place(where)
            story.draw(device)
            body.end_page()
        if on_page is not None:
            on_page(index + 1, len(fragments))
    body.close()

    document = pymupdf.open("pdf", buffer.getvalue())
    _stamp(document, deck, options, generated_at=generated_at)
    # 只嵌用到的那些字（见模块 docstring 的「体积」）。
    # 子集化失败只影响体积，不该让一次导出失败 —— 所以吃掉异常，
    # 而且**不记日志**：它要么不出问题，要么每次都出（同一份 PDF 的字体是同一批）。
    with contextlib.suppress(Exception):  # pragma: no cover
        document.subset_fonts()
    return document.tobytes(garbage=3, deflate=True)


def _stamp(document, deck: Deck, options: RenderOptions, *, generated_at: str) -> None:
    """盖页脚与页码。

    页码是**纸页码**（`第 i / N 页`），不是课程页号 —— 讲义打印出来时，
    老师要找的是「第几张纸」。课程页号在读的时候由标题与页眉认出来。
    """
    total = document.page_count
    for index, page in enumerate(document, start=1):
        rect = page.rect
        left = pymupdf.Point(_MARGIN_X, rect.height - _MARGIN_BOTTOM + 22)
        page.insert_text(left, _clip(deck.title, 40), fontname=_CJK_FONT, fontsize=_FOOT_SIZE,
                         color=_FOOT_GRAY)

        label = f"第 {index} / {total} 页"
        right = pymupdf.Point(
            rect.width - _MARGIN_X - _width(label, _FOOT_SIZE),
            rect.height - _MARGIN_BOTTOM + 22,
        )
        page.insert_text(right, label, fontname=_CJK_FONT, fontsize=_FOOT_SIZE, color=_FOOT_GRAY)

        if options.watermark:
            mark = _watermark(generated_at)
            page.insert_text(
                pymupdf.Point(rect.width - _MARGIN_X - _width(mark, _FOOT_SIZE - 0.5),
                              _MARGIN_TOP - 22),
                mark,
                fontname=_CJK_FONT,
                fontsize=_FOOT_SIZE - 0.5,
                color=_WM_GRAY,
            )


def _watermark(generated_at: str) -> str:
    return "AI 生成 · EduAgentX" + (f" · {generated_at}" if generated_at else "")


def _width(text: str, size: float) -> float:
    """这段字排出来有多宽（用来做右对齐；PyMuPDF 不替我们算）。"""
    return float(pymupdf.get_text_length(text, fontname=_CJK_FONT, fontsize=size))


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
