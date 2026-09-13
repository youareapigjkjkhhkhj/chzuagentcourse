"""工作台会话：消息落库、模型上下文、回退（F4-11 / P4-A12）。

三件事在这里定死：

1. **`seq` 由这里发**。会话内的序号单调递增，回退的界就是它（见 models/workbench.py
   的模块 docstring）。`seq` 必须在写事务里算 —— 先读 max 再写，中间被别人插一条
   就会撞上 `uq_chat_messages_session_seq`；那个唯一键正是为此存在的，撞上了要重来，
   而不是写进去两条同号的。
2. **回退只回退上下文，不回退课程**。删掉 `seq` 之后的消息（连同它们的 Skill 调用），
   页面内容不动 —— 「把第 5 页改回上一版」是页面版本该管的事（`course_page_versions`），
   把它塞进回退里，用户点一次「回退」就会同时发生两件他不一定都想要的事。
3. **给模型的上下文只带最近的 N 条**。工作台里的一句话经常指代前面说过的东西
   （「再短一点」「刚才那页」），所以带上几轮；但一门课做完之后可能有几十条消息，
   全带上只会让每轮的提示词越来越贵、且越早的话反而越干扰。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.common.dbw import db_write
from app.common.timeutil import utcnow_iso
from app.extensions import db
from app.models import ChatMessage, ChatSession, Course

#: 前缀是刻意加的：同一进程里生成任务的事件中心也用字符串频道，
#: 两条流的频道不能撞（撞了就是「工作台的帧跑进了生成流的订阅者队列」）。
CHANNEL_PREFIX = "chat:"

#: 给模型看的最近消息条数（一问一答算两条）。
CONTEXT_MESSAGES = 12

#: 给模型看的单条消息截断长度。一条长回复对下一轮的用处通常只有头几句，
#: 而它会把整个提示词撑大。
CONTEXT_MESSAGE_CHARS = 1200

#: 历史消息接口一次最多回多少条。
MAX_MESSAGES = 200


def channel_of(session_id: str) -> str:
    """会话的 SSE 频道名。"""
    return f"{CHANNEL_PREFIX}{session_id}"


# --- 会话 ---


def session_of(course: Course, *, owner_id: str = "") -> ChatSession:
    """取这门课的会话，没有就建一条。

    一个用户对一门课**通常只有一条**会话：工作台就是「跟这门课的 Agent 说话」，
    多开一条只会让「我刚才说的那句话去哪了」变成一个问题。
    """

    def _work() -> ChatSession:
        found = (
            ChatSession.query.filter_by(course_id=course.id, owner_id=owner_id or None)
            .order_by(ChatSession.created_at)
            .first()
        )
        if found is not None:
            return found
        session = ChatSession(
            course_id=course.id,
            owner_id=owner_id or None,
            title=(course.title or "未命名课程")[:120],
            status="active",
            last_active_at=utcnow_iso(),
        )
        db.session.add(session)
        db.session.flush()
        return session

    return db_write(_work)


def sessions_of(course: Course) -> list[ChatSession]:
    return (
        ChatSession.query.filter_by(course_id=course.id)
        .order_by(ChatSession.created_at)
        .all()
    )


# --- 消息 ---


def messages_of(session: ChatSession, *, after: int = 0, limit: int = MAX_MESSAGES) -> list[dict]:
    """按 `seq` 升序取消息。`after` 是增量拉取（前端断线重连时只补新的）。"""
    size = max(1, min(int(limit or MAX_MESSAGES), MAX_MESSAGES))
    rows = (
        ChatMessage.query.filter(
            ChatMessage.session_id == session.id, ChatMessage.seq > int(after or 0)
        )
        .order_by(ChatMessage.seq)
        .limit(size)
        .all()
    )
    return [row.to_dict() for row in rows]


def append(
    session: ChatSession,
    role: str,
    content: str,
    *,
    ref_page_no: int | None = None,
    tokens: int = 0,
    skill_calls: Sequence[Mapping[str, Any]] | None = None,
) -> ChatMessage:
    """落一条消息并推进 `last_active_at`。"""

    def _work() -> ChatMessage:
        row = ChatMessage(
            session_id=session.id,
            seq=_next_seq(session),
            role=role,
            content=str(content or ""),
            ref_page_no=int(ref_page_no) if ref_page_no else None,
            tokens=int(tokens or 0),
            # 走 JSONField 那半边（`skill_calls`），不是底下那根 TEXT 列 ——
            # 往列上写 list 会被 sqlite 直接挡下来（不能绑 list 参数）。
            skill_calls=list(skill_calls or []),
        )
        db.session.add(row)
        session.last_active_at = utcnow_iso()
        db.session.flush()
        return row

    return db_write(_work)


def update(
    message: ChatMessage,
    *,
    content: str | None = None,
    tokens: int | None = None,
    skill_calls: Sequence[Mapping[str, Any]] | None = None,
) -> ChatMessage:
    """把一轮跑完的结果填回那条 assistant 消息（只改传进来的字段）。"""

    def _work() -> ChatMessage:
        if content is not None:
            message.content = str(content)
        if tokens is not None:
            message.tokens = int(tokens or 0)
        if skill_calls is not None:
            message.skill_calls = list(skill_calls)
        db.session.flush()
        return message

    return db_write(_work)


def context_for_model(session: ChatSession, *, limit: int = CONTEXT_MESSAGES) -> list[dict]:
    """最近几条消息 → 模型的消息数组。**不带 system 消息**（它是内部记账）。"""
    rows = (
        ChatMessage.query.filter(
            ChatMessage.session_id == session.id, ChatMessage.role != "system"
        )
        .order_by(ChatMessage.seq.desc())
        .limit(max(1, int(limit)))
        .all()
    )
    return [
        {"role": row.role, "content": (row.content or "")[:CONTEXT_MESSAGE_CHARS]}
        for row in reversed(rows)
        if (row.content or "").strip()
    ]


def rollback(session: ChatSession, seq: int) -> dict:
    """回退到第 `seq` 条为止：删掉它之后的全部消息（含 Skill 调用记录）。

    `seq=0` 表示清空这条会话的全部消息。返回删了几条、以及回退点前后各是什么 ——
    前端要拿它刷新消息列表，也要告诉用户「回退掉了哪几条」。

    页面内容**不动**：回退改的是「Agent 接下来看到什么」。
    """
    boundary = max(0, int(seq or 0))

    def _work() -> dict:
        doomed = (
            ChatMessage.query.filter(
                ChatMessage.session_id == session.id, ChatMessage.seq > boundary
            )
            .order_by(ChatMessage.seq)
            .all()
        )
        removed = [
            {"seq": row.seq, "role": row.role, "content": (row.content or "")[:80]}
            for row in doomed
        ]
        for row in doomed:
            db.session.delete(row)
        kept = (
            ChatMessage.query.filter(
                ChatMessage.session_id == session.id, ChatMessage.seq <= boundary
            )
            .order_by(ChatMessage.seq.desc())
            .first()
        )
        session.last_active_at = utcnow_iso()
        db.session.flush()
        return {
            "sessionId": session.id,
            "rolledBackTo": boundary,
            "removed": len(removed),
            "removedMessages": removed[:20],
            "lastKeptSeq": kept.seq if kept is not None else 0,
        }

    return db_write(_work)


def _next_seq(session: ChatSession) -> int:
    last = (
        ChatMessage.query.filter(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.seq.desc())
        .first()
    )
    return int(last.seq if last is not None else 0) + 1


__all__ = [
    "CHANNEL_PREFIX",
    "CONTEXT_MESSAGES",
    "CONTEXT_MESSAGE_CHARS",
    "MAX_MESSAGES",
    "append",
    "channel_of",
    "context_for_model",
    "messages_of",
    "rollback",
    "session_of",
    "sessions_of",
    "update",
]
