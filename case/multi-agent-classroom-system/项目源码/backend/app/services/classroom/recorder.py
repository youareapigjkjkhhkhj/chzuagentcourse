"""课堂的落库口（P3-C1 / P3-C2 / AGENTS §17）。

课堂里所有会留下来的东西都从这里写：事件、消息、举手、作答、在线名单。
集中在一个模块，是因为有三条规则**只有在单写者手上才守得住**：

1. **`seq` 单调且不重**（P3-B2）。`next_seq` 从 `session_events` 里取当前最大值 +1。
   这个读-改-写必须在同一把锁里完成，否则两路并发就会发出两个相同的 `seq` ——
   而客户端的去重规则是「同 `seq` 丢弃」，丢掉的会是**后来那条真事件**。
2. **`messages.ts` 严格递增**（P3-C1）。`utcnow_iso()` 不保证（本机粒度 15.6ms，
   同一批写的两条会拿到一模一样的串），所以这里显式比一下会话里上一条，
   不前进就 +1µs。详见 `models/classroom.py` 里 `ClassroomMessage` 的说明。
3. **`session_events` 有上限**（P3-C2）。到顶后从头砍掉最老的十分之一 ——
   砍掉的是「补发能力」，不是「记录」：记录页读 `messages` / `board_strokes`，
   那些一行都不动。

写库一律经 `db_write`（SQLite 单写者，`common/dbw.py`）。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Mapping, Sequence

from flask import current_app

from app.common.dbw import db_write
from app.common.logging import get_logger
from app.common.timeutil import parse_iso, to_iso, utcnow_iso
from app.extensions import db
from app.models import (
    ClassroomMessage,
    ClassroomSession,
    HandQueue,
    QuizAttempt,
    SessionEvent,
    SessionParticipant,
    User,
)
from app.services.classroom import roster

logger = get_logger("app.classroom.recorder")

#: 事件表一次清理的比例。10% 而不是「一条一条删」：一次删一条会让每来一个新事件
#: 都多做一次 DELETE，而真正需要留出余量的场景（45 分钟课堂）是持续写入。
PRUNE_RATIO = 10

#: 学生连续举手无效：已有 `waiting` 的那次还排着，再举一次不该多占一个位置。
HAND_PENDING = "waiting"


def next_seq(session_id: str) -> int:
    """下一个事件序号。同一会话内从 1 开始单调递增。"""
    latest = (
        db.session.query(db.func.max(SessionEvent.seq))
        .filter(SessionEvent.session_id == session_id)
        .scalar()
    )
    return int(latest or 0) + 1


def max_events() -> int:
    return int(current_app.config.get("CLASSROOM_MAX_EVENTS") or 5000)


def publish(
    session_or_id: ClassroomSession | str,
    type: str,
    payload: Mapping[str, Any] | None = None,
) -> dict:
    """记一条下行事件，并返回**要发出去的那个 dict**。

    返回值和落库内容是同一份，这不是省事：如果「发出去的」和「存档的」是两次
    组装，断线补发的客户端拿到的就和别人当时看到的不一样。补发要能替回放。

    出参形状：`{"type": …, <payload 各字段>, "seq": …, "eventId": …, "ts": …}`。
    元信息放在最后 —— `payload` 里若碰巧也有 `seq`，它不该赢。
    """
    session_id = session_or_id.id if isinstance(session_or_id, ClassroomSession) else str(session_or_id)
    body = dict(payload or {})

    def _write() -> dict:
        seq = next_seq(session_id)
        row = SessionEvent(
            session_id=session_id, seq=seq, type=str(type), payload=body
        )
        db.session.add(row)
        db.session.flush()
        event_id = row.id
        created = row.created_at
        _prune(session_id)
        return {"type": str(type), **body, "seq": seq, "eventId": event_id, "ts": created}

    return db_write(_write)


def _prune(session_id: str) -> None:
    """事件表到顶就砍最老的十分之一（P3-C2）。"""
    limit = max_events()
    if limit <= 0:
        return
    total = (
        db.session.query(db.func.count(SessionEvent.id))
        .filter(SessionEvent.session_id == session_id)
        .scalar()
    )
    if int(total or 0) <= limit:
        return
    cutoff = (
        db.session.query(SessionEvent.seq)
        .filter(SessionEvent.session_id == session_id)
        .order_by(SessionEvent.seq.asc())
        .offset(max(1, limit // PRUNE_RATIO) - 1)
        .limit(1)
        .scalar()
    )
    if cutoff is None:
        return
    deleted = (
        db.session.query(SessionEvent)
        .filter(SessionEvent.session_id == session_id, SessionEvent.seq <= cutoff)
        .delete(synchronize_session=False)
    )
    logger.warning(
        "课堂事件留档到顶，清理最早的一批：session=%s 删 %s 条（上限 %s）",
        session_id,
        deleted,
        limit,
    )


def replay(session_id: str, after_seq: int, *, limit: int = 1000) -> list[dict]:
    """补发：`seq > after_seq` 的事件，按 `seq` 升序（§4.2 / P3-B2）。"""
    rows = (
        SessionEvent.query.filter(
            SessionEvent.session_id == session_id, SessionEvent.seq > int(after_seq)
        )
        .order_by(SessionEvent.seq.asc())
        .limit(max(1, limit))
        .all()
    )
    return [
        {"type": row.type, **(row.payload or {}), "seq": row.seq,
         "eventId": row.id, "ts": row.created_at}
        for row in rows
    ]


def next_message_ts(session_id: str) -> str:
    """会话里下一条消息的时间戳，保证比上一条**大**。

    正常情况下就是 `utcnow_iso()`。只有当两次写入落在同一个时钟滴答里时才会
    动这个 +1µs 的手脚 —— 而那种情况在课堂里很常见：一条讲稿消息与它的字幕
    是同一批写下来的。
    """
    now = utcnow_iso()
    latest = (
        db.session.query(db.func.max(ClassroomMessage.ts))
        .filter(ClassroomMessage.session_id == session_id)
        .scalar()
    )
    if not latest or str(latest) < now:
        return now
    moment = parse_iso(str(latest))
    if moment is None:  # 库里那条时间戳坏了：不跟它比，直接用现在
        return now
    return to_iso(moment + timedelta(microseconds=1))


def add_message(
    session_or_id: ClassroomSession | str,
    *,
    speaker_code: str,
    text: str,
    speaker_kind: str = "teacher",
    type: str = "comment",
    page_no: int | None = None,
    beat_id: str = "",
    audio_url: str = "",
    quote_msg_id: str = "",
    ts: str | None = None,
) -> dict:
    """写一条消息，返回它的 `to_dict()`。

    返回 dict 而不是行对象：调用方（runtime）拿到它就直接拼下行事件，
    不需要再碰 session ——「写完就走」能让调用点在事务边界上保持简单。
    """
    session_id = session_or_id.id if isinstance(session_or_id, ClassroomSession) else str(session_or_id)

    def _write() -> dict:
        row = ClassroomMessage(
            session_id=session_id,
            speaker_code=str(speaker_code),
            speaker_kind=str(speaker_kind),
            type=str(type),
            text=str(text),
            page_no=page_no,
            beat_id=beat_id or None,
            audio_url=audio_url or None,
            quote_msg_id=quote_msg_id or None,
            ts=str(ts) if ts else next_message_ts(session_id),
        )
        db.session.add(row)
        db.session.flush()
        return row.to_dict()

    return db_write(_write)


def message_count(session_id: str) -> int:
    return int(
        db.session.query(db.func.count(ClassroomMessage.id))
        .filter(ClassroomMessage.session_id == session_id)
        .scalar()
        or 0
    )


def messages(
    session_id: str, *, before: str = "", size: int = 50
) -> tuple[list[dict], bool]:
    """消息分页（§4.1 `GET /messages`）：按 `ts` 升序，返回 `(列表, 还有更早的吗)`。

    `before` 传一个 `ts` 表示「给我比它更早的」—— 讨论区往上翻用的就是这个，
    所以它取的是**末尾一段**再倒回来，返回时仍按时间正序。
    """
    query = ClassroomMessage.query.filter(ClassroomMessage.session_id == session_id)
    if before:
        query = query.filter(ClassroomMessage.ts < str(before))
    rows = query.order_by(ClassroomMessage.ts.desc()).limit(max(1, int(size)) + 1).all()
    has_more = len(rows) > int(size)
    rows = rows[: int(size)]
    return [row.to_dict() for row in reversed(rows)], has_more


def all_messages(session_id: str) -> list[dict]:
    """整堂课的消息（记录页用）。"""
    rows = (
        ClassroomMessage.query.filter_by(session_id=session_id)
        .order_by(ClassroomMessage.ts.asc())
        .all()
    )
    return [row.to_dict() for row in rows]


# --- 在线名单（P3-A12 / P3-B5 / P3-F5）---


def join(session_id: str, user_id: str, *, role: str = "member", name: str = "") -> dict:
    """一个人进课堂。同一个人重复进来只留一行（`(session_id, user_id)` 唯一）。

    「在线 5」数的是**人**，不是连接：同一个人的两个标签页不该让这个数变成 6。
    连接数另有一条上限（`CLASSROOM_MAX_CONNECTIONS`），那是另一件事。
    """
    def _write() -> dict:
        row = SessionParticipant.query.filter_by(
            session_id=session_id, user_id=user_id or None
        ).first()
        if row is None:
            row = SessionParticipant(
                session_id=session_id,
                user_id=user_id or None,
                role=role,
                online=True,
                joined_at=utcnow_iso(),
            )
            db.session.add(row)
        else:
            row.online = True
            row.left_at = None
            # 开课的人再进来，身份还是 owner；旁听的人进来不该把 owner 降级
            if role == "owner":
                row.role = "owner"
        db.session.flush()
        return {"id": row.id, "userId": row.user_id, "name": name, "role": row.role}

    return db_write(_write)


def leave(session_id: str, user_id: str) -> None:
    def _write() -> None:
        row = SessionParticipant.query.filter_by(
            session_id=session_id, user_id=user_id or None
        ).first()
        if row is not None and row.online:
            row.online = False
            row.left_at = utcnow_iso()

    db_write(_write)


def sync_presence(session_id: str, alive: Sequence[str]) -> list[str]:
    """把在线名单对齐到「连接层认为还活着的人」，返回**刚被摘掉**的 user_id（P3-B5）。

    谁掉线了只有连接层知道（心跳超时、socket 关闭），这里不猜 ——
    它只做对齐：`alive` 里的人置为在线，其余在线的置为离线。

    这条路径必须存在：连接是内存里的，参与者是库里的，两者一旦不一致，
    顶栏那个「在线 5」就会挂着一个已经关掉浏览器的人，直到服务重启。
    """
    living = {str(item) for item in alive if item}

    def _write() -> list[str]:
        rows = SessionParticipant.query.filter_by(session_id=session_id, online=True).all()
        dropped: list[str] = []
        for row in rows:
            if (row.user_id or "") not in living:
                row.online = False
                row.left_at = utcnow_iso()
                dropped.append(row.user_id or "")
        return dropped

    return db_write(_write)


def presence(session_id: str) -> dict:
    """在线数与成员名单（下行 `presence` 事件的载荷）。

    **真人与 AI 同学分开两个字段**：`online` / `members` 是有真实连接的人，
    `aiMembers` 是这堂课的角色（AI 同学）—— 它们不连进来，一直都在（`roster`）。

    分开而不是混在一起数，是因为这两个数各有各的用处：老师看 `online` 判断
    「学生到齐没有」，看 `aiMembers` 知道「这堂课里有哪几位同学会开口」。
    合成一个数之后，两个问题都答不了 —— 而它们**必须同源**：名单里 3 位同学、
    讨论里却冒出第 4 位，是同一件事的两种说法对不上。
    """
    rows = (
        SessionParticipant.query.filter_by(session_id=session_id, online=True).all()
    )
    names = names_of([row.user_id for row in rows if row.user_id])
    members = [
        {
            "userId": row.user_id or "",
            "name": names.get(row.user_id or "", ""),
            "role": row.role,
        }
        for row in rows
    ]
    return {
        "online": len(members),
        "members": members,
        "aiMembers": roster.presence_members(),
    }


def names_of(user_ids: Sequence[str]) -> dict[str, str]:
    """一批用户 id → 显示名（查不到的给空串）。

    **名字现查，不往库里存副本**：`messages` / `hand_queue` /
    `session_participants` 三张表都只存 `user_id`，改个昵称之后全堂课的
    显示名一起跟着变（`HandQueue` 的模型注释写着为什么）。一次 `IN` 查完，
    不是每个人查一遍。
    """
    unique = [item for item in dict.fromkeys(user_ids) if item]
    if not unique:
        return {}
    rows = User.query.filter(User.id.in_(unique)).all()
    return {row.id: row.name for row in rows}


# --- 举手（P3-A5 / F3-7）---


def raise_hand(session_id: str, user_id: str) -> dict:
    """举手入队，返回 `{hand, position}`。已经在队里的再举一次只返回原位次。"""
    def _write() -> dict:
        existing = (
            HandQueue.query.filter_by(session_id=session_id, user_id=user_id or None)
            .filter(HandQueue.status == HAND_PENDING)
            .first()
        )
        if existing is None:
            existing = HandQueue(
                session_id=session_id, user_id=user_id or None, status=HAND_PENDING
            )
            db.session.add(existing)
            db.session.flush()
        return {"hand": existing.to_dict(), "position": _position(session_id, existing.id)}

    return db_write(_write)


def lower_hand(session_id: str, user_id: str) -> bool:
    """撤回举手（`hand action=lower`）。返回是否真的撤掉了一条。"""
    def _write() -> bool:
        row = (
            HandQueue.query.filter_by(session_id=session_id, user_id=user_id or None)
            .filter(HandQueue.status == HAND_PENDING)
            .first()
        )
        if row is None:
            return False
        row.status = "canceled"
        return True

    return db_write(_write)


def call_next(session_id: str) -> dict | None:
    """点名：队首那位从 `waiting` 变 `called`。返回他那一行（没有就 None）。"""
    def _write() -> dict | None:
        row = (
            HandQueue.query.filter_by(session_id=session_id, status=HAND_PENDING)
            .order_by(HandQueue.ts.asc(), HandQueue.created_at.asc())
            .first()
        )
        if row is None:
            return None
        row.status = "called"
        row.called_at = utcnow_iso()
        return row.to_dict(name=names_of([row.user_id or ""]).get(row.user_id or "", ""))

    return db_write(_write)


def finish_called(session_id: str) -> None:
    """被点名的那位问完了（`called` → `done`）。"""
    def _write() -> None:
        row = (
            HandQueue.query.filter(
                HandQueue.session_id == session_id, HandQueue.status == "called"
            )
            .order_by(HandQueue.called_at.desc())
            .first()
        )
        if row is not None:
            row.status = "done"

    db_write(_write)


def hand_queue(session_id: str) -> dict:
    """`{"queue": [...], "called": ...}` —— 下行 `hand_queue` 事件的载荷。"""
    rows = (
        HandQueue.query.filter_by(session_id=session_id, status=HAND_PENDING)
        .order_by(HandQueue.ts.asc(), HandQueue.created_at.asc())
        .all()
    )
    called = (
        HandQueue.query.filter_by(session_id=session_id, status="called")
        .order_by(HandQueue.called_at.desc())
        .first()
    )
    names = names_of([row.user_id or "" for row in rows] + [called.user_id if called else ""])
    return {
        "queue": [row.to_dict(name=names.get(row.user_id or "", "")) for row in rows],
        "called": called.to_dict(name=names.get(called.user_id or "", "")) if called else None,
    }


def _position(session_id: str, hand_id: str) -> int:
    """我在队列里排第几（从 1 起）。"""
    queue = hand_queue(session_id)["queue"]
    for index, item in enumerate(queue, start=1):
        if item["id"] == hand_id:
            return index
    return 0


# --- 作答（P3-A7 / F3-8）---


def record_quiz(
    session_id: str,
    *,
    course_id: str,
    page_no: int,
    option: str,
    correct: bool,
    node_id: str = "",
    response_ms: int = 0,
) -> dict:
    """记一次作答。**一次一行**，答错后重答是第二行（P6.1 要分开算）。"""
    def _write() -> dict:
        row = QuizAttempt(
            session_id=session_id,
            course_id=course_id,
            page_no=int(page_no),
            node_id=node_id or None,
            option=str(option),
            correct=bool(correct),
            response_ms=int(response_ms or 0),
        )
        db.session.add(row)
        db.session.flush()
        return row.to_dict()

    return db_write(_write)


def quiz_attempts(session_id: str) -> list[dict]:
    """这堂课的所有作答，按时间正序（记录页用）。"""
    rows = (
        QuizAttempt.query.filter_by(session_id=session_id)
        .order_by(QuizAttempt.ts.asc(), QuizAttempt.created_at.asc())
        .all()
    )
    return [row.to_dict() for row in rows]


__all__ = [
    "add_message",
    "all_messages",
    "call_next",
    "finish_called",
    "hand_queue",
    "join",
    "leave",
    "lower_hand",
    "max_events",
    "message_count",
    "messages",
    "names_of",
    "next_message_ts",
    "next_seq",
    "presence",
    "publish",
    "quiz_attempts",
    "raise_hand",
    "record_quiz",
    "replay",
    "sync_presence",
]
