"""图示分派：`visual.spec` → 落进 DSL 的那一份（含交互要用的帧）。

五种图共用一套画布与字体（`diagram.VIEW_W/VIEW_H/FONT_STACK`），画法各是
一个模块：

    kind = "flow"（默认）  →  diagram  节点网格 + 箭头
    kind = "plot"         →  plot      坐标轴 + 曲线
    kind = "formula"      →  formula   排版的公式
    kind = "table"        →  table     对比表格
    kind = "timeline"     →  chrono    横向时间轴 + 事件

**分派为什么在这个文件里、而不是 `diagram.render` 里**：其余几个模块要
`import diagram` 拿画布常量，`diagram` 反过来再 import 它们就成了循环。
这里是最上面那一层，谁都能 import，谁都不必被 import。

### 交互

用户要的「交互性」有两处，都在**服务端**做完，前端只负责显示：

1. **可调参数**（滑块 + 播放）。曲线随参数变化的样子一次全画好存进
   `frames`，前端按滑块位置换一张图，不必带一个求值器 —— 在浏览器里跑
   模型给的表达式这件事，能不做就不做，而且做两遍早晚跟后端算出两样。
2. **随讲稿节拍逐步揭示**。各张图的 SVG 里都带了 `data-beat`（曲线一条一个、
   流程一行一个、时间轴一个事件一个），前端按课堂讲到第几拍给对应元素加一个类名。

导出三格式**取静态帧**（`svg` 那个字段）：PPT 与 PDF 是要发出去的东西，
不该带着「拖到第 4 帧」这种状态。
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services.generation import chrono, diagram, formula, plot, table

__all__ = ["build", "kind_of", "render"]

#: 认得的图示种类。表外的（含模型自己编的）一律按流程图试试看 —— 这是
#: 最老的一种，也是模型最熟的一种，认错了顶多是画不出来，不会画错。
_KINDS = {
    "flow": "flow", "diagram": "flow", "flowchart": "flow",
    "plot": "plot", "curve": "plot", "chart": "plot", "line": "plot",
    "formula": "formula", "math": "formula", "equation": "formula",
    "table": "table", "grid": "table", "matrix": "table",
    "timeline": "timeline", "chrono": "timeline", "history": "timeline",
    "roadmap": "timeline", "milestone": "timeline", "sequence": "timeline",
}

#: `kind` 漏写或写了个没见过的词时，按标志字段猜：有 `curves` 的是曲线、
#: 有 `events` 的是时间轴……按顺序认，认不出就退回流程图。
_MARKERS = (("curves", "plot"), ("tex", "formula"), ("headers", "table"), ("events", "timeline"))


def kind_of(spec: Any) -> str:
    """这一份 spec 画的是哪一种图。

    `kind` 没写或者写了个没见过的词时，**按有没有那个标志字段来认**：
    有 `curves` 的是曲线、有 `tex` 的是公式、有 `headers` 的是表格、
    有 `events` 的是时间轴、其余当流程图。
    落库后的 spec 一定带着 `kind`（那是模型 dump 出来的），这一步主要是救
    **模型刚写完、还没过 schema** 的那一份 —— 它经常图省事把 `kind` 漏掉。
    """
    if not isinstance(spec, Mapping):
        return "flow"
    kind = _KINDS.get(str(spec.get("kind") or "").strip().lower())
    if kind is not None:
        return kind
    for field, guess in _MARKERS:
        if field in spec:
            return guess
    return "flow"


def render(spec: Any, *, values: Mapping[str, float] | None = None) -> str:
    """spec → SVG；画不出来返回空串（调用方按「没有图」处理）。

    `values` 只对带可调参数的曲线图有意义（这一帧参数取什么），其余几种忽略。
    """
    kind = kind_of(spec)
    if kind == "plot":
        return plot.render(spec, values=values)
    if kind == "formula":
        return _formula_svg(spec)
    if kind == "table":
        return table.render(spec)
    if kind == "timeline":
        return chrono.render(spec)
    return diagram.render(spec)


def build(spec: Any) -> dict[str, Any]:
    """spec → 落进 DSL 的那一份：静态帧 + 可选的滑块帧。

    返回 `{"svg": …, "frames": […], "params": …}`；画不出来时 `svg` 是空串。
    `frames`/`params` 只在**确实能调**的时候才出现（没有可调参数的图不该在
    DSL 里多两个空字段，前端也不必判断「这个滑块点了没用」）。
    """
    svg = render(spec)
    out: dict[str, Any] = {"svg": svg}
    if not svg or kind_of(spec) != "plot":
        return out
    param = plot.param_of(spec)
    if param is None:
        return out
    frames: list[dict[str, Any]] = []
    for value in param["values"]:
        frame_svg = plot.render(spec, values={param["name"]: value})
        if frame_svg:
            frames.append({"value": value, "svg": frame_svg})
    # 帧画不出来（表达式根本认不出）时不留半截参数在 DSL 里：前端看到一个
    # 「有滑块、但拖了没反应」的图，比没有滑块更让人摸不着头脑。
    if len(frames) > 1:
        out["frames"] = frames
        out["params"] = param
    return out


def _formula_svg(spec: Mapping[str, Any]) -> str:
    """公式图。`tex` 是那一行 LaTeX，`caption` 是图注（可省）。"""
    tex = str(spec.get("tex") or spec.get("expr") or "").strip()
    if not tex:
        return ""
    return formula.render_page(
        tex,
        # 主图默认按 `PAGE_SIZE` 排（行内那个尺寸在这张画布上太小），
        # 模型真指定了就听它的
        size=float(spec.get("size") or formula.PAGE_SIZE),
        caption=str(spec.get("caption") or ""),
    )
