"""时间轴图示 → SVG（`kind = "timeline"`，纯标准库、确定性输出）。

用于「朝代更替、历史阶段、版本演进、发展里程碑」这类**有先后顺序**的内容。
这类内容塞进流程图网格会很难看（节点被摆成 4×3 的格子、箭头斜着穿），
时间轴才是它本来的样子：一条横轴，事件交替摆在上下两侧。

### 设计

- **横轴 + 箭头**：时间从左往右走，轴末端一个箭头
- **上下交替**：事件一上一下错开摆，10 个事件也放得下、不挤
- **三行文字**：年代（粗、靠轴）、事件名（主文字）、补充说明（小字，可省）
- **强调节点**：`accent` 的事件点是实心的，其余是空心圈
- **逐拍揭示**：每个事件一个 `data-beat`，课堂上讲到哪拍到哪

### 约束

- 最多 10 个事件，超出截断
- 年代 ≤8 字、事件名每行 ≤10 字（最多 2 行）、说明 ≤18 字（超了截断）
- 与 diagram / plot / formula / table 共用画布（960×540）与字体

**为什么叫 `chrono` 不叫 `timeline`**：`generation/timeline.py` 已经是
「生成任务时间线」（工作台任务卡用的），`classroom/timeline.py` 是
「课堂播放时间线」。图示这一种按 kind 取名会撞车，就按意思取个不撞的。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence
from xml.sax.saxutils import escape

from app.services.generation.diagram import FONT_STACK, VIEW_H, VIEW_W

__all__ = ["MAX_EVENTS", "render"]

#: 一条轴上最多摆几个事件。上下交替各 5 个，再多文字就开始互相压。
MAX_EVENTS = 10

_PAD = 80
_AXIS_Y = 280
_STEM = 52  # 轴到文字区的竖线长度

_ACCENT = "#2F6BE4"
_LINE = "#C7CEDB"
_INK = "#1F2430"
_MUTED = "#5A6B87"


def render(spec: Any) -> str:
    """spec → SVG；没有事件返回空串（调用方按「没有图」处理）。"""
    if not isinstance(spec, Mapping):
        return ""
    events = _events_of(spec)[:MAX_EVENTS]
    if not events:
        return ""

    n = len(events)
    step = (VIEW_W - 2 * _PAD) / (n - 1) if n > 1 else 0
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEW_W} {VIEW_H}" '
        f'font-family="{FONT_STACK}">',
        f'<rect width="{VIEW_W}" height="{VIEW_H}" fill="#FFFFFF"/>',
        _axis(),
    ]
    for i, ev in enumerate(events):
        x = _PAD + i * step if n > 1 else VIEW_W / 2
        parts.append(f'<g data-beat="{i}">{_event_svg(ev, x, up=i % 2 == 0)}</g>')
    parts.append("</svg>")
    return "".join(parts)


# --------------------------------------------------------------------------
# 内部
# --------------------------------------------------------------------------


def _events_of(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    """把 spec 里的事件收拾成 `{time, label, note, accent}`。

    只认 `events`：`rows` → events 的转换在 `TimelineSpec` 的校验里做完了
    （schema 层做转换、渲染层只画，各管一段）。
    """
    out = []
    for raw in _list_of(spec.get("events")):
        if isinstance(raw, Mapping):
            label = str(raw.get("label") or raw.get("text") or "").strip()
            time = str(raw.get("time") or "").strip()
            note = str(raw.get("note") or "").strip()
            accent = bool(raw.get("accent"))
        else:
            label, time, note, accent = str(raw or "").strip(), "", "", False
        if not label and not time:
            continue
        out.append({"time": time, "label": label, "note": note, "accent": accent})
    return out


def _axis() -> str:
    """横轴 + 右端箭头。轴比首尾两个事件点各长出一点，箭头指「时间往这走」。"""
    x0, x1 = _PAD - 34, VIEW_W - _PAD + 34
    y = _AXIS_Y
    return (
        f'<line x1="{x0}" y1="{y}" x2="{x1 - 10}" y2="{y}" stroke="{_LINE}" stroke-width="2"/>'
        f'<path d="M{x1},{y} L{x1 - 12},{y - 6} L{x1 - 12},{y + 6} Z" fill="{_LINE}"/>'
    )


def _event_svg(ev: Mapping[str, Any], x: float, *, up: bool) -> str:
    """一个事件：轴上的点 + 竖线 + 几行文字（年代 / 事件名 / 说明）。"""
    y = _AXIS_Y
    accent = bool(ev.get("accent"))
    dot = (
        f'<circle cx="{x:.1f}" cy="{y}" r="7" fill="{_ACCENT}"/>'
        if accent
        else f'<circle cx="{x:.1f}" cy="{y}" r="6" fill="#FFFFFF" stroke="{_ACCENT}" stroke-width="3"/>'
    )
    sign = -1 if up else 1
    stem_end = y + sign * _STEM
    stem = (
        f'<line x1="{x:.1f}" y1="{y + sign * 9}" x2="{x:.1f}" y2="{stem_end}" '
        f'stroke="{_LINE}" stroke-width="2"/>'
    )

    # 文字几行：靠轴的是年代（粗），往外是事件名（主）、说明（小）
    lines: list[tuple[str, int, str, str]] = [(str(ev.get("time") or ""), 15, _ACCENT if accent else _MUTED, "600")]
    for text in _wrap(str(ev.get("label") or ""), 10)[:2]:
        lines.append((text, 17, _INK, "500"))
    note = str(ev.get("note") or "")
    if note:
        lines.append((_clip(note, 18), 12, _MUTED, "400"))

    texts = []
    for i, (text, size, color, weight) in enumerate(lines):
        if not text:
            continue
        # 上侧从 stem_end 往上排（y 递减），下侧往下排（y 递增）
        ty = stem_end + sign * (18 + i * 22)
        texts.append(
            f'<text x="{x:.1f}" y="{ty}" text-anchor="middle" font-size="{size}" '
            f'fill="{color}" font-weight="{weight}">{escape(text)}</text>'
        )
    return dot + stem + "".join(texts)


def _wrap(text: str, width: int) -> list[str]:
    """按字数折行（中文一字一宽够准，ASCII 按半宽算）。"""
    lines: list[str] = []
    cur = ""
    cur_w = 0.0
    for ch in text:
        w = 0.55 if ch.isascii() else 1.0
        if cur_w + w > width and cur:
            lines.append(cur)
            cur, cur_w = "", 0.0
        cur += ch
        cur_w += w
    if cur:
        lines.append(cur)
    return lines


def _clip(text: str, width: int) -> str:
    """单行截断：超了加省略号。"""
    return text if len(text) <= width else text[: width - 1] + "…"


def _list_of(value: Any) -> Sequence[Any]:
    return value if isinstance(value, (list, tuple)) else []
