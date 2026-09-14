"""导出中间表示（P5 §3 的 IR）。

**三种渲染器谁也不认识课程 DSL** —— PPTX / HTML / PDF 都只吃这里的数据结构。
DSL 换个字段名、加一种页型，改的是 `from_dsl()` 这一个函数，不是三个渲染器；
反过来，加一种**产物**（将来的 Word、视频）也只是多一个吃 IR 的渲染器。
这就是 F5-1 说的那条解耦线。

IR 只描述**内容与结构**，不含样式：字号、配色、页边距都是各渲染器自己的事。
它保证的是「三种产物讲的是同一件事」，不是「三种产物长得一样」——
PPTX 是给人改的、HTML 是给人看的、PDF 是给人打印的，追求像素一致是错的努力方向。

这里是**纯函数**：进的是字典（DSL 的 `json` 形态），出的是冻结的 dataclass。
没有 DB、没有 Flask 请求上下文 —— 于是它能在任何地方被单独测（P5 §3 的 IR 设计要点）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from app.services.generation import formula

__all__ = [
    "Beat",
    "Block",
    "BoardAction",
    "Bullet",
    "ChapterRef",
    "Code",
    "Deck",
    "Page",
    "Piece",
    "Quiz",
    "RenderOptions",
    "Source",
    "from_dsl",
    "notes_text",
]

# --------------------------------------------------------------------------
# 内容块
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Piece:
    """要点里的一截。`text` 是普通文字，`math` 是行内公式（**LaTeX 原文**）。

    IR 只切不画：给的是式子的写法，怎么画是渲染器的事 —— 网页与 PDF 排成
    真的式子，PPTX 只能排成 `plain()` 那种 Unicode 近似（PPT 的文本框里放不进
    矢量图）。同一句话在三种产物里**读出来**是一样的，长得不一样是有意的。
    """

    kind: str = "text"  # text | math
    text: str = ""


@dataclass(frozen=True)
class Bullet:
    """一条要点。`emphasis` 是要强调的词，渲染器自己决定怎么突出（加粗 / 变色）。

    `text` 是**原文**（可能带 `$…$`），`pieces` 是切好的那几截 —— 原文留着，
    是因为不认识 `pieces` 的渲染器（以及将来加的那个）至少还能把整句话显示出来。
    """

    text: str = ""
    emphasis: tuple[str, ...] = ()
    pieces: tuple[Piece, ...] = ()

    def __post_init__(self) -> None:
        """切行内公式。在这里切一次，比让每个构造点自己切一遍可靠 ——
        要点在 `_blocks_for` 里有七八个来路，漏一个就是「这页的公式没排出来」。"""
        if not self.pieces and "$" in self.text:
            object.__setattr__(self, "pieces", tuple(_pieces_of(self.text)))


@dataclass(frozen=True)
class Code:
    """一段代码。`lang` 只是标签 —— 三种渲染器都不做语法高亮着色（离线 PDF 与
    PPTX 里没有可用的高亮器，HTML 里要内联一份高亮库，为一个代码页背一整个
    依赖不划算）。等宽字体 + 原样缩进足够看清。"""

    lang: str = ""
    content: str = ""


@dataclass(frozen=True)
class Quiz:
    """随堂测验。`answer` 与 `options` 里的某一项**逐字相同**（P1 的硬约束）。"""

    stem: str = ""
    options: tuple[str, ...] = ()
    answer: str = ""
    explain: str = ""
    tag: str = ""


@dataclass(frozen=True)
class Block:
    """一段内容。`kind` 决定渲染器怎么画它，参数落在其余字段里。

    这是一条**有意的窄接口**：加一种块型要动的是三个渲染器各一个分支，
    而不是让每个渲染器都去读一遍 DSL。`kind` 的取值与用法：

    | kind | 用到的字段 | 画成什么 |
    |------|-----------|---------|
    | `heading`   | `text`, `level` | 标题（level 1/2） |
    | `paragraph` | `text`          | 一段正文 |
    | `bullets`   | `items`         | 要点列表 |
    | `steps`     | `items`         | 有序步骤（案例页的「步骤」） |
    | `code`      | `code`, `caption` | 代码块 + 逐行讲解 |
    | `quiz`      | `quiz`          | 题干 + 选项 + 答案与解析 |
    | `image`     | `caption`, `text`, `svg` | 示意图（有 `svg` 就画图，没有就画占位框） |
    | `quote`     | `text`, `caption` | 引文（研讨页的立场、材料原文） |
    """

    kind: str
    text: str = ""
    level: int = 1
    items: tuple[Bullet, ...] = ()
    steps: tuple[str, ...] = ()
    code: Code | None = None
    quiz: Quiz | None = None
    caption: str = ""
    #: 示意图的 SVG 源码（生成时由 `generation.diagram` 画好、随 DSL 落库）。
    #: 空串 = 没有图，只剩描述 —— 渲染器这时画占位框，不假装有图。
    svg: str = ""


# --------------------------------------------------------------------------
# 页与册
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Beat:
    """讲稿的一句。`est_sec` 由服务端算（P1 的 `normalize_beats`）。"""

    beat_id: str = ""
    text: str = ""
    est_sec: int = 0


@dataclass(frozen=True)
class Source:
    """一条出处（P4）。`label` 是**给人看的**那一行（「机器学习讲义.md 第 3 页」），
    由调用方组装 —— IR 不查库，也就不该知道材料的展示名长什么样。"""

    label: str = ""
    quote: str = ""


@dataclass(frozen=True)
class BoardAction:
    """白板上的一个动作（P1 的 `boardPlan`）。P5 的 PDF 讲义把它印成「板书」一栏。"""

    tool: str = ""
    desc: str = ""
    at_beat: str = ""


@dataclass(frozen=True)
class Page:
    """IR 的一页 —— 与课程的一页一一对应（页号也照搬）。

    `blocks` 是**渲染器唯一要画的东西**；`narration` / `sources` / `board` / `gaps`
    是三条旁路：讲稿进备注页、出处印在页脚、缺口如实标出来。
    """

    page_no: int = 0
    chapter_no: int = 0
    kind: str = ""
    title: str = ""
    subtitle: str = ""
    blocks: tuple[Block, ...] = ()
    narration: tuple[Beat, ...] = ()
    sources: tuple[Source, ...] = ()
    gaps: tuple[str, ...] = ()
    board: tuple[BoardAction, ...] = ()

    @property
    def notes(self) -> str:
        """讲稿全文（PPTX 的备注页、PDF 的右栏、HTML 的字幕层都用它）。"""
        return notes_text(self.narration)


def notes_text(beats: Sequence[Beat]) -> str:
    """把讲稿的 beat 拼成一段。beat 是**一句话**，所以是句号级联，不加换行 ——
    换行会让 PPTX 的备注页在每句话后空一行，念起来像断气。"""
    return "".join(beat.text for beat in beats if beat.text)


@dataclass(frozen=True)
class ChapterRef:
    """章。`page_nos` 是这一章覆盖的页号（用于 PPTX 的分节与 PDF 的目录）。"""

    no: int = 0
    title: str = ""
    summary: str = ""
    page_nos: tuple[int, ...] = ()


@dataclass(frozen=True)
class Deck:
    """一门课的导出单元：元信息 + 章 + 页。"""

    title: str = ""
    subtitle: str = ""
    topic: str = ""
    audience: str = ""
    duration_min: int = 0
    lecturer: str = ""
    chapters: tuple[ChapterRef, ...] = ()
    pages: tuple[Page, ...] = ()
    meta: Mapping[str, Any] = field(default_factory=dict)

    def page(self, page_no: int) -> Page | None:
        for item in self.pages:
            if item.page_no == page_no:
                return item
        return None


@dataclass(frozen=True)
class RenderOptions:
    """渲染选项（§4.1 的 `options`）。

    - `watermark`：产物带「AI 生成」水印（P5 的合规项，默认开）。
    - `with_notes`：带讲稿。PPTX 落备注页、PDF 加右侧栏、HTML 显示字幕层。
    - `with_quiz`：带测验与答案解析。
    - `template`：用哪套导出主题（`exports/theme.py` 的 key）。存的是**名字**
      而不是 `Theme` 对象 —— 这一份要原样落进 `options_json` 留档，得是可序列化的
      字符串；渲染器各自 `theme.get(options.template)` 取回那一套令牌。
    """

    watermark: bool = True
    with_notes: bool = True
    with_quiz: bool = True
    template: str = "default"


# --------------------------------------------------------------------------
# DSL → IR
# --------------------------------------------------------------------------


def from_dsl(
    dsl: Mapping[str, Any],
    *,
    sources_by_page: Mapping[int, Sequence[Source]] | None = None,
) -> Deck:
    """课程 DSL → IR。

    `sources_by_page` 是**旁路**：DSL 里的 `sources` 只有 `chunkId` 与 `quote`，
    而人要看的是「《机器学习讲义》第 3 页」—— 展示名与页码在库里，得由调用方
    查好再传进来（IR 不碰 DB）。库里没有这条引用时退化成只显示引文。

    坏数据不抛异常：导出是**只读的最后一公里**，一个字段缺失该让这一页少画一块，
    而不是让整门课导不出来（P1 的 DSL 校验在前面的环节已经做过一遍了）。
    """
    pages_raw = _as_list(dsl.get("pages"))
    chapters_raw = _as_list(dsl.get("chapters"))
    meta = _as_mapping(dsl.get("meta"))
    cover = _as_mapping(meta.get("cover"))

    pages = tuple(
        _page_from_dsl(
            _as_mapping(item),
            (sources_by_page or {}).get(_as_int(_as_mapping(item).get("pageNo"))),
        )
        for item in pages_raw
    )

    return Deck(
        title=_text(meta.get("title")) or _text(cover.get("title")),
        subtitle=_text(meta.get("subtitle")) or _text(cover.get("subtitle")),
        topic=_text(meta.get("topic")),
        audience=_text(meta.get("audience")) or _text(cover.get("audience")),
        duration_min=_as_int(meta.get("durationMin")) or _as_int(cover.get("durationMin")),
        lecturer=_text(cover.get("lecturer")),
        chapters=tuple(_chapter_from_dsl(_as_mapping(item)) for item in chapters_raw),
        pages=pages,
        meta=dict(meta),
    )


def _chapter_from_dsl(raw: Mapping[str, Any]) -> ChapterRef:
    return ChapterRef(
        no=_as_int(raw.get("no")),
        title=_text(raw.get("title")),
        summary=_text(raw.get("summary")),
        page_nos=tuple(_as_int(item) for item in _as_list(raw.get("pages"))),
    )


def _page_from_dsl(raw: Mapping[str, Any], sources: Sequence[Source] | None) -> Page:
    kind = _text(raw.get("kind"))
    quiz = _quiz_from_dsl(_as_mapping(raw.get("quiz"))) if raw.get("quiz") else None
    return Page(
        page_no=_as_int(raw.get("pageNo")),
        chapter_no=_as_int(raw.get("chapterNo")),
        kind=kind,
        title=_text(raw.get("title")),
        subtitle=_text(raw.get("subtitle")),
        blocks=_blocks_for(kind, raw, quiz),
        narration=tuple(
            Beat(
                beat_id=_text(_as_mapping(item).get("beatId")),
                text=_text(_as_mapping(item).get("text")),
                est_sec=_as_int(_as_mapping(item).get("estSec")),
            )
            for item in _as_list(raw.get("narration"))
        ),
        sources=tuple(sources or ()) or _sources_from_dsl(raw),
        gaps=tuple(_text(item) for item in _as_list(raw.get("gaps")) if _text(item)),
        board=tuple(
            BoardAction(
                tool=_text(_as_mapping(item).get("tool")),
                desc=_text(_as_mapping(item).get("desc")),
                at_beat=_text(_as_mapping(item).get("atBeat")),
            )
            for item in _as_list(raw.get("boardPlan"))
        ),
    )


def _blocks_for(  # noqa: PLR0912, PLR0915 —— 九种页型的分派，拆开反而看不出全貌
    kind: str, raw: Mapping[str, Any], quiz: Quiz | None
) -> tuple[Block, ...]:
    """按页型摆块。**每种页型只在这里出现一次** —— 这里是「加一种页型要改哪儿」
    的答案。

    认不出的页型不返回空：退回「标题 + 要点 + 讲稿」，宁可版式不像也不能把
    内容吃掉（将来的 `kind` 一定是先在 DSL 里出现、后在这里补上的）。
    """
    blocks: list[Block] = []
    bullets = tuple(
        Bullet(text=_text(_as_mapping(item).get("text")), emphasis=_emphasis(item))
        for item in _as_list(raw.get("bullets"))
    )
    visual = _as_mapping(raw.get("visual"))

    if kind == "cover":
        cover = _as_mapping(_as_mapping(raw.get("meta")))
        line = _join_meta(cover)
        if line:
            blocks.append(Block(kind="paragraph", text=line))
        elif bullets:
            blocks.append(Block(kind="bullets", items=bullets))

    elif kind == "outline":
        chapters = tuple(
            Bullet(text=f"{_as_int(_as_mapping(item).get('no'))}. {_text(_as_mapping(item).get('title'))}")
            for item in _as_list(raw.get("chapters"))
            if _text(_as_mapping(item).get("title"))
        )
        blocks.append(Block(kind="bullets", items=chapters or bullets, caption="本章目录"))

    elif kind == "code":
        code = _as_mapping(raw.get("code"))
        blocks.append(
            Block(
                kind="code",
                code=Code(lang=_text(code.get("lang")), content=_text(code.get("content"))),
            )
        )
        explain = tuple(_text(item) for item in _as_list(raw.get("explanation")) if _text(item))
        if explain:
            blocks.append(
                Block(
                    kind="steps",
                    items=tuple(Bullet(text=item) for item in explain),
                    caption="逐行讲解",
                )
            )
        if bullets:
            blocks.append(Block(kind="bullets", items=bullets))

    elif kind == "quiz":
        if quiz:
            blocks.append(Block(kind="quiz", quiz=quiz))

    elif kind == "debate":
        topic = _text(raw.get("topic"))
        if topic:
            blocks.append(Block(kind="heading", text=topic, level=2))
        for item in _as_list(raw.get("sides")):
            side = _as_mapping(item)
            points = tuple(
                Bullet(text=_text(point)) for point in _as_list(side.get("points")) if _text(point)
            )
            blocks.append(
                Block(kind="quote", text=_text(side.get("stance")), caption="", items=points)
            )
        summary = _text(raw.get("arbiterSummary"))
        if summary:
            blocks.append(Block(kind="paragraph", text=summary, caption="小结"))
        if bullets:
            blocks.append(Block(kind="bullets", items=bullets))

    elif kind == "summary":
        if bullets:
            blocks.append(Block(kind="bullets", items=bullets, caption="要点回顾"))
        question = _text(raw.get("question"))
        if question:
            blocks.append(Block(kind="paragraph", text=question, caption="思考题"))

    elif kind == "figure":
        if _text(visual.get("desc")):
            blocks.append(Block(kind="image", text=_text(visual.get("desc")), svg=_svg_of(visual)))
        if bullets:
            blocks.append(Block(kind="bullets", items=bullets))

    elif kind == "example":
        steps = tuple(_text(item) for item in _as_list(raw.get("steps")) if _text(item))
        if steps:
            blocks.append(Block(kind="steps", items=tuple(Bullet(text=item) for item in steps)))
        if _text(visual.get("desc")):
            # 案例页的 `visual` 也是示意图（「邮件 → 特征 → 模型」那种流程），
            # 与 concept / figure 同一个待遇。不画它的话，工作台预览里有图、
            # 导出的课件里没有 —— 同一门课两个样子。
            blocks.append(Block(kind="image", text=_text(visual.get("desc")), svg=_svg_of(visual)))
        if bullets:
            blocks.append(Block(kind="bullets", items=bullets))
        explain = tuple(_text(item) for item in _as_list(raw.get("explanation")) if _text(item))
        if explain:
            blocks.append(Block(kind="paragraph", text=" ".join(explain)))

    else:  # concept 与认不出的页型
        if bullets:
            blocks.append(Block(kind="bullets", items=bullets))
        if _text(visual.get("desc")):
            blocks.append(Block(kind="image", text=_text(visual.get("desc")), svg=_svg_of(visual)))
        if not bullets and not _text(visual.get("desc")):
            narration = notes_text(
                tuple(Beat(text=_text(_as_mapping(item).get("text"))) for item in _as_list(raw.get("narration")))
            )
            if narration:
                blocks.append(Block(kind="paragraph", text=narration))

    return tuple(blocks)


def _quiz_from_dsl(raw: Mapping[str, Any]) -> Quiz:
    return Quiz(
        stem=_text(raw.get("stem")),
        options=tuple(_text(item) for item in _as_list(raw.get("options"))),
        answer=_text(raw.get("answer")),
        explain=_text(raw.get("explain")),
        tag=_text(raw.get("conceptTag")),
    )


def _sources_from_dsl(raw: Mapping[str, Any]) -> tuple[Source, ...]:
    """库里没给展示名时的退路：只有 chunkId 与引文。

    显示 `chunkId` 是**有意**的 —— 它至少指得回一个真实存在的分块；编一个
    「出处：第 12 页」出来才是错的。
    """
    return tuple(
        Source(label=_text(_as_mapping(item).get("chunkId")), quote=_text(_as_mapping(item).get("quote")))
        for item in _as_list(raw.get("sources"))
    )


def _pieces_of(text: str) -> list[Piece]:
    """一句话切成「文字 / 公式」几截。切法只有一处（`formula.split`）——
    这里只把它的结果换成 IR 的 `Piece`，不另立一份判据。"""
    return [
        Piece(kind="math" if chunk.math else "text", text=chunk.text)
        for chunk in formula.split(text)
    ]


def _emphasis(raw: Any) -> tuple[str, ...]:
    return tuple(_text(item) for item in _as_list(_as_mapping(raw).get("emphasis")) if _text(item))


def _svg_of(visual: Mapping[str, Any]) -> str:
    """DSL 里那一段 SVG，两道关：以 `<svg` 开头，且不含脚本。

    渲染器要把这段字符串**原样内联**进离线 HTML，所以它得按不可信输入处理
    （P5-F3）—— DSL 是模型产出的，而页面编辑接口也能改它。真出图的是
    `generation.diagram`，它不会产生下面这些花样；会出现的只可能是别人塞的。
    """
    svg = _text(visual.get("svg"))
    if not svg.startswith("<svg") or _SVG_UNSAFE.search(svg):
        return ""
    return svg


#: 内联 SVG 里不该出现的东西：脚本、事件属性、能装 HTML 的外来对象，
#: 以及 `javascript:` 这种 href。
_SVG_UNSAFE = re.compile(r"<\s*(script|foreignObject|iframe)\b|\son[a-z]+\s*=|javascript:", re.IGNORECASE)


def _join_meta(cover: Mapping[str, Any]) -> str:
    parts = []
    if _text(cover.get("lecturer")):
        parts.append(f"主讲：{_text(cover.get('lecturer'))}")
    if _as_int(cover.get("durationMin")):
        parts.append(f"时长：{_as_int(cover.get('durationMin'))} 分钟")
    if _text(cover.get("audience")):
        parts.append(f"对象：{_text(cover.get('audience'))}")
    return " · ".join(parts)


# --- 取值小工具：DSL 是 JSON，什么都可能是 null / 空串 / 串了类型的数 ---


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
