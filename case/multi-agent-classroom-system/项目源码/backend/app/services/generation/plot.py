"""曲线图 → SVG（纯标准库、确定性输出）。

与 `diagram.py` 同一个理由：离线要能跑、同样的输入永远同样的字节、浏览器与
PDF/PPTX（栅格化后）看到的是同一张图。所以不用 matplotlib（拖一个绘图栈进来，
离线装不上，出图还是不确定的）。

**这个模块与另外两张图有一处根本不同：它要算数。** 流程图只是把模型给的
格子摆整齐，公式只是排版，都**不执行任何东西**；曲线得把模型写的那串表达式
逐点求值。模型写的东西是**输入**，不是代码 —— 所以求值走 `_evaluate` 的
AST 白名单，**永远不用 `eval`**：只放行四则运算、几个幂函数与 `math` 里的
初等函数，其余（属性访问、下标、lambda、推导式、赋值）一律拒。

    y = 1/(1+exp(-x))      放行：exp 在白名单里
    __import__('os')...    放行不了：`Call` 的函数名不在表里
    x.real                 放行不了：`Attribute` 根本不在白名单节点里

### 坏数据怎么办

与 `diagram.normalize` 的「截断而不是报错」同一条口径，只是截断的单位是
**一条曲线**：某条画不出来（表达式认不出、采样全是 NaN），就丢那一条，
其余照画；一条都不剩才返回空串，让调用方按「没有图」处理。

### 怎么画

采样 240 个点，`x` 在 `xrange` 上均分。**不连线的地方比连线的地方更要紧**：
`tan(x)` 在 π/2 附近、`1/x` 在 0 附近，值会冲到 ±∞，照直连过去就是一条横穿
画布的竖线 —— 看着像数据里真有个陡坡。所以只画落在绘图区里的点，出界处
接到边界上收笔（`_segments`），曲线于是变成一条条独立的折线。
"""

from __future__ import annotations

import ast
import math
from typing import Any, Callable, Mapping, Sequence
from xml.sax.saxutils import escape

from app.services.generation.diagram import FONT_STACK, VIEW_H, VIEW_W

#: 一条曲线采多少个点。够密（960px 宽上每 3px 一个），又不至于把 SVG 撑大。
SAMPLES = 240

#: 画布四周留白：左边要给 y 轴刻度留字，下边要给 x 轴刻度留字。
_PAD_L = 78.0
_PAD_R = 46.0
_PAD_T = 48.0
_PAD_B = 66.0

_INK = "#1F2430"
_MUTED = "#5A6B87"
_GRID = "#E7EBF2"
_AXIS = "#9AA7BD"
_FONT = FONT_STACK

#: 曲线的默认配色。与 `diagram` 的主色同族：一页里两张图放一起不打架。
_PALETTE = ("#2F6BE4", "#D54941", "#2BA471", "#834EC2", "#E37318", "#0F766E")

#: 最多画几条。再多颜色也分不清了，且页面也放不下图例。
MAX_CURVES = 4
MAX_POINTS = 12
#: 可调参数最多预渲染几帧（每一帧都是一整张 SVG，是要落库的，见 `visual.py`）。
MAX_FRAMES = 8

#: 表达式里能用的函数（**这是全部的家底**，表外的一律拒）。
_FUNCS: dict[str, Callable[..., float]] = {
    "abs": abs,
    "ceil": math.ceil,
    "cos": math.cos,
    "exp": math.exp,
    "floor": math.floor,
    "log": math.log,  # 模型写 log 一般指自然对数，与 numpy/math 的默认一致
    "log10": math.log10,
    "log2": math.log2,
    "max": max,
    "min": min,
    "sin": math.sin,
    "sqrt": math.sqrt,
    "tan": math.tan,
    "tanh": math.tanh,
}

#: 表达式里能用的常数。
_CONSTS: dict[str, float] = {"e": math.e, "pi": math.pi, "tau": math.tau}

#: 表达式里**认得的全部名字**：自变量、常数、函数名。
#: 函数名也在里头 —— 少了这一档，`exp(x)` 里的那个 `exp` 会被当成
#: 「不认识的名字」拒掉，于是**每一个带函数的表达式都排不出来**。
_KNOWN_NAMES = frozenset({"x", *_CONSTS, *_FUNCS})


def render(spec: Any, *, values: Mapping[str, float] | None = None) -> str:
    """spec → 960×540 的 SVG；一条曲线都画不出来时返回空串。

    spec 的样貌（模型给的就是这个）：

        {"kind": "plot", "title": "sigmoid", "xlabel": "z", "ylabel": "σ(z)",
         "xrange": [-6, 6], "yrange": [0, 1],
         "curves": [{"expr": "1/(1+exp(-x))", "label": "σ(z)"}],
         "points": [{"x": 0, "y": 0.5, "label": "阈值"}]}

    `yrange` 可以不写 —— 按采样结果自动定，只是会自动取整到好看的刻度。

    `values` 是**可调参数这一帧取什么**（`{"alpha": 0.4}`）。不传就取每个参数
    的第一个值 —— 于是「静态那一帧」就是滑块的起始位置，导出与网页看到的是
    同一张图。
    """
    if not isinstance(spec, Mapping):
        return ""
    curves = _curves_of(spec, _values_of(spec, values))
    if not curves:
        return ""

    x_range = _range_of(spec.get("xrange"), fallback=None)
    if x_range is None:
        return ""
    if x_range[0] > x_range[1]:
        x_range = (x_range[1], x_range[0])
    if x_range[0] == x_range[1]:
        return ""

    y_range = _range_of(spec.get("yrange"), fallback=None) or _fit_y(curves, x_range)
    if y_range is None or y_range[0] >= y_range[1]:
        return ""

    title = str(spec.get("title") or "").strip()
    subtitle = str(spec.get("subtitle") or "").strip()
    # 有副标题时整块图往下让一行，不去挤画布顶上那 48px
    frame = _Frame(x_range, y_range, top=_PAD_T + (22 if subtitle else 0))
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEW_W} {VIEW_H}" '
        f'width="{VIEW_W}" height="{VIEW_H}" role="img">',
        f'<rect width="{VIEW_W}" height="{VIEW_H}" fill="#FFFFFF"/>',
    ]
    parts.append(_grid_svg(frame))
    parts.extend(
        _curve_svg(curve, frame, index) for index, curve in enumerate(curves)
    )
    parts.extend(_point_svg(point, frame) for point in _points_of(spec))
    parts.append(_title_svg(title, subtitle))
    parts.append(_legend_svg(curves, frame))
    parts.append(
        _axis_labels_svg(str(spec.get("xlabel") or ""), str(spec.get("ylabel") or ""), frame)
    )
    parts.append("</svg>")
    return "".join(parts)


def safe_eval(
    expr: str, *, params: Sequence[str] = (), values: Mapping[str, float] | None = None
) -> Callable[[float], float] | None:
    """表达式 → 一元函数；认不出来返回 None。

    **`x` 是自变量，`params` 里的是这一帧取定值的可调参数**（`{"alpha": 0.4}`）。
    参数在闭包里就定死了，所以返回的仍然只是一元函数 —— 采样那条路不必知道
    参数这回事。

    模型爱写的 `^` 在这里换成 `**`（Python 的 `^` 是异或，1/2 会算出个 0 来，
    而且不报错 —— 那种错最难查）。`²` 这类上标也顺手换成 `**2`：模型从 LaTeX
    那边过来时经常带着它们。
    """
    source = _normalize(expr)
    if not source:
        return None
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError:
        return None
    if not _allowed(tree.body, params):
        return None
    code = compile(tree, "<plot>", "eval")
    fixed = dict(values or {})

    def function(x: float) -> float:
        return float(_evaluate(code, x, fixed))

    return function


def _evaluate(code: Any, x: float, fixed: Mapping[str, float]) -> Any:
    """在只有 `x`、已定值的参数、常数、白名单函数的环境里求值。

    `__builtins__` 直接掐掉：没有 `__import__`、没有 `open`。白名单已经把
    危险节点挡在门外了，这里是第二道 —— 两道都要有，因为白名单靠的是
    「我列全了危险节点」，而这是**唯一一次执行模型输入的地方**。
    """
    scope = {"__builtins__": {}, "x": x, **fixed, **_CONSTS, **_FUNCS}
    return eval(code, scope)  # noqa: S307 —— 已过 `_allowed` 白名单，见模块 docstring


def _normalize(expr: str) -> str:
    """把模型惯用的写法换成 Python 认的。"""
    source = str(expr or "").strip()
    if not source:
        return ""
    # `y = ...` 前缀：模型常把整行式子抄进来，左侧那个 y 只表示「这是 y」
    if "=" in source and "==" not in source.split("=", 1)[0]:
        head, _, tail = source.partition("=")
        if head.strip() in ("y", "f(x)", "y(x)"):
            source = tail.strip()
    for superscript, digits in (
        ("²", "2"), ("³", "3"), ("¹", "1"), ("⁴", "4"),
    ):
        source = source.replace(superscript, "**" + digits)
    return source.replace("^", "**")


_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load, ast.Call,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd,
    ast.FloorDiv,
)


def _allowed(node: ast.AST, params: Sequence[str] = ()) -> bool:
    """白名单式的「能不能执行这棵树」。

    **逐个节点问「是不是我认识的」，而不是问「是不是危险的」** —— 后者是
    黑名单，永远列不全（`ast.Attribute` 能拿 `__class__`、`ast.Subscript` 能
    拿 `__globals__`……）。函数名与常数名也要在表里，不然 `foo()` 这种
    名字上看不出好歹的调用会溜进去。
    """
    names = _KNOWN_NAMES | set(params)
    for child in ast.walk(node):
        if not isinstance(child, _ALLOWED_NODES):
            return False
        if isinstance(child, ast.Name) and child.id not in names:
            return False
        if isinstance(child, ast.Call):
            func = child.func
            if not isinstance(func, ast.Name) or func.id not in _FUNCS:
                return False
    return True


# --- 版式 ---


class _Frame:
    """数据坐标 ↔ 画布坐标的换算。

    y 轴是**翻过来**的：数据里 y 变大是往上走，画布里 y 变大是往下走。
    这处翻转只在这里做一次 —— 散在每处画线的地方，早晚会漏掉一个。
    """

    def __init__(
        self, x_range: tuple[float, float], y_range: tuple[float, float], *, top: float = _PAD_T
    ) -> None:
        self.x0, self.x1 = x_range
        self.y0, self.y1 = y_range
        self.left = _PAD_L
        self.right = VIEW_W - _PAD_R
        self.top = top
        self.bottom = VIEW_H - _PAD_B

    def px(self, x: float) -> float:
        return self.left + (x - self.x0) / (self.x1 - self.x0) * (self.right - self.left)

    def py(self, y: float) -> float:
        return self.bottom - (y - self.y0) / (self.y1 - self.y0) * (self.bottom - self.top)


def _grid_svg(frame: _Frame) -> str:
    """网格 + 刻度 + 两条轴。

    轴**画在 0 上**（0 在范围内时），像一张真的坐标纸；0 不在范围内时退到
    画布边缘 —— 值域全是正数时（比如 sigmoid 的 [0,1]），贴着底边画才有
    「这里就是零点」的意思，画在中间反而像是数据穿过 0。
    """
    parts: list[str] = []
    x_ticks = _ticks(frame.x0, frame.x1)
    y_ticks = _ticks(frame.y0, frame.y1)

    axis_y = frame.py(0.0) if frame.y0 <= 0 <= frame.y1 else frame.bottom
    axis_x = frame.px(0.0) if frame.x0 <= 0 <= frame.x1 else frame.left

    for value in x_ticks:
        x = round(frame.px(value), 1)
        parts.append(
            f'<line x1="{x}" y1="{frame.top}" x2="{x}" y2="{frame.bottom}" '
            f'stroke="{_GRID}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{x}" y="{round(frame.bottom + 22, 1)}" font-size="14" fill="{_MUTED}" '
            f'font-family="{_FONT}" text-anchor="middle">{escape(_tick_label(value))}</text>'
        )
    for value in y_ticks:
        y = round(frame.py(value), 1)
        parts.append(
            f'<line x1="{frame.left}" y1="{y}" x2="{frame.right}" y2="{y}" '
            f'stroke="{_GRID}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{round(frame.left - 12, 1)}" y="{round(y + 5, 1)}" font-size="14" '
            f'fill="{_MUTED}" font-family="{_FONT}" text-anchor="end">{escape(_tick_label(value))}</text>'
        )

    parts.append(
        f'<line x1="{frame.left}" y1="{round(axis_y, 1)}" x2="{frame.right}" '
        f'y2="{round(axis_y, 1)}" stroke="{_AXIS}" stroke-width="1.6"/>'
    )
    parts.append(
        f'<line x1="{round(axis_x, 1)}" y1="{frame.top}" x2="{round(axis_x, 1)}" '
        f'y2="{frame.bottom}" stroke="{_AXIS}" stroke-width="1.6"/>'
    )
    return "".join(parts)


def _curve_svg(curve: Mapping[str, Any], frame: _Frame, beat: int) -> str:
    """一条曲线。**整条包在一个 `data-beat` 分组里** —— 课堂上讲到第几个 beat
    就显示第几条，导出时（栅格化整张图）永远全部显示，见 `visual.py`。"""
    color = escape(str(curve["color"]))
    polylines = []
    for segment in _segments(curve["function"], (frame.x0, frame.x1), (frame.y0, frame.y1)):
        points = " ".join(f"{round(frame.px(px), 1)},{round(frame.py(py), 1)}" for px, py in segment)
        polylines.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" '
            f'stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>'
        )
    return f'<g data-beat="{beat}">{"".join(polylines)}</g>'


def _point_svg(point: Mapping[str, Any], frame: _Frame) -> str:
    """标出来的点（最优点、阈值、截距）。一个点给一个圈 + 一句标注。"""
    x = point["x"]
    y = point["y"]
    if not (math.isfinite(x) and math.isfinite(y)):
        return ""
    cx = round(frame.px(x), 1)
    cy = round(frame.py(y), 1)
    label = str(point.get("label") or "").strip()
    if not (frame.left - 4 <= cx <= frame.right + 4 and frame.top - 4 <= cy <= frame.bottom + 4):
        return ""  # 点落在画布外：画不出来，但那条曲线还在
    parts = [
        f'<circle cx="{cx}" cy="{cy}" r="4.5" fill="#FFFFFF" stroke="{_INK}" stroke-width="2"/>'
    ]
    if label:
        # 标注摆在点的右上方；贴着右边界时改摆左上，免得跑出画布
        right = cx + 10
        anchor = "start"
        if right + len(label) * 14 > frame.right:
            right, anchor = cx - 10, "end"
        parts.append(
            f'<text x="{round(right, 1)}" y="{round(cy - 10, 1)}" font-size="15" fill="{_INK}" '
            f'font-family="{_FONT}" text-anchor="{anchor}">{escape(label)}</text>'
        )
    return "".join(parts)


def _title_svg(title: str, subtitle: str) -> str:
    """标题与副标题，都在顶上。

    副标题**不放底下**：底下那一条已经被 x 轴刻度与轴名占了（三条 16px 的字
    挤在 60px 里，排出来是叠着的）。放在标题下面既是图表里更常见的位置，
    也让底下那条线永远只有刻度与轴名两层。
    """
    parts: list[str] = []
    if title:
        parts.append(
            f'<text x="{VIEW_W / 2}" y="28" font-size="20" fill="{_INK}" '
            f'font-family="{_FONT}" text-anchor="middle">{escape(title)}</text>'
        )
    if subtitle:
        parts.append(
            f'<text x="{VIEW_W / 2}" y="50" font-size="15" fill="{_MUTED}" '
            f'font-family="{_FONT}" text-anchor="middle">{escape(subtitle)}</text>'
        )
    return "".join(parts)


def _legend_svg(curves: Sequence[Mapping[str, Any]], frame: _Frame) -> str:
    """图例摆在右上角的空处。两条以上才画 —— 一条曲线时它就是噪声。

    底下垫一块不透明白板：右上角常常正是曲线爬升的地方（sigmoid 一族都
    这样），不垫的话线从字里穿过去 —— 图例本来是来解释线的，反倒先把线
    糊了。不用 `opacity` 半透：MuPDF 与浏览器对叠加的取整不同，同一张图
    两边会差出几个灰阶。
    """
    labeled = [curve for curve in curves if curve["label"]]
    if len(labeled) < 2:
        return ""
    x = frame.right - 12
    y = frame.top + 6
    width = max(_text_width(str(curve["label"]), 15) for curve in labeled)
    plate = (
        f'<rect x="{round(x - 34 - width - 8, 1)}" y="{round(y - 13, 1)}" '
        f'width="{round(width + 46, 1)}" height="{round((len(labeled) - 1) * 24 + 26, 1)}" rx="6" '
        f'fill="#FFFFFF" stroke="{_GRID}" stroke-width="1"/>'
    )
    parts: list[str] = [plate]
    for index, curve in enumerate(labeled):
        color = escape(str(curve["color"]))
        line_y = round(y + index * 24, 1)
        parts.append(
            f'<line x1="{round(x - 26, 1)}" y1="{line_y}" x2="{round(x - 8, 1)}" y2="{line_y}" '
            f'stroke="{color}" stroke-width="3"/>'
        )
        parts.append(
            f'<text x="{round(x - 34, 1)}" y="{round(line_y + 5, 1)}" font-size="15" '
            f'fill="{_INK}" font-family="{_FONT}" text-anchor="end">{escape(curve["label"])}</text>'
        )
    return "".join(parts)


def _text_width(text: str, size: float) -> float:
    """估一行字的宽度：中日韩按一个字宽、拉丁按 0.55 字宽。
    与 `diagram._wrap` 同一把尺子 —— 两边量出来的宽度不该是两套。"""
    return sum(size if ord(char) > 0x2E80 else size * 0.55 for char in text)


def _axis_labels_svg(xlabel: str, ylabel: str, frame: _Frame) -> str:
    """两条轴的名字。x 轴写在中下，y 轴**竖着**写（`rotate(-90)`）贴左边。"""
    parts: list[str] = []
    if xlabel:
        # 比刻度再往下 26px：刻度的基线在 `frame.bottom + 22`，同高的话
        # 「3」和轴名会叠在一起（排出来看过，是叠着的）
        parts.append(
            f'<text x="{round(VIEW_W / 2, 1)}" y="{round(frame.bottom + 48, 1)}" font-size="16" '
            f'fill="{_INK}" font-family="{_FONT}" text-anchor="middle">{escape(xlabel)}</text>'
        )
    if ylabel:
        parts.append(
            f'<text x="20" y="{round(VIEW_H / 2, 1)}" font-size="16" fill="{_INK}" '
            f'font-family="{_FONT}" text-anchor="middle" '
            f'transform="rotate(-90,20,{round(VIEW_H / 2, 1)})">{escape(ylabel)}</text>'
        )
    return "".join(parts)


# --- 采样 ---


def _samples(function: Callable[[float], float], x_range: tuple[float, float]) -> list[tuple[float, float]]:
    """在 `x_range` 上均分采样，算不出来的点记成 NaN（不抛异常往外走）。"""
    step = (x_range[1] - x_range[0]) / (SAMPLES - 1)
    out: list[tuple[float, float]] = []
    for index in range(SAMPLES):
        x = x_range[0] + index * step
        try:
            out.append((x, float(function(x))))
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            out.append((x, math.nan))
    return out


def _segments(
    function: Callable[[float], float], x_range: tuple[float, float], y_range: tuple[float, float]
) -> list[list[tuple[float, float]]]:
    """逐点求值 → 一段段连得起来的折线，**全部落在绘图区内**。

    曲线在 x 上是单值的，于是「画不画得出来」就只剩「这一点在不在绘图区里」。
    规则三条：

    - 算不出来（NaN／除零／溢出）→ 断开；
    - 走出绘图区 → 断开，但**在边界上补一个交点**，线是走到边上停住的，
      而不是断在半路；
    - 从区外回到区内 → 同样先补边界交点，再接着画。

    两条好处是白捡的。其一，**渐近线自动就断了**：相邻两步跨过整屏时，两头
    必有一头在区外，不可能连出一条假的竖线。其二，出界的点根本不画，曲线
    不会从标题上压过去 —— 外层 `<svg>` 只在画布边上裁，裁不到绘图区，而
    `clip-path` 在 MuPDF 里**不生效**（与 `diagram._arrow_head` 记的 `marker-end`
    是同一个坑），拿它裁就成了「浏览器里好好的、导出到 PDF 就穿了头」。
    """
    low, high = y_range
    segments: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []

    def flush() -> None:
        # 一个点连不成线：孤零零的点画出来什么都没有
        if len(current) > 1:
            segments.append(list(current))
        current.clear()

    previous: tuple[float, float] | None = None
    for x, y in _samples(function, x_range):
        point = (x, y)
        if not math.isfinite(y):
            flush()
            previous = None
            continue
        if low <= y <= high:
            if not current and previous is not None:
                # 从区外回来：先接到边界上的交点，再接着画
                current.append(_cross(point, previous, low, high))
            current.append(point)
        else:
            if current and previous is not None:
                # 走出区外：线走到边界就收笔
                current.append(_cross(previous, point, low, high))
            flush()
        previous = point
    flush()
    return segments


def _cross(
    inside: tuple[float, float], outside: tuple[float, float], low: float, high: float
) -> tuple[float, float]:
    """内点与外点之间，折线与绘图区边界（`y = low` 或 `y = high`）的交点。"""
    (x0, y0), (x1, y1) = inside, outside
    edge = low if y1 < low else high
    if y1 == y0:
        return (x1, edge)
    return (round(x0 + (x1 - x0) * (edge - y0) / (y1 - y0), 4), edge)


def _fit_y(curves: Sequence[Mapping[str, Any]], x_range: tuple[float, float]) -> tuple[float, float] | None:
    """没给值域时按采样结果定一个。

    **取 2% / 98% 分位，不取极值**：`tan(x)`、`1/x` 这种在渐近线附近的点能把
    值甩到几千去，拿极值当边界，整条曲线会被压成一条贴着 0 的直线。分位数把
    那几个野点扔掉之后，剩下的才是这条曲线「主要在讲什么」。
    """
    values = sorted(
        y
        for curve in curves
        for _, y in _samples(curve["function"], x_range)
        if math.isfinite(y)
    )
    if not values:
        return None
    low = _percentile(values, 0.02)
    high = _percentile(values, 0.98)
    if low >= high:
        low, high = low - 1.0, high + 1.0
    pad = (high - low) * 0.12
    step = _nice_step(high - low + pad * 2)
    return math.floor((low - pad) / step) * step, math.ceil((high + pad) / step) * step


def _percentile(values: Sequence[float], fraction: float) -> float:
    """排好序的数列里取一个分位（最近邻，不插值 —— 只要一个数量级对得上）。"""
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, round(fraction * (len(values) - 1))))
    return values[index]


def _ticks(low: float, high: float) -> list[float]:
    """刻度位置。步长落在 1/2/2.5/5 × 10^k 上 —— 人看着顺眼。"""
    step = _nice_step(high - low)
    start = math.ceil(low / step)
    count = math.floor(high / step) - start
    return [round((start + index) * step, 10) for index in range(count + 1)][:24]


#: 「顺眼」的步长档位。2.5 是给 `0.25`、`2.5` 这种刻度留的。
_NICE_STEPS = (1.0, 2.0, 2.5, 5.0, 10.0)


def _nice_step(span: float) -> float:
    """把跨度切成**八段上下**：取最接近 `span/8` 的那一档。

    取最接近而不是「第一个不小于」：后者在 `span/8 = 2.9` 时会跳到 5，
    刻度只剩四条，图上空得像是没算出来。
    """
    if not math.isfinite(span) or span <= 0:
        return 1.0
    raw = span / 8
    magnitude = 10 ** math.floor(math.log10(raw))
    return min(_NICE_STEPS, key=lambda step: abs(raw - step * magnitude)) * magnitude


def _tick_label(value: float) -> str:
    """刻度的字。去掉多余的 0（`1.0` 写成 `1`、`0.5000000001` 写成 `0.5`）。"""
    if abs(value) < 1e-9:
        return "0"
    if abs(value - round(value)) < 1e-9:
        return str(round(value))
    return f"{value:.6g}"


# --- 收拾模型的输入 ---


def param_of(spec: Any) -> dict[str, Any] | None:
    """规范化那个**可调参数**（`{"name", "label", "values"}`）；没有返回 None。

    只认一个：两个参数的滑块是二维网格，页面上摆不下，也没人愿意在课堂上
    拖两个滑块。参数化的曲线用 `curves[].expr` 里的名字引用它，例如
    `{"name": "alpha", "values": [0.1, 0.4]}` 配 `"exp(-alpha*x)"`。
    """
    if not isinstance(spec, Mapping):
        return None
    raw = spec.get("params")
    if isinstance(raw, Sequence) and not isinstance(raw, str):
        raw = raw[0] if raw else None  # 写成数组也认，只取第一个
    if not isinstance(raw, Mapping):
        return None
    name = str(raw.get("name") or "").strip()
    if not name.isidentifier():
        return None
    values: list[float] = []
    for item in _list_of(raw.get("values"))[:MAX_FRAMES]:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            continue
        values.append(float(item))
    if len(values) < 2:
        return None  # 只有一个取值就不叫「可调」了
    return {"name": name, "label": str(raw.get("label") or name).strip(), "values": values}


def _values_of(spec: Mapping[str, Any], values: Mapping[str, float] | None) -> dict[str, float]:
    """这一帧各个参数取什么：调用方给了就用它，没给就落在第一个值上。"""
    param = param_of(spec)
    if param is None:
        return dict(values or {})
    chosen = {param["name"]: param["values"][0]}
    chosen.update(values or {})
    return chosen


def _curves_of(spec: Mapping[str, Any], values: Mapping[str, float]) -> list[dict[str, Any]]:
    """`curves` → 能画的那几条。认不出的表达式直接丢，见模块 docstring。"""
    params = tuple(values)
    out: list[dict[str, Any]] = []
    for item in _list_of(spec.get("curves"))[:MAX_CURVES]:
        # 一条曲线可以就写成一串表达式（模型图省事时的写法）
        raw: Mapping[str, Any] = {"expr": item} if isinstance(item, str) else item
        if not isinstance(raw, Mapping):
            continue
        function = safe_eval(str(raw.get("expr") or raw.get("f") or ""), params=params, values=values)
        if function is None:
            continue
        out.append(
            {
                "function": function,
                "label": str(raw.get("label") or "").strip(),
                # 配色**在这里定死**，不在画的时候各算各的 —— 图例与曲线是
                # 两处代码，各自按下标取色的话，中间只要有一条没标签的曲线，
                # 两边就对不上了（图例里那条红的，画出来是蓝的）
                "color": str(raw.get("color") or "").strip()
                or _PALETTE[len(out) % len(_PALETTE)],
            }
        )
    return out


def _points_of(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in _list_of(spec.get("points"))[:MAX_POINTS]:
        if not isinstance(raw, Mapping):
            continue
        x = raw.get("x")
        y = raw.get("y")
        # `bool` 也是 `int`，但 `"x": true` 显然不是个坐标
        if isinstance(x, bool) or isinstance(y, bool):
            continue
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            continue
        out.append({"x": float(x), "y": float(y), "label": str(raw.get("label") or "").strip()})
    return out


def _range_of(raw: Any, *, fallback: tuple[float, float] | None) -> tuple[float, float] | None:
    """`[0, 1]` 或者 `{"min": 0, "max": 1}` 都认 —— 模型两种写法都会出。"""
    if isinstance(raw, Mapping):
        raw = [raw.get("min"), raw.get("max")]
    if not isinstance(raw, Sequence) or isinstance(raw, str) or len(raw) < 2:
        return fallback
    try:
        return float(raw[0]), float(raw[1])
    except (TypeError, ValueError):
        return fallback


def _list_of(raw: Any) -> list[Any]:
    if isinstance(raw, Sequence) and not isinstance(raw, str):
        return list(raw)
    return []


__all__ = [
    "MAX_CURVES",
    "MAX_FRAMES",
    "MAX_POINTS",
    "SAMPLES",
    "param_of",
    "render",
    "safe_eval",
]
