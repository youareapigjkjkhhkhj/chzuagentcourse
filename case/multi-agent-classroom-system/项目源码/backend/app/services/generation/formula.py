"""公式 → SVG（纯标准库、确定性输出）。

与 `diagram.py` 同一个理由：离线要能跑、同样的输入永远同样的字节、浏览器与
PDF/PPTX（栅格化后）看到的是同一张图。所以不引 KaTeX/MathJax —— 那两个都要
JS 运行时，而导出的 PDF 那份是本机 MuPDF 排的，它不跑脚本。

**只认一个 LaTeX 子集**，够用到「课上会写出来的公式」为止：

    x^2  x_i  x_{i+1}  \\frac{a}{b}  \\sqrt{x}  \\alpha \\beta \\theta … \\
    \\times \\cdot \\pm \\le \\ge \\ne \\approx \\to \\leftarrow \\sum \\int
    \\partial \\nabla \\infty \\in \\notin \\subset \\cup \\cap \\forall \\exists

不支持矩阵、多行对齐、积分上下限的**上下排版**（`\\sum_{i=1}^{n}` 的上下标会
像行内公式那样挂在右边）。读不出来的两处退路，都是**降级不是报错**：

1. 认不出的命令 → 原样当普通文字排（`\\foo` 显示成 `\\foo`）；
2. 整段排不出来 → `plain()` 给一串 Unicode 近似写法（`θ ← θ − α∇J(θ)`），
   前端与导出还能显示得出来。为一条公式把一整页判失败，不值当 ——
   与配图那条口径一致（`diagram.normalize` 的「截断而不是报错」）。

### 版面模型

排的是 TeX 那一套盒模型：每个盒子有 `w`（宽）、`h`（基线以上）、`d`（基线以下），
横向拼接时基线对齐。`_box()` 返回的是**一个 `<g>` 片段**，没有自己的坐标系 ——
外层（行内用它、整页图用 `render_page`）决定摆在哪儿。

宽度是**估**出来的（中日韩一字宽、拉丁 0.55 字宽，与 `diagram._wrap` 同一套）。
估不准只影响相邻元素之间的间隙，不会把算式排错：一段 `<text>` 里各个字的
位置是渲染器自己摆的，我们只决定「下一个东西从哪儿开始」。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from app.services.generation.diagram import FONT_STACK

__all__ = [
    "BASE_SIZE",
    "INLINE_SIZE",
    "PAGE_SIZE",
    "Chunk",
    "inline_metrics",
    "plain",
    "render",
    "render_page",
    "split",
]

#: 默认字号（px）。行内公式按要点的字号给，`render()` 用它排。
BASE_SIZE = 34

#: 整页主图的字号。**比行内大一截**：同一张 960×540 上，34 号的公式只占中间
#: 窄窄一条，投影到教室屏幕上后排看不见。定死一个数（不是「撑满画布」）是为了
#: 让长短两式在同一次课里字号一致 —— 每个式子各自撑满，短的那条会大得离谱。
#: 装不下时 `render_page` 会整体缩到装得下，长式子不会溢出。
PAGE_SIZE = 52

#: 行内公式的字号（px），**按要点的正文字号来**：幻灯片与导出的 HTML 里
#: 要点都是 14px 上下。给 15 不是拍的 —— 拉丁字母的视觉高度比同号的汉字矮
#: 一截，按 14 排会显得式子缩在字里，给到 17 又反过来压过整行字。
#: 生成（写进 DSL）与导出（`exports.html`）两边**必须是同一个数**：
#: 网页上排多大、PDF 里就得多大。
INLINE_SIZE = 15

#: 上下标相对正文字号的缩放与抬升/下沉。
_SCRIPT_SCALE = 0.7
_SCRIPT_SHIFT = 0.42
#: 分数线上下留的空隙、根号的横杠高度。
_FRAC_GAP = 0.22
_RULE = 0.06
#: 整页图左右各留多少（居中缩放时不能贴到画布边上）。
_PAGE_MARGIN = 56.0

_INK = "#1F2430"
_ACCENT = "#2F6BE4"

#: 字体栈。**三张图共用一份**（`diagram.FONT_STACK`），理由见那里 ——
#: 下面那张宽度表是按这一栈量出来的，换字体就得重新量一遍。
_FONT = FONT_STACK

#: 命令 → 字符。表里没有的一律退回 Unicode 近似式（`plain()` 用的也是这张表）。
_SYMBOLS: dict[str, str] = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι",
    "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
    "rho": "ρ", "sigma": "σ", "tau": "τ", "phi": "φ", "varphi": "φ",
    "chi": "χ", "psi": "ψ", "omega": "ω",
    "Alpha": "Α", "Beta": "Β", "Gamma": "Γ", "Delta": "Δ", "Epsilon": "Ε",
    "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ",
    "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓",
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠",
    "approx": "≈", "equiv": "≡", "propto": "∝", "sim": "∼",
    "to": "→", "rightarrow": "→", "leftarrow": "←", "Rightarrow": "⇒",
    "leftrightarrow": "↔",
    "sum": "∑", "prod": "∏", "int": "∫", "oint": "∮",
    "partial": "∂", "nabla": "∇", "infty": "∞", "sqrt": "√",
    "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆", "supset": "⊃",
    "cup": "∪", "cap": "∩", "emptyset": "∅",
    "forall": "∀", "exists": "∃", "neg": "¬", "land": "∧", "lor": "∨",
    "angle": "∠", "perp": "⊥", "parallel": "∥", "degree": "°",
    "left": "", "right": "", "quad": " ", "qquad": " ", ",": " ", ";": " ",
}

#: 排成**大号**的算符（求和、积分、连乘）。
_BIG = frozenset({"sum", "prod", "int", "oint"})

#: 记号（画在盒子上的那一笔）→ 画法。`\overline` 与 `\bar` 同一种。
#: 机器学习里 `\hat{y}`、`\bar{x}`、`\vec{v}` 出现得比分数还勤，值得单独排。
_ACCENTS: dict[str, str] = {
    "bar": "bar", "overline": "bar", "hat": "hat", "widehat": "hat",
    "vec": "vec", "tilde": "tilde", "widetilde": "tilde",
    "dot": "dot", "ddot": "ddot", "underline": "under",
}

#: 记号 → Unicode 组合符（`plain()` 用；`\bar{x}` 写成 `x̄`）。
_ACCENT_MARKS: dict[str, str] = {
    "bar": "̄", "hat": "̂", "vec": "⃗", "tilde": "̃",
    "dot": "̇", "ddot": "̈", "under": "̲",
}

#: 这几个命令是名不是符号（`\log x`、`\sin x` 要正着排、前面留一点空）。
_FUNCTIONS = ("log", "ln", "lg", "exp", "sin", "cos", "tan", "cot", "sec", "csc", "max", "min", "lim")


@dataclass
class _Box:
    """一个排好的盒子。`svg` 以**自己的基线左端**为原点。"""

    svg: str
    w: float = 0.0
    h: float = 0.0  # 基线以上
    d: float = 0.0  # 基线以下
    #: 这一段是「一排文字」还是一个结构（分数、根号）。用来决定要不要斜体。
    is_text: bool = False
    text: str = ""
    #: 这一段的字号。拆盒子（上标要从最后一个字挂起）时要按原字号重排。
    size: float = BASE_SIZE


@dataclass
class _State:
    """一趟排版带的状态：就一个字号。

    字号要跟着走，是因为**上下标是从「最后一个字」重排出来的**
    （`_split_last`）—— 拆出来的那半个盒子必须按它原来的字号重建，
    不然 `w_1` 的 `w` 会涨回正文字号。
    """

    size: float = BASE_SIZE


# --------------------------------------------------------------------------
# 对外的三个口
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    """一句话切出来的一截：`math` 为真时 `text` 是**式子的 LaTeX 原文**。"""

    math: bool
    text: str


def split(text: str) -> list[Chunk]:
    """一句话切成「文字 / 公式」几截。切不出来就整句当文字（返回一截）。

    `$…$` 那一对是**内联公式唯一的约定**（提示词里教过模型）。认不出来的
    一律当普通文字，**不猜**：`$` 在中文里也当货币号用。

    切分这件事放在这里、由 DSL 与三个导出渲染器共用：分开写的话，「什么样算
    一条公式」会有两份判据，早晚分叉（网页上排成公式的，PPT 里还带着两个
    美元号）。
    """
    parts: list[Chunk] = []
    buffer = ""
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text) and text[index + 1] == "$":
            buffer += "$"  # `\$` 是转义的美元号，不是公式的开头
            index += 2
            continue
        if char != "$":
            buffer += char
            index += 1
            continue
        close = text.find("$", index + 1)
        # 收尾的 `$` 找不到、或者中间不是「一个式子」时，这个 `$` 就是普通字符。
        # 「是不是一个式子」的判据是 **内容不许有头尾空白**（Pandoc 那条约定）：
        # 「价格 $5 到 $8」的两个 `$` 之间隔着空格，照理不认 —— 认了的话，
        # 一句讲价钱的话会被排成公式，两个美元号还会被吃掉。
        if (
            close < 0
            or close == index + 1  # `$$`：中间什么都没有
            or text[index + 1 : close] != text[index + 1 : close].strip()
        ):
            buffer += char
            index += 1
            continue
        if buffer:
            parts.append(Chunk(math=False, text=buffer))
            buffer = ""
        parts.append(Chunk(math=True, text=text[index + 1 : close]))
        index = close + 1
    if buffer:
        parts.append(Chunk(math=False, text=buffer))
    return parts


def inline_metrics(tex: str, *, size: float = BASE_SIZE) -> tuple[float, float, float]:
    """行内公式的 `(宽, 高, 基线以下的深度)`，都是 px；排不出来返回三个 0。

    栅格化那条路要拿它给 `<img>` 定尺寸：**MuPDF 按图片自己的像素摆，不认
    CSS 的 `width`** —— 不定尺寸的话，2 倍栅格化出来的公式在 PDF 里就是正文的
    两倍大（实拍过一次，一行要点里的式子比整行字还高）。深度是给
    `vertical-align` 用的：位图没有基线，得靠这个数把它抬回文字基线上，
    与矢量那份 `render()` 写进 `style` 的是同一个值。
    """
    box = _parse(str(tex or ""), _State(size=size))
    if box is None or not box.svg.strip():
        return 0.0, 0.0, 0.0
    pad = round(size * 0.22, 1)
    width, height = _outer_size(box, size)
    return width, height, round(box.d + pad, 1)


def render(tex: str, *, size: float = BASE_SIZE) -> str:
    """公式 → **自带尺寸**的独立 SVG（行内用：要点里夹着的那半句）。

    排不出来返回空串 —— 调用方这时退回 `plain()` 的纯文本，而不是留一个空洞。

    `vertical-align` 是**行内公式的关键一笔**：`<svg>` 默认按底边压在文字基线
    上，于是下标（`x_i` 的 i）会顶在字腰上。按这个盒子自己的深度往下让，
    公式才落在与正文同一条基线上。导出那条路不认这个属性，但它是把图当
    `<img>` 摆的，位置由排版器算，不受影响。
    """
    box = _parse(str(tex or ""), _State(size=size))
    if box is None or not box.svg.strip():
        return ""
    pad = round(size * 0.22, 1)
    depth = round(box.d + pad, 1)
    return _wrap_svg(box, size=size, extra_style=f"vertical-align:-{depth}px")


def render_page(tex: str, *, size: float = BASE_SIZE, caption: str = "") -> str:
    """公式 → 960×540 的一整页图（居中 + 可选图注）。

    与 `diagram` 的图**同一种画布**：课件页的图示位只认这一种尺寸，
    两种图混在一页里才不会一页大一幅小一幅。

    **装不下就整体缩到装得下**，而不是居中溢出画布：`\\sum_{i=1}^{m}` 那种
    长式子按 34 号排轻松超过 960，居中放出去左右两头会被裁掉 ——
    那正是「截断而不是报错」最不该发生的地方（截掉的恰好是等号两边，
    读者会以为公式本来就这样）。缩放同理走 `transform`，不重排。
    """
    box = _parse(str(tex or ""), _State(size=size))
    if box is None or not box.svg.strip():
        return ""

    from app.services.generation.diagram import VIEW_H, VIEW_W

    room_h = VIEW_H - (140 if caption else 90)
    scale = min(1.0, (VIEW_W - _PAGE_MARGIN * 2) / box.w, room_h / (box.h + box.d))
    width = round(box.w * scale, 1)
    height = round((box.h + box.d) * scale, 1)
    above = round(box.h * scale, 1)
    x = round((VIEW_W - width) / 2, 1)
    # 垂直居中：整体（含下标那一截）落在画布中间；有图注时往上让 40px。
    y = round((VIEW_H - height) / 2 + above - (40 if caption else 0), 1)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEW_W} {VIEW_H}" '
        f'width="{VIEW_W}" height="{VIEW_H}" role="img">',
        f'<rect width="{VIEW_W}" height="{VIEW_H}" fill="#FFFFFF"/>',
        f'<g transform="translate({x},{y}) scale({round(scale, 4)})">{box.svg}</g>',
    ]
    if caption:
        parts.append(
            f'<text x="{VIEW_W / 2}" y="{VIEW_H - 60}" font-size="20" fill="#5A6B87" '
            f'font-family="{_FONT}" text-anchor="middle">{_escape(caption)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def plain(tex: str) -> str:  # noqa: PLR0912 —— 认得的命令一个一支笔，拆成表反而看不出谁是谁
    """公式 → Unicode 近似写法（PPTX 的文本框用，也是排不出来时的退路）。

    `\\frac{a}{b}` 写成 `a/b`、`x^2` 写成 `x²` —— 不追求好看，追求**读得出来**：
    一份 PPT 里出现 `\\theta \\leftarrow \\theta - \\alpha \\nabla J(\\theta)`
    是没法看的。
    """
    source = str(tex or "").strip()
    if not source:
        return ""
    out: list[str] = []
    index = 0
    while index < len(source):
        char = source[index]
        if char == "\\":
            name, index = _command_at(source, index)
            if name == "frac":
                numerator, index = _group_text(source, index)
                denominator, index = _group_text(source, index)
                out.append(f"{_side(plain(numerator))}/{_side(plain(denominator))}")
            elif name == "sqrt":
                # 可选的开方次数：`\sqrt[3]{x}` 写成 `∛x`、`\sqrt[5]{x}` 写成 `⁵√x`
                degree = ""
                if index < len(source) and source[index] == "[":
                    close = source.find("]", index)
                    if close > index:
                        degree = _radical_of(plain(source[index + 1 : close]))
                        index = close + 1
                body, index = _group_text(source, index)
                # `∛` 自己就是根号，不能再补一个 `√`（否则 `\sqrt[3]{x}` 出 `∛√x`）
                root = degree or "√"
                inner = plain(body)
                if not inner:
                    out.append(root)
                # 单个字符不套括号：`√2` 比 `√(2)` 更像人写的
                else:
                    out.append(f"{root}{inner}" if len(inner) == 1 else f"{root}({inner})")
            elif name in _ACCENTS:
                body, index = _group_text(source, index)
                mark = _ACCENT_MARKS.get(_ACCENTS[name], "")
                text = plain(body)
                # 组合符落在它前面那个字符上：单字分组正好，多字分组只能盖住最后一个
                out.append(text + mark if text else "")
            elif name in _FUNCTIONS:
                out.append(name)
            else:
                out.append(_SYMBOLS.get(name, "\\" + name))
            continue
        if char == "^":
            body, index = _group_text(source, index + 1)
            out.append(_superscript(plain(body)))
            continue
        if char == "_":
            body, index = _group_text(source, index + 1)
            out.append(_subscript(plain(body)))
            continue
        if char in "{}":
            index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out).strip()


# --------------------------------------------------------------------------
# 排版
# --------------------------------------------------------------------------


def _parse(tex: str, state: _State) -> _Box | None:
    """一行公式 → 一个盒子。

    支持单行公式与多行环境（matrix / pmatrix / bmatrix / aligned / cases）。
    多行环境由 `_read_sequence` 在遇到 `\\begin` 命令时分派，认不出的环境退回纯文本。
    """
    source = str(tex or "").strip()
    if not source:
        return None
    try:
        box, _ = _read_sequence(source, 0, state, stop=None)
        return box
    except (ValueError, IndexError):
        return None


def _read_environment(source: str, index: int, state: _State) -> tuple[_Box, int]:
    """读一个 `\\begin{xxx}...\\end{xxx}` 环境，返回盒子与下一个下标。

    认不出的环境**原样当文字排**（与 `\\foo` 同一条口径）：为一个没见过的
    环境名把整条公式判失败，比留一段 `\\begin{foo}...` 在算式里难看得多。
    """
    # 跳过 \begin
    if source[index:index + 6] != "\\begin":
        raise ValueError("expected \\begin")
    index += 6
    # 读环境名 {xxx}
    if index >= len(source) or source[index] != "{":
        raise ValueError("expected { after \\begin")
    close = source.find("}", index)
    if close < 0:
        raise ValueError("unclosed environment name")
    env_name = source[index + 1:close]
    index = close + 1

    # 找到 \end{xxx}
    end_marker = f"\\end{{{env_name}}}"
    end_pos = source.find(end_marker, index)
    if end_pos < 0:
        raise ValueError(f"missing \\end{{{env_name}}}")

    # 环境体
    body = source[index:end_pos]
    index = end_pos + len(end_marker)

    # 按环境名分派
    if env_name in ("matrix", "pmatrix", "bmatrix"):
        return _matrix_box(body, env_name, state), index
    elif env_name in ("aligned", "cases"):
        return _multiline_box(body, env_name, state), index
    else:
        # 不认识的环境：原样当文字排
        return _text_box(f"\\begin{{{env_name}}}{body}\\end{{{env_name}}}", state), index


def _matrix_box(body: str, env_name: str, state: _State) -> _Box:
    """矩阵环境：按 `&` 分列、`\\\\` 分行，拼成网格。

    `pmatrix` 加圆括号、`bmatrix` 加方括号、`matrix` 不加。
    每个单元格递归排版，列宽取该列最宽者，行高取该行最高者。
    """
    # 按 \\ 分行
    rows_text = [row.strip() for row in body.split("\\\\") if row.strip()]
    if not rows_text:
        return _Box(svg="", is_text=True)

    # 每行按 & 分列，每个单元格递归排版
    rows: list[list[_Box]] = []
    for row_text in rows_text:
        cells_text = [cell.strip() for cell in row_text.split("&")]
        cells = []
        for cell_text in cells_text:
            if cell_text:
                cell_box, _ = _read_sequence(cell_text, 0, state, stop=None)
                cells.append(cell_box)
            else:
                cells.append(_Box(svg="", is_text=True))
        rows.append(cells)

    # 计算每列的最大宽度、每行的最大高度/深度
    col_count = max(len(row) for row in rows)
    col_widths = [0.0] * col_count
    row_heights = [0.0] * len(rows)
    row_depths = [0.0] * len(rows)

    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            if j < col_count:
                col_widths[j] = max(col_widths[j], cell.w)
        row_heights[i] = max((cell.h for cell in row), default=0.0)
        row_depths[i] = max((cell.d for cell in row), default=0.0)

    # 拼成网格
    col_gap = state.size * 0.5  # 列间距
    row_gap = state.size * 0.3  # 行间距

    parts: list[str] = []
    total_width = sum(col_widths) + col_gap * (col_count - 1) if col_count > 0 else 0.0
    total_height = sum(row_heights[i] + row_depths[i] for i in range(len(rows)))
    total_height += row_gap * (len(rows) - 1) if len(rows) > 1 else 0.0

    y_cursor = 0.0
    for i, row in enumerate(rows):
        x_cursor = 0.0
        for j, cell in enumerate(row):
            if j < col_count and cell.svg:
                # 单元格在列内居中
                x_offset = x_cursor + (col_widths[j] - cell.w) / 2
                # 单元格在行内基线对齐
                y_offset = y_cursor + row_heights[i]
                parts.append(_placed(cell.svg, x_offset, y_offset))
            x_cursor += col_widths[j] + (col_gap if j < col_count - 1 else 0)
        y_cursor += row_heights[i] + row_depths[i] + (row_gap if i < len(rows) - 1 else 0)

    # 加上左右括号
    bracket_width = state.size * 0.4
    if env_name == "pmatrix":
        left_bracket = _draw_paren(bracket_width, total_height, state, left=True)
        right_bracket = _draw_paren(bracket_width, total_height, state, left=False)
        parts.insert(0, _placed(left_bracket, -bracket_width, 0))
        parts.append(_placed(right_bracket, total_width, 0))
        total_width += bracket_width * 2
    elif env_name == "bmatrix":
        left_bracket = _draw_bracket(bracket_width, total_height, state, left=True)
        right_bracket = _draw_bracket(bracket_width, total_height, state, left=False)
        parts.insert(0, _placed(left_bracket, -bracket_width, 0))
        parts.append(_placed(right_bracket, total_width, 0))
        total_width += bracket_width * 2

    # 基线在第一行的基线处
    baseline = row_heights[0] if rows else 0.0

    return _Box(
        svg="".join(parts),
        w=round(total_width, 1),
        h=round(baseline, 1),
        d=round(total_height - baseline, 1),
        text=f"matrix({body})",
    )


def _draw_paren(width: float, height: float, state: _State, *, left: bool) -> str:
    """画一个圆括号（SVG path）。"""
    stroke = round(max(state.size * 0.06, 1.2), 1)
    if left:
        # 左括号：(
        return (
            f'<path d="M{width},0 Q0,{height / 2} {width},{height}" '
            f'fill="none" stroke="{_INK}" stroke-width="{stroke}"/>'
        )
    else:
        # 右括号：)
        return (
            f'<path d="M0,0 Q{width},{height / 2} 0,{height}" '
            f'fill="none" stroke="{_INK}" stroke-width="{stroke}"/>'
        )


def _draw_bracket(width: float, height: float, state: _State, *, left: bool) -> str:
    """画一个方括号（SVG path）。"""
    stroke = round(max(state.size * 0.06, 1.2), 1)
    if left:
        # 左括号：[
        return (
            f'<path d="M{width},0 L0,0 L0,{height} L{width},{height}" '
            f'fill="none" stroke="{_INK}" stroke-width="{stroke}"/>'
        )
    else:
        # 右括号：]
        return (
            f'<path d="M0,0 L{width},0 L{width},{height} L0,{height}" '
            f'fill="none" stroke="{_INK}" stroke-width="{stroke}"/>'
        )


def _multiline_box(body: str, env_name: str, state: _State) -> _Box:
    """多行对齐环境：`aligned`（按 `&` 对齐）/ `cases`（左对齐 + 大括号）。

    `aligned` 的 `&` 是对齐点：每行在 `&` 处断开，左半截右对齐、右半截左对齐，
    于是所有行的 `&` 落在同一条竖线上（推导过程的标准写法）。
    `cases` 是分段函数：每行左对齐，左边加一个大括号。
    """
    # 按 \\ 分行
    lines_text = [line.strip() for line in body.split("\\\\") if line.strip()]
    if not lines_text:
        return _Box(svg="", is_text=True)

    # 每行排版
    lines: list[tuple[_Box, float]] = []  # (盒子, 对齐点 x 坐标)
    for line_text in lines_text:
        if env_name == "aligned" and "&" in line_text:
            # 按 & 对齐：分成左右两部分
            parts_text = line_text.split("&", 1)
            left_text = parts_text[0].strip()
            right_text = parts_text[1].strip() if len(parts_text) > 1 else ""

            left_box = _read_sequence(left_text, 0, state, stop=None)[0] if left_text else _Box(svg="", is_text=True)
            right_box = _read_sequence(right_text, 0, state, stop=None)[0] if right_text else _Box(svg="", is_text=True)

            # 拼成一行，记录对齐点
            line_box = _cat([left_box, right_box])
            lines.append((line_box, left_box.w))
        else:
            # cases 或没有 & 的 aligned：整行排版
            line_box, _ = _read_sequence(line_text, 0, state, stop=None)
            lines.append((line_box, 0.0))

    # 计算对齐（aligned 环境）
    align_offsets: list[float] = []
    if env_name == "aligned":
        # 找到所有行的对齐点的最大值
        max_align_x = max(align_x for _, align_x in lines)
        # 调整每行的位置，使对齐点对齐
        for _, align_x in lines:
            align_offsets.append(max_align_x - align_x)
    else:
        # cases：左对齐
        align_offsets = [0.0] * len(lines)

    # 垂直堆叠
    line_gap = state.size * 0.4  # 行间距
    total_height = sum(line.h + line.d for line, _ in lines)
    total_height += line_gap * (len(lines) - 1) if len(lines) > 1 else 0.0
    total_width = max(line.w for line, _ in lines) if lines else 0.0

    parts: list[str] = []
    y_cursor = 0.0
    for i, (line, _) in enumerate(lines):
        x_offset = align_offsets[i]
        y_offset = y_cursor + line.h
        parts.append(_placed(line.svg, x_offset, y_offset))
        y_cursor += line.h + line.d + (line_gap if i < len(lines) - 1 else 0)

    # cases 环境：左边加一个大括号
    if env_name == "cases":
        brace_width = state.size * 0.6
        brace = _draw_brace(brace_width, total_height, state)
        parts.insert(0, _placed(brace, -brace_width, 0))
        total_width += brace_width

    # 基线在第一行的基线处
    baseline = lines[0][0].h if lines else 0.0

    return _Box(
        svg="".join(parts),
        w=round(total_width, 1),
        h=round(baseline, 1),
        d=round(total_height - baseline, 1),
        text=f"{env_name}({body})",
    )


def _draw_brace(width: float, height: float, state: _State) -> str:
    """画一个大括号 `{`（SVG path）。

    用三段二次贝塞尔曲线近似：上弯 → 中尖 → 下弯。
    """
    stroke = round(max(state.size * 0.06, 1.2), 1)
    mid = height / 2
    # 简化：用三段线近似
    return (
        f'<path d="M{width},0 Q{width / 2},0 {width / 2},{mid * 0.3} '
        f'Q{width / 2},{mid * 0.7} 0,{mid} '
        f'Q{width / 2},{mid * 1.3} {width / 2},{mid * 1.7} '
        f'Q{width / 2},{height} {width},{height}" '
        f'fill="none" stroke="{_INK}" stroke-width="{stroke}"/>'
    )


def _read_sequence(  # noqa: PLR0912, PLR0915 —— 一棵记号的读法，拆开就看不出全貌了
    source: str, index: int, state: _State, stop: str | None
) -> tuple[_Box, int]:
    """读到 `stop`（`}` 或结尾）为止的一串原子，横向拼成一个盒子。"""
    parts: list[_Box] = []
    while index < len(source):
        char = source[index]
        if stop is not None and char == stop:
            break
        if char in "^_":
            base = parts.pop() if parts else _Box(svg="", is_text=True, size=state.size)
            # 先把最后一个字拆出来当底座：`w_1` 的「1」要贴着 w，而不是贴着
            # 「前面那一整段文字」的估宽末端 —— 估宽总有误差，底座越长误差越大。
            head, base = _split_last(base)
            if head is not None:
                parts.append(head)
            script, index = _read_script(source, index + 1, state)
            parts.append(_attach(base, script, above=char == "^"))
            continue
        if char == "}":
            # 落单的 `}`：当普通文字排（不判失败），与 `\foo` 一个待遇
            parts.append(_text_box("}", state))
            index += 1
            continue
        if char == "{":
            inner, index = _read_sequence(source, index + 1, state, stop="}")
            index += 1 if index < len(source) and source[index] == "}" else 0
            parts.append(inner)
            continue
        if char == "\\":
            name, after = _command_at(source, index)
            if name in ("", None):
                index = after
                continue
            if name in _FUNCTIONS:
                parts.append(_text_box(name, state, upright=True))
                index = after
                continue
            if name in _ACCENTS:
                body, index = _read_group(source, after, state)
                parts.append(
                    _underline_box(body, state)
                    if _ACCENTS[name] == "under"
                    else _accent_box(_ACCENTS[name], body, state)
                )
                continue
            if name == "frac":
                numerator, index = _read_group(source, after, state)
                denominator, index = _read_group(source, index, state)
                parts.append(_frac_box(numerator, denominator, state))
                continue
            if name == "sqrt":
                index = after
                degree = None
                if index < len(source) and source[index] == "[":
                    close = source.find("]", index)
                    if close > index:
                        degree = _read_sequence(source, index + 1, state, stop="]")[0]
                        index = close + 1
                body, index = _read_group(source, index, state)
                parts.append(_sqrt_box(body, degree, state))
                continue
            if name in _BIG:
                # 大算符（\sum / \int / \prod）：检查后面是否跟着上下限
                op_box, index = _read_big_operator(source, after, state, name)
                parts.append(op_box)
                continue
            if name == "begin":
                # 多行环境：\begin{xxx}...\end{xxx}
                env_box, index = _read_environment(source, index, state)
                parts.append(env_box)
                continue
            symbol = _SYMBOLS.get(name)
            if symbol is None:
                # 认不出的命令：原样当文字排（`\foo` 显示成 `\foo`）。
                # **只赔这一处，不赔整条公式** —— 一个没见过的符号让满页公式
                # 退回纯文本，比留个`\foo`在算式里难看得多。
                symbol = "\\" + name
            if symbol:
                parts.append(_text_box(symbol, state))
            index = after
            continue
        # 普通字符：连着的一片字母数字攒成一个盒子，字距才不会被拆散。
        #
        # `stop` 也要在这里挡一道：上面那个 break 只在**每轮开头**看，而这一
        # 圈会把 `]` 这样的收尾字符一路吃进文字里 —— `\sqrt[3]{x}` 的 `[3]`
        # 因此被读成 `3]`，而且 `]` 没了、后面再也停不下来，整条公式的剩余
        # 部分全被当成根指数排成了小字。
        start = index
        while (
            index < len(source)
            and source[index] not in "^_{}\\"
            and (stop is None or source[index] != stop)
            and (index == start or not _is_symbolic(source[index]))
        ):
            index += 1
        parts.append(_text_box(source[start:index], state))
    return _cat(parts), index


def _read_big_operator(source: str, index: int, state: _State, name: str) -> tuple[_Box, int]:
    """读一个大算符（`\\sum` / `\\int` / `\\prod`）及其上下限，返回 display style 的盒子。

    有上下限时，上下限排在算符的正上/正下方（display style），而不是挂在右边
    （inline style）。这是数学排版的标准写法：`\\sum_{i=1}^{n}` 的上下限在正上/正下。
    """
    symbol = _SYMBOLS[name]
    op_size = state.size * 1.35
    op_box = _text_box(symbol, state, size=op_size)

    # 尝试读下限 _{...}
    lower_box = None
    if index < len(source) and source[index] == "_":
        lower_box, index = _read_script(source, index + 1, state)

    # 尝试读上限 ^{...}
    upper_box = None
    if index < len(source) and source[index] == "^":
        upper_box, index = _read_script(source, index + 1, state)

    # 如果没有上下限，就返回普通的算符
    if lower_box is None and upper_box is None:
        return op_box, index

    # 有上下限：display style 排版
    return _big_operator_box(op_box, lower_box, upper_box, state), index


def _big_operator_box(op: _Box, lower: _Box | None, upper: _Box | None, state: _State) -> _Box:
    """大算符 + 上下限的 display style 排版：上下限排在正上/正下方。

    算符居中，上限排在正上方，下限排在正下方。整体宽度 = max(算符宽, 上限宽, 下限宽)。
    高度 = 算符高 + 上限高 + 间距，深度 = 算符深 + 下限高 + 间距。
    """
    gap = state.size * 0.15  # 算符与上下限的间距

    # 计算总宽度
    width = op.w
    if lower and lower.svg:
        width = max(width, lower.w)
    if upper and upper.svg:
        width = max(width, upper.w)

    # 计算总高度与深度
    height = op.h
    depth = op.d
    if upper and upper.svg:
        height += upper.h + upper.d + gap
    if lower and lower.svg:
        depth += lower.h + lower.d + gap

    # 拼装
    parts: list[str] = []

    # 算符居中
    op_x = (width - op.w) / 2
    op_y = height - op.h if upper and upper.svg else 0
    parts.append(_placed(op.svg, op_x, op_y))

    # 上限排在正上方
    if upper and upper.svg:
        upper_x = (width - upper.w) / 2
        upper_y = 0
        parts.append(_placed(upper.svg, upper_x, upper_y))

    # 下限排在正下方
    if lower and lower.svg:
        lower_x = (width - lower.w) / 2
        lower_y = height + gap + lower.h
        parts.append(_placed(lower.svg, lower_x, lower_y))

    return _Box(
        svg="".join(parts),
        w=round(width, 1),
        h=round(height, 1),
        d=round(depth, 1),
        text=op.text + (upper.text if upper else "") + (lower.text if lower else ""),
    )


def _read_group(source: str, index: int, state: _State) -> tuple[_Box, int]:
    """读一个 `{…}` 分组（没有花括号就读一个原子），返回盒子与下一个下标。"""
    if index < len(source) and source[index] == "{":
        box, index = _read_sequence(source, index + 1, state, stop="}")
        return box, (index + 1 if index < len(source) and source[index] == "}" else index)
    return _read_script(source, index, state)


def _frac_box(numerator: _Box, denominator: _Box, state: _State) -> _Box:
    """分数：分子分母缩到 0.9，中间一条分数线。

    分数线比两边都宽一点，两个半截各自居中 —— 不然「长分子 + 短分母」
    排出来像两截断线。基线定在分数线中心，所以整个分数是**跨基线**的：
    上面 h、下面 d 各自算到最远处。
    """
    num = _shrink(numerator, 0.9)
    den = _shrink(denominator, 0.9)
    width = round(max(num.w, den.w) + state.size * 0.18, 1)
    gap = round(state.size * _FRAC_GAP, 1)
    rule = round(state.size * _RULE, 1)
    # 分子底边距分数线 gap：它的基线因此在 -(gap + num.d)
    num_y = round(-(gap + num.d), 1)
    den_y = round(gap + den.h, 1)
    parts = [
        _placed(num.svg, (width - num.w) / 2, num_y),
        f'<rect x="0" y="{round(-rule / 2, 1)}" width="{width}" height="{rule}" fill="{_INK}"/>',
        _placed(den.svg, (width - den.w) / 2, den_y),
    ]
    return _Box(
        svg="".join(parts),
        w=width,
        h=round(gap + num.d + num.h, 1),
        d=round(gap + den.h + den.d, 1),
        text=f"({num.text})/({den.text})",
    )


def _sqrt_box(body: _Box, degree: _Box | None, state: _State) -> _Box:
    """根号：外框一条折线（起笔 → 斜下 → 横杠），被开方的内容挂在横杠下面。

    横杠画在 y=0（也就是这个盒子的基线处），内容整体沉到杠下的 `pad`，
    所以这个盒子的 `d` 是「内容高度 + pad」——**不设 d 的话，根号会骑在
    相邻文字的字腰上**。
    """
    pad = round(state.size * 0.14, 1)
    rise = round(state.size * 0.45, 1)
    head = round(state.size * 0.4, 1)
    width = round(body.w + pad * 2, 1)
    body_y = round(body.h + pad, 1)
    points = " ".join(
        f"{x},{y}"
        for x, y in (
            (0, -rise),
            (round(head * 0.45, 1), round(-rise * 0.75, 1)),
            (head, 0),
            (width, 0),
        )
    )
    parts = [
        f'<polyline points="{points}" fill="none" stroke="{_INK}" stroke-width="2"/>',
        _placed(body.svg, pad, body_y),
    ]
    box = _Box(
        svg="".join(parts),
        w=width,
        h=rise,
        d=round(body_y + body.d, 1),
        text=f"√({body.text})",
    )
    if degree is None or not degree.svg:
        return box
    # 根指数（`\sqrt[3]{x}`）：缩到上下标大小，掖在折线起笔的左上角
    small = _shrink(degree, _SCRIPT_SCALE)
    # 往左压进折线里一点（与手写一致），但**不能压过头**：根指数宽过折线起笔
    # 那一撇时，超出的部分会挂到整个盒子左边去，把前面的算式盖住。
    tucked = round(min(small.w * 0.8, head), 1)
    parts.insert(
        0, _placed(small.svg, -tucked, round(-rise - small.d * 0.5, 1))
    )
    return _Box(
        svg="".join(parts),
        w=round(width + tucked, 1),
        h=round(rise + small.d * 0.5 + small.h, 1),
        d=box.d,
        text=box.text,
    )


def _accent_box(kind: str, body: _Box, state: _State) -> _Box:
    """给一个盒子加记号：`\\bar{x}`、`\\hat{y}`、`\\vec{v}`、`\\dot{x}`。

    记号画在盒子上方（`underline` 在下），盒子因此长高一点 —— 不额外留这段
    高度的话，`\\bar{x}` 上的横线会压在上一行的字脚上。
    """
    if not body.svg:
        return body
    size = state.size
    gap = round(size * 0.1, 1)
    stroke = f'stroke="{_INK}" stroke-width="{round(max(size * 0.06, 1.2), 1)}"'
    top = round(body.h + gap, 1)
    width = body.w
    if kind == "bar":
        mark = f'<line x1="0" y1="0" x2="{width}" y2="0" {stroke}/>'
        height = round(top + size * 0.08, 1)
    elif kind == "hat":
        mark = (
            f'<polyline points="0,{size * 0.1} {round(width / 2, 1)},0 {width},{size * 0.1}" '
            f'fill="none" {stroke}/>'
        )
        height = round(top + size * 0.1, 1)
    elif kind == "vec":
        head = round(size * 0.14, 1)
        mark = (
            f'<line x1="0" y1="{size * 0.06}" x2="{round(width - head, 1)}" y2="{size * 0.06}" {stroke}/>'
            f'<polygon points="{width},{size * 0.06} {round(width - head, 1)},{round(size * 0.06 - head * 0.5, 1)} '
            f'{round(width - head, 1)},{round(size * 0.06 + head * 0.5, 1)}" fill="{_INK}"/>'
        )
        height = round(top + size * 0.14, 1)
    elif kind == "tilde":
        mark = (
            f'<path d="M0,{size * 0.06} q{round(width * 0.25, 1)},{round(-size * 0.13, 1)} '
            f'{round(width * 0.5, 1)},0 q{round(width * 0.25, 1)},{round(size * 0.13, 1)} {round(width * 0.5, 1)},0" '
            f'fill="none" {stroke}/>'
        )
        height = round(top + size * 0.1, 1)
    elif kind == "ddot":
        radius = round(size * 0.05, 1)
        mark = (
            f'<circle cx="{round(width * 0.3, 1)}" cy="0" r="{radius}" fill="{_INK}"/>'
            f'<circle cx="{round(width * 0.7, 1)}" cy="0" r="{radius}" fill="{_INK}"/>'
        )
        height = round(top + size * 0.06, 1)
    else:  # dot
        radius = round(size * 0.05, 1)
        mark = f'<circle cx="{round(width / 2, 1)}" cy="0" r="{radius}" fill="{_INK}"/>'
        height = round(top + size * 0.06, 1)

    return _Box(
        svg=body.svg + _placed(mark, 0, -top),
        w=width,
        h=height,
        d=body.d,
        text=body.text,
        size=body.size,
    )


def _underline_box(body: _Box, state: _State) -> _Box:
    """下划线（`\\underline{x}`）：画在盒子底下，`d` 跟着加深。"""
    if not body.svg:
        return body
    size = state.size
    depth = round(body.d + size * 0.12, 1)
    stroke = f'stroke="{_INK}" stroke-width="{round(max(size * 0.06, 1.2), 1)}"'
    mark = f'<line x1="0" y1="0" x2="{body.w}" y2="0" {stroke}/>'
    return _Box(
        svg=body.svg + _placed(mark, 0, depth),
        w=body.w,
        h=body.h,
        d=round(depth + size * 0.06, 1),
        text=body.text,
        size=body.size,
    )


def _placed(svg: str, x: float, y: float) -> str:
    """把一段 `<g>` 挪到 (x, y)。挪动比嵌套 `translate` 更好读，也少一层。"""
    if not svg:
        return ""
    return f'<g transform="translate({round(x, 1)},{round(y, 1)})">{svg}</g>'


def _shrink(box: _Box, scale: float) -> _Box:
    """把一个盒子整体缩小（分数线上下、根指数用）。

    缩放走 `transform` 而不是重排：每个原子的字号都已经定好了，重排等于把
    缩放比例再往下传一层。`scale()` 浏览器与 MuPDF 都认；盒子自己的宽高
    跟着乘 —— 上层拼版用的是这几个数，不乘就会留出过大的空。
    """
    if not box.svg:
        return _Box(svg="", is_text=True)
    return _Box(
        svg=f'<g transform="scale({scale})">{box.svg}</g>',
        w=round(box.w * scale, 1),
        h=round(box.h * scale, 1),
        d=round(box.d * scale, 1),
        text=box.text,
    )


def _read_script(source: str, index: int, state: _State) -> tuple[_Box, int]:
    """`^` 或 `_` 后面的那一个原子：单个字符，或者一对花括号。"""
    inner = _State(size=state.size * _SCRIPT_SCALE)
    if index < len(source) and source[index] == "{":
        box, index = _read_sequence(source, index + 1, inner, stop="}")
        return box, (index + 1 if index < len(source) and source[index] == "}" else index)
    if index >= len(source):
        return _Box(svg="", is_text=True), index
    char = source[index]
    if char == "\\":
        name, after = _command_at(source, index)
        symbol = _SYMBOLS.get(name)
        if symbol is None:
            return _Box(svg="", is_text=True), after
        return _text_box(symbol, inner), after
    return _text_box(char, inner), index + 1


def _split_last(box: _Box) -> tuple[_Box | None, _Box]:
    """把一段多字文字拆成「前面那些字」与「最后一个字」。

    认不出来的结构（分数、根号）不动 —— 它们本来就是**一个**原子，
    `x_{\frac{1}{2}}` 里那个分数就是底座本身。
    """
    if not box.is_text or len(box.text) < 2:
        return None, box
    head = _text_box(box.text[:-1], _State(size=box.size))
    tail = _text_box(box.text[-1], _State(size=box.size))
    return head, tail


def _attach(base: _Box, script: _Box, *, above: bool) -> _Box:
    """把上标 / 下标挂到 `base` 右上 / 右下。"""
    shift = round(base.h * _SCRIPT_SHIFT, 1)
    if above:
        top = max(base.h, shift + script.h)
        bottom = base.d
        offset = -shift
    else:
        top = base.h
        bottom = max(base.d, shift + script.d)
        offset = shift
    svg = (
        f'{base.svg}<g transform="translate({round(base.w + base.w * 0.04, 1)},{offset})">'
        f"{script.svg}</g>"
    )
    return _Box(
        svg=svg,
        w=round(base.w + base.w * 0.04 + script.w, 1),
        h=round(top, 1),
        d=round(bottom, 1),
        is_text=False,
        text=base.text + script.text,
    )


def _cat(parts: Sequence[_Box]) -> _Box:
    """横向拼接：基线对齐，取最高的 h 与最深的 d。"""
    x = 0.0
    pieces: list[str] = []
    h = d = 0.0
    text = ""
    for box in parts:
        if not box.svg:
            continue
        pieces.append(
            box.svg if x == 0 else f'<g transform="translate({round(x, 1)},0)">{box.svg}</g>'
        )
        x += box.w
        h = max(h, box.h)
        d = max(d, box.d)
        text += box.text
    return _Box(svg="".join(pieces), w=round(x, 1), h=round(h, 1), d=round(d, 1), text=text)


def _runs(text: str, upright: bool) -> str:
    """一段文字 → 若干 `tspan`，**一个一个字母判斜正**。

    整段只挑一种体例的话，`J(\\theta)` 里的 `J` 会跟着括号一起正着排 ——
    同一页上 `x` 是斜的、`J` 是正的，看着像两套东西。TeX 里变量本来就是
    一个一个斜排的。相邻的同体例字合成一个 `tspan`：`0.794` 这种整段一样的
    不必拆成四段。斜体不改字宽（Helvetica-Oblique 与 Helvetica 同宽），
    所以上面那张宽度表不用分体例。
    """
    runs: list[tuple[bool, str]] = []
    for char in text:
        italic = (not upright) and char.isascii() and char.isalpha()
        if runs and runs[-1][0] == italic:
            runs[-1] = (italic, runs[-1][1] + char)
        else:
            runs.append((italic, char))
    return "".join(
        f'<tspan font-style="italic">{_escape(run)}</tspan>' if italic else _escape(run)
        for italic, run in runs
    )


def _text_box(
    text: str, state: _State, *, size: float | None = None, upright: bool = False
) -> _Box:
    """一串普通文字。

    拉丁字母用**斜体**（数学里的变量就该是斜的，`x` 与 `×` 一眼分得开），
    数字、算符、中日韩文字正着排。`_FUNCTIONS` 里的函数名也要正着排。
    """
    if not text:
        return _Box(svg="", is_text=True, size=size or state.size)
    font = size if size is not None else state.size
    svg = (
        f'<text x="0" y="0" font-size="{round(font, 1)}" fill="{_INK}" '
        f'font-family="{_FONT}" xml:space="preserve">{_runs(text, upright)}</text>'
    )
    return _Box(
        svg=svg,
        w=round(_width_of(text, font), 1),
        h=round(font * 0.74, 1),
        d=round(font * 0.24, 1),
        is_text=True,
        text=text,
        size=font,
    )


#: 每个字形占几个字宽（em）。
#:
#: **逐个量出来的**（按下面那一栈字体渲一遍，量右边界），不是查一套 AFM 抄的。
#: 为什么非量不可：这里是「下一个盒子从哪儿开始」的**唯一依据**，而一段
#: `<text>` 里各个字的位置是渲染器自己摆的，我们插不上手 —— 估宽偏一点，
#: 上标就会离开它该靠着的那个字母（`w_1` 变成 `w ₁`），括号后面会空出一大截
#: （`J(  θ)`）。拍脑袋的「大写一律 0.68」在 `J`（实为 0.50）上就差了 5px。
#:
#: 表覆盖全部 ASCII 与 `_SYMBOLS` 里排得出来的数学符号 —— 这是个**闭集**，
#: 我们发得出哪些字形是已知的，所以不必为「万一出现生僻字」留悬念。
_GLYPH_WIDTH: dict[str, float] = {
    # ASCII：字母、数字、标点
    " ": 0.278, "!": 0.278, '"': 0.355, "#": 0.556, "$": 0.556, "%": 0.889,
    "&": 0.667, "'": 0.191, "(": 0.333, ")": 0.333, "*": 0.389, "+": 0.584,
    ",": 0.278, "-": 0.333, ".": 0.278, "/": 0.278, ":": 0.278, ";": 0.278,
    "<": 0.584, "=": 0.584, ">": 0.584, "?": 0.556, "@": 1.015, "[": 0.278,
    "\\": 0.278, "]": 0.278, "^": 0.469, "_": 0.556, "`": 0.333, "{": 0.334,
    "|": 0.260, "}": 0.334, "~": 0.584,
    "0": 0.556, "1": 0.556, "2": 0.556, "3": 0.556, "4": 0.556,
    "5": 0.556, "6": 0.556, "7": 0.556, "8": 0.556, "9": 0.556,
    "A": 0.667, "B": 0.667, "C": 0.722, "D": 0.722, "E": 0.667, "F": 0.611,
    "G": 0.778, "H": 0.722, "I": 0.278, "J": 0.500, "K": 0.667, "L": 0.556,
    "M": 0.833, "N": 0.722, "O": 0.778, "P": 0.667, "Q": 0.778, "R": 0.722,
    "S": 0.667, "T": 0.611, "U": 0.722, "V": 0.667, "W": 0.944, "X": 0.667,
    "Y": 0.667, "Z": 0.611,
    "a": 0.556, "b": 0.556, "c": 0.500, "d": 0.556, "e": 0.556, "f": 0.278,
    "g": 0.556, "h": 0.556, "i": 0.222, "j": 0.222, "k": 0.500, "l": 0.222,
    "m": 0.833, "n": 0.556, "o": 0.556, "p": 0.556, "q": 0.556, "r": 0.333,
    "s": 0.500, "t": 0.278, "u": 0.556, "v": 0.500, "w": 0.722, "x": 0.500,
    "y": 0.500, "z": 0.500,
    # 希腊字母
    "α": 0.578, "β": 0.575, "γ": 0.500, "δ": 0.557, "ε": 0.446, "ζ": 0.441,
    "η": 0.556, "θ": 0.556, "ι": 0.222, "κ": 0.500, "λ": 0.500, "μ": 0.576,
    "ν": 0.500, "ξ": 0.448, "π": 0.690, "ρ": 0.569, "σ": 0.617, "τ": 0.395,
    "φ": 0.648, "χ": 0.525, "ψ": 0.713, "ω": 0.781,
    "Α": 0.667, "Β": 0.667, "Γ": 0.551, "Δ": 0.668, "Ε": 0.667, "Θ": 0.778,
    "Λ": 0.668, "Ξ": 0.650, "Π": 0.722, "Σ": 0.618, "Φ": 0.798, "Ψ": 0.835,
    "Ω": 0.748,
    # （微）算符与关系符。**箭头、集合符、∑ 都是一整个字宽** ——
    # 按 0.55 算的话，后面那个字母会压在箭头上。
    "±": 0.584, "∓": 0.572, "×": 0.584, "÷": 0.584, "·": 0.278, "¬": 0.584,
    "°": 0.400, "√": 0.453, "∞": 0.713, "∂": 0.476, "∇": 0.581, "∠": 0.652,
    "⊥": 0.756, "∥": 0.360, "∅": 0.838, "∝": 0.540, "∼": 0.572,
    "≈": 0.549, "≠": 0.549, "≡": 0.583, "≤": 0.549, "≥": 0.549,
    "←": 1.000, "→": 1.000, "↔": 1.000, "⇒": 0.814,
    "∈": 1.000, "∉": 1.000, "⊂": 1.000, "⊃": 1.000, "⊆": 0.699, "∪": 0.719,
    "∩": 0.719, "∧": 1.000, "∨": 1.000, "∀": 0.593, "∃": 0.424,
    "∑": 0.996, "∏": 0.996, "∫": 0.274, "∮": 0.545,
}

#: 表里没有的（生僻符号、模型自己编出来的字）：按半个字宽蒙一个，
#: 与 `_WIDE_ASCII` 一起覆盖「表外」这一档。
_DEFAULT_WIDTH = 0.55

#: 中文与全角符号按一个字宽。`diagram._wrap` 用的是同一套判断。
_WIDE_ASCII = 1.0


def _width_of(text: str, size: float) -> float:
    """估宽：先查 `_GLYPH_WIDTH`，中日韩一字宽，其余蒙一个。"""
    total = 0.0
    for char in text:
        if char in _GLYPH_WIDTH:
            total += size * _GLYPH_WIDTH[char]
        elif ord(char) > 0x2E80:
            total += size * _WIDE_ASCII
        else:
            total += size * _DEFAULT_WIDTH
    return total


def _is_symbolic(char: str) -> bool:
    """这些字符自带间距，要跟前面的字母断开成两个盒子。"""
    return char in "+-=<>±×÷·∑∫≈≤≥≠→←"


def _wrap_svg(box: _Box, *, size: float, extra_style: str = "") -> str:
    """盒子 → 独立 SVG。基线留出上下的余量，`viewBox` 就是内容大小。"""
    pad = round(size * 0.22, 1)
    width, height = _outer_size(box, size)
    style = f' style="{extra_style}"' if extra_style else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}"{style} role="img">'
        f'<g transform="translate({pad},{round(pad + box.h, 1)})">{box.svg}</g></svg>'
    )


def _outer_size(box: _Box, size: float) -> tuple[float, float]:
    """行内公式连留白带框占多大（px）。`render` 与 `inline_size` 共用一个算法 ——
    两边各算一遍的话，栅格化那条路量出来的尺寸会跟矢量那条差一点。"""
    pad = round(size * 0.22, 1)
    return round(box.w + pad * 2, 1), round(box.h + box.d + pad * 2, 1)


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------

_COMMAND = re.compile(r"\\([A-Za-z]+|.)")


def _command_at(source: str, index: int) -> tuple[str, int]:
    """从 `index` 的 `\\` 起读一个命令名，返回 (名字, 下一个下标)。"""
    match = _COMMAND.match(source, index)
    if match is None:
        return "", index + 1
    return match.group(1), match.end()


def _group_text(source: str, index: int) -> tuple[str, int]:
    """读一个 `{…}` 分组（没有花括号就读一个字符），给 `plain()` 用。"""
    if index < len(source) and source[index] == "{":
        depth = 0
        start = index + 1
        while index < len(source):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    return source[start:index], index + 1
            index += 1
        return source[start:], index
    if index < len(source):
        return source[index], index + 1
    return "", index


_SUPERSCRIPTS = str.maketrans("0123456789+-=()ni", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ")
_SUBSCRIPTS = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")


def _side(text: str) -> str:
    """分数线的一半 → 写成一行时的样子。

    **排成图时有分数线兜着，写成一行就得自己加括号**：
    `\\frac{1}{1+e^{-z}}` 少了这对括号会变成 `1/1 + e⁻z`，被读成
    「1 除以 1，再加 e 的负 z 次方」—— 意思整个反了。分母只有一个字母
    （`2a`）、或者只是几个字母连乘（`P(B|A) P(A)`）时不加，不然
    `sigmoid` 那种式子会排成一串括号，比不加还难读。

    判据是**这一半自己有没有低优先级的算符**（加减、等号、除号），在开头
    的那个不算：`-b` 是负号，`-b/2a` 本来就读得通。
    """
    if not text:
        return text
    return f"({text})" if any(char in text[1:] for char in "+-=±∓/") else text


def _radical_of(degree: str) -> str:
    """开方次数 → Unicode 根号前缀。3 与 4 有现成的字符，其余写在上标里。"""
    if degree == "3":
        return "∛"
    if degree == "4":
        return "∜"
    return _superscript(degree) if degree else ""


def _superscript(text: str) -> str:
    return text.translate(_SUPERSCRIPTS) if text and len(text) < 8 else f"^({text})"


def _subscript(text: str) -> str:
    return text.translate(_SUBSCRIPTS) if text and len(text) < 8 else f"_({text})"


def _escape(text: str) -> str:
    from xml.sax.saxutils import escape

    return escape(text)
