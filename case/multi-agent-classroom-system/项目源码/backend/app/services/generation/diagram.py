"""结构化图示 → SVG（纯标准库、确定性输出）。

为什么自己拼字符串，而不是引一个绘图库：
1. **离线要能跑** —— 验收环境没有外网，也不该为一张流程图绑一个渲染后端；
2. **确定性** —— 同样的 spec 永远渲染出同样的字节，导出产物的哈希才稳定；
3. **谁都能显示** —— SVG 是浏览器、PPTX（栅格化后）、PDF 三边的最小公约数。

输入是模型给的**节点网格 + 箭头**（`visual.spec`），不是自由画布：模型
画不准坐标，但「谁在谁右边、谁指向谁」说得准。布局由这里算，所以图画
出来一定是正的；模型给歪了（行数超了、箭头指向不存在的节点），这里
**截断而不是报错** —— 配图是锦上添花，为它把一整页判失败不值当。

坐标系统一：viewBox 960×540，内容按行/列均分，节点居格心。
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence
from xml.sax.saxutils import escape

from app.services.generation import icons

VIEW_W = 960
VIEW_H = 540

MAX_ROWS = 4
MAX_COLS = 3
MAX_EDGES = 12
MAX_NODE_LINES = 3

PAD = 34
FONT = 17
LINE_H = 22

_NODE_FILL = "#F5F7FB"
_NODE_STROKE = "#C7CEDB"
_ACCENT_FILL = "#E8F1FF"
_ACCENT_STROKE = "#2F6BE4"
_INK = "#1F2430"
_MUTED = "#5A6B87"

#: 字体栈。**必须显式指定**，而且三张图（流程/公式/曲线）得是同一份：
#: 不指定时浏览器与 MuPDF 各挑各的默认字体（MuPDF 挑的是 Times），同一个字
#: 两边能差出三成宽 —— 一份课件在屏幕上是好的、导出到 PDF 就散了，正是
#: 「同一门课两个样子」。`formula` 的宽度表也是按这一栈量出来的。
FONT_STACK = "Helvetica, Arial, sans-serif"

_SHAPES = ("box", "ellipse", "diamond")


def normalize(spec: Any) -> dict | None:
    """把模型给的 spec 收拾成能画的结构；画不出来返回 None。

    容忍三种常见走样：整行写成字符串数组、节点写成字符串、箭头指向越界。
    前两种就地补全，第三种直接丢那条箭头（其余照画）。
    """
    if not isinstance(spec, Mapping):
        return None

    rows: list[list[dict]] = []
    for raw_row in _list_of(spec.get("rows"))[:MAX_ROWS]:
        cells = _list_of(raw_row)[:MAX_COLS]
        row: list[dict] = []
        for cell in cells:
            if isinstance(cell, str):
                row.append({"text": cell.strip(), "shape": "box", "accent": False, "icon": ""})
            elif isinstance(cell, Mapping):
                row.append(
                    {
                        "text": str(cell.get("text") or "").strip(),
                        "shape": _shape_of(cell.get("shape")),
                        "accent": bool(cell.get("accent")),
                        "icon": str(cell.get("icon") or "").strip(),
                    }
                )
        # 空行也留着：行号是箭头指节点用的坐标，**不能因为一行没字就把它抽掉**
        # （抽掉之后那一行下面的所有箭头都会指错一格）。
        rows.append(row)
    if not any(cell["text"] for row in rows for cell in row):
        return None

    height = len(rows)
    edges: list[dict] = []
    for raw_edge in _list_of(spec.get("edges"))[:MAX_EDGES]:
        if not isinstance(raw_edge, Mapping):
            continue
        source = _point(raw_edge.get("from"), rows)
        target = _point(raw_edge.get("to"), rows)
        if source is None or target is None or source == target:
            continue
        edges.append(
            {
                "from": source,
                "to": target,
                "label": str(raw_edge.get("label") or "").strip(),
            }
        )
    return {"rows": rows, "edges": edges, "height": height}


def render(spec: Any) -> str:
    """spec → SVG 字符串；画不出来返回空串（调用方按「没有图」处理）。"""
    drawing = normalize(spec)
    if drawing is None:
        return ""
    rows: list[list[dict]] = drawing["rows"]
    cols = max(len(row) for row in rows)
    grid = _grid(rows, cols)

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEW_W} {VIEW_H}" '
        f'width="{VIEW_W}" height="{VIEW_H}" role="img">',
        f'<rect width="{VIEW_W}" height="{VIEW_H}" fill="#FFFFFF"/>',
    ]

    # 一行一个 `data-beat`：课堂上讲到第几步就亮到第几行，导出栅格化整张图
    # 时全部显示（属性对 MuPDF 与 PPTX 都是透明的）。
    for edge in drawing["edges"]:
        # 箭头跟着**它指向的那一行**出现 —— 目标还没讲，先冒出一根指过去的
        # 箭头，看的人会以为那一格是空的
        beat = max(edge["from"][0], edge["to"][0])
        parts.append(f'<g data-beat="{beat}" class="dg-edge">{_edge_svg(edge, grid)}</g>')
    for row_index, row in enumerate(rows):
        for col_index, node in enumerate(row):
            parts.append(
                f'<g data-beat="{row_index}" class="dg-node">{_node_svg(node, grid[row_index][col_index])}</g>'
            )

    parts.append("</svg>")
    return "".join(parts)


# --- 版式 ---


def _grid(rows: Sequence[Sequence[dict]], cols: int) -> list[list[tuple[float, float, float, float]]]:
    """每个节点一格：返回 (中心 x, 中心 y, 宽, 高)。"""
    cell_w = (VIEW_W - 2 * PAD) / cols
    cell_h = (VIEW_H - 2 * PAD) / len(rows)
    # 横向留出 60px 以上的缝：箭头标签（「清洗」「是/否」）就画在缝里，
    # 缝比标签还窄时标签会压在框上。
    box_w = min(cell_w - 64, 250.0)
    box_h = min(cell_h - 30, 108.0)
    out: list[list[tuple[float, float, float, float]]] = []
    for row_index, row in enumerate(rows):
        line: list[tuple[float, float, float, float]] = []
        for col_index in range(len(row)):
            center_x = PAD + cell_w * (col_index + 0.5)
            center_y = PAD + cell_h * (row_index + 0.5)
            line.append((round(center_x, 1), round(center_y, 1), round(box_w, 1), round(box_h, 1)))
        out.append(line)
    return out


def _node_svg(node: Mapping[str, Any], box: tuple[float, float, float, float]) -> str:
    if not node["text"]:
        # 空格子：不画框，但**占着位置** —— 这样「一行放不下、折到下一行
        # 某个列上」的流程（邮件→特征→模型 ↓ 判定）还能用行列号指清楚。
        return ""
    cx, cy, w, h = box
    fill = _ACCENT_FILL if node["accent"] else _NODE_FILL
    stroke = _ACCENT_STROKE if node["accent"] else _NODE_STROKE
    shape = node["shape"]
    if shape == "ellipse":
        body = (
            f'<ellipse cx="{cx}" cy="{cy}" rx="{w / 2}" ry="{h / 2}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        )
    elif shape == "diamond":
        body = (
            f'<polygon points="{cx},{cy - h / 2} {cx + w / 2},{cy} '
            f'{cx},{cy + h / 2} {cx - w / 2},{cy}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        )
    else:
        body = (
            f'<rect x="{cx - w / 2}" y="{cy - h / 2}" width="{w}" height="{h}" rx="12" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="2"/>'
        )
    text_width = w if shape != "diamond" else w * 0.6
    # 图标：模型显式给的 `icon` 优先（它懂任何学科的语义），没给或认不得就按
    # 文字关键词兜底。菱形（判定节点）空间太挤，不配图标，文字仍居中。
    icon_key = None if shape == "diamond" else icons.pick(node.get("icon"), str(node["text"]))
    if icon_key:
        # 有图标：图标占格子上部，文字整体下移让位 —— 两者不叠在一起。
        # 菱形（判定节点）空间太挤，不配图标，文字仍居中。
        icon_size = min(34.0, h * 0.34)
        icon_cy = cy - h / 2 + icon_size / 2 + 8
        icon = icons.render(
            icon_key, cx, icon_cy, icon_size, _ACCENT_STROKE if node["accent"] else _MUTED
        )
        text_cy = cy + icon_size / 2
    else:
        icon = ""
        text_cy = cy
    text = _text_svg(str(node["text"]), cx, text_cy, text_width)
    return body + icon + text


def _text_svg(text: str, cx: float, cy: float, width: float) -> str:
    if not text:
        return ""
    lines = _wrap(text, width - 24, MAX_NODE_LINES)
    start = cy - (len(lines) - 1) * LINE_H / 2 + FONT * 0.36
    spans = "".join(
        f'<tspan x="{cx}" y="{round(start + index * LINE_H, 1)}">{escape(line)}</tspan>'
        for index, line in enumerate(lines)
    )
    return (
        f'<text font-size="{FONT}" fill="{_INK}" font-family="{FONT_STACK}" '
        f'text-anchor="middle">{spans}</text>'
    )


def _edge_svg(edge: Mapping[str, Any], grid: Sequence[Sequence[tuple[float, float, float, float]]]) -> str:
    source = grid[edge["from"][0]][edge["from"][1]]
    target = grid[edge["to"][0]][edge["to"][1]]
    start = _border_point(source, target, gap=4.0)
    tip = _border_point(target, source, gap=10.0)
    line = (
        f'<path d="M{start[0]},{start[1]} L{tip[0]},{tip[1]}" fill="none" '
        f'stroke="{_MUTED}" stroke-width="2"/>'
    )
    label = str(edge.get("label") or "")
    if not label:
        return line + _arrow_head(start, tip)
    mid_x = round((start[0] + tip[0]) / 2, 1)
    mid_y = round((start[1] + tip[1]) / 2, 1)
    width = max(len(label) * 13 * 0.62 + 14, 30)
    return (
        line
        + _arrow_head(start, tip)
        + f'<rect x="{round(mid_x - width / 2, 1)}" y="{mid_y - 12}" width="{round(width, 1)}" '
        f'height="23" rx="11" fill="#FFFFFF" stroke="{_NODE_STROKE}"/>'
        + f'<text x="{mid_x}" y="{mid_y + 4}" font-size="{FONT - 4}" fill="{_MUTED}" '
        + f'font-family="{FONT_STACK}" text-anchor="middle">{escape(label)}</text>'
    )


def _arrow_head(start: tuple[float, float], tip: tuple[float, float]) -> str:
    """箭头画成显式多边形，**不用 `marker-end`**：MuPDF 的 SVG 解析不认
    marker，走「导出 PPT/PDF 先栅格化」那条路时箭头会凭空消失，而浏览器里
    一切正常 —— 这种「一半环境好一半坏」的差异最难查，索性不用。
    """
    dx = tip[0] - start[0]
    dy = tip[1] - start[1]
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    base_x = tip[0] - ux * 12
    base_y = tip[1] - uy * 12
    left = (round(base_x - uy * 5.5, 1), round(base_y + ux * 5.5, 1))
    right = (round(base_x + uy * 5.5, 1), round(base_y - ux * 5.5, 1))
    return (
        f'<polygon points="{tip[0]},{tip[1]} {left[0]},{left[1]} {right[0]},{right[1]}" '
        f'fill="{_MUTED}"/>'
    )


def _border_point(
    box: tuple[float, float, float, float], other: tuple[float, float, float, float], *, gap: float
) -> tuple[float, float]:
    """从 box 中心朝 other 中心走，落在 box 边框上、再往外让开 gap 的点。"""
    cx, cy, w, h = box
    dx = other[0] - cx
    dy = other[1] - cy
    length = math.hypot(dx, dy)
    if not length:
        return round(cx, 1), round(cy, 1)
    scale_x = (w / 2) / abs(dx) if dx else float("inf")
    scale_y = (h / 2) / abs(dy) if dy else float("inf")
    ratio = min(scale_x, scale_y) + gap / length
    return round(cx + dx * ratio, 1), round(cy + dy * ratio, 1)


# --- 小工具 ---


def _wrap(text: str, budget: float, max_lines: int) -> list[str]:
    """按像素预算折行：中日韩字符按一个字宽算，拉丁字符按 0.55 字宽算。"""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        width = 0.0
        for char in paragraph.strip():
            char_width = FONT if _is_wide(char) else FONT * 0.55
            if current and width + char_width > budget:
                lines.append(current)
                current, width = char, char_width
            else:
                current += char
                width += char_width
        if current:
            lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…" if len(lines[-1]) > 1 else lines[-1] + "…"
    return lines


def _is_wide(char: str) -> bool:
    return ord(char) > 0x2E80


def _list_of(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        return list(value)
    return []


def _shape_of(value: Any) -> str:
    shape = str(value or "").strip().lower()
    return shape if shape in _SHAPES else "box"


def _point(raw: Any, rows: Sequence[Sequence[dict]]) -> tuple[int, int] | None:
    """`[行, 列]`，越界返回 None。"""
    coords = _list_of(raw)
    if len(coords) != 2:
        return None
    try:
        row, col = int(coords[0]), int(coords[1])
    except (TypeError, ValueError):
        return None
    if 0 <= row < len(rows) and 0 <= col < len(rows[row]):
        return row, col
    return None


__all__ = ["MAX_COLS", "MAX_ROWS", "VIEW_H", "VIEW_W", "normalize", "render"]
