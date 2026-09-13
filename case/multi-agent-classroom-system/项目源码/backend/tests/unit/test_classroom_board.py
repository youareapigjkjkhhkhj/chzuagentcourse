"""板书画笔（§2.4 / P3-A8 / P3-C3）。

板书是「一次性生成、每次课照抄」的：老师重开一堂课，同一页的白板必须长得
一模一样（P3-A8）。所以这里钉三件事：

- **一门课的一页只问模型一次**，第二个会话拿到的是抄本（不是另画一块）；
- **清洗**：坐标夹回 0~1、时长补齐、看不懂的笔画丢掉 —— 模型与浏览器送来的
  都当不可信输入；
- **失败即空板书**，不抛异常：没有板书课照上，画错一笔学生就记住了错的。
"""

from __future__ import annotations

import pytest

from app.extensions import db
from app.models import BoardStroke, ClassroomSession, Course, CoursePage
from app.services.classroom import board

pytestmark = pytest.mark.unit


@pytest.fixture()
def app(app_factory):
    """板书要走模型，所以本模块也全程离线桩。"""
    return app_factory(env={"LLM_PROVIDER": "mock"})


PAGE = {
    "pageNo": 3,
    "kind": "concept",
    "title": "梯度下降",
    "bullets": [{"text": "先定目标"}, {"text": "再往下走"}],
    "boardPlan": [
        {"tool": "polyline", "desc": "画一条从左上到右下的下降曲线", "atBeat": "p3-b1"},
        {"tool": "text", "desc": "在曲线最低点写上「最小值」", "atBeat": "p3-b2"},
    ],
}


def _session(course: Course | None = None) -> ClassroomSession:
    course = course or Course(title="机器学习入门", topic="机器学习入门", status="ready", dsl={})
    if course.id is None:
        db.session.add(course)
        db.session.commit()
    session = ClassroomSession(course_id=course.id, status="lecture")
    db.session.add(session)
    db.session.commit()
    return session


def _page_row(course: Course, page_no: int = 3, plan: list | None = None) -> CoursePage:
    row = CoursePage(
        course_id=course.id,
        page_no=page_no,
        chapter_no=1,
        kind="concept",
        title="梯度下降",
        status="ready",
        dsl={"pageNo": page_no, "title": "梯度下降", "boardPlan": plan if plan is not None else PAGE["boardPlan"]},
    )
    db.session.add(row)
    db.session.commit()
    return row


# --- 清洗（不可信输入）---


def test_points_are_clamped_into_range(app):
    """越界的点夹回 0~1，而不是丢掉整笔：一笔越界就丢掉整块板书就残了。"""
    with app.app_context():
        cleaned = board.clean([{"tool": "polyline", "points": [[-0.5, 1.4], [0.5, 0.5]]}])

        assert cleaned[0]["points"] == [[0.0, 1.0], [0.5, 0.5]]


def test_unknown_tools_are_dropped(app):
    """认不出的工具直接丢 —— 落库会被 CHECK 挡下（`tool IN (…)`）。"""
    with app.app_context():
        cleaned = board.clean([{"tool": "pen", "points": [[0.1, 0.1], [0.2, 0.2]]}])

        assert cleaned == []


def test_single_point_line_is_dropped(app):
    """一个点画不出线，也定不出箭头的方向。"""
    with app.app_context():
        assert board.clean([{"tool": "polyline", "points": [[0.1, 0.1]]}]) == []
        assert board.clean([{"tool": "arrow", "points": [[0.1, 0.1]]}]) == []


def test_text_stroke_needs_its_text(app):
    """写字的那一笔没有字，就等于没有。有字时给个默认位置。"""
    with app.app_context():
        assert board.clean([{"tool": "text", "points": [[0.1, 0.2]]}]) == []

        kept = board.clean([{"tool": "text", "text": "最小值"}])
        assert kept[0]["text"] == "最小值"
        assert kept[0]["points"], "没给位置也要有个默认落点，否则前端不知道画哪儿"


def test_duration_defaults_and_is_clamped(app):
    """每笔 `durMs` 默认 800（§2.4）；太快像闪一下，太慢会挡住下一笔。"""
    with app.app_context():
        default = board.clean([{"tool": "polyline", "points": [[0, 0], [1, 1]]}])
        assert default[0]["durMs"] == board.DEFAULT_DUR_MS

        fast = board.clean([{"tool": "polyline", "points": [[0, 0], [1, 1]], "durMs": 5}])
        assert fast[0]["durMs"] == board.MIN_DUR_MS

        slow = board.clean([{"tool": "polyline", "points": [[0, 0], [1, 1]], "durMs": 99999}])
        assert slow[0]["durMs"] == board.MAX_DUR_MS


def test_stroke_count_is_capped(app):
    """一块板书最多几十笔 —— 学生盯着的是讲解，不是一幅画。"""
    with app.app_context():
        many = [{"tool": "polyline", "points": [[0, 0], [1, 1]]} for _ in range(100)]

        assert len(board.clean(many)) == board.MAX_STROKES


def test_garbage_entries_are_skipped(app):
    """模型偶尔会混进 `null`、字符串、缺字段的项 —— 跳过它们，别让整块板书失败。"""
    with app.app_context():
        cleaned = board.clean(
            [None, "画一条线", {}, {"tool": "polyline", "points": [[0, 0], [1, 1]], "durMs": 800}]
        )

        assert len(cleaned) == 1


# --- 生成与去重（P3-A8）---


def test_ensure_generates_and_persists(app):
    """有 `boardPlan` 的页会生成笔画并落库，顺序按 `stroke_no`。"""
    with app.app_context():
        session = _session()
        strokes = board.ensure(session, PAGE)

        assert strokes, "离线桩应该能给出笔画"
        assert [item["strokeNo"] for item in strokes] == list(range(1, len(strokes) + 1))
        assert all(item["author"] == "teacher" for item in strokes)
        assert BoardStroke.query.filter_by(session_id=session.id, page_no=3).count() == len(strokes)


def test_second_call_does_not_call_the_model_again(app, monkeypatch):
    """同一页第二次进来直接用现成的 —— 既不重复问模型，也不会画出另一块白板。"""
    with app.app_context():
        session = _session()
        first = board.ensure(session, PAGE)

        def _boom(*args, **kwargs):
            raise AssertionError("有现成的笔画就不该再问模型")

        monkeypatch.setattr(board, "call_json", _boom)
        again = board.ensure(session, PAGE)

        assert [item["id"] for item in again] == [item["id"] for item in first]


def test_a_new_session_copies_the_same_board(app):
    """P3-A8：重开一堂课，同一页的板书**一模一样**（抄一份，不是另画一块）。

    这条也是「一门课的一页只生成一次」的另一半 —— 否则第二堂课的白板
    会和第一堂不一样，而学生手里的截图就对不上了。
    """
    with app.app_context():
        course = Course(title="机器学习入门", topic="机器学习入门", status="ready", dsl={})
        db.session.add(course)
        db.session.commit()
        first_session = _session(course)
        original = board.ensure(first_session, PAGE)

        second_session = _session(course)
        copied = board.ensure(second_session, PAGE)

        assert second_session.id != first_session.id
        assert copied, "第二个会话要有板书"
        assert [(item["tool"], item["points"], item["durMs"]) for item in copied] == [
            (item["tool"], item["points"], item["durMs"]) for item in original
        ]
        assert [item["id"] for item in copied] != [item["id"] for item in original], "是新行"


def test_force_regenerates(app):
    """`force=True` 时重画（老师在课上要求「重新画一遍」）。"""
    with app.app_context():
        session = _session()
        first = board.ensure(session, PAGE)

        again = board.ensure(session, PAGE, force=True)

        assert again, "重画也得有笔画"
        assert BoardStroke.query.filter_by(session_id=session.id, page_no=3).count() >= len(first)


def test_page_without_a_plan_has_no_board(app):
    """没有 `boardPlan` 的页就是没有板书 —— 不要为了「有点东西」让模型自由发挥。"""
    with app.app_context():
        session = _session()
        page = {**PAGE, "boardPlan": []}

        assert board.ensure(session, page) == []
        assert BoardStroke.query.count() == 0


def test_model_failure_means_an_empty_board(app, monkeypatch):
    """模型挂了就空着 —— 没有板书课照上，抛异常会让整堂课停住。"""
    from app.common.errors import AppError

    with app.app_context():
        session = _session()

        def _boom(*args, **kwargs):
            raise AppError("上游超时")

        monkeypatch.setattr(board, "call_json", _boom)

        assert board.ensure(session, PAGE) == []
        assert BoardStroke.query.count() == 0


# --- 客户端同步（`board_sync`）---


def test_client_strokes_append_with_the_me_author(app):
    """学生端教具条画的那几笔标 `author=me` —— 记录页要分得清谁画的。"""
    with app.app_context():
        session = _session()
        board.ensure(session, PAGE)

        strokes = board.append_client_strokes(
            session, 3, [{"tool": "curve", "points": [[0.2, 0.2], [0.4, 0.3]]}]
        )

        assert strokes[-1]["author"] == "me"
        assert strokes[-1]["strokeNo"] == len(strokes), "接在老师那几笔后面"


def test_client_strokes_are_cleaned_too(app):
    """浏览器送来的东西和模型送来的东西一样不可信 —— 同一套清洗。"""
    with app.app_context():
        session = _session()

        board.append_client_strokes(session, 3, [{"tool": "pen", "points": [[9, 9]]}])

        assert BoardStroke.query.count() == 0


def test_client_sync_with_nothing_usable_returns_the_existing_board(app):
    """清洗后一笔都不剩时返回现有板书 —— 前端照它重画，不必处理空响应。"""
    with app.app_context():
        session = _session()
        board.ensure(session, PAGE)

        strokes = board.append_client_strokes(session, 3, [])

        assert strokes, "现有的笔画还在"


# --- 预生成（后台任务）---


def test_pregeneration_runs_in_the_background(app):
    """老师翻到前一页时就可以先把下一页的板书算出来（§8 风险对策里的预生成）。"""
    from app.common.tasks import get_runner, wait_for

    with app.app_context():
        course = Course(title="机器学习入门", topic="机器学习入门", status="ready", dsl={})
        db.session.add(course)
        db.session.commit()
        session = _session(course)
        _page_row(course)

        assert board.submit_pregeneration(session.id, 3) is True
        assert wait_for(f"board:{session.id}:3", 10) is True

        assert BoardStroke.query.filter_by(session_id=session.id, page_no=3).count() > 0
        # 跑完就从登记表里摘掉，不留一条永远「在跑」的记录
        assert f"board:{session.id}:3" not in get_runner().running_keys()


def test_pregeneration_for_a_missing_page_is_a_no_op(app):
    """请求把板书预生成到一页不存在的页上：任务自己收场，不留异常。"""
    from app.common.tasks import wait_for

    with app.app_context():
        session = _session()

        assert board.submit_pregeneration(session.id, 99) is True
        assert wait_for(f"board:{session.id}:99", 10) is True

        assert BoardStroke.query.count() == 0


def test_pregeneration_is_not_queued_twice(app):
    """同一页已经在算了就不重复提交（`submit` 的既有语义）。"""
    from app.common.tasks import get_runner

    with app.app_context():
        session = _session()
        key = f"board:{session.id}:3"
        started = __import__("threading").Event()

        def _wait_for_the_flag():
            started.set()
            import time

            time.sleep(0.3)

        assert get_runner().submit(key, _wait_for_the_flag) is True
        started.wait(2)
        assert board.submit_pregeneration(session.id, 3) is False


# --- 读（`GET /board/{pageNo}`）---


def test_strokes_of_returns_the_page_in_order(app):
    """`GET /board/{pageNo}` 的数据源：本会话本页的笔画，按 `stroke_no` 升序。"""
    with app.app_context():
        session = _session()
        board.ensure(session, PAGE)

        strokes = board.strokes_of(session, 3)

        assert [item["strokeNo"] for item in strokes] == sorted(
            item["strokeNo"] for item in strokes
        )
        assert all(item["pageNo"] == 3 for item in strokes)


def test_stroke_payload_carries_the_text_field(app):
    """写字那一笔的 `text` 要能传到前端 —— §5 的表里原本没有这一列（建表时补的）。"""
    with app.app_context():
        session = _session()
        strokes = board.ensure(session, PAGE)

        written = [item for item in strokes if item["tool"] == "text"]
        assert written, "板书计划里有一笔是写字"
        assert all(item["text"] for item in written)
