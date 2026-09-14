"""课堂记录：回看页要的那一份只读投影（F3-11 / P3-A14 / P3-C3）。

**它读什么、不读什么，是这一层最要紧的一件事。** 记录来自 `messages`、
`board_strokes`、`quiz_attempts` 三张**只增不改、永不清理**的表，而不是
`session_events`：事件留档有上限（P3-C2 到顶砍最老的十分之一），砍掉的正是
「断线补发」这一项能力。要是记录页也读留档，一堂超过上限的课回看时就会
**前半段字幕整段消失** —— 而那恰恰是一堂课里最难重来的一段。

所以这里不做任何写入、不碰任何内存状态：`build()` 是「这门课现在留下来什么」
的纯投影，重启服务之后（P3-C3）与刚下课时给的是同一份东西。

三件事顺带说清：

1. **字幕就是讲稿消息。** `_speak` 写消息时带的 `beatId` 是「这条是照着某个
   beat 讲的」的记号，字幕与讨论区看到的是同一行。不另存一份「字幕表」——
   两份就会有一份是旧的。
2. **板书写进它自己的表**（`board_strokes`），带页号与笔序；记录页按页取快照，
   与课上白板看到的是同一份数据（`board.strokes_of`）。
3. **作答一次一行**：答错重答是第二行，记录页照原样展示（P6.1 要分开算第一次
   答对率与最终答对率，在这里合并掉就再也拆不开了）。
4. **思辨轨迹也是投影**：`trails` 不查第四张表 —— 它是 `messages` 里那些引用
   关系折出来的（`scaffold.build_trails`）。学生的产出（他自己说的那几句）本来
   就在消息流里，这里只是把它按「一次引导」重新分组。
"""

from __future__ import annotations

from typing import Any

from app.common.timeutil import parse_iso
from app.extensions import db
from app.models import ClassroomSession, Course, SessionParticipant
from app.services.classroom import board, recorder, scaffold


def build(session: ClassroomSession) -> dict[str, Any]:
    """这堂课的完整记录（§4.1 `GET /sessions/{id}/record`）。

    返回 `{session, courseTitle, participants, subtitles, messages, boards,
    quizzes, trails, stats}`。已经结束的课给的是最终结果，还在上的课给的是
    「到此刻为止」—— 同一个函数不为两种时刻写两遍，页面显示什么由
    `session.status` 决定。
    """
    messages = recorder.all_messages(session.id)
    boards = [
        {"pageNo": page_no, "strokes": board.strokes_of(session, page_no)}
        for page_no in board.pages_with_strokes(session)
    ]
    quizzes = recorder.quiz_attempts(session.id)
    subtitles = subtitles_of(messages)
    trails = scaffold.build_trails(messages)
    course = db.session.get(Course, session.course_id)
    return {
        "session": session.to_dict(),
        "courseTitle": course.title if course is not None else "",
        "participants": _participants(session.id),
        "subtitles": subtitles,
        "messages": messages,
        "boards": boards,
        "quizzes": quizzes,
        "trails": trails,
        # 五个列表一个个点名传：都是 list[dict]，位置传错了 mypy 也看不出来
        "stats": _stats(
            session,
            messages=messages,
            subtitles=subtitles,
            boards=boards,
            quizzes=quizzes,
            trails=trails,
        ),
    }


def subtitles_of(messages: list[dict]) -> list[dict]:
    """从消息里挑出**讲稿**（完整字幕，P3-A1 的「课堂记录页可查看全文」）。

    判据是 `beatId`：一条发言带着 beat，说明它是照着时间线讲出来的，
    课上也就同时走过字幕（`runtime._speak` 里 `subtitle` 与消息是同一次写入）。
    学生的提问、讨论区的发言不带 beat —— 它们在讨论区那一栏里，不在字幕栏。
    """
    return [
        {
            "beatId": str(item.get("beatId") or ""),
            "pageNo": int(item.get("pageNo") or 0),
            "speaker": str(item.get("speaker") or ""),
            "text": str(item.get("text") or ""),
            "audioUrl": str(item.get("audioUrl") or ""),
            "ts": str(item.get("ts") or ""),
        }
        for item in messages
        if str(item.get("beatId") or "")
    ]


# --- 内部 ---


def _participants(session_id: str) -> list[dict]:
    """进过这堂课的人（不是「此刻在线」，记录页问的是「谁上过」）。

    名字现从 `users` 表查（`recorder.names_of`），与在线名单同一个来源 ——
    参与表里只存 `user_id`。少了这一项，记录页上就只剩一串用户号，
    而「这堂课有谁上过」是回看的人第一眼要看的东西。
    """
    rows = (
        SessionParticipant.query.filter_by(session_id=session_id)
        .order_by(SessionParticipant.joined_at.asc(), SessionParticipant.id.asc())
        .all()
    )
    names = recorder.names_of([row.user_id or "" for row in rows])
    return [
        row.to_dict() | {"name": names.get(row.user_id or "", "")}
        for row in rows
    ]


def _stats(
    session: ClassroomSession,
    *,
    messages: list[dict],
    subtitles: list[dict],
    boards: list[dict],
    quizzes: list[dict],
    trails: list[dict],
) -> dict[str, Any]:
    """记录页顶部那几条。`durationMs` 取实际下课时刻减上课时刻（拿不到就退回
    会话行上的 `elapsedMs`）—— 一堂课上多久，是回看的人第一个想知道的事。

    末尾三个是**思辨**那一组（`scaffold.stats_of`）：追问了几次、学生自己说了
    几句、几次没接住。只报次数、不打分 —— 任何「思辨分数」都是伪量化。
    """
    return {
        "messages": len(messages),
        "subtitles": len(subtitles),
        "boardPages": len(boards),
        "strokes": sum(len(item["strokes"]) for item in boards),
        "quizAttempts": len(quizzes),
        "quizCorrect": len([item for item in quizzes if item.get("correct")]),
        "durationMs": _duration_ms(session),
        **scaffold.stats_of(trails),
    }


def _duration_ms(session: ClassroomSession) -> int:
    start = parse_iso(str(session.started_at or ""))
    ended = parse_iso(str(session.ended_at or ""))
    if start is None or ended is None:
        return int(session.elapsed_ms or 0)
    return max(0, int((ended - start).total_seconds() * 1000))


__all__ = ["build", "subtitles_of"]
