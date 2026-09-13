"""P5-4 导出接口契约：§4.1 那五条路由的一份账本（F5-6）。

每条路由至少出现一次，成功与失败两条路都落到具体的业务码上。五件事是这个
文件真正要守住的：

1. **建完就返回，产物在别处生成**（P5-A5）：`POST` 只落一行 `queued` 就把请求
   放走，渲染由后台线程做（这里用 `sync_render` 夹具把它换成同步执行 ——
   契约测试要判的是「跑完之后是什么样」，不是「线程池有没有把任务接住」）。
2. **下载链接是签出来的、一次性的**（`_file_url` / `tickets`）：浏览器打开链接时
   不带 `X-Owner-Id`，所以归属写在 URL 里的票据上；票据用过即废，
   而且**一张票只对一次导出有效**（`scope=export:{id}`）。
3. **不可见的是 404**（AGENTS §4.1）：别人的导出、别人的课堂记录，
   答复都是同一句话。403 等于承认「这个 id 存在，只是不给你看」。
4. **不支持的格式当场拒绝**（40001），不留到渲染时才发现 ——
   课件导不出 `md`、课堂记录导不出 `pptx`，这两格在 `create()` 就挡住。
5. **到期是承诺**：`expires_at` 过了之后，即便行与文件都还在，
   下载也回 40902 而不是把文件发出去。

三种渲染器本身（PPTX 可编辑、HTML 自包含、PDF 页数）在
`tests/unit/test_exports_queue.py` 里逐条验过，这里只走用户真会走的那条路。
"""

from __future__ import annotations

import pytest

from app.common.identity import OWNER_HEADER
from app.extensions import db
from app.models import (
    AgentRole,
    ClassroomMessage,
    ClassroomSession,
    Course,
    CoursePage,
    Export,
    User,
)
from app.services.courses import store as courses_store
from app.services.exports import queue, store
from tests.contract.test_p1_api import data_of, envelope

pytestmark = pytest.mark.contract

ME = "u1"
GUEST = "u2"

#: 归属人。用例一律带这个头，好让「别人的导出」有办法验。
OWNER = {OWNER_HEADER: ME}
OTHER = {OWNER_HEADER: GUEST}

#: 一门三页的课：封面 / 概念 / 测验。三种渲染器都吃这套 DSL。
PAGES = [
    {"kind": "cover", "title": "什么是机器学习", "bullets": ["从数据里找规则"]},
    {"kind": "concept", "title": "监督学习", "bullets": ["有标注", "目标是预测"]},
    {"kind": "example", "title": "一个例子", "bullets": ["房价预测"]},
]


@pytest.fixture()
def app(app_factory):
    """一台刚部署好的机器 + 两个用户 + 一位老师（不跑生成，所以不需要模型替身）。"""
    application = app_factory()
    with application.app_context():
        db.session.add_all(
            [
                User(id=ME, name="小明", role="student"),
                User(id=GUEST, name="小红", role="student"),
                AgentRole(code="shen", name="沈老师", role="teacher", sort_order=1),
            ]
        )
        db.session.commit()
    return application


@pytest.fixture()
def sync_render(monkeypatch):
    """渲染在请求里同步跑完（同 P4 的 `sync_parse`）。

    异步那一版在 `tests/unit/test_exports_queue.py` 里跑真线程验过：
    `submit` 会进线程池、进度会被写进去。这里把它换掉，是为了让断言只关心
    「跑完之后接口给出的是什么」。
    """

    def _run(export_id: str) -> bool:
        queue.run(export_id)
        return True

    monkeypatch.setattr(queue, "submit", _run)
    return _run


# --- 布景 ---


def _course(pages: list[dict] | None = None, *, owner: str = ME, title: str = "机器学习入门") -> Course:
    """建一门 ready 的课（与 P3/P4 的契约测试同一套口径）。"""
    course = Course(
        title=title, topic=title, status="ready", dsl={"chapters": []}, owner_id=owner or None
    )
    db.session.add(course)
    db.session.commit()
    for index, spec in enumerate(pages or PAGES, start=1):
        dsl = {
            "pageNo": index,
            "kind": spec.get("kind", "concept"),
            "title": spec.get("title", f"第 {index} 页"),
            "bullets": [{"text": text} for text in spec.get("bullets") or ["本页要点"]],
            "narration": [
                {"beatId": f"p{index}-b1", "text": "第一句讲稿。", "estSec": 4},
                {"beatId": f"p{index}-b2", "text": "第二句讲稿。", "estSec": 4},
            ],
        }
        db.session.add(
            CoursePage(
                course_id=course.id,
                page_no=index,
                chapter_no=1,
                kind=dsl["kind"],
                title=dsl["title"],
                status="ready",
                dsl=dsl,
            )
        )
    db.session.commit()
    # 页面正文由 `rebuild_dsl` 汇总进 `courses.dsl_json`，而渲染读的正是那一份
    # （`queue._deck_of`）。手写一份 DSL 会绕开这条真实路径 —— 那样测出来的
    # 「导出成功」不作数，真实系统里导出的是一份空产物。
    courses_store.rebuild_dsl(course)
    db.session.commit()
    return course


def _session(course: Course, *, owner: str = ME) -> ClassroomSession:
    """开一堂课并留下两条发言：一条讲稿（进字幕栏）、一条提问（进讨论区）。"""
    session = ClassroomSession(course_id=course.id, owner_id=owner, status="lecture")
    db.session.add(session)
    db.session.flush()
    db.session.add_all(
        [
            ClassroomMessage(
                session_id=session.id,
                speaker_code="shen",
                speaker_kind="teacher",
                type="lecture",
                text="大家好，今天我们讲机器学习。",
                page_no=1,
                beat_id="p1-b1",
                ts="2026-09-13T10:00:00",
            ),
            ClassroomMessage(
                session_id=session.id,
                speaker_code=ME,
                speaker_kind="me",
                type="question",
                text="老师，规则是程序自己找的吗？",
                page_no=1,
                ts="2026-09-13T10:01:00",
            ),
        ]
    )
    db.session.commit()
    return session


def _create(client, course_id: str, **body):
    payload = {"format": "pptx", "scope": "course"}
    payload.update(body)
    return client.post(f"/api/courses/{course_id}/exports", json=payload, headers=OWNER)


def _done(client, course_id: str, **body) -> dict:
    """建一次导出并等它跑完，返回状态载荷。"""
    created = data_of(_create(client, course_id, **body), 0)
    return data_of(client.get(f"/api/exports/{created['exportId']}", headers=OWNER))


# --- 建 ---


def test_create_returns_a_row_without_rendering(app, client):
    """P5-A5：`POST` 只落一行 `queued` 就返回，渲染不在请求里发生。

    这一条**不能用 `sync_render` 验** —— 夹具的作用正是把渲染挪回请求里。
    所以这里把 submit 换成「什么都不做」，看到的才是真实的创建语义。
    """
    with app.app_context():
        course = _course()
        import app.services.exports.queue as queue_module

        original = queue_module.submit
        queue_module.submit = lambda export_id: True  # 假装丢进线程池了
        try:
            response = _create(client, course.id)
        finally:
            queue_module.submit = original

        assert response.status_code == 201
        data = data_of(response)
        assert data["exportId"] and data["status"] == "queued"
        assert data["progress"] == 0 and data["fileUrl"] == ""
        assert data["downloadable"] is False
        assert data["options"] == {"watermark": True, "withNotes": True, "withQuiz": True}


def test_pptx_export_runs_and_is_downloadable(app, client, sync_render):
    """F5-2 + F5-6：导出 → 状态是 `done` → 链接能下载到真字节。"""
    with app.app_context():
        course = _course()
        data = _done(client, course.id, format="pptx")

        assert data["status"] == "done" and data["progress"] == 100
        assert data["downloadable"] is True and data["sizeBytes"] > 0
        assert data["expiresAt"] and data["error"] == ""
        # 盘上路径不出现在载荷里：它回答不了用户的任何问题
        assert "filePath" not in data

        blob = client.get(data["fileUrl"])
        assert blob.status_code == 200
        # PPTX 是个 zip：拿它当「这是一份真文件」的判据，比查长度可靠
        assert blob.data[:2] == b"PK"


@pytest.mark.parametrize(
    "case",
    [
        ("html", "course", b"<!doctype html>"),
        ("pdf", "course", b"%PDF"),
        ("md", "record", None),
        ("pdf", "record", b"%PDF"),
    ],
    ids=["html-course", "pdf-course", "md-record", "pdf-record"],
)
def test_every_supported_format_round_trips(app, client, sync_render, case):
    """§4.1 那张表里能走通的每一格，都要真的下得下来一份文件。"""
    fmt, scope, head = case
    with app.app_context():
        course = _course()
        session = _session(course)
        body = {"format": fmt, "scope": scope}
        if scope == "record":
            body["sessionId"] = session.id

        data = _done(client, course.id, **body)
        assert data["status"] == "done", data["error"]
        blob = client.get(data["fileUrl"])
        assert blob.status_code == 200 and len(blob.data) > 0
        if head is not None:
            assert blob.data[: len(head)] == head


def test_a_record_export_carries_the_transcript(app, client, sync_render):
    """F5-5：课堂记录里得有人名与发言 —— 导出是给**读的人**看的。"""
    with app.app_context():
        course = _course()
        session = _session(course)
        data = _done(client, course.id, format="md", scope="record", sessionId=session.id)
        text = client.get(data["fileUrl"]).data.decode("utf-8")

        assert "沈老师" in text and "机器学习" in text
        assert "老师，规则是程序自己找的吗？" in text
        # 说话人是人名，不是 agent_roles.code
        assert "shen" not in text


# --- 下载链接 ---


def test_download_filename_is_a_readable_chinese_name(app, client, sync_render):
    """下载下来的文件名要能看懂：`机器学习入门-课件.pptx`。

    中文名走 RFC 5987 的 `filename*=UTF-8''…`（werkzeug 自己会编），
    而 `filename=` 那个 ASCII 兜底值会退成空或问号 —— 两个都在才算完整。
    """
    with app.app_context():
        course = _course(title="机器学习入门")
        data = _done(client, course.id, format="pptx")
        disposition = client.get(data["fileUrl"]).headers["Content-Disposition"]

        assert "attachment" in disposition
        assert "filename*=UTF-8''" in disposition
        assert "%E6%9C%BA%E5%99%A8%E5%AD%A6%E4%B9%A0%E5%85%A5%E9%97%A8" in disposition  # 机器学习入门
        assert ".pptx" in disposition


def test_a_filename_cannot_escape_into_a_path(app, client, sync_render):
    """课程标题是用户输入，而它会变成文件名 —— 分隔符必须被换掉。"""
    with app.app_context():
        course = _course(title="../../etc/机器学习")
        data = _done(client, course.id, format="pptx")
        disposition = client.get(data["fileUrl"]).headers["Content-Disposition"]

        assert ".." not in disposition and "etc/" not in disposition
        assert "attachment" in disposition


def test_the_download_link_is_one_time(app, client, sync_render):
    """票据用过即废：链接被抄走（历史记录、聊天、日志）也只能用一次。"""
    with app.app_context():
        course = _course()
        data = _done(client, course.id, format="pptx")

        assert client.get(data["fileUrl"]).status_code == 200
        again = client.get(data["fileUrl"])
        assert again.status_code == 401
        body = envelope(again, 40101)
        # 前端据此知道该做什么：回去重新问一次状态，拿一张新票
        assert body["data"]["details"]["fallback"] == "refetch"


def test_a_ticket_only_opens_the_export_it_was_issued_for(app, client, sync_render):
    """一张票只对一次导出有效（`scope=export:{id}`）：改一下 URL 换不到别人的产物。"""
    with app.app_context():
        course = _course()
        first = _done(client, course.id, format="pptx")
        second = _done(client, course.id, format="html")

        token = first["fileUrl"].split("token=", 1)[1]
        stolen = client.get(f"/api/exports/{second['exportId']}/download?token={token}")
        assert stolen.status_code == 401
        envelope(stolen, 40101)


def test_download_without_a_token_falls_back_to_the_request_header(app, client, sync_render):
    """不带票据时按请求头判归属 —— 本机部署下浏览器之外的调用方走这条。"""
    with app.app_context():
        course = _course()
        export_id = _done(client, course.id, format="pptx")["exportId"]
        blob = client.get(f"/api/exports/{export_id}/download", headers=OWNER)
        assert blob.status_code == 200 and blob.data[:2] == b"PK"


def test_a_garbage_token_is_refused(app, client, sync_render):
    """不认识的票据与过期的票据给同一句话：说清哪一步不对等于给出绕过的线索。"""
    with app.app_context():
        course = _course()
        export_id = _done(client, course.id, format="pptx")["exportId"]
        response = client.get(f"/api/exports/{export_id}/download?token=not-a-ticket")
        assert response.status_code == 401
        envelope(response, 40101)


def test_the_status_endpoint_mints_a_fresh_link_every_time(app, client, sync_render):
    """每次问状态都给一张新票 —— 前端因此不该缓存上一次拿到的那条链接。"""
    with app.app_context():
        course = _course()
        export_id = _done(client, course.id, format="pptx")["exportId"]

        first = data_of(client.get(f"/api/exports/{export_id}", headers=OWNER))["fileUrl"]
        second = data_of(client.get(f"/api/exports/{export_id}", headers=OWNER))["fileUrl"]

        assert first and second and first != second
        assert client.get(first).status_code == 200
        # 第二条链接不受影响：它们各是一张票
        assert client.get(second).status_code == 200


# --- 状态与历史 ---


def test_progress_is_reported_for_a_running_export(app, client):
    """进度可查（F5-6）：渲染中也能问出「到哪了」。"""
    with app.app_context():
        course = _course()
        row = Export(
            course_id=course.id, owner_id=ME, format="pdf", scope="course",
            status="running", progress=42,
        )
        db.session.add(row)
        db.session.commit()

        data = data_of(client.get(f"/api/exports/{row.id}", headers=OWNER))
        assert data["status"] == "running" and data["progress"] == 42
        assert data["downloadable"] is False and data["fileUrl"] == ""


def test_a_failed_export_reports_the_reason(app, client):
    """失败要留下**给人看的**那句话（`queue._fail`），而不是一个 500。"""
    with app.app_context():
        course = _course()
        row = Export(
            course_id=course.id, owner_id=ME, format="pdf", scope="course",
            status="failed", error="导出内容过大，试试少带讲稿",
        )
        db.session.add(row)
        db.session.commit()

        data = data_of(client.get(f"/api/exports/{row.id}", headers=OWNER))
        assert data["status"] == "failed" and "过大" in data["error"]

        download = client.get(f"/api/exports/{row.id}/download", headers=OWNER)
        assert download.status_code == 409
        envelope(download, 40902)


def test_history_is_newest_first_and_pages(app, client, sync_render):
    """F5-6：导出历史新的在前，`hasMore` 由多取一条算出来。"""
    with app.app_context():
        course = _course()
        ids = [_done(client, course.id, format=fmt)["exportId"] for fmt in ("pptx", "html", "pdf")]

        data = data_of(client.get(f"/api/courses/{course.id}/exports?size=2", headers=OWNER))
        assert [item["exportId"] for item in data["items"]] == [ids[2], ids[1]]
        assert data["hasMore"] is True
        # 列表只回答「哪些能下」：链接要现签，所以这里不签（免得攒一堆没人用的票）
        assert all(item["downloadable"] for item in data["items"])
        assert all(item["fileUrl"] == "" for item in data["items"])
        # 面板要按它渲染「能导什么」，所以跟着历史一起回去
        assert data["supported"]["course"] == ["pptx", "html", "pdf"]
        assert data["supported"]["record"] == ["md", "pdf"]

        rest = data_of(
            client.get(f"/api/courses/{course.id}/exports?size=2&page=2", headers=OWNER)
        )
        assert [item["exportId"] for item in rest["items"]] == [ids[0]]
        assert rest["hasMore"] is False


# --- 拒绝的几条路 ---


def test_a_format_that_does_not_fit_the_scope_is_refused_at_creation(app, client, sync_render):
    """课件导不出 `md`、课堂记录导不出 `pptx` —— 当场 40001，不留到渲染时。"""
    with app.app_context():
        course = _course()
        session = _session(course)

        bad = _create(client, course.id, format="md", scope="course")
        assert bad.status_code == 400
        body = envelope(bad, 40001)
        assert body["data"]["details"]["allowed"] == ["pptx", "html", "pdf"]

        worse = _create(client, course.id, format="pptx", scope="record", sessionId=session.id)
        assert worse.status_code == 400
        assert envelope(worse, 40001)["data"]["details"]["allowed"] == ["md", "pdf"]


def test_a_record_export_without_a_session_is_refused(app, client, sync_render):
    """课堂记录导出必须说清是哪一堂课。"""
    with app.app_context():
        course = _course()
        response = _create(client, course.id, format="md", scope="record")
        assert response.status_code == 400
        envelope(response, 40001)


def test_exporting_someone_elses_class_is_404(app, client, sync_render):
    """别人的课堂记录导不出来，而且答复与「这堂课不存在」一模一样（P3-F4）。"""
    with app.app_context():
        course = _course(owner=GUEST)
        session = _session(course, owner=GUEST)

        response = _create(client, course.id, format="md", scope="record", sessionId=session.id)
        assert response.status_code == 404
        envelope(response, 40401)

        # 归属判在**建的时候**：越权请求不该先排上队再变成一个失败行
        assert Export.query.count() == 0


def test_a_course_without_ready_pages_cannot_be_exported(app, client, sync_render):
    """还没有生成好的页面 → 40902（状态不对，不是请求不对）。"""
    with app.app_context():
        course = Course(title="空课", topic="空课", status="draft", owner_id=ME)
        db.session.add(course)
        db.session.commit()

        response = _create(client, course.id)
        assert response.status_code == 409
        body = envelope(response, 40902)
        assert body["data"]["details"]["courseId"] == course.id


def test_options_that_are_not_booleans_are_refused(app, client, sync_render):
    """`"false"` 是个真值 —— 一路放行下去就是「关了水印却拿到带水印的产物」。"""
    with app.app_context():
        course = _course()
        response = _create(client, course.id, options={"watermark": "false"})
        assert response.status_code == 400
        assert envelope(response, 40001)["data"]["details"]["option"] == "watermark"


def test_options_can_be_turned_off(app, client, sync_render):
    """关掉水印那一份**原样记进库**：看到一份没水印的 PDF 时能说清它从哪来。"""
    with app.app_context():
        course = _course()
        data = _done(client, course.id, format="pptx", options={"watermark": False, "withQuiz": False})
        assert data["options"]["watermark"] is False
        assert data["options"]["withQuiz"] is False
        assert data["options"]["withNotes"] is True  # 没传的键取缺省


# --- 归属与删除 ---


def test_someone_elses_export_is_404(app, client, sync_render):
    """不存在、越权 —— 同一句话（AGENTS §4.1）。"""
    with app.app_context():
        course = _course()
        export_id = _done(client, course.id, format="pptx")["exportId"]

        for response in (
            client.get(f"/api/exports/{export_id}", headers=OTHER),
            client.delete(f"/api/exports/{export_id}", headers=OTHER),
            client.get(f"/api/courses/{course.id}/exports", headers=OTHER),
        ):
            assert response.status_code == 404
            envelope(response, 40401)

        assert client.get("/api/exports/nope", headers=OWNER).status_code == 404


def test_delete_removes_the_row_and_the_file(app, client, sync_render):
    """F5-6：删掉一次导出 = 删那一行 + 盘上那份产物。"""
    with app.app_context():
        course = _course()
        export_id = _done(client, course.id, format="pptx")["exportId"]
        row = db.session.get(Export, export_id)
        path = store.file_of(row)
        assert path is not None

        data = data_of(client.delete(f"/api/exports/{export_id}", headers=OWNER))
        assert data["deletedFiles"] == 1
        assert db.session.get(Export, export_id) is None
        assert not path.exists()

        assert client.get(f"/api/exports/{export_id}", headers=OWNER).status_code == 404


def test_deleting_a_running_export_is_refused(app, client):
    """正在跑的那一次不删（40902）：后台线程手里攥着那一行，删了它会自己回来。"""
    with app.app_context():
        course = _course()
        row = Export(
            course_id=course.id, owner_id=ME, format="pdf", scope="course",
            status="running", progress=30,
        )
        db.session.add(row)
        db.session.commit()

        response = client.delete(f"/api/exports/{row.id}", headers=OWNER)
        assert response.status_code == 409
        body = envelope(response, 40902)
        assert body["data"]["details"]["progress"] == 30
        assert db.session.get(Export, row.id) is not None


def test_an_expired_artifact_is_not_handed_out(app, client, sync_render):
    """到期是承诺：行与文件都还在，也不发（清理任务只是还没扫到它）。"""
    with app.app_context():
        course = _course()
        export_id = _done(client, course.id, format="pptx")["exportId"]
        row = db.session.get(Export, export_id)
        row.expires_at = "2020-01-01T00:00:00Z"
        db.session.commit()

        data = data_of(client.get(f"/api/exports/{export_id}", headers=OWNER))
        assert data["downloadable"] is False and data["fileUrl"] == ""

        response = client.get(f"/api/exports/{export_id}/download", headers=OWNER)
        assert response.status_code == 409
        assert "过期" in envelope(response, 40902)["message"]


def test_deleting_a_course_takes_its_exports_with_it(app, client, sync_render):
    """P1-C3 那条「删完不留孤儿」延续到 P5：真删一门课，导出目录也得端掉。"""
    with app.app_context():
        course = _course()
        export_id = _done(client, course.id, format="pptx")["exportId"]
        path = store.file_of(db.session.get(Export, export_id))
        folder = store.physical_path(store.rel_dir(course.id))
        assert path is not None and folder.is_dir()

        courses_store.purge_course(course)
        db.session.commit()

        assert not path.exists() and not folder.exists()
        assert db.session.get(Export, export_id) is None
