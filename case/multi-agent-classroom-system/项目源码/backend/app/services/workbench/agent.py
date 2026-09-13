"""对话 Agent 的一轮（F4-10 / P4-A9、P4-A10）。

一轮是怎么走的：

    send()          落用户消息 → 开频道 → 丢给后台线程 → 立即返回 assistant 的 messageId
    run_turn()      [后台] 组上下文 → 一次 call_json 出计划 → 按句推 agent.delta
                    → 逐条执行 Skill（推 agent.skill / agent.skill_done / page.rewritten）
                    → 把结果写回那条 assistant 消息 → 推 agent.done

几个刻意的取舍：

- **先出计划、再执行**，而不是「模型边想边调工具」。一次结构化调用拿到
  `{reply, actions[]}`，好处是：回复的话在执行之前就完整了，前端的操作卡
  与文字能对得上；而且执行阶段**不再需要模型**（除了技能内部自己的调用），
  中途断线不会留下「改了一半、话没说完」的状态。
- **assistant 消息先建后填**。`POST /chat` 必须立刻返回一个 `messageId` ——
  `agent.delta` 的每一帧都带着它，前端拿它把流式的字接到正确的气泡上。
  代价是进程被打断时会留下一条空回复；那比「前端收到一堆没有归属的帧」好。
- **技能失败不中断这一轮**。第 2 个技能失败，第 3 个照跑，最后在回复里说明 ——
  「改大纲失败了，所以这一轮什么都没做」比「另一个能做的事也没做」更糟。
"""

from __future__ import annotations

import time
from typing import Any, Mapping, Sequence

from app.common.errors import AppError
from app.common.logging import get_logger
from app.extensions import db
from app.models import ChatMessage, SkillInvocation
from app.services.courses import store
from app.services.generation.llm import call_json
from app.services.generation.schema import load_json
from app.services.materials import citations
from app.services.workbench import REF_TYPE_CHAT, chat, skills
from app.services.workbench import stream as stream_mod

logger = get_logger("app.workbench.agent")

#: 一轮最多执行几个技能。模型偶尔会把一件事拆成七八步，而每一步都是一次
#: 分钟级的模型调用 —— 用户等的是「把这一页改一下」，不是一次批量重构。
MAX_ACTIONS = 4

#: 回复里的分句上限（流式帧数）。详见 `_stream_reply`。
MAX_DELTA_FRAMES = 24

#: 每帧之间停一下。见 `_stream_reply` 的说明。
DELTA_PAUSE_SEC = 0.03

#: 课程现状里最多列几页。工作台里的话经常指代页号，所以页列表要给全；
#: 但一门课 40 页的清单本身就是一大段提示词，超过就只列每章的头尾。
MAX_DIGEST_PAGES = 40


def turn_llm() -> Any:
    """取这一轮用的文本模型。单独抽出来是为了测试能塞一个桩进去。"""
    from app.services.provider_registry import get_registry

    return get_registry().current_llm()


# --- 一轮 ---


def send(
    course: Any,
    session: Any,
    text: str,
    *,
    ref_page_no: int | None = None,
    owner_id: str = "",
    submit: bool = True,
) -> dict:
    """收下用户的一句话，起一轮对话。返回 `{messageId, userMessageId, seq}`。

    返回的是**那条 assistant 消息**的 id（前端拿它接收 `agent.delta`），
    以及用户消息的 id（前端用它做乐观渲染的对账）。
    """
    user_row = chat.append(session, "user", text, ref_page_no=ref_page_no)
    reply_row = chat.append(session, "assistant", "", ref_page_no=ref_page_no)
    channel = chat.channel_of(session.id)
    # 清掉上一轮的积压**必须在第一帧之前**：接晚了的前端会先看到上一轮的回放。
    stream_mod.begin(channel)

    if submit:
        from app.common.tasks import get_runner

        def _job() -> None:
            run_turn(reply_row.id, owner_id=owner_id)

        get_runner().submit(channel, _job)

    return {
        "sessionId": session.id,
        "messageId": reply_row.id,
        "userMessageId": user_row.id,
        "seq": reply_row.seq,
    }


def run_turn(message_id: str, *, llm: Any = None, owner_id: str = "", pause: float = DELTA_PAUSE_SEC) -> dict:
    """跑一轮（后台线程里调）。**不抛异常**：失败也要有 `agent.done`。

    前端整轮都在等 `agent.done`：它不来，界面就永远停在「正在输入」。
    所以异常一律在这里收口，转成一条说明 + 一帧终态。
    """
    row = db.session.get(ChatMessage, message_id)
    if row is None:  # pragma: no cover - 消息被回退删掉了
        logger.warning("这一轮的消息已经不在了 message=%s", message_id)
        return {"status": "missing"}
    session = row.session
    if session is None:  # pragma: no cover - 会话被删了
        return {"status": "missing"}
    course = store.get_course(session.course_id)
    if course is None:  # pragma: no cover - 课程被删了
        return {"status": "missing"}

    channel = chat.channel_of(session.id)
    context = _turn_context(session, row)
    try:
        provider = llm if llm is not None else turn_llm()
        plan = _plan(course, session, context, provider, owner_id=owner_id)
    except AppError as exc:
        return _fail(row, channel, exc.message)
    except Exception as exc:  # pragma: no cover - 计划阶段的意外
        logger.exception("工作台一轮失败 message=%s", message_id)
        return _fail(row, channel, f"这一轮没能开始（{type(exc).__name__}）")

    tokens = int(plan.get("tokens") or 0)
    reply = str(plan.get("reply") or "").strip() or "好的。"
    _stream_reply(channel, row.id, reply, pause=pause)

    done: list[dict] = []
    for action in plan.get("actions") or []:
        record = _execute(
            course, session, row, action,
            context=context, provider=provider, owner_id=owner_id,
        )
        tokens += int(record.pop("tokens", 0) or 0)
        done.append(record)
        _push_rewrites(channel, row.id, course, record)

    content = _compose(reply, done)
    chat.update(row, content=content, tokens=tokens, skill_calls=done)
    frame = stream_mod.publish(channel, "agent.done", {"messageId": row.id, "tokens": tokens})
    return {"status": "ok", "messageId": row.id, "tokens": tokens, "seq": frame["seq"], "actions": done}


# --- 计划 ---


def _plan(
    course: Any,
    session: Any,
    context: Mapping[str, Any],
    provider: Any,
    *,
    owner_id: str = "",
) -> dict:
    """一次结构化调用：拿到「这一轮说什么」与「要调哪些技能」。"""
    call = call_json(
        provider,
        _plan_messages(course, session, context),
        schema=PLAN_SCHEMA,
        parse=_parse_plan,
        job_id="",
        owner_id=owner_id,
        ref_type=REF_TYPE_CHAT,
        ref_id=course.id,
    )
    data = dict(call.data)
    data["tokens"] = call.tokens
    return data


def _plan_messages(course: Any, session: Any, context: Mapping[str, Any]) -> list[dict]:
    text = str(context.get("text") or "")
    page_no = int(context.get("refPageNo") or 0)
    body = [
        "【课程现状】",
        course_digest(course),
        f"【用户正看着】第 {page_no} 页" if page_no else "【用户正看着】没指定（可能在看大纲）",
        "",
        "【可用技能】",
        *[
            f"- {item['name']}（{item['title']}）：{item['description']}；参数："
            + "，".join(f"{param['name']} {param['desc']}" for param in item["params"])
            for item in skills.catalogue()
        ],
        "",
        "【最近的对话】",
        *([f"{row['role']}：{row['content'][:200]}" for row in context.get("history") or []] or ["（还没有）"]),
        "",
        "【用户这句话】",
        text,
        "",
        "请输出 JSON：`reply` 是要对用户说的话（口语、别客套、说清你打算怎么做）；"
        f"`actions` 是要执行的技能，最多 {MAX_ACTIONS} 条，不需要改课程时给空数组。"
        "能一句话说清的事就不要调技能；调了就一定要把 `args` 填全"
        "（没写页号就用上面「用户正看着」的那一页）。",
    ]
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        *list(context.get("history") or []),
        {"role": "user", "content": "\n".join(body)},
    ]


SYSTEM_PROMPT = (
    "你是一门已经做好的课程的助教 Agent，负责按老师的要求修改这门课。"
    "你只输出 JSON，不要输出别的。不要编造课程里没有的页号或章节；"
    "拿不准的时候就只用 reply 说明，不要调技能。"
)


PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "skill": {"type": "string"},
                    "args": {"type": "object"},
                    "why": {"type": "string"},
                },
                "required": ["skill"],
            },
        },
    },
    "required": ["reply", "actions"],
}


def _parse_plan(text: str) -> dict:
    """计划的校验与规范化。

    **宽松是刻意的**：模型给一个不存在的技能名、把 `args` 写成字符串、
    多写了两条动作 —— 这些都不该让整轮对话失败。丢掉那条动作、
    在回复里说明一句，比让用户重新说一遍强。真正要拦的只有「计划不是个对象」。
    """
    data = load_json(text)
    actions: list[dict] = []
    for item in data.get("actions") or []:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("skill") or "").strip()
        if name not in skills.SKILLS:
            continue
        args = item.get("args")
        actions.append(
            {
                "skill": name,
                "args": dict(args) if isinstance(args, Mapping) else {},
                "why": str(item.get("why") or "")[:200],
            }
        )
    return {"reply": str(data.get("reply") or ""), "actions": actions[:MAX_ACTIONS]}


# --- 执行 ---


def _execute(
    course: Any,
    session: Any,
    row: ChatMessage,
    action: Mapping[str, Any],
    *,
    context: Mapping[str, Any],
    provider: Any,
    owner_id: str = "",
) -> dict:
    """执行一条技能：先推 `agent.skill`（前端开始转圈），跑完推 `agent.skill_done`。

    调用记录**先落库再执行**（`status=running`）：操作卡在事件到达时就出现，
    而它必须有 id 才能在跑完之后被更新 —— 结果靠 `agent.skill_done` 补。
    """
    name = str(action.get("skill") or "")
    args = dict(action.get("args") or {})
    channel = chat.channel_of(session.id)
    invocation = _start_invocation(session.id, row.id, name, args)
    stream_mod.publish(
        channel, "agent.skill",
        {"messageId": row.id, "skillId": invocation.id, "skill": name, "args": args,
         "why": str(action.get("why") or ""), "status": "running"},
    )

    ctx = skills.SkillContext(
        course=course, session=session, owner_id=owner_id,
        ref_page_no=int(context.get("refPageNo") or 0),
        instruction=str(context.get("text") or ""),
        provider=provider,
    )
    result = skills.run(ctx, name, args)
    _finish_invocation(invocation, result)
    stream_mod.publish(
        channel, "agent.skill_done",
        {"messageId": row.id, "skillId": invocation.id, "skill": name,
         "status": result["status"], "result": result.get("result"),
         "error": result.get("error") or "", "durationMs": result["durationMs"]},
    )
    for note in ctx.notes:
        logger.info("工作台技能附注 skill=%s note=%s", name, note)
    return {
        "skill": name,
        "status": result["status"],
        "durationMs": result["durationMs"],
        "error": result.get("error") or "",
        "result": result.get("result") or {},
        "tokens": int((result.get("result") or {}).get("tokens") or 0),
    }


def _start_invocation(
    session_id: str, message_id: str, name: str, args: Mapping[str, Any]
) -> SkillInvocation:
    from app.common.dbw import db_write

    def _work() -> SkillInvocation:
        item = SkillInvocation(
            session_id=session_id, message_id=message_id, skill=name,
            # 走 JSONField 那半边（`args`），不是底下那根 TEXT 列
            args=dict(args), result=None, status="running",
        )
        db.session.add(item)
        db.session.flush()
        return item

    return db_write(_work)


def _finish_invocation(invocation: SkillInvocation, result: Mapping[str, Any]) -> None:
    from app.common.dbw import db_write

    def _work() -> None:
        invocation.status = str(result.get("status") or "ok")
        invocation.result = result.get("result")
        invocation.duration_ms = int(result.get("durationMs") or 0)
        invocation.error = str(result.get("error") or "")[:512]
        db.session.flush()

    db_write(_work)


def _push_rewrites(channel: str, message_id: str, course: Any, record: Mapping[str, Any]) -> None:
    """页面真的变了才推 `page.rewritten`（F4-8 的徽标跟着刷新）。"""
    if record.get("status") != "ok":
        return
    name = str(record.get("skill") or "")
    payload = dict(record.get("result") or {})
    for page_no, extra in _touched_pages(name, payload):
        page = store.page_by_no(course, page_no)
        sources = citations.sources_of(page.id) if page is not None else []
        stream_mod.publish(
            channel, "page.rewritten",
            {"messageId": message_id, "pageNo": page_no, "reason": name,
             "rev": int(page.rev or 0) if page is not None else 0,
             "skill": name, "sources": sources, **extra},
        )


def _touched_pages(name: str, result: Mapping[str, Any]) -> list[tuple[int, dict]]:
    """这次技能改了哪几页（`page.rewritten` 一页推一帧）。"""
    if name in {"rewrite_page", "add_page", "add_quiz"}:
        page_no = int(result.get("pageNo") or 0)
        return [(page_no, {})] if page_no else []
    if name == "change_tone":
        return [(int(item.get("pageNo") or 0), {}) for item in result.get("pages") or []]
    if name == "remove_page":
        page_no = int(result.get("pageNo") or 0)
        # 删页不能报 rev：那一页已经不在了，前端据此把它从大纲里去掉。
        return [(page_no, {"removed": True})] if page_no else []
    # revise_outline 改的是章节信息，页面正文没变 —— 前端按 skill_done 里的
    # changedPages 刷新大纲树，这里不推 page.rewritten（推了就等于说「这一页重写了」）。
    return []


# --- 收尾 ---


def _stream_reply(channel: str, message_id: str, reply: str, *, pause: float) -> None:
    """把回复按句推成 `agent.delta`。

    回复本身是**一次调用就完整拿到**的（见模块 docstring），这里逐句发只是为了
    界面上是「一个字一个字出现」的样子。所以分块按标点切、不按 token 切，
    而且超过 `MAX_DELTA_FRAMES` 就不再细分 —— 一个 3000 字的回复切成 300 帧，
    只是让 SSE 连接多忙几百毫秒，用户看到的仍然是「一下子出来」。

    `pause` 是每帧之间的小停顿（30ms）。它不改变任何结果，但去掉的话，
    几十帧会在同一毫秒里挤到前端，React 只渲染最后一帧 —— 流式就白做了。
    """
    chunks = _chunks(reply)
    for index, chunk in enumerate(chunks):
        stream_mod.publish(channel, "agent.delta", {"messageId": message_id, "text": chunk})
        if pause > 0 and index < len(chunks) - 1:
            time.sleep(pause)


def _chunks(text: str) -> list[str]:
    """按句切（标点跟着前一句），超长则整段返回。"""
    if not text:
        return [""]
    pieces: list[str] = []
    current = ""
    for char in text:
        current += char
        if char in "。！？；\n":
            pieces.append(current)
            current = ""
    if current:
        pieces.append(current)
    if len(pieces) > MAX_DELTA_FRAMES:
        return [text]
    return pieces


def _compose(reply: str, done: Sequence[Mapping[str, Any]]) -> str:
    """回复正文 + 一段「做了什么」的清单。

    清单要进正文而不只是操作卡：消息是**归档**，操作卡是这一轮的界面；
    回看历史时（尤其是回退之后重建上下文），那段话得自己说得清当时改了什么。
    """
    lines = [reply]
    changed = [item for item in done if item.get("status") == "ok"]
    failed = [item for item in done if item.get("status") != "ok"]
    if changed:
        lines.append("")
        lines.append("已执行：" + "、".join(_describe(item) for item in changed))
    if failed:
        lines.append("")
        lines.append(
            "没做成："
            + "、".join(f"{skills.SKILLS[item['skill']].title}（{item.get('error') or '原因不明'}）"
                       for item in failed if item.get("skill") in skills.SKILLS)
        )
    return "\n".join(lines)


def _describe(record: Mapping[str, Any]) -> str:
    name = str(record.get("skill") or "")
    title = skills.SKILLS[name].title if name in skills.SKILLS else name
    result = dict(record.get("result") or {})
    detail = ""
    if "pageNo" in result:
        detail = f"第 {result['pageNo']} 页"
    elif result.get("pages"):
        detail = "第 " + "、".join(str(item.get("pageNo")) for item in result["pages"]) + " 页"
    elif "chapterNo" in result:
        detail = f"第 {result['chapterNo']} 章"
    return f"{title}{'·' + detail if detail else ''}"


def _fail(row: ChatMessage, channel: str, message: str) -> dict:
    """这一轮没起来：把原因写成这条 assistant 消息，并推终态。

    `agent.done` 一定要发 —— 前端整轮都在等它（见 `run_turn`）。
    """
    content = f"这一轮没能完成：{message}"
    chat.update(row, content=content)
    stream_mod.publish(channel, "agent.done", {"messageId": row.id, "tokens": 0, "error": message})
    return {"status": "failed", "messageId": row.id, "error": message}


def _turn_context(session: Any, row: ChatMessage) -> dict:
    """这一轮要用的上下文：用户那句话、看着哪一页、最近几轮对话。"""
    history = chat.messages_of(session, after=max(0, int(row.seq) - 1 - chat.CONTEXT_MESSAGES))
    user_text = ""
    for item in reversed(history):
        if item["seq"] >= int(row.seq):
            continue
        if item["role"] == "user":
            user_text = item["content"]
            break
    return {
        "text": user_text,
        "refPageNo": int(row.ref_page_no or 0),
        "history": chat.context_for_model(session),
    }


def course_digest(course: Any, *, max_pages: int = MAX_DIGEST_PAGES) -> str:
    """课程现状（给模型看的）：章节、页号、页型、状态。

    这是 Agent 唯一的「课程知识」来源 —— 不做成一次检索是因为一门课本身就不大
    （几十页），而页号写错的代价很高（它直接进技能参数）。
    """
    dsl = course.dsl or {}
    rows = store.pages_of(course)
    by_chapter: dict[int, list[Any]] = {}
    for row in rows:
        by_chapter.setdefault(int(row.chapter_no or 0), []).append(row)
    lines = [f"课程《{course.title}》，共 {len(rows)} 页，状态 {course.status}。"]
    chapters = dsl.get("chapters") or []
    for chapter in chapters:
        no = int(chapter.get("no") or 0)
        pages = by_chapter.get(no, [])
        listing = "、".join(
            f"{row.page_no}·{row.kind}·{row.title or ''}"[:40] for row in pages[:max_pages]
        )
        lines.append(f"第 {no} 章《{chapter.get('title') or ''}》要点：{'；'.join(str(x) for x in (chapter.get('points') or [])[:5])}")
        lines.append(f"  页面：{listing or '（无）'}")
    if not chapters:
        lines.append("（还没有大纲）")
    return "\n".join(lines)


__all__ = [
    "DELTA_PAUSE_SEC",
    "MAX_ACTIONS",
    "MAX_DELTA_FRAMES",
    "PLAN_SCHEMA",
    "SYSTEM_PROMPT",
    "course_digest",
    "run_turn",
    "send",
    "turn_llm",
]
