"""导出主题（PPT 模板）。

一份「模板」= 一组配色与字体令牌。三个渲染器过去各自把品牌色写死成常量
（PPTX 的 `_BRAND = 0052D9`、HTML 的 `--brand:#0052d9`、PDF 的 `h1{color:#0052d9}`），
换一套风格要改三处、还容易漏掉一处。这里把它们收敛成**一份数据**：渲染器只问
`get(key)` 要一套令牌，再各自决定怎么落到 PPTX 的 `RGBColor` / HTML 的 CSS 变量 /
PDF 的样式表上。

**只换颜色与字体，不动版式**：字号、栏宽、页边距这些几何量留在各渲染器里 ——
它们是「排得下、读得清」调出来的结果，不随风格变。模板因此是一份**纯数据**，
不跑任何脚本（这与「导入一个可执行 skill」是两回事：那种要跑别人的引擎，
这种只是给自家渲染器换一套色号）。

内置三套：

- `default` 品牌蓝 —— 现状，也是**向后兼容的退路**：老导出记录的 `options_json`
  里没有 `template` 这一项，`get()` 认不出就退回它，于是「加模板」不会让任何一份
  历史产物在重导时悄悄变了样子。
- `swiss`   瑞士国际主义 —— 黑白 + 正红、Arial，网格感、无衬线。
- `tech`    科技青 —— 深墨 + 青蓝强调，现代无衬线。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DEFAULT_KEY", "Theme", "catalogue", "get"]


@dataclass(frozen=True)
class Theme:
    """一套导出配色与字体。

    颜色是 6 位十六进制、**不带 `#`** —— PPTX 的 `RGBColor.from_string` 直接吃
    这个格式，HTML / PDF 那边用 `css()` 补一个 `#` 即可。字体分两份：PPTX 要的是
    单一字体名（写进 `<a:latin>`/`<a:ea>`），HTML / PDF 要的是一整条 CSS 字体栈
    （带兜底），两边各取所需。
    """

    key: str
    name: str  #: 给前端选择器显示的中文名
    brand: str  #: 强调色：标题、strong、引用条、选中项
    ink: str  #: 正文主色
    muted: str  #: 次要文字：副标题、页脚、图注
    warn: str  #: 提醒色：测验答案、材料缺口
    line: str  #: 分隔线、边框、水印
    font_family: str  #: PPTX 用的单一无衬线字体名（写进 `<a:latin>`/`<a:ea>`）
    font_mono_family: str  #: PPTX 用的单一等宽字体名
    font_sans: str  #: HTML / PDF 用的 CSS 无衬线字体栈（带兜底）
    font_mono: str  #: HTML / PDF 用的 CSS 等宽字体栈

    def css(self, color: str) -> str:
        """`0052D9` → `#0052d9`（CSS 里用小写带井号）。"""
        return f"#{color.lower()}"


#: 缺省模板的 key。`get()` 认不出名字时退回它（见模块 docstring 的向后兼容那条）。
DEFAULT_KEY = "default"

_DEFAULT = Theme(
    key="default",
    name="品牌蓝（默认）",
    brand="0052D9",
    ink="181818",
    muted="6B7280",
    warn="92400E",
    line="E7E7E7",
    font_family="Microsoft YaHei",
    font_mono_family="Consolas",
    font_sans='"PingFang SC","Microsoft YaHei","Source Han Sans SC",system-ui,sans-serif',
    font_mono='Consolas,"Courier New",monospace',
)

_SWISS = Theme(
    key="swiss",
    name="瑞士黑白红",
    brand="E30613",
    ink="1A1A1A",
    muted="999999",
    warn="92400E",
    line="DDDDDD",
    font_family="Arial",
    font_mono_family="Courier New",
    font_sans='Arial,"Helvetica Neue",Helvetica,sans-serif',
    font_mono='"Courier New",monospace',
)

_TECH = Theme(
    key="tech",
    name="科技青",
    brand="0E7490",
    ink="0F172A",
    muted="64748B",
    warn="B45309",
    line="E2E8F0",
    font_family="Microsoft YaHei",
    font_mono_family="Consolas",
    font_sans='"Segoe UI","PingFang SC","Microsoft YaHei",system-ui,sans-serif',
    font_mono='Consolas,"Courier New",monospace',
)

#: 注册表。**插入顺序就是前端选择器里的顺序**（缺省排在最前）。
THEMES: dict[str, Theme] = {item.key: item for item in (_DEFAULT, _SWISS, _TECH)}


def get(key: str) -> Theme:
    """按 key 取一套主题。

    认不出的（空串、`None`、老记录里没有这一项、前端传了个陌生名字）一律退回
    缺省 —— 渲染不该因为一个陌生的模板名而失败，那是把「选错模板」变成「导不出」。
    校验陌生名字是接口层的事（`queue._clean_options` 会当场 40001），这里只兜底。
    """
    return THEMES.get(str(key or "").strip(), THEMES[DEFAULT_KEY])


def catalogue() -> list[dict[str, str]]:
    """给前端选择器的清单：`[{key, name}]`，按注册顺序。"""
    return [{"key": item.key, "name": item.name} for item in THEMES.values()]
