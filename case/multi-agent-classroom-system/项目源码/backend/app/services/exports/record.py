"""课堂记录 → Markdown / IR（F5-5）。

课堂记录（F3-11）与课件（F5-2/F5-3/F5-4）是**两种东西**，所以走两条渲染路径：

- 课件是「一页一屏」的，页号、块型、板书计划都是它的骨架 → `from_dsl` → IR。
- 课堂记录是**流水**：一节课下来有几百条字幕、几十条讨论。它没有「页」这个概念，
  硬塞进 IR 的页模型只会得到一堆只有一句话的页。

所以这里另写一份，但**复用 IR 的数据类**（`Deck`/`Page`/`Block`）：
「一节记录 = IR 里的一个 Page」这个映射是贴切的 —— 字幕栏、讨论栏、板书栏
各自是一个可长可短的流，`pdf.py` 排版时会自动接着往下排（一页放不下就续纸）。

Markdown 是**同一份数据的第二种排版**，不是另一条数据路径：`to_markdown` 与
`to_deck` 都只读 `record.build()` 的返回值，谁都不去查第二遍库。堂课记录导出
一次要出两种格式时，两条路算出来的东西必然一致。

### 说话人是谁

`messages.speaker_code` 对 AI 角色是 `agent_roles.code`（`teacher` / `s1`），
对真人是 `user_id`。导出时**必须**把这两个都还原成人名 —— 一份写着
`speaker: s1` 的记录交出去，读的人根本不知道那是谁。`_names()` 一次查完两张表。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.models import AgentRole, User
from app.services.exports.ir import Block, Bullet, Deck, Page

__all__ = ["to_deck", "to_markdown"]


# --------------------------------------------------------------------------
# 名字
# --------------------------------------------------------------------------


def _names(codes: Sequence[str]) -> dict[str, str]:
    """一批 `speaker_code` → 显示名。

    AI 角色与真人共用一个命名空间，所以两张表都查：`agent_roles.code` 命中的
    是老师与 AI 同学，`users.id` 命中的是真人。两边都没命中的**原样显示 code** ——
    显示成「（未知）」会把「这是谁」这个信息彻底丢掉，而 code 至少还能对上号。
    """
    unique = [item for item in dict.fromkeys(str(code or "") for code in codes) if item]
    if not unique:
        return {}

    names = {
        row.code: row.name
        for row in AgentRole.query.filter(AgentRole.code.in_(unique)).all()
        if row.name
    }
    humans = {
        row.id: row.name
        for row in User.query.filter(User.id.in_(unique)).all()
        if row.name
    }
    names.update(humans)
    return names


def _speaker(code: Any, names: Mapping[str, str]) -> str:
    """署名。收 `Any` 是因为它来自 JSON 里的字段 —— 缺了、是 `null`、是数字
    都算「没署名」，而不是让整份记录导不出来。"""
    text = str(code or "")
    return names.get(text) or text or "（未署名）"


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------


def _as_list(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clock(ts: Any) -> str:
    """ISO 时刻 → `HH:MM`。记录是按时间读的，秒与日期在正文里是噪音。

    改不了格式就原样返回：宁可显示一长串，也不要显示一个空字符串。
    """
    text = _text(ts)
    return text[11:16] if len(text) >= 16 and text[10] == "T" else text


def _minutes(ms: int) -> str:
    total = max(0, int(ms or 0)) // 1000
    hours, minutes = divmod(total // 60, 60)
    return f"{hours} 小时 {minutes} 分" if hours else f"{minutes} 分钟"


def _page_label(page_no: Any) -> str:
    number = int(page_no or 0)
    return f"第 {number} 页" if number else "未标页"


# --------------------------------------------------------------------------
# → IR（PDF 用）
# --------------------------------------------------------------------------


def to_deck(record: Mapping[str, Any]) -> Deck:
    """课堂记录 → IR。六个栏目各一「页」，页内是那个栏目的全部内容。

    空栏目**也出一页**，页里写一句「这堂课没有讨论」：一份记录里「没有」
    与「漏导了」是两件事，后者会让读的人以为材料丢了。
    """
    session = _as_mapping(record.get("session"))
    course_title = _text(record.get("courseTitle")) or "（课程已删除）"
    stats = _as_mapping(record.get("stats"))
    participants = _as_list(record.get("participants"))
    subtitles = _as_list(record.get("subtitles"))
    messages = _as_list(record.get("messages"))
    boards = _as_list(record.get("boards"))
    quizzes = _as_list(record.get("quizzes"))

    names = _names(
        [
            # 会话的 ownerId 也要查：它是「主讲」那一行，而不一定在任何一条
            # 发言里出现过（老师可能一句话都没说就下课了）。
            _text(session.get("ownerId")),
            *(_text(item.get("speaker")) for item in messages),
            *(_text(_as_mapping(item).get("speaker")) for item in subtitles),
            *(_text(_as_mapping(item).get("userId")) for item in participants),
        ]
    )

    pages = [
        _cover_page(course_title, session, names),
        _summary_page(stats, participants, names),
        _subtitles_page(subtitles, names),
        _messages_page(messages, names),
        _boards_page(boards),
        _quizzes_page(quizzes),
    ]
    for index, page in enumerate(pages, start=1):
        # 记录没有课程页号，用栏目序号：页码要能回答「这是第几栏」，
        # 而 0 号页在 PDF 页脚里会显示成「第 0 页」。
        pages[index - 1] = _with_no(page, index)

    return Deck(
        title=f"{course_title} · 课堂记录",
        subtitle=_started_label(session),
        topic=course_title,
        audience="",
        duration_min=int(stats.get("durationMs") or 0) // 60000,
        meta={"kind": "record"},
        pages=tuple(pages),
    )


def _with_no(page: Page, number: int) -> Page:
    from dataclasses import replace

    return replace(page, page_no=number)


def _cover_page(course_title: str, session: Mapping[str, Any], names: Mapping[str, str]) -> Page:
    ended = _text(session.get("endedAt"))
    return Page(
        kind="cover",
        title=course_title,
        subtitle="课堂记录",
        blocks=(
            Block(kind="paragraph", caption="上课", text=_started_label(session)),
            Block(kind="paragraph", caption="下课", text=_clock(ended) or "尚未下课"),
            Block(kind="paragraph", caption="主讲", text=_speaker(session.get("ownerId"), names)),
            Block(kind="paragraph", caption="会话", text=_text(session.get("id"))),
        ),
        gaps=() if ended else ("这节课还没有下课，记录是「到此刻为止」的一份投影",),
    )


def _started_label(session: Mapping[str, Any]) -> str:
    """`2026-09-13 10:00` —— 日期要留，因为记录会被存档到别的日子再看。"""
    started = _text(session.get("startedAt"))
    if len(started) >= 16 and started[10] == "T":
        return f"{started[:10]} {started[11:16]}"
    return started


def _summary_page(
    stats: Mapping[str, Any], participants: list, names: Mapping[str, str]
) -> Page:
    items = [
        Bullet(f"发言 {int(stats.get('messages') or 0)} 条"),
        Bullet(f"字幕 {int(stats.get('subtitles') or 0)} 条"),
        Bullet(
            f"板书 {int(stats.get('boardPages') or 0)} 页、"
            f"{int(stats.get('strokes') or 0)} 笔"
        ),
        Bullet(
            f"随堂作答 {int(stats.get('quizAttempts') or 0)} 次，"
            f"其中答对 {int(stats.get('quizCorrect') or 0)} 次"
        ),
        Bullet(f"用时 {_minutes(int(stats.get('durationMs') or 0))}"),
    ]
    roster = "、".join(
        _speaker(_as_mapping(item).get("userId"), names) for item in participants
    )
    blocks = [Block(kind="bullets", items=tuple(items))]
    if roster:
        blocks.append(Block(kind="heading", level=2, text="参与的人"))
        blocks.append(Block(kind="paragraph", text=roster))
    return Page(kind="summary", title="课堂概览", blocks=tuple(blocks))


def _subtitles_page(subtitles: list, names: Mapping[str, str]) -> Page:
    """字幕全文（P3-A1）。按课程页分组，页内保持原始先后。"""
    if not subtitles:
        return _empty_page("字幕全文", "这堂课没有字幕 —— 讲稿没有走语音合成，或课还没开始。")

    blocks: list[Block] = []
    current = None
    for item in subtitles:
        page_no = int(_as_mapping(item).get("pageNo") or 0)
        if page_no != current:
            current = page_no
            blocks.append(Block(kind="heading", level=2, text=_page_label(page_no)))
        blocks.append(
            Block(
                kind="paragraph",
                caption=f"{_speaker(_as_mapping(item).get('speaker'), names)}"
                f"　{_clock(_as_mapping(item).get('ts'))}".strip(),
                text=_text(_as_mapping(item).get("text")),
            )
        )
    return Page(kind="concept", title="字幕全文", blocks=tuple(blocks))


def _messages_page(messages: list, names: Mapping[str, str]) -> Page:
    """讨论区。**不含字幕** —— 字幕在上面那一栏已经全文登过一遍了。

    判据与 `record.subtitles_of` 一致（有没有 `beatId`）：两处用同一条线，
    一份记录里同一条发言才不会既算字幕又算讨论。
    """
    discussion = [item for item in messages if not _text(_as_mapping(item).get("beatId"))]
    if not discussion:
        return _empty_page("讨论区", "这堂课没有讨论区发言。")

    blocks: list[Block] = []
    for item in discussion:
        row = _as_mapping(item)
        quote = _text(row.get("quoteMsgId"))
        caption = f"{_speaker(row.get('speaker'), names)}　{_clock(row.get('ts'))}".strip()
        text = _text(row.get("text"))
        if quote:
            # 引用的那一条正文在别处，这里只标「这是回复」——
            # 把 id 拼进正文会让人以为那是发言内容。
            text = f"（回复 {quote}）{text}"
        blocks.append(Block(kind="paragraph", caption=caption, text=text))
    return Page(kind="debate", title="讨论区", blocks=tuple(blocks))


def _boards_page(boards: list) -> Page:
    if not boards:
        return _empty_page("板书", "这堂课没有板书。")

    blocks: list[Block] = []
    for item in boards:
        row = _as_mapping(item)
        strokes = _as_list(row.get("strokes"))
        blocks.append(
            Block(kind="heading", level=2, text=f"{_page_label(row.get('pageNo'))}（{len(strokes)} 笔）")
        )
        items = []
        for stroke in strokes:
            detail = _as_mapping(stroke)
            desc = _text(detail.get("text")) or _text(detail.get("tool"))
            if detail.get("color"):
                desc = f"{desc}　{_text(detail.get('color'))}"
            if desc:
                items.append(Bullet(desc))
        if items:
            blocks.append(Block(kind="bullets", items=tuple(items)))
    return Page(kind="figure", title="板书", blocks=tuple(blocks))


def _quizzes_page(quizzes: list) -> Page:
    if not quizzes:
        return _empty_page("随堂作答", "这堂课没有随堂作答记录。")

    blocks: list[Block] = []
    current = None
    for item in quizzes:
        row = _as_mapping(item)
        page_no = int(row.get("pageNo") or 0)
        if page_no != current:
            current = page_no
            blocks.append(Block(kind="heading", level=2, text=_page_label(page_no)))
        mark = "答对" if row.get("correct") else "答错"
        ms = int(row.get("responseMs") or 0)
        spend = f"，用时 {ms / 1000:.1f} 秒" if ms else ""
        blocks.append(
            Block(
                kind="paragraph",
                caption=f"{mark}　{_clock(_text(row.get('ts')))}",
                text=f"{_text(row.get('option'))}{spend}",
            )
        )
    return Page(kind="quiz", title="随堂作答", blocks=tuple(blocks))


def _empty_page(title: str, note: str) -> Page:
    return Page(kind="summary", title=title, blocks=(Block(kind="paragraph", text=note),))


# --------------------------------------------------------------------------
# → Markdown
# --------------------------------------------------------------------------


def to_markdown(record: Mapping[str, Any]) -> str:
    """课堂记录 → 一份 Markdown。

    为什么是 Markdown 而不是直接 PDF：老师要的是**能改、能复制、能贴进教研文档**
    的那一份。MD 是纯文本，任何编辑器都打得开，转 Word / 公众号也不用我们操心。
    PDF 那份（`to_deck` + `pdf.render`）是给「打印出来归档」用的。

    用 IR 的页序写，不另排一遍 —— 两种产物栏目顺序一致，读的人换个格式不用重找。
    """
    deck = to_deck(record)
    lines: list[str] = [f"# {deck.title}", ""]
    if deck.subtitle:
        lines += [f"> {deck.subtitle}", ""]

    for page in deck.pages:
        # 栏目名是 `Page.title`，不是块 —— 三种渲染器都从那儿取。
        # 漏掉它，Markdown 里就只剩一条条流水，读的人不知道哪几行是字幕、
        # 哪几行是讨论。
        if page.title:
            lines += ["", f"## {page.title}"]
        for block in page.blocks:
            lines.extend(_markdown_of(block))
        if page.gaps:
            lines.append("")
            for gap in page.gaps:
                lines.append(f"> {gap}")
        lines.append("")

    lines += [
        "---",
        "",
        "本记录由 EduAgentX 自动导出，内容来自课堂上的实际发言与作答。",
        "",
    ]
    return "\n".join(lines)


def _markdown_of(block: Block) -> list[str]:
    """一个内容块 → Markdown 行。

    只认记录里真会出现的四种块型（heading / paragraph / bullets / quiz）。
    别的一律降级成正文 —— 导出是最后一公里，一个不认识的块型该少画一行，
    而不是让整份记录导不出来。
    """
    if block.kind == "heading":
        # 文档标题占掉 `#`，所以正文里的一级小标题从 `##` 起 —— 否则「课堂概览」
        # 会和这份记录的标题一样大，读的人分不清哪句是标题哪句是栏目。
        return ["", f"{'###' if block.level >= 2 else '##'} {block.text}", ""]

    if block.kind == "bullets":
        return [f"- {item.text}" for item in block.items]

    if block.kind == "quiz" and block.quiz is not None:
        lines = [f"**{block.quiz.stem}**"]
        lines += [f"- {item}" for item in block.quiz.options]
        if block.quiz.answer:
            lines.append(f"  答案：{block.quiz.answer}")
        return lines

    text = block.text
    if not text:
        return []
    # 有署名就**并成一行**（`**沈老师 10:00**：大家好……`）。记录里绝大多数
    # 段落都是「某人某时说了某话」，拆成三行会把一份 200 行的记录撑成 600 行，
    # 而它是要被通读的。
    if block.caption:
        return ["", f"**{block.caption}**：{text}"]
    return ["", text]
