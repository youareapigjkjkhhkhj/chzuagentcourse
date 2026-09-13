"""工作台接口（P4 §3.2）。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/courses/{id}/chat`           | 发一句话，立刻返回 assistant 的 messageId |
| GET  | `/api/courses/{id}/chat/stream`    | SSE：Agent 回复与 Skill 调用事件 |
| GET  | `/api/courses/{id}/chat/messages`  | 历史消息（`after` 增量） |
| POST | `/api/courses/{id}/chat/rollback`  | 回退上下文 |
| GET  | `/api/courses/{id}/skills`         | 可用技能与参数说明 |

三条与其他接口一致的规矩：

1. **归属**一律走 `library.course_or_404`（不存在/已删/不是你的，都是 404）——
   工作台是这个项目里唯一「一句话就能改课程内容」的入口，它必须比别处更早判归属。
2. **POST 立刻返回**。改一页要十几秒、换语气要一分钟，同步做完就是把超时算在
   对话头上（P1-B1 同一条口径）：消息先落库，结果靠 SSE 推。
3. **SSE 的帧不落库**，所以这里**不补发历史**（`stream.py` 的模块 docstring 讲了
   为什么）。`after` 只用来跳过积压里已经收到的那几帧。
"""

from __future__ import annotations

import queue
from typing import Any, Iterator

from flask import Blueprint, Response, current_app, request

from app.api import json_body
from app.api.generation import SSE_HEADERS
from app.common.errors import ValidationError
from app.common.identity import current_owner_id
from app.common.response import ok
from app.extensions import db
from app.services.courses import library
from app.services.workbench import agent, chat, skills
from app.services.workbench import stream as stream_mod

bp = Blueprint("workbench", __name__)

#: 一句话的长度上限。比生成时的改写指令（200 字）宽得多：工作台里用户是在
#: **说话**，不是填表单 —— 「第三章太浅了，把第三节拆成两页，一页讲排序一页讲
#: 复杂度，语气也别那么书面」这种要求两三百字很正常。
MAX_CHAT_CHARS = 2000

#: 收到这个事件这一轮就结束了（与生成流的 TERMINAL_EVENTS 同一套用法）。
TERMINAL_EVENTS = frozenset({"agent.done"})


@bp.post("/api/courses/<course_id>/chat")
def send_message(course_id: str):
    """收下用户的一句话，起一轮对话。

    请求示例：
        POST /api/courses/c_01H…/chat
        {"text": "把第 3 页改口语一点", "refPageNo": 3}

    立刻返回那条 **assistant 消息**的 id：`agent.delta` 的每一帧都带着它，
    前端拿它把流式的字接到正确的气泡上。回复与技能结果走
    `GET /api/courses/{id}/chat/stream`。
    """
    body = json_body()
    text = _clean_text(body.get("text"))
    course = library.course_or_404(course_id, current_owner_id())
    ref_page_no = _ref_page(course, body.get("refPageNo"))
    session = chat.session_of(course, owner_id=current_owner_id())
    payload = agent.send(
        course, session, text, ref_page_no=ref_page_no,
        owner_id=current_owner_id(),
    )
    payload["stream"] = f"/api/courses/{course.id}/chat/stream"
    return ok(payload)


@bp.get("/api/courses/<course_id>/chat/stream")
def stream_chat(course_id: str):
    """订阅这条会话的事件流（Agent 回复 + Skill 调用）。

    请求示例：
        GET /api/courses/c_01H…/chat/stream
        GET /api/courses/c_01H…/chat/stream?after=7   （跳过已收到的 7 帧）
    """
    course = library.course_or_404(course_id, current_owner_id())
    session = chat.session_of(course, owner_id=current_owner_id())
    heartbeat = float(current_app.config.get("SSE_HEARTBEAT") or 15.0)
    after = _resume_from()
    from app.common.context import real_app

    app = real_app()
    return Response(
        _stream(app, session.id, after=after, heartbeat=heartbeat), headers=SSE_HEADERS
    )


@bp.get("/api/courses/<course_id>/chat/messages")
def list_messages(course_id: str):
    """历史消息（按 `seq` 升序）。

    请求示例：
        GET /api/courses/c_01H…/chat/messages
        GET /api/courses/c_01H…/chat/messages?after=12&limit=50
    """
    course = library.course_or_404(course_id, current_owner_id())
    session = chat.session_of(course, owner_id=current_owner_id())
    items = chat.messages_of(
        session, after=_int_arg("after", 0), limit=_int_arg("limit", chat.MAX_MESSAGES)
    )
    return ok(
        {
            "sessionId": session.id,
            "items": items,
            "lastSeq": int(items[-1]["seq"]) if items else 0,
            "running": _running(session.id),
        }
    )


@bp.post("/api/courses/<course_id>/chat/rollback")
def rollback_chat(course_id: str):
    """回退到某条消息为止：它之后的上下文不再参与新一轮（F4-11 / P4-A12）。

    请求示例：
        POST /api/courses/c_01H…/chat/rollback   {"messageId": "m_01H…"}
        POST /api/courses/c_01H…/chat/rollback   {"seq": 6}   （保留 1..6）

    **只回退上下文，不回退课程内容**。想撤销一次页面修改，用页面自己的版本号
    （`course_page_versions`）—— 两件事合成一个按钮的话，用户点一次会发生
    两件他不一定都想要的事。响应里的 `pageNotice` 就是提醒前端把这句话说出来。
    """
    body = json_body()
    course = library.course_or_404(course_id, current_owner_id())
    session = chat.session_of(course, owner_id=current_owner_id())
    if _running(session.id):
        # 一轮还在跑的时候回退，那一轮的 `agent.done` 会落在一堆已被删掉的消息
        # 后面；用户在界面上看到的是「刚删掉的话又被加了回来」。
        raise ValidationError("这一轮还在进行中，等它结束再回退")

    if body.get("messageId"):
        row = _message_or_400(session, str(body["messageId"]))
        boundary = int(row.seq) - 1
    elif body.get("seq") is not None:
        boundary = max(0, int(body["seq"]))
    else:
        raise ValidationError("请给出要回退到的 messageId 或 seq")

    result = chat.rollback(session, boundary)
    result["pageNotice"] = "课程内容没有跟着回退：页面改动要用页面自己的版本回退"
    return ok(result)


@bp.get("/api/courses/<course_id>/skills")
def list_skills(course_id: str):
    """可用技能清单与参数说明（前端提示用户「这个助手能做什么」）。

    请求示例：
        GET /api/courses/c_01H…/skills
    """
    library.course_or_404(course_id, current_owner_id())
    return ok({"items": skills.catalogue(), "maxActions": agent.MAX_ACTIONS})


# --- 内部 ---


def _stream(app, session_id: str, *, after: int = 0, heartbeat: float = 15.0) -> Iterator[str]:
    """先补积压 → 再收新帧，直到 `agent.done`。"""
    yield ": ok\n\n"  # 先发一帧注释，让前端立刻知道连接建立成功
    channel = chat.channel_of(session_id)
    with app.app_context():
        # 订阅与取积压在同一把锁里完成（stream.subscribe）：中间没有缝，
        # 所以既不会丢帧也不会重（各归各的）。
        target, pending = stream_mod.subscribe(channel, since=after)
        try:
            for frame in pending:
                yield stream_mod.frame_text(frame)
                after = int(frame["seq"])
                if frame["event"] in TERMINAL_EVENTS:
                    return
            while True:
                try:
                    frame = target.get(timeout=heartbeat)
                except queue.Empty:
                    yield ": ping\n\n"
                    continue
                if int(frame.get("seq") or 0) <= after:
                    continue
                yield stream_mod.frame_text(frame)
                after = int(frame["seq"])
                if frame["event"] in TERMINAL_EVENTS:
                    return
        finally:
            stream_mod.unsubscribe(channel, target)
            db.session.remove()


def _clean_text(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValidationError("请先输入一句话")
    text = " ".join(raw.split())
    if len(text) > MAX_CHAT_CHARS:
        raise ValidationError(f"一句话不能超过 {MAX_CHAT_CHARS} 字")
    return text


def _ref_page(course: Any, raw: Any) -> int | None:
    """用户「正看着哪一页」。给了就校验一次 —— 它会被当成技能的默认页号，
    一个不存在的页号会让技能去改一门课里根本没有的页。"""
    if raw in (None, "", 0):
        return None
    page_no = int(raw)
    library.page_or_400(course, page_no)
    return page_no


def _message_or_400(session: Any, message_id: str):
    from app.models import ChatMessage

    row = db.session.get(ChatMessage, message_id)
    if row is None or row.session_id != session.id:
        raise ValidationError("这条消息不在当前会话里")
    return row


def _running(session_id: str) -> bool:
    from app.common.tasks import get_runner

    return get_runner().is_running(chat.channel_of(session_id))


def _int_arg(name: str, default: int) -> int:
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except ValueError:
        raise ValidationError(f"{name} 必须是整数") from None


def _resume_from() -> int:
    """`Last-Event-ID` 头优先，其次 `?after=`（与生成流同一套）。"""
    raw = (request.headers.get("Last-Event-ID") or request.args.get("after") or "").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


__all__ = ["MAX_CHAT_CHARS", "TERMINAL_EVENTS", "bp"]
