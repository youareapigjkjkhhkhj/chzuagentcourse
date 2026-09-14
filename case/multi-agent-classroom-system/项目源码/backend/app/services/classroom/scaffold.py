"""苏格拉底式引导：把一次答疑变成一小段「学生先想、老师再收束」的对话。

**为什么要有这个模块**：「什么算一次追问」「什么算一条轨迹」有两个读者 ——
课堂运行时（此刻该追问还是该给答案）与课堂记录（这条链子该怎么画出来）。
两边各写一份判据，就会出现「课上追了两轮、记录里只画出一条」这种对不上，
和 `roster` 单独成模块是同一个理由。

**一条轨迹长什么样** —— 全部落在已有的 `messages` 表里，**不新增表、不新增
消息类型、不动 CHECK 约束**，只用 `quote_msg_id`（那列本来就留着「引用上一条」
的口子）：

    学生问  ──引用──▶  老师追问  ──引用──▶  学生答  ──引用──▶  老师收束
    question            question             comment             answer
    speaker=我          speaker=老师          speaker=我          speaker=老师
                        ↑ 这条是「问题」，不是「答案」

于是「学生自己说了几句」这个数能从**已有数据**里数出来 —— 不用模型打分，
也不用学生填问卷。这是「看得见的思辨行为」唯一诚实的口径：AI 问得再漂亮也
不算证据，**学生说出来的才算**。

**两条兜底**，都好过「把学生困在问题里」：

1. `wants_answer()`：学生说「直接告诉我」，立刻给答案。学生要答案时被反问，
   读到的不是「老师在引导」，是「这东西坏了」。
2. `MAX_ASKS = 1`：只追一层 —— 学生接住一轮就直接收束，不追问第二次。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

#: 学生的逃生阀。命中这些词就不再追问、直接给答案。
ESCAPE_PHRASES = (
    "直接告诉",
    "直接说",
    "告诉我答案",
    "说答案",
    "给个答案",
    "答案是什么",
    "别问了",
    "不要问",
    "快点说",
)

#: 老师的追问用哪个消息类型。`question` 本来就在 `MESSAGE_TYPES` 里 ——
#: 「老师在提问」这件事不需要新造一个类型来表达。
ASK_TYPE = "question"

#: 老师的收束（真的给答案）。
ANSWER_TYPE = "answer"

#: 同一个问题最多追问几次。1 = 只追一层。
MAX_ASKS = 1

#: 设置里那个开关的键（`settings_service` 的生成参数）。
SOCRATIC_KEY = "socraticAnswer"

#: 学生的 `speaker_kind`（真人学生在这堂课里就叫 `me`）。
_STUDENT_KINDS = ("me", "student")


def wants_answer(text: str) -> bool:
    """学生这句话是不是在要答案（逃生阀）。"""
    return any(phrase in str(text or "") for phrase in ESCAPE_PHRASES)


def enabled() -> bool:
    """设置里的「苏格拉底式引导」开着没有。

    **读不出来按开着**：与 `roster.classmate_count()` 的取向不同 —— 那边读不
    出来按「全员上」是为了别让课开不起来，这边读不出来按关掉会让新功能看着像
    没做。而追问有逃生阀兜底，开着不会把人困住。
    """
    from app.services import settings_service

    try:
        return bool(settings_service.get_generation().get(SOCRATIC_KEY, True))
    except Exception:  # 设置读不出来不该让答疑开不了口
        return True


def awaiting_reply(recent: Sequence[Mapping[str, Any]]) -> bool:
    """最后一条是不是老师的追问（学生还没接上）。

    **与 `next_stage` 的区别是调用时机**：这个在学生那句话**落库之前**问 ——
    `_on_chat` 要先决定「这句话要不要引用老师的追问」，再决定落库时带什么。
    """
    items = [item for item in recent if isinstance(item, Mapping)]
    return bool(items) and _is_ask(items[-1])


def next_stage(recent: Sequence[Mapping[str, Any]], *, on: bool) -> str:
    """这一次答疑：`ASK_TYPE`（先追问一层）还是 `ANSWER_TYPE`（直接收束）。

    `recent` 是会话里最后几条消息（升序），**最后一条就是学生刚说的那句** ——
    `_answer` 是在它落库之后才被调用的。

    判据全在消息本身上，不看任何内存状态：换个标签页重进、断线重连之后判出来
    的还是同一条路。往回看这几条，按先撞上谁算：

    - 撞上老师的**追问** → 已经追过一层了 → 收束；
    - 撞上老师的**别的发言**（讲稿、上一次答疑）→ 上一段已经翻篇 → 这是新的一问 → 追问；
    - 撞上**学生自己的话** → 不算数，接着往回看（学生连着说两句仍然是同一次提问）。

    两条提前返回：开关关着、或者学生在要答案（逃生阀）—— 都直接给答案。
    """
    items = [item for item in recent if isinstance(item, Mapping)]
    if not on or not items:
        return ANSWER_TYPE
    if wants_answer(str(items[-1].get("text") or "")):
        return ANSWER_TYPE

    asked = 0
    for item in reversed(items[:-1]):
        if _is_ask(item):
            asked += 1
            if asked >= MAX_ASKS:
                return ANSWER_TYPE
            continue
        if _is_teacher(item):
            break  # 老师上一句是收束/讲稿：这一问是新开的一段
    return ASK_TYPE


def original_question(recent: Sequence[Mapping[str, Any]]) -> str:
    """这一轮引导最初那个问题（收束时告诉老师「他一开始问的是什么」）。

    只回看到上一条学生提问为止，看不到就返回空串 —— 这个信息是**锦上添花**，
    为它多查一次库不值得。
    """
    items = [item for item in recent if isinstance(item, Mapping)]
    for item in reversed(items[:-1]):
        if _is_student_question(item):
            return str(item.get("text") or "")
    return ""


def build_trails(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """消息流 → 一条条引导轨迹（记录页与导出读它）。

    **根是学生的提问，链是引用关系**：只有「有老师回应过」的学生提问才算一条，
    没有人接的普通发言不算。一条链的状态只有两种：

    - `closed`：链里出现了老师的收束（`answer`）—— 这场引导走完了；
    - `open`：只追到一半 —— 学生没接住，或者老师还没给答案。**这一条最有教学
      价值**：它指出哪一页没讲清。
    """
    items = [item for item in messages if isinstance(item, Mapping)]
    by_id = {str(item.get("id") or ""): item for item in items if item.get("id")}
    children: dict[str, list[Mapping[str, Any]]] = {}
    for item in items:
        parent = str(item.get("quoteMsgId") or "")
        if parent and parent in by_id:
            children.setdefault(parent, []).append(item)

    trails: list[dict[str, Any]] = []
    for item in items:
        if not _is_student(item) or _answers_an_ask(item, by_id):
            continue  # 不是学生说的，或者这是别人那条链里的一环
        steps = _descendants(str(item.get("id") or ""), children)
        if not steps:
            continue  # 没有人接的提问，算不上一条轨迹
        student_turns = 1 + len([step for step in steps if _is_student(step)])
        trails.append(
            {
                "rootId": str(item.get("id") or ""),
                "pageNo": int(item.get("pageNo") or 0),
                "question": str(item.get("text") or ""),
                "ts": str(item.get("ts") or ""),
                "status": "closed" if any(_is_answer(step) for step in steps) else "open",
                "studentTurns": student_turns,
                "steps": [
                    {
                        "id": str(item.get("id") or ""),
                        "speaker": str(item.get("speaker") or ""),
                        "speakerKind": str(item.get("speakerKind") or ""),
                        "type": str(item.get("type") or ""),
                        "role": "question",
                        "text": str(item.get("text") or ""),
                        "ts": str(item.get("ts") or ""),
                        "pageNo": int(item.get("pageNo") or 0),
                    },
                    *[
                        {
                            "id": str(step.get("id") or ""),
                            "speaker": str(step.get("speaker") or ""),
                            "speakerKind": str(step.get("speakerKind") or ""),
                            "type": str(step.get("type") or ""),
                            "role": _role_of(step),
                            "text": str(step.get("text") or ""),
                            "ts": str(step.get("ts") or ""),
                            "pageNo": int(step.get("pageNo") or 0),
                        }
                        for step in steps
                    ],
                ],
            }
        )
    return trails


def stats_of(trails: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """记录页顶部那三个数。**只报次数，不打分** —— 任何「思辨分数」都是伪量化。"""
    return {
        "thinkingTrails": len(trails),
        "studentTurns": sum(int(trail.get("studentTurns") or 0) for trail in trails),
        "openTrails": len([trail for trail in trails if trail.get("status") == "open"]),
    }


# --- 形状判据（都只看消息自己的字段，不看上下文）---


def _is_student(item: Mapping[str, Any]) -> bool:
    return str(item.get("speakerKind") or "") in _STUDENT_KINDS


def _is_teacher(item: Mapping[str, Any]) -> bool:
    return str(item.get("speakerKind") or "") == "teacher"


def _is_ask(item: Mapping[str, Any]) -> bool:
    """老师的追问（引导模式下发的那种 `question`）。"""
    return _is_teacher(item) and str(item.get("type") or "") == ASK_TYPE


def _is_answer(item: Mapping[str, Any]) -> bool:
    return _is_teacher(item) and str(item.get("type") or "") == ANSWER_TYPE


def _is_student_question(item: Mapping[str, Any]) -> bool:
    return _is_student(item) and str(item.get("type") or "") == ASK_TYPE


def _answers_an_ask(item: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]]) -> bool:
    """这条学生消息是在回答老师的追问吗（是的话它属于别人那条链）。"""
    parent = by_id.get(str(item.get("quoteMsgId") or ""))
    return parent is not None and _is_ask(parent)


def _descendants(
    root_id: str, children: Mapping[str, list[Mapping[str, Any]]]
) -> list[Mapping[str, Any]]:
    """根下面按引用关系串起来的全部消息，按 `ts` 升序。

    `visited` 是防呆：`quote_msg_id` 是人填得出来的，两个 id 互相引用就会把
    递归变成死循环。记录页不该因为一条坏数据整页打不开。
    """
    found: list[Mapping[str, Any]] = []
    visited = {root_id}
    queue = list(children.get(root_id, []))
    while queue:
        item = queue.pop(0)
        key = str(item.get("id") or "")
        if not key or key in visited:
            continue
        visited.add(key)
        found.append(item)
        queue.extend(children.get(key, []))
    found.sort(key=lambda item: str(item.get("ts") or ""))
    return found


def _role_of(item: Mapping[str, Any]) -> str:
    """链上这一环演的是哪一出。老师不是追问的都算收束（含讨论里的普通回应）。"""
    if _is_ask(item):
        return "ask"
    if _is_student(item):
        return "reply"
    return ANSWER_TYPE


__all__ = [
    "ANSWER_TYPE",
    "ASK_TYPE",
    "ESCAPE_PHRASES",
    "MAX_ASKS",
    "SOCRATIC_KEY",
    "awaiting_reply",
    "build_trails",
    "enabled",
    "next_stage",
    "original_question",
    "stats_of",
    "wants_answer",
]
