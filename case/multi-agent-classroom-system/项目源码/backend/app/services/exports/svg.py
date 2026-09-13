"""SVG → 位图（给装不下矢量的那两个产物用）。

PPTX 与 PDF 都**收不了矢量图**：

- `python-pptx` 的 `add_picture` 要的是 png/jpeg 字节，EMF/WMF 之外不认 SVG；
- PDF 那条路走 MuPDF 排 `print_pages()` 的 HTML，它把内联 `<svg>` 当没看见，
  只认 `<img>`。

所以两处都得先把 `generation.diagram` 画好的 SVG 栅格化。用 PyMuPDF 而不是
cairosvg / Playwright：它**已经在依赖里**（PDF 导出用的就是它），离线装得上，
也不拖一个本地图形栈进来。

栅格化是**尽力而为**的：失败返回空字节，调用方退回占位框。一张示意图画不出来
不该让一整门课导不出来 —— 这与 `ir.from_dsl` 的「坏数据不抛异常」是同一条口径。
"""

from __future__ import annotations

import base64

import pymupdf

from app.common.logging import get_logger

__all__ = ["pixel_size", "render_png", "to_data_uri"]

logger = get_logger("app.exports.svg")

#: 默认放大倍数。SVG 是矢量的，栅格化时的倍数直接决定 PPTX/PDF 里那张图的清晰度：
#: 2 倍相当于按 1920×1080 出图，投影仪与打印都够用，体积也在几百 KB 以内。
DEFAULT_SCALE = 2.0


def render_png(svg: str, *, scale: float = DEFAULT_SCALE) -> bytes:
    """SVG 源码 → 白底 PNG 字节；画不出来返回 `b""`。"""
    if not svg or not svg.lstrip().startswith("<svg"):
        return b""
    try:
        with pymupdf.open(stream=svg.encode("utf-8"), filetype="svg") as document:
            if document.page_count < 1:
                return b""
            page = document.load_page(0)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            return pixmap.tobytes("png")
    except Exception as exc:
        # 只记类型不记堆栈：SVG 是模型产出 + 落库内容，堆栈里会带上它的片段，
        # 而日志（P5 §6 的口径）不该出现课程内容的原文。
        logger.warning("示意图栅格化失败（%s），这一页退回占位框", type(exc).__name__)
        return b""


def to_data_uri(svg: str, *, scale: float = DEFAULT_SCALE) -> str:
    """SVG → `data:image/png;base64,…`；画不出来返回空串。

    给 PDF 那条路用：`print_pages()` 出来的是**一个字符串**，交给 MuPDF 之前
    没有机会做别的事，图片只能内联在 `src` 里（外链文件一拷走就断）。
    """
    png = render_png(svg, scale=scale)
    if not png:
        return ""
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def pixel_size(png: bytes) -> tuple[int, int]:
    """PNG 的像素尺寸 (宽, 高)；认不出来返回 (0, 0)。

    直接读 IHDR —— 八个字节的签名加固定偏移的两个大端整数，比为了拿尺寸去
    引一个图像库划算。PPTX 要按这个比例算置入尺寸（`add_picture` 不给尺寸时
    按 72dpi 算，一张 1920px 宽的图会占掉 26 英寸，整张幻灯片都装不下）。
    """
    if len(png) >= 24 and png[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
    return 0, 0
