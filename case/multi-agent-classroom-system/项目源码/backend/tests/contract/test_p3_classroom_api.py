"""P3-B4 课堂 HTTP 契约：§4.1 那八条路由的一份账本。

每条路由在这里至少出现一次，成功与失败两条路都落到具体的业务码上。四件事是
这个文件真正要守住的：

1. **P3-B4：没开始的课不能答题、不能举手**（40901）。`idle` 与 `lecture` 分开
   正是为了这一条 —— 开了一个教室不等于开始讲课。
2. **可见性是 404**（P3-F4 / AGENTS §4.1）：不存在、不是创建者也不是参与者，
   给的是同一句话。403 等于承认「这个 id 存在，只是不给你看」。
3. **HTTP 与 WS 是同一份逻辑**：举手 / 作答 / 下课这几条都只 `publish` 一次，
   所以 HTTP 这一侧改了什么，WS 上的人**看得到**（下面几条断言查的就是留档）。
4. **记录页不读事件留档**（P3-C2 / P3-C3）：留档到顶会砍最老的那一批，
   记录页读的是 `messages` / `board_strokes` / `quiz_attempts`。
   最后那组用例把留档删光，记录仍然完整 —— 那是这条口径唯一测得出来的方式。

模型一律是离线替身（AGENTS §23）：`LLM_PROVIDER=mock`，板书与插话都由替身
按固定脚本给，不联网、不需要密钥。
"""

from __future__ import annotations

import pytest

from app.common.identity import OWNER_HEADER
from app.extensions import db
from app.models import AgentRole, ClassroomSession, Course, CoursePage, SessionEvent, User
from app.services.classroom import recorder, runtime, sessions, state
from tests.contract.test_p1_api import data_of, envelope

pytestmark = pytest.mark.contract

ME = "u1"
GUEST = "u2"


@pytest.fixture()
def app(app_factory):
    """一台刚部署好的机器 + 两个用户 + 一位老师（模型走离线桩）。"""
    application = app_factory(env={"LLM_PROVIDER": "mock"})
    with application.app_context():
        db.session.add_all(
            [
                User(id=ME, name="小明", role="student"),
                User(id=GUEST, name="小红", role="student"),
                AgentRole(
                    code="shen",
                    name="沈老师",
                    role="teacher",
                    persona={"style": "沉稳", "systemHint": "你是主讲老师，负责讲解。"},
                    sort_order=1,
                ),
            ]
        )
        db.session.commit()
    return application


#: 归属人。用例一律带这个头，好让「别人的课」有办法验 —— 不带头时
#: `current_owner_id()` 会取本机种子里的第一位用户，两个用例会挤在一个人身上。
OWNER = {OWNER_HEADER: ME}


# --- 布景 ---


def _course(pages: list[dict] | None = None, *, owner: str = ME, title: str = "机器学习入门") -> Course:
    """建一门 ready 的课（与 P3 其余契约测试同一套口径）。"""
    course = Course(
        title=title, topic=title, status="ready", dsl={"chapters": []}, owner_id=owner or None
    )
    db.session.add(course)
    db.session.commit()
    for index, spec in enumerate(pages or [{}], start=1):
        beats = tuple(spec.get("beats") or ("第一句讲稿。", "第二句讲稿。"))
        quiz = spec.get("quiz")
        dsl = {
            "pageNo": index,
            "kind": "quiz" if quiz else spec.get("kind", "example"),
            "title": f"第 {index} 页",
            "bullets": [{"text": "本页要点"}],
            "narration": [
                {"beatId": f"p{index}-b{number}", "text": text, "estSec": 4}
                for number, text in enumerate(beats, start=1)
            ],
        }
        if quiz:
            dsl["quiz"] = quiz
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
    return course


#: 一页带题的 DSL。**选项是整句话、答案也是其中一句话**（§ 技术实现方案 161）——
#: 这不是随便造的数据：`option` 列曾经只有 16 个字符，而这里最短的一条有 17 个字，
#: 于是「答对」永远判成「答错」。用 "A"/"B" 造数据就永远测不出那类错。
QUIZ_OPTIONS = (
    "给人标注过的数据，让程序自己找规则",
    "把业务规则一条条写进程序里",
    "先写规则，再用数据验证规则对不对",
    "把历史数据存起来，用的时候直接查",
)
QUIZ_ANSWER = QUIZ_OPTIONS[0]
QUIZ_WRONG = QUIZ_OPTIONS[1]
QUIZ_EXPLAIN = "机器学习的核心是「从数据里找规则」，规则不写在代码里。"


def _quiz_page() -> dict:
    return {
        "quiz": {
            "stem": "下面哪一项最接近机器学习的做法？",
            "options": list(QUIZ_OPTIONS),
            "answer": QUIZ_ANSWER,
            "explain": QUIZ_EXPLAIN,
            "conceptTag": "什么是机器学习",
        }
    }


def _started(client, course_id: str) -> dict:
    """开一堂课，返回 `POST /sessions` 的 data。"""
    response = client.post(
        "/api/classroom/sessions", json={"courseId": course_id}, headers=OWNER
    )
    return data_of(response, 0)


def _lecture(session_id: str) -> ClassroomSession:
    """把课推到「正在上」—— 举手/答题要的是这个状态（P3-B4）。

    **要 commit**：状态改在测试的会话里，而下面每一个请求都在自己的应用上下文里
    开一个新会话 —— 只 flush 的话，请求那一侧读到的还是 `idle`。
    """
    session = sessions.require(session_id)
    state.transition(session, state.LECTURE, reason="测试：开始上课")
    db.session.commit()
    return session


def _join(session_id: str, user_id: str) -> None:
    """把第二个人记成参与者 —— 真实世界里这件事发生在 WS 的 `hello`
    （`runtime._on_hello` → `sessions.join`）。

    **必须先有这一步**：课堂只对创建者与参与者可见（P3-F4），没进来过的人
    连举手接口都看不见这堂课（404）—— 这正是要守的那条口径，不是障碍。
    """
    sessions.join(sessions.require(session_id), user_id, name=user_id)
    db.session.commit()


# --- 1. 开始上课 ---


def test_start_a_class_returns_a_usable_ticket(app, client):
    """`POST /sessions`：建会话 + 签票据 + 给时间线，三步在一条响应里。"""
    with app.app_context():
        course = _course([{}, {}])
        data = _started(client, course.id)

        assert data["sessionId"]
        assert data["status"] == state.IDLE  # 开教室不等于开始讲
        assert data["mode"] == "auto"
        assert [page["pageNo"] for page in data["timeline"]["pages"]] == [1, 2]
        # 票据要真能用：拿它去核销，换回的应该是开课的人（P3-F1）
        from app.services.voice import tickets

        assert tickets.consume(data["wsToken"], scope=data["sessionId"]) == ME


def test_start_a_class_needs_a_course_id(app, client):
    """没有 `courseId` 就是 40001 —— 不是 500，也不是悄悄建一门空课。"""
    with app.app_context():
        response = client.post("/api/classroom/sessions", json={}, headers=OWNER)
        assert envelope(response, 40001)


def test_start_a_class_i_cannot_see_is_404(app, client):
    """别人的课：404（与课程库同一个口径），不告诉他「这门课存在」。"""
    with app.app_context():
        theirs = _course(owner=GUEST)
        response = client.post(
            "/api/classroom/sessions", json={"courseId": theirs.id}, headers=OWNER
        )
        assert response.status_code == 404


def test_start_a_class_without_pages_is_refused(app, client):
    """一页都没有的课开不了：没有可讲的东西，`start` 就该拦下来。"""
    with app.app_context():
        course = Course(title="空课", topic="空课", status="ready", dsl={}, owner_id=ME)
        db.session.add(course)
        db.session.commit()

        response = client.post(
            "/api/classroom/sessions", json={"courseId": course.id}, headers=OWNER
        )
        assert envelope(response, 40001)


# --- 1.1 重签票据（刷新恢复 / 断线重连）---


def test_renew_ticket_hands_out_another_usable_one(app, client):
    """`POST /sessions/{id}/ticket`：P3-A10 刷新 / P3-A11 重连唯一拿票的路。

    票据是**一次性**的（`tickets.consume` 取走就没了），所以「刷新」这件事
    必然要再签一张。用例不只断言「拿到一串字符」，还要把它**真的核销一次** ——
    签出来一张核销不掉的票，等于前端刷新后卡在握手那一步。
    """
    with app.app_context():
        from app.services.voice import tickets

        course = _course()
        data = _started(client, course.id)
        session_id = data["sessionId"]
        tickets.consume(data["wsToken"], scope=session_id)  # 第一次接入用掉了

        body = data_of(client.post(f"/api/classroom/sessions/{session_id}/ticket", headers=OWNER))

        assert body["ttlSec"] == sessions.ws_ticket_ttl()
        assert tickets.consume(body["wsToken"], scope=session_id) == ME


def test_renew_ticket_of_an_ended_class_is_a_conflict(app, client):
    """下课之后不再签票（40901，与「课堂已结束」的其余几条同一个答复）。

    这一条存在的意义是**别把它做成「重新开一堂课」**：那样同一门课会开成一串
    互不相干的会话，课上到一半的位置、板书、举手队列全留在旧的那一堂里。
    要接着看走记录页（P3-6 的 `GET /record`），不是回到课堂。
    """
    with app.app_context():
        course = _course()
        data = _started(client, course.id)
        sessions.end(sessions.require(data["sessionId"]))

        response = client.post(f"/api/classroom/sessions/{data['sessionId']}/ticket", headers=OWNER)

        assert envelope(response, 40901)


def test_renew_ticket_of_a_stranger_is_404(app, client):
    """不是创建者也不是参与者 → 404，与其余课堂接口同一条口径。

    这一条尤其要紧：签票是**唯一**能把人放进课堂通道的那一步，
    它要是按 403 回答，就等于承认「这堂课存在，只是不给你看」。
    """
    with app.app_context():
        theirs = sessions.start(_course(owner=GUEST), GUEST)

        assert client.post(f"/api/classroom/sessions/{theirs.id}/ticket", headers=OWNER).status_code == 404
        assert client.post("/api/classroom/sessions/cs_nope/ticket", headers=OWNER).status_code == 404


# --- 2. 会话状态 ---


def test_get_session_gives_the_state_and_the_room(app, client):
    """`GET /sessions/{id}`：刷新页面后前端问的第一条。"""
    with app.app_context():
        course = _course()
        data = _started(client, course.id)
        _lecture(data["sessionId"])

        body = data_of(client.get(f"/api/classroom/sessions/{data['sessionId']}", headers=OWNER))

        assert body["id"] == data["sessionId"]
        assert body["status"] == state.LECTURE
        assert body["courseTitle"] == "机器学习入门"
        assert body["presence"]["online"] == 1  # 开课的人自己就在课堂里


def test_get_session_of_a_stranger_is_404(app, client):
    """不是创建者也不是参与者 → 404（P3-F4）。"""
    with app.app_context():
        course = _course(owner=GUEST)
        theirs = sessions.start(course, GUEST)

        assert client.get(f"/api/classroom/sessions/{theirs.id}", headers=OWNER).status_code == 404
        assert client.get("/api/classroom/sessions/cs_nope", headers=OWNER).status_code == 404


# --- 3. 下课 ---


def test_end_a_class_broadcasts_and_is_idempotent(app, client):
    """下课：落库 + 广播同一条 `state`，再点一次不改结束时刻。"""
    with app.app_context():
        course = _course()
        data = _started(client, course.id)

        body = data_of(
            client.post(
                f"/api/classroom/sessions/{data['sessionId']}/end",
                json={"reason": "讲完了"},
                headers=OWNER,
            )
        )

        assert body["session"]["status"] == state.ENDED
        assert body["event"]["type"] == "state"
        assert body["event"]["status"] == state.ENDED
        ended_at = sessions.require(data["sessionId"]).ended_at

        again = data_of(
            client.post(f"/api/classroom/sessions/{data['sessionId']}/end", json={}, headers=OWNER)
        )

        assert again["session"]["status"] == state.ENDED
        assert sessions.require(data["sessionId"]).ended_at == ended_at


# --- 4. 消息分页 ---


def test_messages_page_backwards(app, client):
    """`GET /messages`：`before` 往前翻一页，返回的仍是时间正序。"""
    with app.app_context():
        course = _course()
        data = _started(client, course.id)
        session_id = data["sessionId"]
        for index in range(5):
            recorder.add_message(
                session_id, speaker_code="me", text=f"第 {index} 条", speaker_kind="me"
            )

        first = data_of(
            client.get(f"/api/classroom/sessions/{session_id}/messages?size=2", headers=OWNER)
        )

        assert [item["text"] for item in first["items"]] == ["第 3 条", "第 4 条"]
        assert first["hasMore"] is True
        assert first["total"] == 5

        older = data_of(
            client.get(
                f"/api/classroom/sessions/{session_id}/messages?size=3"
                f"&before={first['items'][0]['ts']}",
                headers=OWNER,
            )
        )

        assert [item["text"] for item in older["items"]] == ["第 0 条", "第 1 条", "第 2 条"]
        assert older["hasMore"] is False


def test_messages_size_must_be_a_number(app, client):
    """`size=abc` 报 40001，而不是悄悄按默认值给 —— 前端会以为自己翻到底了。"""
    with app.app_context():
        course = _course()
        session_id = _started(client, course.id)["sessionId"]
        response = client.get(
            f"/api/classroom/sessions/{session_id}/messages?size=abc", headers=OWNER
        )
        assert envelope(response, 40001)


# --- 5. 举手（P3-A5 / P3-B4）---


def test_raise_hand_returns_my_position(app, client):
    """举手入队 → 返回位次，并且**广播一条 `hand_queue`**（WS 上的人看得到）。"""
    with app.app_context():
        course = _course()
        session_id = _started(client, course.id)["sessionId"]
        _lecture(session_id)
        _join(session_id, GUEST)

        mine = data_of(
            client.post(f"/api/classroom/sessions/{session_id}/raise-hand", json={}, headers=OWNER)
        )
        assert mine["position"] == 1

        theirs = data_of(
            client.post(
                f"/api/classroom/sessions/{session_id}/raise-hand",
                json={"action": "raise"},
                headers={OWNER_HEADER: GUEST},
            )
        )
        assert theirs["position"] == 2

        queue = recorder.hand_queue(session_id)
        assert [item["userId"] for item in queue["queue"]] == [ME, GUEST]
        assert recorder.replay(session_id, 0)[-1]["type"] == "hand_queue"


def test_raise_hand_in_an_idle_class_is_40901(app, client):
    """**P3-B4 点名的码**：还没开始的课，举手返回 40901。"""
    with app.app_context():
        course = _course()
        session_id = _started(client, course.id)["sessionId"]

        response = client.post(
            f"/api/classroom/sessions/{session_id}/raise-hand", json={}, headers=OWNER
        )

        assert envelope(response, 40901)


def test_lower_and_call_hand(app, client):
    """撤回与点名：两条都走同一批 service 函数。"""
    with app.app_context():
        course = _course()
        session_id = _started(client, course.id)["sessionId"]
        _lecture(session_id)
        _join(session_id, GUEST)
        client.post(f"/api/classroom/sessions/{session_id}/raise-hand", json={}, headers=OWNER)
        client.post(
            f"/api/classroom/sessions/{session_id}/raise-hand",
            json={},
            headers={OWNER_HEADER: GUEST},
        )

        called = data_of(
            client.post(
                f"/api/classroom/sessions/{session_id}/raise-hand",
                json={"action": "call"},
                headers=OWNER,
            )
        )
        assert called["called"]["userId"] == ME

        lowered = data_of(
            client.post(
                f"/api/classroom/sessions/{session_id}/raise-hand",
                json={"action": "lower"},
                headers={OWNER_HEADER: GUEST},
            )
        )
        assert lowered["lowered"] is True
        assert recorder.hand_queue(session_id)["queue"] == []


# --- 6. 测验作答（P3-A7）---


def test_quiz_submit_judges_and_explains(app, client):
    """答对 / 答错两条路：`quiz_result` 是判定结果本身，答案只在判完之后给。"""
    with app.app_context():
        course = _course([_quiz_page()])
        session_id = _started(client, course.id)["sessionId"]
        session = _lecture(session_id)

        # 停在第一页（有题的那页），题目下发时**不带答案与解析**
        assert data_of(client.get(f"/api/classroom/sessions/{session_id}", headers=OWNER))[
            "pageNo"
        ] == 1
        page = sessions.timeline_of(session).page(1)
        assert page is not None and page.quiz is not None
        assert page.quiz["answer"] == QUIZ_ANSWER  # 答案在服务端这边
        question = runtime.quiz_question(page)
        assert "answer" not in question and "explain" not in question

        wrong = data_of(
            client.post(
                f"/api/classroom/sessions/{session_id}/quiz-submit",
                json={"option": QUIZ_WRONG, "responseMs": 4200},
                headers=OWNER,
            )
        )
        assert wrong["correct"] is False
        assert wrong["branch"] == "remedial"
        assert wrong["explain"] == QUIZ_EXPLAIN
        assert wrong["answer"] == QUIZ_ANSWER

        right = data_of(
            client.post(
                f"/api/classroom/sessions/{session_id}/quiz-submit",
                json={"option": QUIZ_ANSWER},
                headers=OWNER,
            )
        )
        assert right["correct"] is True
        assert right["branch"] == "pass"

        # 作答**整句存下来**：截断过的选项是错数据（答对的那次也会对不上答案）
        attempts = recorder.quiz_attempts(session_id)
        assert [(item["option"], item["correct"]) for item in attempts] == [
            (QUIZ_WRONG, False),
            (QUIZ_ANSWER, True),
        ]



def test_quiz_submit_without_a_quiz_is_409(app, client):
    """这一页没有题：40902 之外的 40901/409 系，总之不是 200。"""
    with app.app_context():
        course = _course()  # 唯一一页没有 quiz
        session_id = _started(client, course.id)["sessionId"]
        _lecture(session_id)

        response = client.post(
            f"/api/classroom/sessions/{session_id}/quiz-submit",
            json={"option": "A"},
            headers=OWNER,
        )

        assert response.status_code == 409


# --- 7. 板书 ---


def test_board_of_a_page(app, client):
    """`GET /board/{pageNo}`：归一化坐标 + 笔序，没有板书的页给空数组。"""
    with app.app_context():
        from app.services.classroom import board

        course = _course()
        session_id = _started(client, course.id)["sessionId"]
        session = sessions.require(session_id)
        board.append_client_strokes(
            session,
            1,
            [{"tool": "polyline", "points": [[0.1, 0.1], [0.9, 0.9]], "durMs": 500}],
        )

        body = data_of(client.get(f"/api/classroom/sessions/{session_id}/board/1", headers=OWNER))
        assert body["pageNo"] == 1
        assert [stroke["strokeNo"] for stroke in body["strokes"]] == [1]
        assert body["strokes"][0]["tool"] == "polyline"

        empty = data_of(client.get(f"/api/classroom/sessions/{session_id}/board/2", headers=OWNER))
        assert empty["strokes"] == []


# --- 8. 课堂记录（P3-C2 / P3-C3 / P3-A14）---


def test_record_covers_the_whole_class(app, client):
    """记录页要的四样东西一次给全：字幕、消息、板书快照、作答。"""
    with app.app_context():
        from app.services.classroom import board

        course = _course([{}, _quiz_page()])
        session_id = _started(client, course.id)["sessionId"]
        session = _lecture(session_id)

        # 一堂课留下什么：讲稿消息（=字幕）、一条讨论区发言、一页板书、两次作答
        recorder.add_message(
            session_id,
            speaker_code="shen",
            speaker_kind="teacher",
            text="第一句讲稿。",
            page_no=1,
            beat_id="p1-b1",
        )
        recorder.add_message(
            session_id, speaker_code=ME, speaker_kind="me", text="老师这里没听懂"
        )
        board.append_client_strokes(
            session,
            1,
            [{"tool": "polyline", "points": [[0.1, 0.1], [0.5, 0.5]], "durMs": 500}],
        )
        recorder.record_quiz(
            session_id, course_id=course.id, page_no=2, option="A", correct=False
        )
        recorder.record_quiz(session_id, course_id=course.id, page_no=2, option="B", correct=True)
        client.post(f"/api/classroom/sessions/{session_id}/end", json={}, headers=OWNER)

        body = data_of(client.get(f"/api/classroom/sessions/{session_id}/record", headers=OWNER))

        assert body["session"]["status"] == state.ENDED
        assert body["courseTitle"] == "机器学习入门"
        # 字幕 = 有 beatId 的讲稿；讨论区那条不进字幕
        assert [item["text"] for item in body["subtitles"]] == ["第一句讲稿。"]
        assert len(body["messages"]) == 2
        assert [item["pageNo"] for item in body["boards"]] == [1]
        assert body["boards"][0]["strokes"][0]["author"] == "me"
        assert [item["correct"] for item in body["quizzes"]] == [False, True]
        assert [item["userId"] for item in body["participants"]] == [ME]
        # 名字现查（`users` 表），记录页要拿它写「谁上过这堂课」
        assert body["participants"][0]["name"] == "小明"
        assert body["stats"]["subtitles"] == 1
        assert body["stats"]["quizAttempts"] == 2
        assert body["stats"]["quizCorrect"] == 1
        assert body["stats"]["strokes"] == 1


def test_the_record_survives_the_event_log_being_pruned(app, client):
    """**留档可以砍，记录不能丢**（P3-C2 / P3-C3）。

    事件留档到顶会从头砍掉最老的十分之一 —— 砍掉的是「断线补发」这项能力，
    不是「记录」。所以这里把留档删光（模拟一趟很久的课），记录页仍要给全。
    """
    with app.app_context():
        course = _course()
        session_id = _started(client, course.id)["sessionId"]
        recorder.add_message(
            session_id,
            speaker_code="shen",
            speaker_kind="teacher",
            text="很早就讲过的一句。",
            page_no=1,
            beat_id="p1-b1",
        )
        recorder.publish(session_id, "subtitle", {"beatId": "p1-b1", "text": "讲过的"})
        assert recorder.replay(session_id, 0)  # 留档里本来是有东西的

        SessionEvent.query.filter_by(session_id=session_id).delete()
        db.session.commit()

        body = data_of(client.get(f"/api/classroom/sessions/{session_id}/record", headers=OWNER))

        assert [item["text"] for item in body["subtitles"]] == ["很早就讲过的一句。"]
        assert body["stats"]["messages"] == 1


def test_record_of_a_stranger_is_404(app, client):
    """记录页也守可见性（P3-F4）：别人上过的课，回看不了。"""
    with app.app_context():
        course = _course(owner=GUEST)
        theirs = sessions.start(course, GUEST)

        assert (
            client.get(f"/api/classroom/sessions/{theirs.id}/record", headers=OWNER).status_code
            == 404
        )
