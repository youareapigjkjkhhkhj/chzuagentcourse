"""P3 数据模型测试（P3 §5 / P3-B2 / P3-C4）。

七张表里只有一张是「状态」，其余六张都是它的日志。断言也照这条线分开写：

- `classroom_sessions` 是**唯一的当前状态**：页号/beat 索引/时长/速度都在这一行上，
  所以「刷新能恢复」（P3-A10）与「服务重启后记录还能看」（P3-C3）才谈得上。
- 另外六张是**已经发生的事**：事件、消息、举手、作答、画笔画。它们的行会被更新
  （举手被点名、消息补上音频地址），但**不能被重排**——顺序错了，回放就不成立。
  所以 `session_events` 连 `updated_at` 都没有。

最后两条是横向的：删课要带走整堂课（P3-C4），而 §5 承诺的列与索引一个都不能少。
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.extensions import db

pytestmark = pytest.mark.unit

CLASSROOM_TABLES = {
    "classroom_sessions",
    "session_participants",
    "session_events",
    "messages",
    "hand_queue",
    "quiz_attempts",
    "board_strokes",
}

#: §5 逐字抄下来的列清单。这张表就是契约本身 —— 少一列、多一列都该在这里现形，
#: 而不是等到前端拿不到字段时才发现。
DOCUMENTED_COLUMNS = {
    "classroom_sessions": {
        "id",
        "course_id",
        "owner_id",
        "mode",
        "status",
        "current_page_no",
        "current_beat_idx",
        "elapsed_ms",
        "total_ms",
        "speed",
        "started_at",
        "ended_at",
        "state_json",
        "created_at",
        "updated_at",
    },
    "session_participants": {
        "id",
        "session_id",
        "user_id",
        "role",
        "online",
        "joined_at",
        "left_at",
        "created_at",
        "updated_at",
    },
    "session_events": {"id", "session_id", "seq", "type", "payload_json", "created_at"},
    "messages": {
        "id",
        "session_id",
        "speaker_code",
        "speaker_kind",
        "type",
        "text",
        "page_no",
        "beat_id",
        "audio_url",
        "quote_msg_id",
        "ts",
        "created_at",
        "updated_at",
    },
    "hand_queue": {
        "id",
        "session_id",
        "user_id",
        "ts",
        "called_at",
        "status",
        "created_at",
        "updated_at",
    },
    "quiz_attempts": {
        "id",
        "session_id",
        "course_id",
        "page_no",
        "node_id",
        "option",
        "correct",
        "response_ms",
        "ts",
        "created_at",
        "updated_at",
    },
    "board_strokes": {
        "id",
        "session_id",
        "course_id",
        "page_no",
        "stroke_no",
        "tool",
        "color",
        "width",
        "points_json",
        # §5 的表里没有这一列，是建表时补的（§5 注 3）：`text` 笔画要有个地方
        # 放它写的那行字。
        "text",
        "at_beat_id",
        "dur_ms",
        "author",
        "created_at",
        "updated_at",
    },
}


def test_seven_classroom_tables_exist(app):
    with app.app_context():
        names = set(inspect(db.engine).get_table_names())

    missing = CLASSROOM_TABLES - names
    assert not missing, f"缺少表：{missing}"


@pytest.mark.parametrize("table", sorted(DOCUMENTED_COLUMNS))
def test_columns_match_the_documented_schema(app, table: str):
    """§5 写下来的列就是契约。多一列少一列都在这里拦住。"""
    with app.app_context():
        columns = {c["name"] for c in inspect(db.engine).get_columns(table)}

    assert columns == DOCUMENTED_COLUMNS[table], f"{table} 与 §5 不一致"


def test_session_events_is_append_only(app):
    """事件表没有 `updated_at`：写下去的事不会变。

    加一列 `updated_at` 看着无害，但它的意思是「这行会被改」—— 而补发靠的是
    `seq` 顺序，一条被改过的事件和一个新事件在客户端看来没有区别。
    没有这一列，也就没有「改一下状态重发」这条歧义。
    """
    with app.app_context():
        columns = {c["name"] for c in inspect(db.engine).get_columns("session_events")}

    assert "created_at" in columns
    assert "updated_at" not in columns, "事件只增不改，不该有 updated_at"


def test_the_indexes_the_doc_lists_exist(app):
    """§5 末尾那四条。它们不是优化，是四个真实读路径：
    补发（session_id, seq）、消息流（session_id, ts）、举手队列（session_id, status）、
    按页取板书（course_id, page_no, stroke_no）。

    `(session_id, seq)` 是**唯一约束**而不是普通索引，两样分开查 ——
    它就在 §5 里被点名写了「唯一」。
    """
    with app.app_context():
        inspector = inspect(db.engine)

        def columns_of(table: str) -> set[tuple[str, ...]]:
            return {
                tuple(index["column_names"]) for index in inspector.get_indexes(table)
            }

        unique = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("session_events")
        }
        assert ("session_id", "seq") in unique, "补发靠 (session_id, seq) 唯一"

        assert ("session_id", "ts") in columns_of("messages")
        assert ("session_id", "status") in columns_of("hand_queue")
        assert ("course_id", "page_no", "stroke_no") in columns_of("board_strokes")


def test_session_events_unique_constraint_actually_holds(app):
    """唯一约束是真的在库里，不只是模型里写了一句（P3-B2）。"""
    from app.models import SessionEvent

    with app.app_context():
        session = _session()

        db.session.add(SessionEvent(session_id=session.id, seq=7, type="state"))
        db.session.commit()

        db.session.add(SessionEvent(session_id=session.id, seq=7, type="speak"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        assert SessionEvent.query.count() == 1


def test_seq_restarts_at_one_for_each_session(app):
    """`seq` 是**每个会话内**单调，不是全局序号：两堂课各自从 1 开始。

    这条看着像废话，但它决定了 `seq` 不能做成全局自增 ——
    那样补发时的 `seq > N` 就跨课了，客户端一重连就会捞到别人的事件。
    """
    from app.models import SessionEvent

    with app.app_context():
        course = _course()
        first = _session(course_id=course.id)
        second = _session(course_id=course.id)

        db.session.add(SessionEvent(session_id=first.id, seq=1, type="state"))
        db.session.add(SessionEvent(session_id=second.id, seq=1, type="state"))
        db.session.commit()

        assert SessionEvent.query.count() == 2


@pytest.mark.parametrize(
    ("model_name", "field", "bad_value"),
    [
        ("ClassroomSession", "status", "running"),  # 状态机里没有这个状态
        ("ClassroomSession", "mode", "replay"),
        ("SessionParticipant", "role", "teacher"),  # 老师不是「参与者」这个意义上的角色
        ("ClassroomMessage", "speaker_kind", "ai"),
        ("ClassroomMessage", "type", "note"),
        ("HandQueue", "status", "raised"),  # 是 waiting，不是 raised
        ("BoardStroke", "author", "student"),
        ("BoardStroke", "tool", "pen"),  # 是 polyline，不是 pen
    ],
)
def test_enum_columns_are_enforced(app, model_name: str, field: str, bad_value: str):
    """枚举值写错必须在库里被挡住 —— 这些值的另一端是前端的分支渲染。"""
    from app import models

    with app.app_context():
        session = _session()
        row = {
            "ClassroomSession": lambda: models.ClassroomSession(course_id=session.course_id),
            "SessionParticipant": lambda: models.SessionParticipant(session_id=session.id),
            "ClassroomMessage": lambda: models.ClassroomMessage(
                session_id=session.id, speaker_code="teacher", text="同学好"
            ),
            "HandQueue": lambda: models.HandQueue(session_id=session.id),
            "BoardStroke": lambda: models.BoardStroke(
                session_id=session.id, course_id=session.course_id, page_no=1, stroke_no=1
            ),
        }[model_name]()

        setattr(row, field, bad_value)
        db.session.add(row)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


@pytest.mark.parametrize(
    ("model_name", "kwargs"),
    [
        ("ClassroomSession", {"current_page_no": 0}),
        ("ClassroomSession", {"current_beat_idx": -1}),
        ("ClassroomSession", {"speed": 0}),
        ("QuizAttempt", {"page_no": 0}),
        ("BoardStroke", {"page_no": 0}),
        ("BoardStroke", {"dur_ms": -1}),
    ],
)
def test_impossible_numbers_are_rejected(app, model_name: str, kwargs: dict):
    """页号从 1 开始、beat 索引从 0 开始、时长非负。

    这些数会被用来做除法与切片（进度条、`beats[idx]`），
    负数与 0 页号在库里就该死掉，而不是留到运行时抛 IndexError。
    """
    from app import models

    with app.app_context():
        session = _session()
        base = {
            "ClassroomSession": {"course_id": session.course_id},
            "QuizAttempt": {"session_id": session.id, "course_id": session.course_id},
            "BoardStroke": {
                "session_id": session.id,
                "course_id": session.course_id,
                "stroke_no": 1,
            },
        }[model_name]

        db.session.add(models.__dict__[model_name](**{**base, **kwargs}))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_deleting_a_course_takes_the_whole_classroom_with_it(app):
    """P3-C4：删课级联带走 sessions/messages/strokes，不留孤儿。

    这一条不靠 ORM 逐个删（`db.session.delete(course)` 只发一条 DELETE），
    靠的是迁移里写的 `ON DELETE CASCADE` 加 `PRAGMA foreign_keys=ON`。
    所以它同时验证了两件事：级联写进迁移了，且外键是真开着的。
    """
    from app.models import (
        BoardStroke,
        ClassroomMessage,
        ClassroomSession,
        Course,
        HandQueue,
        QuizAttempt,
        SessionEvent,
        SessionParticipant,
    )

    with app.app_context():
        course = _course()
        session = _session(course_id=course.id)

        db.session.add(SessionParticipant(session_id=session.id, role="owner"))
        db.session.add(SessionEvent(session_id=session.id, seq=1, type="state"))
        db.session.add(
            ClassroomMessage(session_id=session.id, speaker_code="teacher", text="第一句")
        )
        db.session.add(HandQueue(session_id=session.id))
        db.session.add(QuizAttempt(session_id=session.id, course_id=course.id, page_no=1))
        db.session.add(
            BoardStroke(
                session_id=session.id,
                course_id=course.id,
                page_no=1,
                stroke_no=1,
                points=[[0.1, 0.1], [0.2, 0.2]],
            )
        )
        db.session.commit()

        db.session.delete(course)
        db.session.commit()

        for model in (
            ClassroomSession,
            SessionParticipant,
            SessionEvent,
            ClassroomMessage,
            HandQueue,
            QuizAttempt,
            BoardStroke,
        ):
            assert model.query.count() == 0, f"{model.__name__} 留下了孤儿行"
        assert Course.query.count() == 0


def test_deleting_one_session_leaves_the_other_alone(app):
    """一堂课结束不该动另一堂课 —— 级联要按行走，不是按表走。"""
    from app.models import ClassroomMessage, ClassroomSession

    with app.app_context():
        course = _course()
        kept = _session(course_id=course.id)
        dropped = _session(course_id=course.id)

        db.session.add(
            ClassroomMessage(session_id=kept.id, speaker_code="teacher", text="留着的")
        )
        db.session.add(
            ClassroomMessage(session_id=dropped.id, speaker_code="teacher", text="清掉的")
        )
        db.session.commit()

        db.session.delete(dropped)
        db.session.commit()

        assert ClassroomSession.query.count() == 1
        assert [m.text for m in ClassroomMessage.query.all()] == ["留着的"]


def test_board_points_round_trip_as_normalized_coordinates(app):
    """笔画坐标存 0~1 的归一化值，取出来还是同一个列表 —— 换屏幕尺寸重算即可。"""
    from app.models import BoardStroke

    with app.app_context():
        session = _session()
        points = [[0.12, 0.5], [0.4, 0.62], [0.88, 0.9]]
        db.session.add(
            BoardStroke(
                session_id=session.id,
                course_id=session.course_id,
                page_no=7,
                stroke_no=1,
                tool="curve",
                points=points,
                at_beat_id="p7-b2",
            )
        )
        db.session.commit()
        db.session.expire_all()

        stroke = BoardStroke.query.one()
        assert stroke.points == points
        assert stroke.to_dict()["atBeatId"] == "p7-b2"
        assert stroke.to_dict()["pageNo"] == 7


def test_session_state_round_trips_and_survives_corruption(app):
    """状态机那点东西（讨论轮次、当前说话者）存得进也取得出。

    最后一步是脏数据：库里一段坏 JSON 只该让这个字段读成空，
    不该让「刷新恢复课堂」这条路上抛异常 —— 那会变成一进课堂就 500。
    """
    from app.models import ClassroomSession

    with app.app_context():
        session = _session()
        session.state = {"rounds": {"低": 1, "适中": 2, "高": 3}, "speaker": "teacher"}
        db.session.commit()
        db.session.expire_all()

        assert db.session.get(ClassroomSession, session.id).state["speaker"] == "teacher"

        db.session.execute(
            db.text(
                "UPDATE classroom_sessions SET state_json = '{坏掉的' WHERE id = :id"
            ),
            {"id": session.id},
        )
        db.session.commit()
        db.session.expire_all()

        assert db.session.get(ClassroomSession, session.id).state is None


def test_to_dict_speaks_camel_case(app):
    """出参一律 camelCase（与既有模型同一个口径），前端不用做两套字段名。"""
    from app.models import (
        ClassroomMessage,
        ClassroomSession,
        HandQueue,
        QuizAttempt,
    )

    with app.app_context():
        session = _session()
        message = ClassroomMessage(
            session_id=session.id,
            speaker_code="linxiao",
            speaker_kind="student_ai",
            type="question",
            text="老师，这一步为什么可以这样变形？",
            page_no=3,
            quote_msg_id="m1",
        )
        db.session.add(message)
        db.session.add(HandQueue(session_id=session.id))
        db.session.add(
            QuizAttempt(
                session_id=session.id,
                course_id=session.course_id,
                page_no=9,
                option="B",
                correct=True,
                response_ms=4200,
            )
        )
        db.session.commit()

        assert set(ClassroomSession.query.one().to_dict()) >= {"courseId", "pageNo", "beatIdx"}
        assert message.to_dict()["quoteMsgId"] == "m1"
        assert message.to_dict()["speakerKind"] == "student_ai"
        assert HandQueue.query.one().to_dict()["calledAt"] == ""
        assert QuizAttempt.query.one().to_dict()["responseMs"] == 4200


# --- 造数据的小工具 ---


def _course():
    """一门最小可用的课，返回已提交的 Course。"""
    from app.models import Course

    course = Course(title="机器学习入门", topic="机器学习入门", status="ready")
    db.session.add(course)
    db.session.commit()
    return course


def _session(course_id: str = ""):
    """一堂刚开始的课，返回已提交的 ClassroomSession。"""
    from app.models import ClassroomSession

    session = ClassroomSession(course_id=course_id or _course().id, status="idle")
    db.session.add(session)
    db.session.commit()
    return session
