"""课堂状态机（§2.1 / P3-A2 / P3-B4 / P3-A10）。

两类错误码在这里分家：

- **40902 `StateError`**：这个转移在 §2.1 的表里不存在（`ended` 之后还想继续讲）。
- **40901 `ConflictError`**：状态本身合法，但此刻不能做这件事（`idle` 的会话
  去答题、去举手 —— P3-B4 点名的就是这条）。

状态落在 `classroom_sessions` 行上（`status` + `state_json`），
所以「刷新可恢复」（P3-A10）与「重启后记录还能看」都不依赖进程内存 ——
这里用一个新 session 对象读同一行来验它。
"""

from __future__ import annotations

import pytest

from app.common.errors import ConflictError, StateError
from app.extensions import db
from app.models import ClassroomSession, Course
from app.services.classroom import state, timeline

pytestmark = pytest.mark.unit


def _session(status: str = "idle") -> ClassroomSession:
    course = Course(title="机器学习入门", topic="机器学习入门", status="ready", dsl={})
    db.session.add(course)
    db.session.commit()
    session = ClassroomSession(course_id=course.id, status=status)
    db.session.add(session)
    db.session.commit()
    return session


def _line(*, pages: int = 2, beats: int = 3) -> timeline.Timeline:
    """一条现造的时间线（不碰库）：每页 3 条 beat，各 1 秒。"""
    built = []
    cursor = 0
    for page_no in range(1, pages + 1):
        rows = tuple(
            timeline.Beat(f"p{page_no}-b{i + 1}", f"第 {i + 1} 句", 1000, cursor + i * 1000)
            for i in range(beats)
        )
        built.append(
            timeline.TimelinePage(
                page_no=page_no,
                chapter_no=1,
                kind="concept",
                title=f"第 {page_no} 页",
                beats=rows,
                quiz=None,
                board_plan=(),
                discussion=(),
                start_ms=cursor,
                duration_ms=beats * 1000,
            )
        )
        cursor += beats * 1000
    return timeline.Timeline(pages=tuple(built), total_ms=cursor)


def test_the_documented_transitions_are_all_allowed(app):
    """§2.1 那张图上的每一条边都能走。"""
    with app.app_context():
        for source, targets in state.TRANSITIONS.items():
            for target in targets:
                assert state.can_transition(source, target), f"{source} → {target} 该是合法的"


def test_illegal_transition_raises_state_error(app):
    """§2.1 上不存在的边抛 40902（P3-B4 的邻座：那个是 40901）。"""
    with app.app_context():
        session = _session("idle")

        with pytest.raises(StateError) as caught:
            state.transition(session, "discussing")

        assert caught.value.code == 40902
        assert session.status == "idle", "抛了异常就不该动状态"


def test_ended_is_terminal(app):
    """结束了的课不能重新开始 —— 要重上就新开一场，否则课堂记录会被改写。"""
    with app.app_context():
        session = _session("lecture")
        state.transition(session, "ended")

        for target in state.STATUSES:
            if target == "ended":
                continue
            with pytest.raises(StateError):
                state.transition(session, target)


def test_same_status_is_idempotent(app):
    """重复报同一个状态算成功：重连的前端会重报它以为自己所在的状态。"""
    with app.app_context():
        session = _session("lecture")

        before, after = state.transition(session, "lecture")

        assert (before, after) == ("lecture", "lecture")
        assert session.status == "lecture"


def test_unknown_status_is_rejected(app):
    """状态名写错要当场报，不能写进库 —— 前端的分支渲染认的是这七个字。"""
    with app.app_context():
        session = _session("lecture")

        with pytest.raises(StateError):
            state.transition(session, "playing")


def test_pause_remembers_where_to_resume(app):
    """暂停记下「从哪儿停的」，继续时回到那个状态，而不是一律回讲授。"""
    with app.app_context():
        session = _session("lecture")
        state.transition(session, "quiz_wait")
        state.transition(session, "paused")

        assert state.resume_target(session) == "quiz_wait"

        state.transition(session, "quiz_wait")
        assert state.get_flag(session, "resumeStatus") is None, "回来了就把记号擦掉"


def test_resume_without_a_mark_goes_back_to_lecture(app):
    """没记过记号（或记号是 `paused` 自己）时回讲授 —— 不能回到 `paused`。"""
    with app.app_context():
        session = _session("paused")

        assert state.resume_target(session) == "lecture"

        state.set_flags(session, resumeStatus="paused")
        assert state.resume_target(session) == "lecture"


def test_ending_stamps_the_time(app):
    """`ended_at` 是「这堂课上了多久」的唯一依据（课堂记录页要用）。"""
    with app.app_context():
        session = _session("lecture")

        state.transition(session, "ended", reason="老师点了下课")

        assert session.ended_at
        assert state.get_flag(session, "lastReason") == "老师点了下课"


def test_position_survives_a_reload(app):
    """P3-A10：位置在**行**上，不在 Python 对象里。

    这里模拟一次刷新 —— 换一个 ORM 对象读同一行（等价于另一个请求/另一个进程）。
    """
    with app.app_context():
        session = _session("lecture")
        line = _line()
        state.progress(session, line, page_no=2, beat_idx=1)
        db.session.commit()
        session_id = session.id

    with app.app_context():
        db.session.expire_all()
        reloaded = db.session.get(ClassroomSession, session_id)
        assert reloaded is not None
        assert (reloaded.current_page_no, reloaded.current_beat_idx) == (2, 1)
        assert reloaded.elapsed_ms == line.offset_of(2, 1)


def test_elapsed_comes_from_the_timeline_not_a_counter(app):
    """`elapsed_ms` 由时间线算出来：跳页、拖进度条、重连三条路径必须得到同一个数。

    三处各自累加，迟早会对不上 —— 而进度条对不上的时候，没人知道该信哪个。
    """
    with app.app_context():
        session = _session("lecture")
        line = _line()

        snapshot = state.progress(session, line, page_no=2, beat_idx=2)

        assert snapshot.elapsed_ms == 5000
        assert snapshot.total_ms == 6000


def test_advance_walks_beats_then_pages(app):
    """`beat_done` 驱动时间线：页尾翻下一页，最后一个 beat 之后停在原地。"""
    with app.app_context():
        session = _session("lecture")
        line = _line(pages=2, beats=3)
        state.progress(session, line, page_no=1, beat_idx=2)

        state.advance(session, line)
        assert (session.current_page_no, session.current_beat_idx) == (2, 0)

        state.progress(session, line, page_no=2, beat_idx=2)
        state.advance(session, line)  # 最后一个 beat：站住
        assert (session.current_page_no, session.current_beat_idx) == (2, 2)
        assert state.at_end(session, line) is True


def test_at_end_is_false_in_the_middle(app):
    with app.app_context():
        session = _session("lecture")
        line = _line(pages=2, beats=3)
        state.progress(session, line, page_no=1, beat_idx=0)

        assert state.at_end(session, line) is False


def test_speed_is_clamped(app):
    """倍速限定 0.5~2.0：再快的 TTS 听起来是另一种语言，再慢学生直接走神。"""
    with app.app_context():
        session = _session("lecture")

        assert state.set_speed(session, 5) == 2.0
        assert state.set_speed(session, 0.1) == 0.5
        assert state.set_speed(session, 1.25) == 1.25
        assert state.set_speed(session, None) == 1.0


def test_idle_session_cannot_answer_or_raise_hand(app):
    """P3-B4：未开始的会话调用答题/举手接口返回 40901。"""
    with app.app_context():
        session = _session("idle")

        with pytest.raises(ConflictError) as caught:
            state.require_interactive(session)

        assert caught.value.code == 40901
        assert caught.value.http_status == 409


def test_paused_is_live_but_not_interactive(app):
    """暂停时人还在教室里：翻页、发言照常，但**答题与举手**要先把课继续起来。

    这条区分是刻意的 —— 暂停后还能答题，学生会在白板上留下答案然后困惑
    「为什么没往下走」。
    """
    with app.app_context():
        session = _session("paused")

        state.require_live(session)  # 不抛

        with pytest.raises(ConflictError):
            state.require_interactive(session)


def test_ended_session_refuses_playback(app):
    """下课后拖进度条要能看懂地说「结束了」，而不是默默什么都不做。"""
    with app.app_context():
        session = _session("ended")

        with pytest.raises(ConflictError) as caught:
            state.require_live(session)

        assert "结束" in caught.value.message


def test_snapshot_shape_matches_the_state_event(app):
    """`state` 事件的载荷字段（§4.2）。前端只认这一份形状。"""
    with app.app_context():
        session = _session("lecture")
        state.progress(session, _line(), page_no=1, beat_idx=1)

        payload = state.snapshot(session).to_dict()

        assert set(payload) == {"status", "pageNo", "beatIdx", "elapsedMs", "totalMs", "speed"}
        assert payload["status"] == "lecture"
