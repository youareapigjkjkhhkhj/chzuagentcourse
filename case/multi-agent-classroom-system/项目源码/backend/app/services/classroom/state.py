"""课堂状态机（§2.1 / P3-A2 / P3-B4）。

七个状态、一张转移表。表就是验收依据 —— 「观察到的状态转移符合 §2.1 图」
这句话要能变成断言，就不能让转移散落在各处的 `if` 里。

三条口径：

1. **非法转移抛 `StateError`（40902）**，不静默修正。课堂状态是前端的唯一依据，
   悄悄改一下等于让两边对不上，而且事后查不出是谁改的。
2. **接口层的「没开始就答题」用 `ConflictError`（40901）**，这是 P3-B4 点名的码，
   与「转移非法」区分开：前者是「现在不能做这件事」，后者是「这个转移不存在」。
3. **状态落在 `classroom_sessions` 行上**（`status` + `state_json`），
   不放进程内存 —— 「刷新可恢复」（P3-A10）与「重启后记录还能看」（P3-C3）
   都要求如此。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.common.errors import ConflictError, StateError
from app.common.timeutil import utcnow_iso
from app.models import CLASSROOM_STATUSES, ClassroomSession
from app.services.classroom import timeline as timeline_module

STATUSES = CLASSROOM_STATUSES

IDLE = "idle"
LECTURE = "lecture"
DISCUSSING = "discussing"
QUIZ_WAIT = "quiz_wait"
BOARD_SHOW = "board_show"
PAUSED = "paused"
ENDED = "ended"

#: §2.1 那张图。左边的每个键能去右边集合里的状态。
TRANSITIONS: dict[str, frozenset[str]] = {
    # 开了还没讲：可以直接结束（用户进来又退出去）
    IDLE: frozenset({LECTURE, ENDED}),
    LECTURE: frozenset({DISCUSSING, QUIZ_WAIT, BOARD_SHOW, PAUSED, ENDED}),
    # 板书放完回讲授；中途也能暂停或收尾
    BOARD_SHOW: frozenset({LECTURE, PAUSED, ENDED}),
    # 讨论收尾回讲授
    DISCUSSING: frozenset({LECTURE, BOARD_SHOW, PAUSED, ENDED}),
    # 测验作答完回讲授，也可能转成讨论（答错后的补救讲解）
    QUIZ_WAIT: frozenset({LECTURE, DISCUSSING, PAUSED, ENDED}),
    # 从暂停回来：回到暂停前的那个状态（存在 state_json.resumeStatus 里）
    PAUSED: frozenset({LECTURE, DISCUSSING, QUIZ_WAIT, BOARD_SHOW, ENDED}),
    # 终态：结束了的课不能重新开始，要重上就新开一场（记录才不会被改写）
    ENDED: frozenset(),
}

#: 能被称为「正在上课」的状态。`paused` 也算 —— 课上到一半停了，
#: 人还在教室里，举手、发言、看板书都该照常可用。
LIVE_STATUSES = frozenset({LECTURE, DISCUSSING, QUIZ_WAIT, BOARD_SHOW, PAUSED})

#: 允许答题/举手的教学状态。P3-B4 要的是「`idle` 的会话调这两个接口返回 40901」。
INTERACTIVE_STATUSES = frozenset({LECTURE, DISCUSSING, QUIZ_WAIT, BOARD_SHOW})


@dataclass(frozen=True)
class Snapshot:
    """`state` 事件的全部内容（§4.2）。"""

    status: str
    page_no: int
    beat_idx: int
    elapsed_ms: int
    total_ms: int
    speed: float

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "pageNo": self.page_no,
            "beatIdx": self.beat_idx,
            "elapsedMs": self.elapsed_ms,
            "totalMs": self.total_ms,
            "speed": self.speed,
        }


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def transition(session: ClassroomSession, target: str, *, reason: str = "") -> tuple[str, str]:
    """移动到 `target`。返回 `(原状态, 新状态)`。

    Raises:
        StateError: 这个转移不在 §2.1 的表里（40902）。
    """
    current = str(session.status or IDLE)
    if target not in STATUSES:
        raise StateError(f"未知的课堂状态：{target}")
    if current == target:
        # 原地不动是幂等的「成功」：前端重连常常重复报同一个状态。
        return current, current
    if not can_transition(current, target):
        raise StateError(
            f"课堂状态不能从 {current} 变成 {target}",
            details={"from": current, "to": target, "reason": reason},
        )

    session.status = target
    patch: dict[str, Any] = {"statusChangedAt": utcnow_iso(), "lastReason": reason}
    if target == ENDED:
        session.ended_at = utcnow_iso()
    if target == PAUSED:
        patch["resumeStatus"] = current
    # 从暂停回来就把记号擦掉：留着它，下一次暂停会被旧的记号带偏
    leaving_pause = current == PAUSED and target != ENDED
    _patch_state(session, patch, drop=("resumeStatus",) if leaving_pause else ())
    return current, target


def resume_target(session: ClassroomSession) -> str:
    """从 `paused` 回来该去哪个状态。没记过就回讲授。"""
    bag = session.state or {}
    target = str(bag.get("resumeStatus") or LECTURE)
    return target if target in STATUSES and target != PAUSED else LECTURE


def progress(
    session: ClassroomSession,
    timeline: timeline_module.Timeline,
    *,
    page_no: int,
    beat_idx: int = 0,
) -> Snapshot:
    """把时间线推到某一页的某个 beat，并把会话行更新成这个位置。

    `elapsed_ms` 由时间线算出来（不是累加的计数器）：这样跳页、拖进度条、
    断线重连三条路径得到的是同一个数 —— 三处各自累加迟早会对不上。
    """
    offset = timeline.offset_of(page_no, beat_idx)
    session.current_page_no = int(page_no)
    session.current_beat_idx = max(0, int(beat_idx))
    session.elapsed_ms = int(offset)
    session.total_ms = int(timeline.total_ms)
    return snapshot(session)


def advance(
    session: ClassroomSession, timeline: timeline_module.Timeline, *, beats: int = 1
) -> Snapshot:
    """往后走 `beats` 个 beat；走到页尾就翻到下一页的第一个 beat。

    返回新的位置快照。已经到最后一页最后一个 beat 时停在原地 ——
    是否下课由调用方决定（runtime 会在这里转 `ended`），这一层不越权。
    """
    page = timeline.page(int(session.current_page_no or 1))
    if page is None or not page.beats:
        return progress(session, timeline, page_no=int(session.current_page_no or 1))

    index = int(session.current_beat_idx or 0) + int(beats)
    if index < len(page.beats):
        return progress(session, timeline, page_no=page.page_no, beat_idx=index)

    position = timeline.index_of(page.page_no)
    if position + 1 < len(timeline.pages):
        following = timeline.pages[position + 1]
        return progress(session, timeline, page_no=following.page_no, beat_idx=0)
    # 最后一页的最后一个 beat：停在原地
    return progress(session, timeline, page_no=page.page_no, beat_idx=len(page.beats) - 1)


def at_end(session: ClassroomSession, timeline: timeline_module.Timeline) -> bool:
    """整门课讲完了没有（最后一页的最后一个 beat）。"""
    if not timeline.pages:
        return True
    last = timeline.pages[-1]
    return int(session.current_page_no or 0) >= last.page_no and int(
        session.current_beat_idx or 0
    ) >= max(0, len(last.beats) - 1)


def snapshot(session: ClassroomSession) -> Snapshot:
    return Snapshot(
        status=str(session.status or IDLE),
        page_no=int(session.current_page_no or 0),
        beat_idx=int(session.current_beat_idx or 0),
        elapsed_ms=int(session.elapsed_ms or 0),
        total_ms=int(session.total_ms or 0),
        speed=float(session.speed or 1.0),
    )


def set_speed(session: ClassroomSession, value: float) -> float:
    """倍速。限定在 0.5~2.0：再快的 TTS 听起来是另一种语言，再慢学生直接走神。"""
    speed = max(0.5, min(float(value or 1.0), 2.0))
    session.speed = speed
    return speed


# --- 状态口袋（`state_json`）---


def get_flag(session: ClassroomSession, key: str, default: Any = None) -> Any:
    return (session.state or {}).get(key, default)


def set_flags(session: ClassroomSession, **values: Any) -> None:
    _patch_state(session, values)


def _patch_state(
    session: ClassroomSession, patch: Mapping[str, Any], *, drop: Sequence[str] = ()
) -> None:
    """合并着写状态口袋。`drop` 里的键**从口袋里删掉**（不是设成 None）。

    删与「设成 None」是两件事：`get_flag(..., "resumeStatus")` 拿 None 时
    分不清「从没记过」与「记过又被擦掉」，而 `resume_target` 要靠这个区分。
    """
    bag = dict(session.state or {})
    for key in drop:
        bag.pop(key, None)
    bag.update(patch)
    session.state = bag


# --- 接口层的守卫（P3-B4 / P3-F1）---


def require_status(session: ClassroomSession, *allowed: str) -> None:
    """不在 `allowed` 里就抛 40901（P3-B4 点名的码）。"""
    current = str(session.status or IDLE)
    if current not in allowed:
        raise ConflictError(
            f"课堂当前状态（{current}）不允许这个操作",
            details={"status": current, "allowed": list(allowed)},
        )


def require_interactive(session: ClassroomSession) -> None:
    """答题、举手、发言都要求课正在上（P3-B4：`idle` 的会话调它们返回 40901）。"""
    if str(session.status or IDLE) == ENDED:
        raise ConflictError("课堂已结束", details={"status": ENDED})
    require_status(session, *sorted(INTERACTIVE_STATUSES))


def require_live(session: ClassroomSession) -> None:
    """WS 上的播放控制（play/pause/seek/beat_done）要求课正在上。"""
    if str(session.status or IDLE) == ENDED:
        raise ConflictError("课堂已结束", details={"status": ENDED})
    require_status(session, *sorted(LIVE_STATUSES))


__all__ = [
    "BOARD_SHOW",
    "DISCUSSING",
    "ENDED",
    "IDLE",
    "INTERACTIVE_STATUSES",
    "LECTURE",
    "LIVE_STATUSES",
    "PAUSED",
    "QUIZ_WAIT",
    "STATUSES",
    "TRANSITIONS",
    "Snapshot",
    "advance",
    "at_end",
    "can_transition",
    "get_flag",
    "progress",
    "require_interactive",
    "require_live",
    "require_status",
    "resume_target",
    "set_flags",
    "set_speed",
    "snapshot",
    "transition",
]
