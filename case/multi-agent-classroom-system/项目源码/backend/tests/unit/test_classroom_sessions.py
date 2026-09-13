"""课堂会话的生命周期（F3-1 / P3-A1 / P3-F4 / P3-F5）。

这一层管的是「有没有这堂课、谁看得见、还能不能进」，所以钉的是四道护栏：

- 开课要有页面可讲，且 `status` 停在 `idle`（P3-B4 依赖这一点）；
- 并发上限数的是**没结束的**课（P3-F5）；
- 可见性是创建者 + 参与者，其他人 404（P3-F4）；
- 票据带 `scope`，为 A 课签的票接不进 B 课（P3-F1）。
"""

from __future__ import annotations

import pytest

from app.common.errors import (
    ConflictError,
    NotFoundError,
    RateLimitError,
    UnauthorizedError,
    ValidationError,
)
from app.extensions import db
from app.models import BoardStroke, ClassroomSession, Course, CoursePage, User
from app.services.classroom import sessions, state
from app.services.voice import tickets

pytestmark = pytest.mark.unit


def _user(name: str = "沈老师") -> User:
    row = User(name=name, role="teacher")
    db.session.add(row)
    db.session.commit()
    return row


def _course(pages: int = 3, *, status: str = "ready") -> Course:
    course = Course(title="机器学习入门", topic="机器学习入门", status="ready", dsl={})
    db.session.add(course)
    db.session.commit()
    for page_no in range(1, pages + 1):
        db.session.add(
            CoursePage(
                course_id=course.id,
                page_no=page_no,
                chapter_no=1,
                kind="concept",
                title=f"第 {page_no} 页",
                status=status,
                dsl={
                    "pageNo": page_no,
                    "title": f"第 {page_no} 页",
                    "narration": [{"beatId": f"p{page_no}-b1", "text": "一句话", "estSec": 4}],
                },
            )
        )
    db.session.commit()
    return course


# --- 开课 ---


def test_start_opens_an_idle_room_with_a_timeline(app):
    """开课建行、按时间线定总时长，但**开讲是下一步**（P3-B4 靠这个区分）。"""
    with app.app_context():
        owner = _user()
        course = _course(pages=3)

        session = sessions.start(course, owner.id)

        assert session.status == state.IDLE
        assert session.mode == "auto"
        assert session.current_page_no == 1
        assert session.total_ms == 3 * 4000, "三页各 4 秒（没有音频时按 estSec 估算）"
        assert session.started_at
        assert session.ended_at is None


def test_start_puts_the_owner_in_the_room(app):
    """开课的人自己也是参与者 —— 记录页对参与者可见（P3-F4）。"""
    with app.app_context():
        owner = _user()
        session = sessions.start(_course(), owner.id)

        assert sessions.summary(session)["presence"]["online"] == 1
        assert sessions.visible_to(session, owner.id) is True


def test_start_refuses_a_course_without_pages(app):
    """没有可讲的页面就开不了课 —— 空课堂的每一页操作都得另写一套空状态。"""
    with app.app_context():
        owner = _user()
        course = _course(pages=0)

        with pytest.raises(ValidationError):
            sessions.start(course, owner.id)

        assert ClassroomSession.query.count() == 0


def test_a_course_with_only_unready_pages_cannot_start(app):
    """页面还在生成（`status != ready`）也算没有页面：讲稿都没写出来。"""
    with app.app_context():
        owner = _user()

        with pytest.raises(ValidationError):
            sessions.start(_course(pages=2, status="pending"), owner.id)


def test_manual_mode_survives_and_unknown_modes_fall_back_to_auto(app):
    with app.app_context():
        owner = _user()

        assert sessions.start(_course(), owner.id, mode="manual").mode == "manual"
        assert sessions.start(_course(), owner.id, mode="赛车").mode == "auto"


def test_without_the_push_channel_the_room_opens_in_manual_mode(app_factory):
    """P3-G3：没有 WS 就没有推进时间线的手段，这时候按 auto 开只是记了个假状态。"""
    with app_factory(env={"CLASSROOM_WS": "false"}).app_context():
        owner = _user()
        session = sessions.start(_course(), owner.id, mode="auto")

        assert session.mode == "manual"
        assert sessions.ws_enabled() is False


# --- 并发上限（P3-F5）---


def test_a_user_cannot_open_more_rooms_than_the_limit(app):
    """P3-F5：默认同时最多两堂课，第三堂回 42901。"""
    with app.app_context():
        owner = _user()
        course = _course()
        sessions.start(course, owner.id)
        sessions.start(course, owner.id)

        with pytest.raises(RateLimitError) as caught:
            sessions.start(course, owner.id)

        assert caught.value.code == 42901
        assert caught.value.details["limit"] == 2


def test_finished_rooms_do_not_hold_the_quota(app):
    """上完的课不占名额 —— 否则「今天上过两节」就等于「今天不能再上课」。"""
    with app.app_context():
        owner = _user()
        course = _course()
        sessions.start(course, owner.id)
        second = sessions.start(course, owner.id)
        sessions.end(second)

        third = sessions.start(course, owner.id)

        assert third.status == state.IDLE
        assert len(sessions.active_of(owner.id)) == 2


def test_the_quota_is_per_user(app):
    with app.app_context():
        mine, yours = _user("我"), _user("你")
        course = _course()
        sessions.start(course, mine.id)
        sessions.start(course, mine.id)

        # 别人开着几堂课与我无关
        assert sessions.start(course, yours.id).status == state.IDLE


# --- 可见性（P3-F4）---


def test_a_stranger_gets_a_404_not_a_403(app):
    """P3-F4：用错误码的差别确认「这个 id 存在」，就等于泄露了它的存在。"""
    with app.app_context():
        owner = _user()
        stranger = _user("路人")
        session = sessions.start(_course(), owner.id)

        assert sessions.visible_to(session, stranger.id) is False
        with pytest.raises(NotFoundError) as caught:
            sessions.require_visible(session, stranger.id)

        assert caught.value.code == 40401


def test_a_participant_can_see_the_record(app):
    """旁听的人上过这堂课，记录页就不该把他挡在外面。"""
    with app.app_context():
        owner = _user()
        guest = _user("旁听")
        session = sessions.start(_course(), owner.id)

        sessions.join(session, guest.id)
        sessions.leave(session, guest.id)  # 人走了，但上过

        assert sessions.visible_to(session, guest.id) is True


def test_an_unknown_session_is_a_404(app):
    with app.app_context():
        with pytest.raises(NotFoundError):
            sessions.require("nope")

        assert sessions.get("nope") is None


def test_a_session_without_an_owner_is_visible(app):
    """库里早于归属约定的行（`owner_id` 为空）按 `owned_by` 的口径不拦。"""
    with app.app_context():
        course = _course()
        session = sessions.start(course, "")

        assert sessions.visible_to(session, "anyone") is True


# --- 票据（P3-F1）---


def test_the_ticket_opens_this_room_and_only_this_room(app):
    with app.app_context():
        owner = _user()
        first = sessions.start(_course(), owner.id)
        second = sessions.start(_course(), owner.id)

        ticket = sessions.ws_ticket(first, owner.id)["ticket"]

        assert tickets.consume(ticket, scope=first.id) == owner.id
        with pytest.raises(UnauthorizedError):
            tickets.consume(ticket, scope=second.id)


def test_a_stranger_cannot_get_a_ticket(app):
    """越权在**签票**时就挡掉：拿到票才发现进不去，客户端只会看到连接失败。"""
    with app.app_context():
        owner = _user()
        stranger = _user("路人")
        session = sessions.start(_course(), owner.id)

        with pytest.raises(NotFoundError):
            sessions.ws_ticket(session, stranger.id)


def test_an_ended_room_issues_no_ticket(app):
    with app.app_context():
        owner = _user()
        session = sessions.start(_course(), owner.id)
        sessions.end(session)

        with pytest.raises(ConflictError):
            sessions.ws_ticket(session, owner.id)


def test_the_ticket_belongs_to_the_joiner_not_the_owner(app):
    """票上的归属人是**来的人**：并发上限与在线名单都按他算。"""
    with app.app_context():
        owner = _user()
        guest = _user("旁听")
        session = sessions.start(_course(), owner.id)
        sessions.join(session, guest.id)

        ticket = sessions.ws_ticket(session, guest.id)["ticket"]

        assert tickets.consume(ticket, scope=session.id) == guest.id


# --- 结束 ---


def test_end_stamps_the_time_and_announces_it(app):
    """下课要落 `ended_at`（记录页算「上了多久」的唯一依据）并留一条 `state`。"""
    with app.app_context():
        owner = _user()
        session = sessions.start(_course(), owner.id)
        state.transition(session, state.LECTURE)  # 讲了一会儿再下课

        event = sessions.end(session, reason="讲完了")

        assert session.status == state.ENDED
        assert session.ended_at
        assert event["type"] == "state"
        assert event["status"] == state.ENDED
        assert event["seq"] == 1


def test_ending_twice_is_not_an_error(app):
    """重复点「下课」是幂等的成功 —— 第二次不该改写结束时刻。"""
    with app.app_context():
        owner = _user()
        session = sessions.start(_course(), owner.id)
        sessions.end(session)
        first_ended_at = session.ended_at

        sessions.end(session)

        assert session.ended_at == first_ended_at
        assert ClassroomSession.query.count() == 1


def test_ending_a_finished_room_from_another_path_moves_nothing(app):
    with app.app_context():
        owner = _user()
        session = sessions.start(_course(), owner.id)
        sessions.end(session)

        assert sessions.summary(session)["status"] == state.ENDED


# --- 列表与详情 ---


def test_active_of_lists_the_newest_first(app):
    with app.app_context():
        owner = _user()
        course = _course()
        first = sessions.start(course, owner.id)
        second = sessions.start(course, owner.id)

        ids = [row.id for row in sessions.active_of(owner.id)]

        assert ids == [second.id, first.id]


def test_summary_carries_the_title_and_the_online_count(app):
    with app.app_context():
        owner = _user()
        guest = _user("旁听")
        course = _course()
        session = sessions.start(course, owner.id)
        sessions.join(session, guest.id)

        payload = sessions.summary(session)

        assert payload["courseTitle"] == "机器学习入门"
        assert payload["presence"]["online"] == 2
        assert {item["name"] for item in payload["presence"]["members"]} == {"沈老师", "旁听"}


def test_timeline_is_rebuilt_from_the_course_not_from_the_row(app):
    """时间线是「这门课现在长什么样」的纯函数：页面改了，下一堂课就该按新时长讲。"""
    with app.app_context():
        owner = _user()
        course = _course(pages=2)
        session = sessions.start(course, owner.id)
        assert sessions.timeline_of(session).total_ms == 8000

        extra = CoursePage(
            course_id=course.id,
            page_no=3,
            chapter_no=1,
            kind="concept",
            title="新加的一页",
            status="ready",
            dsl={"pageNo": 3, "narration": [{"beatId": "p3-b1", "text": "一", "estSec": 2}]},
        )
        db.session.add(extra)
        db.session.commit()

        assert sessions.timeline_of(session).total_ms == 10000
        assert BoardStroke.query.count() == 0, "建时间线不写任何东西"
