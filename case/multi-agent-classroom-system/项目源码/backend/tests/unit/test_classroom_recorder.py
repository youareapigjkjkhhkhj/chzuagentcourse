"""课堂记录器（P3-B2 / P3-C1 / P3-C2 / P3-A5 / P3-A12）。

课堂里所有会留下来的东西都从这里写。三条规则只有单写者守得住，所以逐条钉：

1. `seq` 单调且不重 —— 客户端的去重规则是「同 `seq` 丢弃」，重号会丢掉**真事件**；
2. `messages.ts` 严格递增 —— 本机时钟粒度 15.6ms，同一批写的两条会撞在一起，
   撞了之后 `ORDER BY ts` 的先后就是「数据库碰巧怎么返回」；
3. `session_events` 有上限 —— 到顶砍最老的一批，砍的是补发能力，不是记录。

`publish` 返回的就是**存档的那一份**：断线补发的客户端拿到的必须和别人当时看到的一样。
"""

from __future__ import annotations

import pytest

from app.extensions import db
from app.models import (
    ClassroomMessage,
    ClassroomSession,
    Course,
    SessionEvent,
    User,
)
from app.services.classroom import recorder

pytestmark = pytest.mark.unit


def _session() -> ClassroomSession:
    course = Course(title="机器学习入门", topic="机器学习入门", status="ready", dsl={})
    db.session.add(course)
    db.session.commit()
    session = ClassroomSession(course_id=course.id, status="lecture")
    db.session.add(session)
    db.session.commit()
    return session


def _user(name: str = "小明", role: str = "student") -> User:
    user = User(name=name, role=role)
    db.session.add(user)
    db.session.commit()
    return user


def test_seq_starts_at_one_and_only_grows(app):
    """`seq` 从 1 开始、每次 +1（P3-B2）。"""
    with app.app_context():
        session = _session()

        first = recorder.publish(session, "state", {"status": "lecture"})
        second = recorder.publish(session, "speak", {"turnId": "t_1"})

        assert (first["seq"], second["seq"]) == (1, 2)


def test_publish_returns_exactly_what_is_archived(app):
    """发出去的与存档的是同一份 —— 补发要能替回放。

    两次组装（一次发、一次存）迟早会分叉，而分叉的表现是
    「补发的消息和别人当时看到的不是同一条」，这种 bug 几乎查不出来。
    """
    with app.app_context():
        session = _session()

        event = recorder.publish(session, "speak", {"turnId": "t_1", "text": "同学好"})

        row = SessionEvent.query.filter_by(session_id=session.id).one()
        assert {"type": row.type, **row.payload, "seq": row.seq,
                "eventId": row.id, "ts": row.created_at} == event


def test_payload_cannot_shadow_the_metadata(app):
    """载荷里若碰巧也有 `seq` / `eventId`，它们不该赢过元信息。"""
    with app.app_context():
        session = _session()

        event = recorder.publish(session, "speak", {"seq": 999, "eventId": "假的"})

        assert event["seq"] == 1
        assert event["eventId"] != "假的"


def test_replay_returns_only_what_the_client_is_missing(app):
    """`resumeFrom` 补发：只给 `seq > after_seq` 的，且按 `seq` 升序（P3-B2）。"""
    with app.app_context():
        session = _session()
        for index in range(5):
            recorder.publish(session, "subtitle", {"index": index})

        events = recorder.replay(session.id, 3)

        assert [item["seq"] for item in events] == [4, 5]
        assert [item["index"] for item in events] == [3, 4], "载荷也要原样带回来"


def test_replay_of_an_uptodate_client_is_empty(app):
    with app.app_context():
        session = _session()
        recorder.publish(session, "state", {})

        assert recorder.replay(session.id, 1) == []


def test_events_are_pruned_when_they_hit_the_limit(app):
    """到顶后砍掉最老的十分之一（P3-C2）—— 砍的是补发能力，不是记录。

    这是个「有界」的性质，不是「正好剩 N 条」：清理在写入过程中发生，
    所以稳态略低于上限（越过一次就砍一批）。三条断言分别对应
    「不涨破」「砍的是最老的」「新的还在」。
    """
    app.config["CLASSROOM_MAX_EVENTS"] = 20
    with app.app_context():
        session = _session()
        for index in range(25):
            recorder.publish(session, "subtitle", {"index": index})

        events = SessionEvent.query.filter_by(session_id=session.id)
        assert events.count() <= 20, "总量必须有上限，不能随课堂时长一直涨"
        assert events.filter(SessionEvent.seq <= 2).count() == 0, "最老的一批被清掉了"
        assert events.filter_by(seq=25).first() is not None, "最新的那条一定还在"


def test_pruning_does_not_touch_messages(app):
    """P3-C2 的后半句：清事件不影响记录页 —— 记录页读的是 `messages`。"""
    app.config["CLASSROOM_MAX_EVENTS"] = 3
    with app.app_context():
        session = _session()
        recorder.add_message(session, speaker_code="shen", text="上课")
        for index in range(6):
            recorder.publish(session, "subtitle", {"index": index})

        assert ClassroomMessage.query.filter_by(session_id=session.id).count() == 1


def test_message_ts_is_strictly_increasing(app):
    """P3-C1：同一批写下来的消息，`ts` 也必须一个比一个大。

    这不是洁癖：讲稿与字幕就是同一批写的，撞成同一个时间戳之后，
    `ORDER BY ts` 的先后由数据库自己决定 —— 课堂记录页的顺序就成了随机的。
    """
    with app.app_context():
        session = _session()

        stamps = [
            recorder.add_message(session, speaker_code="shen", text=f"第 {index} 句")["ts"]
            for index in range(30)
        ]

        assert stamps == sorted(stamps), "时间戳必须单调递增"
        assert len(set(stamps)) == len(stamps), "且不许重号"


def test_message_ts_can_be_given_explicitly(app):
    """讲稿消息的 `ts` 是它在时间线上的位置（beat 的起点），不是写库的那一刻。"""
    with app.app_context():
        session = _session()

        row = recorder.add_message(
            session, speaker_code="shen", text="第一句", ts="2026-09-13T00:00:00.000000Z"
        )

        assert row["ts"] == "2026-09-13T00:00:00.000000Z"


def test_message_dict_shape_matches_the_event(app):
    """`message` 事件的 `msg` 字段（§4.2）—— 前端按它渲染头像、徽标与时间。"""
    with app.app_context():
        session = _session()

        row = recorder.add_message(
            session,
            speaker_code="xiaoxiao",
            speaker_kind="student_ai",
            type="question",
            text="老师，为什么？",
            page_no=3,
            beat_id="p3-b1",
        )

        assert row["speaker"] == "xiaoxiao"
        assert row["speakerKind"] == "student_ai"
        assert row["type"] == "question"
        assert row["pageNo"] == 3
        assert row["beatId"] == "p3-b1"


def test_messages_page_backwards(app):
    """`?before=&size=` 是往上翻历史：返回的仍是时间正序，且告知还有没有更早的。"""
    with app.app_context():
        session = _session()
        for index in range(10):
            recorder.add_message(session, speaker_code="shen", text=f"第 {index} 句")

        page, has_more = recorder.messages(session.id, size=4)
        assert [item["text"] for item in page] == [f"第 {i} 句" for i in range(6, 10)]
        assert has_more is True

        older, has_more_older = recorder.messages(session.id, before=page[0]["ts"], size=6)
        assert [item["text"] for item in older] == [f"第 {i} 句" for i in range(0, 6)]
        assert has_more_older is False


def test_join_twice_keeps_one_row(app):
    """在线数数的是**人**：同一个人的两个标签页不该让「在线 2」变成「在线 3」。"""
    with app.app_context():
        session = _session()
        user = _user()

        recorder.join(session.id, user.id, role="owner", name=user.name)
        recorder.join(session.id, user.id, role="member", name=user.name)

        assert recorder.presence(session.id)["online"] == 1
        assert recorder.presence(session.id)["members"][0]["role"] == "owner", "身份不该被降级"


def test_leave_and_presence(app):
    """走了就下线，在线数跟着掉（P3-A12）。"""
    with app.app_context():
        session = _session()
        user = _user()

        recorder.join(session.id, user.id)
        assert recorder.presence(session.id)["online"] == 1

        recorder.leave(session.id, user.id)
        assert recorder.presence(session.id)["online"] == 0


def test_presence_names_come_from_the_user_table(app):
    """名单里要有名字，前端顶栏显示的是「谁在」，不是一串 id。"""
    with app.app_context():
        session = _session()
        user = _user("小明")

        recorder.join(session.id, user.id)
        members = recorder.presence(session.id)["members"]

        assert members[0]["name"] == "小明"


def test_sync_presence_drops_the_ghosts(app):
    """P3-B5：连接层说谁还活着，这里就把其余的对齐成离线。

    没有这条，顶栏那个「在线 5」会一直挂着一个已经关掉浏览器的人，
    直到服务重启 —— 而「在线数真实」正是 P3-A12 量的东西。
    """
    with app.app_context():
        session = _session()
        alive = _user("小明")
        ghost = _user("小刚")
        recorder.join(session.id, alive.id)
        recorder.join(session.id, ghost.id)

        dropped = recorder.sync_presence(session.id, [alive.id])

        assert dropped == [ghost.id]
        assert recorder.presence(session.id)["online"] == 1


def test_hand_queue_positions(app):
    """举手入队返回位次；同一个人的第二下不该多占一个位置（P3-A5）。"""
    with app.app_context():
        session = _session()
        first, second = _user("小明"), _user("小刚")

        a = recorder.raise_hand(session.id, first.id)
        b = recorder.raise_hand(session.id, second.id)
        again = recorder.raise_hand(session.id, first.id)

        assert (a["position"], b["position"]) == (1, 2)
        assert again["position"] == 1, "已经排着的人再举一次还是原位"
        assert len(recorder.hand_queue(session.id)["queue"]) == 2


def test_call_next_and_finish(app):
    """点名：队首从 `waiting` 变 `called`；问完了变 `done`（P3-A5 的闭环）。"""
    with app.app_context():
        session = _session()
        user = _user("小明")
        recorder.raise_hand(session.id, user.id)

        called = recorder.call_next(session.id)
        assert called is not None and called["status"] == "called"
        assert called["name"] == "小明", "点名要点到名字"
        assert recorder.hand_queue(session.id)["called"] is not None

        recorder.finish_called(session.id)
        assert recorder.hand_queue(session.id)["called"] is None


def test_lower_hand_removes_from_the_queue(app):
    """举手可以撤：撤掉之后再举手，位次重新排（不是记着老位置）。"""
    with app.app_context():
        session = _session()
        user = _user()
        recorder.raise_hand(session.id, user.id)

        assert recorder.lower_hand(session.id, user.id) is True
        assert recorder.hand_queue(session.id)["queue"] == []
        assert recorder.lower_hand(session.id, user.id) is False, "没举着的时候撤不动"

        assert recorder.raise_hand(session.id, user.id)["position"] == 1


def test_call_next_on_an_empty_queue(app):
    with app.app_context():
        session = _session()
        assert recorder.call_next(session.id) is None


def test_quiz_attempts_are_one_row_each(app):
    """答错后重答是第二行（P6.1 要分开算「第一次答对率」与「最终答对率」）。"""
    with app.app_context():
        session = _session()

        recorder.record_quiz(
            session.id, course_id=session.course_id, page_no=9,
            option="甲", correct=False, response_ms=4200,
        )
        recorder.record_quiz(
            session.id, course_id=session.course_id, page_no=9,
            option="乙", correct=True, response_ms=3100,
        )

        rows = recorder.quiz_attempts(session.id)
        assert [row["correct"] for row in rows] == [False, True]
        assert rows[0]["responseMs"] == 4200


def test_message_count_agrees_with_the_rows(app):
    """P3-C1：记录页数的条数与实际行数一致（前端看到的条数取自这里）。"""
    with app.app_context():
        session = _session()
        for index in range(7):
            recorder.add_message(session, speaker_code="shen", text=f"第 {index} 句")

        assert recorder.message_count(session.id) == len(recorder.all_messages(session.id)) == 7
