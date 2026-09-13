"""P4-5 工作台接口契约：§3.2 那五条路由的一条账（F4-10~F4-12）。

对着用户走的那条路验：**说一句话 → 事件流里看得到 Agent 说了什么、改了什么 →
消息列表里有一条完整的回复 → 回退之后那一段不再参与下一轮**。

- 技能调用的可见性（P4-A10）用事件流验：`agent.skill` / `agent.skill_done` 必须
  成对出现，且**课程真的变了**（大纲页数、页面 rev 都是库里的事实）。
- 回退（P4-A12）只用消息验：`seq` 之后的上下文消失了，**页面内容没跟着退**
  （这是刻意的语义，不是漏测）。
- 归属（P4-F4）用另一个人验：别人的课，五条路由都是同一个 404。

模型调用全走桩（`PlanLLM`）：这里要量的是接口把「一句话」变成了什么，
而不是模型写得好不好。桩按「这一问是不是要计划」分派，页面/测验照生成域的
那套造 —— 于是写页、定出处、落版本走的都是真链路。
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from app.common import tasks
from app.common.identity import OWNER_HEADER
from app.extensions import db
from app.models import ChatMessage, Course, SkillInvocation, User
from app.services.courses import store
from app.services.generation import pipeline
from app.services.workbench import agent as agent_service
from app.services.workbench import chat as chat_service
from tests.contract.test_p1_api import data_of
from tests.unit.test_generation_pipeline import StubLLM

pytestmark = pytest.mark.contract

ME = "u1"
GUEST = "u2"
OWNER = {OWNER_HEADER: ME}
OTHER = {OWNER_HEADER: GUEST}

_HEADER = re.compile(r"【任务】(\{[^\n]*\})")
#: 计划的提示词里只有它带这一段 —— 桩据此认出「这一问是要一个计划」。
_PLAN_MARK = "【可用技能】"


def _task_of(messages) -> dict:
    for message in messages:
        found = _HEADER.search(message.get("content") or "")
        if found:
            return json.loads(found.group(1))
    return {}


class PlanLLM(StubLLM):
    """工作台的桩：认「计划」那一问与出题那一问，其余交给生成桩。"""

    def __init__(self, *plans: dict, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.plans = list(plans)
        self.plan_prompts: list[str] = []

    def chat(self, messages, *, model=None, json_schema=None, timeout=None, **options):
        task = _task_of(messages)
        joined = "\n".join(str(item.get("content") or "") for item in messages)
        if task.get("task") == "quiz_skill":
            return self._as_result(
                {
                    "stem": "倒排索引为什么能加速检索？",
                    "options": ["因为它把词映射到文档", "因为它压缩了原文", "因为它缓存了结果", "因为它并发查询"],
                    "answer": "A",
                    "explain": "倒排索引把词映射到文档，查一个词就不必扫全部原文。",
                    "conceptTag": "倒排索引",
                }
            )
        if _PLAN_MARK in joined:
            self.plan_prompts.append(joined)
            plan = self.plans.pop(0) if self.plans else {"reply": "好的。", "actions": []}
            return self._as_result(plan)
        return super().chat(messages, model=model, json_schema=json_schema, timeout=timeout, **options)

    def _as_result(self, payload: dict):
        from app.providers.base import LLMResult

        return LLMResult(
            text=json.dumps(payload, ensure_ascii=False),
            model=self.default_model,
            provider=self.name,
            usage={"prompt_tokens": 100, "completion_tokens": 120, "total_tokens": 220},
            finish_reason="stop",
        )


@pytest.fixture()
def app(app_factory):
    application = app_factory()
    with application.app_context():
        db.session.add_all(
            [User(id=ME, name="小明", role="teacher"), User(id=GUEST, name="小红", role="teacher")]
        )
        db.session.commit()
    return application


@pytest.fixture(autouse=True)
def _reap_workers(app):
    yield
    tasks.shutdown_runner(app)


def _course(client, monkeypatch, *plans: dict, headers: dict | None = None) -> tuple[str, PlanLLM]:
    """跑一次真生成（桩），返回 `(courseId, 工作台的桩)`。"""
    llm = PlanLLM(*plans)
    monkeypatch.setattr(pipeline, "_provider", lambda: llm)
    # 工作台那一轮在后台线程里取模型 —— 拦在这里，测试才不会真的去连上游。
    monkeypatch.setattr(agent_service, "turn_llm", lambda: llm)
    created = data_of(
        client.post("/api/courses/generate", json={"topic": "机器学习入门"}, headers=headers or OWNER)
    )
    assert tasks.wait_for(created["jobId"], 30), "生成没在 30 秒内跑完"
    return created["courseId"], llm


def _say(client, course_id: str, text: str, *, ref_page_no: int | None = None, headers=None) -> dict:
    body = {"text": text}
    if ref_page_no:
        body["refPageNo"] = ref_page_no
    response = client.post(
        f"/api/courses/{course_id}/chat", json=body, headers=headers or OWNER
    )
    assert response.status_code in {200, 202}, response.get_json()
    return data_of(response)


def _turn_done(course_id: str, session_id: str, timeout: float = 30.0) -> None:
    from app.common.tasks import get_runner

    assert get_runner().wait(chat_service.channel_of(session_id), timeout), "这一轮没跑完"


def _frames(client, course_id: str, *, after: int = 0, headers=None) -> list[dict]:
    """把这一轮的 SSE 读成帧列表（终态之后流自己结束，所以这里不会挂住）。"""
    response = client.get(
        f"/api/courses/{course_id}/chat/stream?after={after}", headers=headers or OWNER
    )
    assert response.headers["Content-Type"].startswith("text/event-stream")
    out: list[dict] = []
    current: dict[str, Any] = {}
    for line in response.get_data(as_text=True).splitlines():
        if line.startswith("event: "):
            current["event"] = line[7:]
        elif line.startswith("data: "):
            current["data"] = json.loads(line[6:])
        elif line.startswith("id: "):
            current["id"] = int(line[4:])
        elif not line and current:
            out.append(current)
            current = {}
    return out


def _messages(client, course_id: str, *, headers=None) -> list[dict]:
    return data_of(client.get(f"/api/courses/{course_id}/chat/messages", headers=headers or OWNER))["items"]


# --- 技能清单 ---


def test_skills_are_listed_with_their_params(client, monkeypatch):
    """F4-12：七个技能都在，每条都带参数说明（前端据此提示用户怎么说话）。"""
    course_id, _ = _course(client, monkeypatch)
    data = data_of(client.get(f"/api/courses/{course_id}/skills", headers=OWNER))
    assert [item["name"] for item in data["items"]] == [
        "revise_outline",
        "rewrite_page",
        "add_quiz",
        "add_page",
        "remove_page",
        "change_tone",
        "summarize_material",
    ]
    assert all(item["params"] for item in data["items"])


# --- 一轮对话 ---


def test_one_sentence_rewrites_a_page_and_shows_up_in_the_stream(client, monkeypatch):
    """P4-A9/A10：说「改写第 3 页」→ 事件流里看得到回复、技能与页面变更。"""
    course_id, _ = _course(
        client,
        monkeypatch,
        {
            "reply": "好的，我把第 3 页改得更口语一些。",
            "actions": [{"skill": "rewrite_page", "args": {"pageNo": 3, "instruction": "更口语"}, "why": "用户要求"}],
        },
    )
    sent = _say(client, course_id, "第 3 页改口语一点", ref_page_no=3)
    _turn_done(course_id, sent["sessionId"])

    frames = _frames(client, course_id)
    events = [frame["event"] for frame in frames]
    assert events[0] == "agent.delta" and events[-1] == "agent.done"
    assert "agent.skill" in events and "agent.skill_done" in events
    assert "page.rewritten" in events
    # 每一帧都带同一条 assistant 消息的 id：前端靠它把字接到正确的气泡上
    assert {frame["data"]["messageId"] for frame in frames} == {sent["messageId"]}
    rewritten = next(frame for frame in frames if frame["event"] == "page.rewritten")
    assert rewritten["data"]["pageNo"] == 3 and rewritten["data"]["rev"] == 2

    items = _messages(client, course_id)
    assert [item["role"] for item in items] == ["user", "assistant"]
    assert items[1]["content"].startswith("好的，我把第 3 页改得更口语")
    assert "重写某页" in items[1]["content"] and items[1]["tokens"] > 0
    assert [call["skill"] for call in items[1]["skillCalls"]] == ["rewrite_page"]


def test_skill_calls_are_recorded_and_never_silent(client, monkeypatch):
    """P4-A10：操作卡读的那张表里，这次调用有结果、有耗时、有状态。"""
    course_id, _ = _course(
        client,
        monkeypatch,
        {
            "reply": "第三章的标题我改一下。",
            "actions": [
                {"skill": "revise_outline", "args": {"chapterNo": 1, "title": "检索与索引"}, "why": ""}
            ],
        },
    )
    sent = _say(client, course_id, "第一章改叫「检索与索引」")
    _turn_done(course_id, sent["sessionId"])

    rows = db.session.query(SkillInvocation).all()
    assert [row.skill for row in rows] == ["revise_outline"]
    assert rows[0].status == "ok" and rows[0].result["changed"] == ["title"]
    course = db.session.get(Course, course_id)
    assert (course.dsl or {})["chapters"][0]["title"] == "检索与索引"


def test_a_page_can_be_added_and_the_outline_grows(client, monkeypatch):
    """F4-12 的 add_page：加一页不只是插个空行 —— 它带着内容落库。"""
    course_id, _ = _course(
        client,
        monkeypatch,
        {
            "reply": "我在第 1 章后面补一页讲倒排索引。",
            "actions": [
                {"skill": "add_page", "args": {"chapterNo": 1, "title": "倒排索引", "kind": "concept"}, "why": ""}
            ],
        },
    )
    before = len(store.pages_of(db.session.get(Course, course_id)))
    sent = _say(client, course_id, "补一页讲倒排索引", ref_page_no=3)
    _turn_done(course_id, sent["sessionId"])

    pages = store.pages_of(db.session.get(Course, course_id))
    assert len(pages) == before + 1
    added = next(page for page in pages if page.title == "倒排索引")
    assert added.status == "ready" and added.dsl
    assert added.page_no == 4, "插在这一章最后一页之后"


# --- 回退 ---


def test_rollback_drops_the_context_but_not_the_pages(client, monkeypatch):
    """P4-A12：回退把 `seq` 之后的消息删掉，页面内容**不跟着回退**（这是设计）。"""
    course_id, _ = _course(
        client,
        monkeypatch,
        {"reply": "好的，改了。", "actions": [{"skill": "rewrite_page", "args": {"pageNo": 2, "instruction": "更短"}, "why": ""}]},
    )
    sent = _say(client, course_id, "第 2 页短一点", ref_page_no=2)
    _turn_done(course_id, sent["sessionId"])
    page = store.page_by_no(db.session.get(Course, course_id), 2)
    rev_after_rewrite = page.rev

    dropped = data_of(
        client.post(
            f"/api/courses/{course_id}/chat/rollback",
            json={"messageId": sent["messageId"]},
            headers=OWNER,
        )
    )
    assert dropped["removed"] == 1 and dropped["rolledBackTo"] == sent["seq"] - 1
    assert [item["role"] for item in _messages(client, course_id)] == ["user"]
    assert db.session.query(ChatMessage).count() == 1
    assert store.page_by_no(db.session.get(Course, course_id), 2).rev == rev_after_rewrite


def test_the_next_round_only_sees_what_survived_the_rollback(client, monkeypatch):
    """回退之后那一轮，模型看到的历史里没有回退掉的那段。"""
    course_id, llm = _course(
        client,
        monkeypatch,
        {"reply": "第一轮。", "actions": []},
        {"reply": "第二轮。", "actions": []},
    )
    first = _say(client, course_id, "第一句话")
    _turn_done(course_id, first["sessionId"])
    data_of(
        client.post(
            f"/api/courses/{course_id}/chat/rollback", json={"seq": 1}, headers=OWNER
        )
    )
    second = _say(client, course_id, "第二句话")
    _turn_done(course_id, second["sessionId"])

    prompt = llm.plan_prompts[-1]
    assert "第一句话" in prompt, "用户自己那条还在"
    assert "第一轮。" not in prompt, "被回退掉的回复不该再进上下文"


# --- 归属 ---


def test_another_users_course_is_a_404_on_every_route(client, monkeypatch):
    """P4-F4 / AGENTS §4.1：不存在与不是你的，答复是同一句话。"""
    course_id, _ = _course(client, monkeypatch)
    for response in (
        client.post(f"/api/courses/{course_id}/chat", json={"text": "改一下"}, headers=OTHER),
        client.get(f"/api/courses/{course_id}/chat/stream", headers=OTHER),
        client.get(f"/api/courses/{course_id}/chat/messages", headers=OTHER),
        client.post(f"/api/courses/{course_id}/chat/rollback", json={"seq": 1}, headers=OTHER),
        client.get(f"/api/courses/{course_id}/skills", headers=OTHER),
    ):
        assert response.status_code == 404, response.get_json()
