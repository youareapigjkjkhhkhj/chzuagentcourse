"""对比表格渲染：`TableSpec` → 960×540 的 SVG。

用于「三种算法的复杂度对比」、「优缺点对照表」这类需要结构化对比的场景。

### 设计

- **表头加粗 + 底色**：与数据行区分开
- **斑马纹**：偶数行浅灰底，提升可读性
- **高亮单元格**：`highlight` 指定的单元格用强调色底色
- **自动列宽**：按每列最宽内容分配，总宽不超过画布
- **自动换行**：单元格内容过长时自动换行（最多 3 行）

### 约束

- 最多 8 列 × 12 行（含表头），超出截断
- 单元格内容最多 40 字，超出截断加 `…`
- 与 diagram / plot / formula 共用画布（960×540）与字体
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.services.generation.diagram import FONT_STACK, VIEW_H, VIEW_W

__all__ = ["render"]

#: 表格的颜色常量（与 diagram 共用一套配色）
_HEADER_BG = "#E8F0FE"  # 表头底色（浅蓝）
_HEADER_INK = "#1A2B4A"  # 表头文字（深蓝）
_ROW_BG_EVEN = "#F8F9FA"  # 偶数行底色（浅灰）
_ROW_BG_ODD = "#FFFFFF"  # 奇数行底色（白）
_HIGHLIGHT_BG = "#FFF3CD"  # 高亮底色（浅黄）
_BORDER = "#D0D7DE"  # 边框（浅灰）
_INK = "#1A2B4A"  # 正文文字（深蓝）

#: 表格的尺寸约束
_MAX_COLS = 8
_MAX_ROWS = 12  # 含表头
_MAX_CELL_LEN = 40
_CELL_PADDING = 12  # 单元格内边距
_ROW_HEIGHT = 40  # 行高
_HEADER_HEIGHT = 48  # 表头行高
_FONT_SIZE = 16  # 正文字号
_HEADER_FONT_SIZE = 18  # 表头字号


def render(spec: Any) -> str:
    """`TableSpec` → 960×540 的 SVG；画不出来返回空串。"""
    if not isinstance(spec, Mapping):
        return ""

    headers = [str(h).strip() for h in (spec.get("headers") or []) if str(h).strip()]
    rows_raw = spec.get("rows") or []
    caption = str(spec.get("caption") or "").strip()
    highlight = spec.get("highlight") or []

    if not headers or not rows_raw:
        return ""

    # 截断到约束范围
    headers = headers[:_MAX_COLS]
    col_count = len(headers)
    rows: list[list[str]] = []
    for row in rows_raw[: _MAX_ROWS - 1]:  # 减去表头那一行
        if not isinstance(row, Sequence):
            continue
        cells = [str(cell).strip()[:_MAX_CELL_LEN] for cell in row[:col_count]]
        # 补齐列数
        while len(cells) < col_count:
            cells.append("")
        rows.append(cells)

    if not rows:
        return ""

    # 解析高亮坐标
    highlight_set: set[tuple[int, int]] = set()
    for item in highlight:
        if isinstance(item, Sequence) and len(item) == 2:
            try:
                r, c = int(item[0]), int(item[1])
                if 0 <= r < len(rows) and 0 <= c < col_count:
                    highlight_set.add((r, c))
            except (ValueError, TypeError):
                pass

    # 计算列宽
    col_widths = _calc_col_widths(headers, rows, col_count)
    table_width = sum(col_widths)
    table_height = _HEADER_HEIGHT + len(rows) * _ROW_HEIGHT

    # 居中放置
    x_offset = (VIEW_W - table_width) / 2
    y_offset = (VIEW_H - table_height - (60 if caption else 0)) / 2

    # 绘制 SVG
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEW_W} {VIEW_H}" '
        f'width="{VIEW_W}" height="{VIEW_H}" role="img">',
        f'<rect width="{VIEW_W}" height="{VIEW_H}" fill="#FFFFFF"/>',
        f'<g transform="translate({x_offset},{y_offset})">',
    ]

    # 绘制表头
    parts.append(_draw_header(headers, col_widths))

    # 绘制数据行
    for i, row in enumerate(rows):
        y = _HEADER_HEIGHT + i * _ROW_HEIGHT
        bg = _ROW_BG_EVEN if i % 2 == 0 else _ROW_BG_ODD
        parts.append(_draw_row(row, col_widths, y, bg, i, highlight_set))

    # 绘制边框
    parts.append(_draw_borders(col_widths, table_height, len(rows)))

    parts.append("</g>")

    # 绘制图注
    if caption:
        parts.append(
            f'<text x="{VIEW_W / 2}" y="{VIEW_H - 30}" font-size="18" fill="#5A6B87" '
            f'font-family="{FONT_STACK}" text-anchor="middle">{_escape(caption)}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def _calc_col_widths(headers: list[str], rows: list[list[str]], col_count: int) -> list[float]:
    """计算每列的宽度：按最宽内容分配，总宽不超过画布的 90%。"""
    max_width = VIEW_W * 0.9
    min_col_width = 80  # 最小列宽

    # 估算每列的最大内容宽度
    col_max_len = [0] * col_count
    for j, header in enumerate(headers):
        col_max_len[j] = max(col_max_len[j], len(header))
    for row in rows:
        for j, cell in enumerate(row):
            if j < col_count:
                col_max_len[j] = max(col_max_len[j], len(cell))

    # 按内容长度分配宽度
    total_len = sum(col_max_len) or 1
    col_widths = [max(min_col_width, (length / total_len) * max_width) for length in col_max_len]

    # 调整总宽不超过 max_width
    total_width = sum(col_widths)
    if total_width > max_width:
        scale = max_width / total_width
        col_widths = [w * scale for w in col_widths]

    return col_widths


def _draw_header(headers: list[str], col_widths: list[float]) -> str:
    """绘制表头行。"""
    parts: list[str] = [
        f'<rect x="0" y="0" width="{sum(col_widths)}" height="{_HEADER_HEIGHT}" '
        f'fill="{_HEADER_BG}" stroke="{_BORDER}" stroke-width="1"/>',
    ]

    x = 0
    for j, header in enumerate(headers):
        width = col_widths[j]
        # 文字居中
        text_x = x + width / 2
        text_y = _HEADER_HEIGHT / 2 + _HEADER_FONT_SIZE / 3
        parts.append(
            f'<text x="{text_x}" y="{text_y}" font-size="{_HEADER_FONT_SIZE}" '
            f'fill="{_HEADER_INK}" font-family="{FONT_STACK}" text-anchor="middle" '
            f'font-weight="bold">{_escape(header)}</text>'
        )
        x += width

    return "".join(parts)


def _draw_row(
    row: list[str],
    col_widths: list[float],
    y: float,
    bg: str,
    row_index: int,
    highlight_set: set[tuple[int, int]],
) -> str:
    """绘制一行数据。"""
    parts: list[str] = []
    x = 0

    for j, cell in enumerate(row):
        width = col_widths[j]

        # 判断是否高亮
        cell_bg = _HIGHLIGHT_BG if (row_index, j) in highlight_set else bg

        # 绘制单元格底色
        parts.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{_ROW_HEIGHT}" '
            f'fill="{cell_bg}" stroke="{_BORDER}" stroke-width="1"/>'
        )

        # 绘制文字（居中）
        text_x = x + width / 2
        text_y = y + _ROW_HEIGHT / 2 + _FONT_SIZE / 3
        parts.append(
            f'<text x="{text_x}" y="{text_y}" font-size="{_FONT_SIZE}" '
            f'fill="{_INK}" font-family="{FONT_STACK}" text-anchor="middle">'
            f'{_escape(cell)}</text>'
        )

        x += width

    return "".join(parts)


def _draw_borders(col_widths: list[float], table_height: float, row_count: int) -> str:
    """绘制外边框。"""
    total_width = sum(col_widths)
    return (
        f'<rect x="0" y="0" width="{total_width}" height="{table_height}" '
        f'fill="none" stroke="{_BORDER}" stroke-width="2"/>'
    )


def _escape(text: str) -> str:
    """XML 转义。"""
    from xml.sax.saxutils import escape

    return escape(text)
