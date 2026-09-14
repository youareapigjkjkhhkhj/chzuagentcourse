"""IR → HTML（P5 §3 的 `renderHtml`）。

两个产物共用这一个文件，是有意的：

- **离线 HTML**（F5-3）：`document()` 出一个自包含的单文件，双击就能翻页看。
  没有 CDN、没有外链字体、没有外部 JS —— 断网、拷到 U 盘、发微信都照常打开。
- **PDF**（F5-4）：`print_pages()` 出**逐页**的简化 HTML，交给 `pdf.py` 用
  PyMuPDF 排进 PDF。同一套内容、同一套色彩令牌，只有排版约束不同。

为什么 PDF 不直接用 `document()`：那一份是给浏览器看的，用了 flex / grid /
绝对定位，而 MuPDF 的排版器只认 CSS 的一个子集（`.slide` 那种整屏定位它排不出来）。
所以这里分成两条路：**内容同源、排版各表**。想「一份 HTML 两处用」听着省事，
实际会在 PDF 里排出一堆错位，再回头加一堆 `@media print` 特例 —— 更难维护。

HTML 转义只有一处（`esc`），所有外部文本都必须过它：课程内容里出现 `<script>`
时，导出的 HTML 不该在别人机器上执行（P5-F3 的同一条思路，P4-F3 在前端也是这么做的）。

**示意图是这条规矩的唯一例外**：`Block.svg` 要原样内联进文档（转义了就不是图了），
所以把关放在上游 —— `ir._svg_of()` 只收以 `<svg` 开头、且不含脚本的那一段。
"""

from __future__ import annotations

import json
from typing import Callable, Iterable, Sequence

from app.services.exports import svg as svg_export
from app.services.exports import theme as themes
from app.services.exports.ir import Block, Bullet, Deck, Page, RenderOptions
from app.services.generation import formula

__all__ = ["document", "esc", "print_pages", "render_body"]


# --------------------------------------------------------------------------
# 转义与行内标记
# --------------------------------------------------------------------------


def esc(text: str) -> str:
    """HTML 转义。文本里可能有材料原文、用户输入、模型输出 —— 都是不可信来源。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _marked(text: str, emphasis: Sequence[str]) -> str:
    """要点里的强调词加 `<strong>`。

    先转义再包标签：反过来做的话，强调词里一个 `<` 就能把标签撑破。
    强调词是**一段连续的原文**（P1 的约定），所以直接做子串替换是安全的；
    长的先替，免得「梯度」把「梯度下降」切碎。
    """
    out = esc(text)
    for word in sorted((item for item in emphasis if item), key=len, reverse=True):
        needle = esc(word)
        if needle and needle in out:
            out = out.replace(needle, f"<strong>{needle}</strong>", 1)
    return out


def _bullet_html(item: Bullet, *, rasterize: bool) -> str:
    """一条要点。带行内公式时按截来画，否则就是加粗强调那句话。

    两种排法的差别只在「谁来画那个式子」：浏览器那份内联矢量（放大不糊，
    单文件也不变大），MuPDF 那份先栅格化成 `data:` URI（它不认内联 `<svg>`，
    与示意图同一个理由，见 `_image_html`）。图是同一张。
    """
    if not item.pieces:
        return _marked(item.text, item.emphasis)
    parts: list[str] = []
    for piece in item.pieces:
        if piece.kind != "math":
            parts.append(_marked(piece.text, item.emphasis))
            continue
        parts.append(f'<span class="math">{_inline_math(piece.text, rasterize=rasterize)}</span>')
    return "".join(parts)


def _inline_math(tex: str, *, rasterize: bool) -> str:
    """一条行内公式。排不出来时退回 `plain()` 的 Unicode 近似，**不留空洞**。

    字号按正文给（`formula.INLINE_SIZE`）：行内公式比正文略大一点点才不显得缩着，
    但太大了会把一条要点的行高撑开。这个数是排出来看过的，不是拍的。
    **和生成侧共用同一个常量** —— 幻灯片上排多大、导出的 PDF 里就得多大，
    两边各写一个数迟早会对不上。

    栅格化那条路**必须把尺寸写死在 `<img>` 上**：MuPDF 按图片自己的像素摆，
    2 倍栅格化出来的公式在 PDF 里就是正文的两倍大。位图按 2 倍出、框按 1 倍
    给 —— 打印时是 2 倍的实际分辨率，屏幕上又是对的尺寸。
    """
    svg = formula.render(tex, size=formula.INLINE_SIZE)
    if not svg:
        return esc(formula.plain(tex))
    if rasterize:
        width, height, depth = formula.inline_metrics(tex, size=formula.INLINE_SIZE)
        uri = svg_export.to_data_uri(svg)
        if uri and width and height:
            return (
                f'<img class="math__img" src="{uri}" width="{width}" height="{height}" '
                f'style="vertical-align:-{depth}px" alt="{esc(tex)}" />'
            )
        return esc(formula.plain(tex))
    return svg


# --------------------------------------------------------------------------
# 块 → HTML
# --------------------------------------------------------------------------


def _blocks_html(blocks: Iterable[Block], options: RenderOptions, *, rasterize: bool = False) -> str:
    """块列表 → HTML 片段。`kind` 的每一种在这里出现**一次**。

    这是「加一种块型要改哪儿」的答案（F5-1）：三个渲染器各一处，别的地方不用动。

    `rasterize` 只影响示意图（见 `_image_html`）：浏览器那份内联矢量，
    MuPDF 那份走位图。两条路出的图是同一张，差别只在谁去画它。
    """
    parts: list[str] = []
    for block in blocks:
        if block.kind == "heading":
            level = 2 if block.level >= 2 else 1
            parts.append(f"<h{level}>{esc(block.text)}</h{level}>")

        elif block.kind == "paragraph":
            caption = f'<span class="cap">{esc(block.caption)}</span>' if block.caption else ""
            parts.append(f"<p>{caption}{esc(block.text)}</p>")

        elif block.kind == "bullets":
            caption = _caption(block.caption)
            items = "".join(
                f"<li>{_bullet_html(item, rasterize=rasterize)}</li>" for item in block.items
            )
            parts.append(f"{caption}<ul>{items}</ul>")

        elif block.kind == "steps":
            caption = _caption(block.caption)
            items = "".join(
                f"<li>{_bullet_html(item, rasterize=rasterize)}</li>" for item in block.items
            )
            parts.append(f"{caption}<ol>{items}</ol>")

        elif block.kind == "code":
            code = block.code
            lang = f'<span class="lang">{esc(code.lang)}</span>' if code and code.lang else ""
            body = esc(code.content) if code else ""
            parts.append(f'<figure class="code">{lang}<pre><code>{body}</code></pre></figure>')

        elif block.kind == "image":
            parts.append(_image_html(block, rasterize=rasterize))

        elif block.kind == "quote":
            caption = f'<cite>{esc(block.caption)}</cite>' if block.caption else ""
            points = "".join(f"<li>{esc(item.text)}</li>" for item in block.items)
            body = f"<ul class='plain'>{points}</ul>" if points else ""
            parts.append(f'<blockquote><p>{esc(block.text)}</p>{body}{caption}</blockquote>')

        elif block.kind == "quiz":
            parts.append(_quiz_html(block, options))

    return "\n".join(parts)


def _caption(text: str) -> str:
    return f'<span class="cap">{esc(text)}</span>' if text else ""


def _image_html(block: Block, *, rasterize: bool) -> str:
    """示意图：有 SVG 就真画出来，没有才画占位框。

    两条路的差别只在一处 —— **浏览器认内联 `<svg>`，MuPDF 不认**（它的排版器
    只排 `<img>`）。所以离线 HTML 内联矢量（放大不糊、单文件还小），PDF 那份先
    `svg.render_png` 栅格化成 `data:` URI 再放进去。图是同一张，只是一个由浏览器
    画、一个由 PyMuPDF 画。

    没有图（老课程，或这一页的 spec 没画出来）时维持原样：**占位框 + 描述**。
    凭空画一个假示意图才是骗人 —— 读者会以为那是模型画的（P1 §3.2）。
    """
    caption = f"<figcaption>{esc(block.text)}</figcaption>" if block.text else ""
    if block.svg:
        if rasterize:
            uri = svg_export.to_data_uri(block.svg)
            if uri:
                return (
                    f'<figure class="visual"><img class="visual__img" src="{uri}" '
                    f'alt="{esc(block.text)}" />{caption}</figure>'
                )
        else:
            return f'<figure class="visual">{block.svg}{caption}</figure>'
    return f'<figure class="visual"><div class="visual__ph">图示</div>{caption}</figure>'


def _quiz_html(block: Block, options: RenderOptions) -> str:
    quiz = block.quiz
    if not quiz:
        return ""
    options_html = "".join(
        f'<li{" class=correct" if item == quiz.answer else ""}>{esc(item)}</li>'
        for item in quiz.options
    )
    # 「答案」与「解析」是一体的：只报答案等于把测验变成对答案，学生学不到东西。
    answer = ""
    if options.with_quiz:
        answer = (
            '<div class="quiz__answer"><strong>答案</strong> '
            f"{esc(quiz.answer)}"
            + (f"<br /><strong>解析</strong> {esc(quiz.explain)}" if quiz.explain else "")
            + "</div>"
        )
    tag = f'<span class="tag">{esc(quiz.tag)}</span>' if quiz.tag else ""
    return (
        f'<div class="quiz"><div class="quiz__stem">{tag}{esc(quiz.stem)}</div>'
        f'<ol class="quiz__options">{options_html}</ol>{answer}</div>'
    )


def _sources_html(page: Page) -> str:
    if not page.sources:
        return ""
    items = "".join(
        f"<li>{esc(item.label)}{f'：{esc(item.quote)}' if item.quote else ''}</li>"
        for item in page.sources
    )
    return f'<div class="src"><span class="cap">出处</span><ul>{items}</ul></div>'


def _gaps_html(page: Page) -> str:
    if not page.gaps:
        return ""
    items = "".join(f"<li>{esc(item)}</li>" for item in page.gaps)
    return f'<div class="gap"><span class="cap">材料未涉及</span><ul>{items}</ul></div>'


def _board_html(page: Page) -> str:
    if not page.board:
        return ""
    items = "".join(f"<li>{esc(item.desc)}</li>" for item in page.board if item.desc)
    return f'<div class="board"><span class="cap">板书</span><ul>{items}</ul></div>' if items else ""


def _notes_html(page: Page) -> str:
    if not page.notes:
        return ""
    return f'<div class="notes"><span class="cap">讲稿</span><p>{esc(page.notes)}</p></div>'


# --------------------------------------------------------------------------
# 离线 HTML（单文件）
# --------------------------------------------------------------------------


def document(
    deck: Deck,
    options: RenderOptions,
    *,
    generated_at: str = "",
    on_page: Callable[[int, int], None] | None = None,
) -> str:
    """整门课 → 一个自包含的 HTML 文件。

    翻页用**纯 JS**（`show(i)` 切 class），没有框架、没有依赖；讲稿在字幕层里，
    按 `N` 或点按钮展开 —— 上课时它是字幕，备课时它是逐字稿。

    `on_page(已拼完, 共几页)`：这一份拼得极快（纯字符串），回调更多是为了
    让导出任务对三种格式**用同一套报法**，不必为 HTML 单独写一条「秒完」的路径。
    """
    slides = []
    total = len(deck.pages)
    for index, page in enumerate(deck.pages):
        notes = _notes_html(page) if options.with_notes else ""
        slides.append(
            f'''<section class="slide" data-no="{page.page_no}">
  <div class="slide__head">
    <span class="slide__kind">{esc(_KIND_LABELS.get(page.kind, page.kind))}</span>
    <h1>{esc(page.title)}</h1>
    <p class="sub">{esc(page.subtitle)}</p>
  </div>
  <div class="slide__body">
    {_blocks_html(page.blocks, options)}
    {_board_html(page)}
    {_gaps_html(page)}
    {_sources_html(page)}
  </div>
  {notes}
  <footer class="slide__foot">
    <span>{esc(deck.title)}</span>
    <span>{index + 1} / {total}</span>
  </footer>
</section>'''
        )
        if on_page is not None:
            on_page(index + 1, total)

    payload = json.dumps(
        {"watermark": options.watermark, "generatedAt": generated_at},
        ensure_ascii=False,
    )
    theme = themes.get(options.template)
    return (
        _DOCUMENT_TEMPLATE.replace("<!--THEME_VARS-->", _theme_vars(theme))
        .replace("<!--SLIDES-->", "\n".join(slides))
        .replace("<!--META-->", payload)
    )


def render_body(page: Page, options: RenderOptions, *, rasterize: bool = False) -> str:
    """一页的正文（不含页头页脚）—— 也是 HTML 里那一块的内容。"""
    return _blocks_html(page.blocks, options, rasterize=rasterize)


def print_pages(deck: Deck, options: RenderOptions) -> list[str]:
    """逐页的**简化** HTML，专供 MuPDF 排版（`pdf.py`）。

    这里刻意不使用：flex / grid / 绝对定位 / `position: fixed`。
    MuPDF 的排版器只认 CSS 的一个子集，上面那几样要么被忽略、要么把内容挤出页面。
    用最简单的流式结构（标题 + 段落 + 列表 + 引用），换来的是**不会错位**。

    这里也**不写页码与水印** —— 那两样由 `pdf.py` 在排完版之后盖上去。
    写在这里的话，一页课程排出两张纸时它会被复制一遍，而纸页码也就没法算对了。

    示意图走**位图**那条路（`rasterize=True`）：MuPDF 排内联 `<svg>` 是把整段
    当没看见，宁可多花一次栅格化，也不能让 PDF 里少一张图。
    """
    pages: list[str] = []
    for page in deck.pages:
        notes = ""
        if options.with_notes and page.notes:
            notes = f'<p class="notes"><b>讲稿</b> {esc(page.notes)}</p>'
        board = ""
        if page.board:
            items = "".join(f"<li>{esc(item.desc)}</li>" for item in page.board if item.desc)
            board = f'<p class="notes"><b>板书</b></p><ul>{items}</ul>' if items else ""
        gaps = ""
        if page.gaps:
            items = "".join(f"<li>材料未涉及：{esc(item)}</li>" for item in page.gaps)
            gaps = f"<ul class='gap'>{items}</ul>"
        sources = ""
        if page.sources:
            items = "".join(f"<li>{esc(item.label)}</li>" for item in page.sources)
            sources = f"<p class='notes'><b>出处</b></p><ul>{items}</ul>"
        pages.append(
            f'''<h1>{esc(page.title)}</h1>
{_blocks_html(page.blocks, options, rasterize=True)}
{board}
{gaps}
{sources}
{notes}'''
        )
    return pages


#: 页型的中文名。**认不出就显示原样** —— 空着比显示错的好。
_KIND_LABELS = {
    "cover": "封面",
    "outline": "目录",
    "concept": "讲解",
    "figure": "图示",
    "example": "案例",
    "code": "代码",
    "quiz": "测验",
    "summary": "小结",
    "debate": "研讨",
}

_WATERMARK = "AI 生成 · EduAgentX"


def _theme_vars(theme: themes.Theme) -> str:
    """一套主题 → `:root` 里的 CSS 变量声明（填进模板的 `<!--THEME_VARS-->`）。

    颜色与字体都收敛在这里：模板里凡是 `var(--brand)` / `var(--font-sans)` 的地方，
    换主题就跟着变，不必再去 CSS 里逐条改色号。
    """
    return (
        f"--brand:{theme.css(theme.brand)}; --ink:{theme.css(theme.ink)}; "
        f"--muted:{theme.css(theme.muted)}; --line:{theme.css(theme.line)}; "
        f"--warn:{theme.css(theme.warn)}; "
        f"--font-sans:{theme.font_sans}; --font-mono:{theme.font_mono};"
    )


#: 单文件模板。样式只在**一处**定义（`_DOCUMENT_TEMPLATE`），配色与字体走
#: `<!--THEME_VARS-->` 这个占位注入 —— `document()` 按 `options.template` 从
#: `exports/theme.py` 取一套令牌填进去，于是「换个模板」只是换一组 CSS 变量。
_DOCUMENT_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>课程课件</title>
<style>
  :root { <!--THEME_VARS--> }
  * { box-sizing: border-box; }
  body { margin:0; background:#f5f6f8; color:var(--ink);
         font-family:var(--font-sans); }
  .deck { max-width:960px; margin:0 auto; padding:16px; }
  .slide { display:none; background:#fff; border-radius:12px; padding:32px 40px 56px;
           box-shadow:0 2px 12px rgba(0,0,0,.06); position:relative; min-height:540px; }
  .slide.is-on { display:block; }
  .slide__kind { display:inline-block; font-size:12px; color:var(--brand);
                 border:1px solid var(--brand); border-radius:10px; padding:1px 8px; }
  .slide h1 { font-size:28px; margin:12px 0 4px; }
  .slide h2 { font-size:20px; margin:20px 0 8px; }
  .sub { color:var(--muted); margin:0 0 16px; }
  .cap { display:inline-block; font-size:12px; color:var(--muted); margin:12px 0 4px; }
  ul, ol { padding-left:22px; line-height:1.9; }
  ul.plain { list-style:none; padding-left:0; }
  strong { color:var(--brand); }
  pre { background:#0f172a; color:#e2e8f0; padding:14px; border-radius:8px; overflow:auto;
        font-family:var(--font-mono); font-size:13px; }
  .lang { display:inline-block; font-size:12px; color:var(--muted); }
  blockquote { margin:12px 0; padding:8px 16px; border-left:3px solid var(--brand);
               background:#f8fafc; }
  blockquote cite { display:block; color:var(--muted); font-size:12px; font-style:normal; }
  .visual { margin:12px 0; }
  /* 示意图：内联 SVG 与栅格化后的 img 走同一套壳子。SVG 自带 width/height
     属性，不写 height:auto 的话它按 960px 固定宽画，窄屏上会被裁掉。 */
  .visual svg, .visual__img { display:block; width:100%; max-width:100%; height:auto;
                              margin:0 auto; border-radius:8px; }
  .visual figcaption { color:var(--muted); font-size:13px; margin-top:6px; }
  /* 流程图「动起来」：边线做成流动虚线。HTML 是能跑 CSS 的产物，所以这里让它
     动；PPTX / PDF 取静态帧、不带这段 —— 发出去的课件不该自己动。钩子是服务端
     在 SVG 上打的 class="dg-edge"（generation.diagram）。 */
  .visual .dg-edge path { stroke-dasharray:7 5; animation:dg-flow 1.1s linear infinite; }
  @keyframes dg-flow { to { stroke-dashoffset:-12; } }
  @media (prefers-reduced-motion: reduce) {
    .visual .dg-edge path { animation:none; }
  }
  .visual__ph { border:1px dashed var(--line); border-radius:8px; height:120px;
                display:flex; align-items:center; justify-content:center; color:var(--muted); }
  /* 行内公式（要点的 `$…$`）。内联 SVG 自带尺寸与 vertical-align，
     这里只需要别让它换行、别让它被压扁。 */
  .math svg, .math__img { display:inline-block; vertical-align:middle; max-width:none; }
  .quiz { border:1px solid var(--line); border-radius:10px; padding:16px; margin-top:12px; }
  .quiz__stem { font-weight:600; margin-bottom:8px; }
  .quiz__options li.correct { color:var(--brand); font-weight:600; }
  .quiz__answer { margin-top:10px; padding-top:10px; border-top:1px dashed var(--line);
                  color:#374151; }
  .tag { font-size:12px; color:var(--muted); border:1px solid var(--line);
         border-radius:8px; padding:0 6px; margin-right:6px; }
  .src, .gap, .board, .notes { margin-top:18px; font-size:14px; }
  .note, .gap { color:var(--warn); }
  .notes p { margin:6px 0 0; color:#374151; line-height:1.8; }
  .slide__foot { position:absolute; left:40px; right:40px; bottom:16px; display:flex;
                 justify-content:space-between; color:var(--muted); font-size:12px; }
  .bar { position:fixed; left:0; right:0; bottom:0; background:#fff; border-top:1px solid var(--line);
         display:flex; gap:12px; align-items:center; justify-content:center; padding:10px; }
  .bar button { font:inherit; padding:6px 16px; border:1px solid var(--line); border-radius:8px;
                background:#fff; cursor:pointer; }
  .bar button:hover { border-color:var(--brand); color:var(--brand); }
  .bar .pos { color:var(--muted); font-size:13px; min-width:72px; text-align:center; }
  .wm { position:fixed; right:12px; top:12px; color:#9ca3af; font-size:12px; }
  @media print {
    body { background:#fff; }
    .slide { display:block !important; box-shadow:none; page-break-after:always; }
    .bar, .wm { display:none; }
  }
</style>
</head>
<body>
<div class="deck">
<!--SLIDES-->
</div>
<div class="bar">
  <button id="prev" type="button">上一页</button>
  <span class="pos" id="pos"></span>
  <button id="next" type="button">下一页</button>
  <button id="notes" type="button">讲稿</button>
</div>
<script>
var META = <!--META-->;
(function () {
  var slides = Array.prototype.slice.call(document.querySelectorAll('.slide'));
  var notesOn = true;
  var i = 0;
  function paint() {
    slides.forEach(function (el, n) { el.classList.toggle('is-on', n === i); });
    document.getElementById('pos').textContent = (i + 1) + ' / ' + slides.length;
    document.querySelectorAll('.notes').forEach(function (el) {
      el.style.display = notesOn ? '' : 'none';
    });
  }
  function go(step) { i = Math.min(slides.length - 1, Math.max(0, i + step)); paint(); }
  document.getElementById('prev').onclick = function () { go(-1); };
  document.getElementById('next').onclick = function () { go(1); };
  document.getElementById('notes').onclick = function () { notesOn = !notesOn; paint(); };
  document.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') { go(1); e.preventDefault(); }
    if (e.key === 'ArrowLeft' || e.key === 'PageUp') { go(-1); }
    if (e.key === 'n' || e.key === 'N') { notesOn = !notesOn; paint(); }
  });
  if (META.watermark) {
    var wm = document.createElement('div');
    wm.className = 'wm';
    wm.textContent = 'AI 生成 · EduAgentX' + (META.generatedAt ? ' · ' + META.generatedAt : '');
    document.body.appendChild(wm);
  }
  paint();
})();
</script>
</body>
</html>
"""
