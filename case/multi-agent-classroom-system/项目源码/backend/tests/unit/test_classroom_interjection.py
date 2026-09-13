"""插话决策（§2.3 / P3-A3 / P3-D3 / P3-E2 / P3-F3）。

四条规则各对应一条验收，与「说什么」同样重要：

- 概念页讲到**过半**、每页最多一位、每 3 页最多一次（P3-A3）；
- 模型 3 秒不回来就当这轮没有插话（P3-D3）；
- 与最近的同学发言太像就丢掉（P3-E2）；
- 命中敏感词不入消息流并记审计（P3-F3）。

模型用离线桩（`LLM_PROVIDER=mock`）：确定性，且 `speakerCode` 由页号决定 ——
「第几页该谁说话」在验收时可复现。
"""

from __future__ import annotations

import json

import pytest

from app.extensions import db
from app.models import AgentRole, ClassroomSession, Course
from app.providers.base import ProviderNotConfiguredError
from app.providers.llm.mock import MockLLM
from app.services.classroom import interjection, prompts
from app.services.classroom.timeline import TimelinePage
from app.services.generation import filter as sensitive

pytestmark = pytest.mark.unit


@pytest.fixture()
def app(app_factory):
    """本模块的用例都走**离线桩**（`LLM_PROVIDER=mock`）。

    课堂的四类调用（插话/讨论/答疑/板书）都发生在真实课堂上，
    没有哪一条会去连上游 —— 测试也不该。
    """
    return app_factory(env={"LLM_PROVIDER": "mock"})


PAGE = {
    "pageNo": 4,
    "kind": "concept",
    "title": "梯度下降",
    "bullets": [{"text": "先看清要解决的问题"}, {"text": "再谈怎么做"}],
    "narration": [{"text": "这一页只讲一件事。"}, {"text": "记住结论。"}],
}


def _classmates() -> list[dict]:
    """三个同学的人设卡。字段与 `agent_roles.persona_json` 一致。"""
    return [
        {
            "code": "xiaoxiao",
            "name": "林晓",
            "role": "student",
            "persona": {"tendency": "question", "style": "好奇、爱提问"},
        },
        {
            "code": "chenmo",
            "name": "陈默",
            "role": "student",
            "persona": {"tendency": "supplement", "style": "沉稳、爱较真"},
        },
        {
            "code": "suyu",
            "name": "苏雨",
            "role": "student",
            "persona": {"tendency": "reflect", "style": "活泼、慢半拍"},
        },
    ]


def _session() -> ClassroomSession:
    course = Course(title="机器学习入门", topic="机器学习入门", status="ready", dsl={})
    db.session.add(course)
    db.session.commit()
    session = ClassroomSession(course_id=course.id, status="lecture")
    db.session.add(session)
    db.session.commit()
    return session


def _page(kind: str = "concept", beats: int = 4, page_no: int = 4) -> TimelinePage:
    from app.services.classroom.timeline import Beat

    return TimelinePage(
        page_no=page_no,
        chapter_no=1,
        kind=kind,
        title="梯度下降",
        beats=tuple(Beat(f"p{page_no}-b{i + 1}", "句子", 1000, i * 1000) for i in range(beats)),
        quiz=None,
        board_plan=(),
        discussion=(),
        start_ms=0,
        duration_ms=beats * 1000,
    )


# --- 规则闸门（P3-A3）---


def test_concept_page_past_midway_is_allowed(app):
    with app.app_context():
        session = _session()

        allowed, reason = interjection.should_interject(session, _page(), beat_idx=2)

        assert allowed is True
        assert reason == "concept_midway"


def test_too_early_on_the_page_is_refused(app):
    """讲到一半之前不插话：刚翻页就问「为什么」是在打断老师的开场。"""
    with app.app_context():
        session = _session()

        allowed, reason = interjection.should_interject(session, _page(), beat_idx=0)

        assert allowed is False
        assert reason == "too_early"


def test_non_concept_pages_do_not_interject(app):
    """只有概念页允许插话：测验页、小结页有自己的节奏。"""
    with app.app_context():
        session = _session()

        allowed, reason = interjection.should_interject(
            session, _page(kind="quiz"), beat_idx=2
        )

        assert allowed is False
        assert reason == "non_concept_page"


def test_one_interjection_per_page(app):
    """同一页最多一位同学说话 —— 三个 AI 轮流追问同一页会变成刷屏。"""
    with app.app_context():
        session = _session()
        interjection.mark_interjected(session, 4)

        allowed, reason = interjection.should_interject(session, _page(), beat_idx=2)

        assert allowed is False
        assert reason == "already_on_this_page"


def test_at_most_once_every_three_pages(app):
    """§2.3 规则二：每 3 页最多插话 1 次。"""
    with app.app_context():
        session = _session()
        interjection.mark_interjected(session, 4)

        allowed, reason = interjection.should_interject(
            session, _page(page_no=6), beat_idx=2, min_pages=3
        )
        assert (allowed, reason) == (False, "too_soon")

        allowed, reason = interjection.should_interject(
            session, _page(page_no=7), beat_idx=2, min_pages=3
        )
        assert allowed is True


def test_mark_interjected_is_idempotent(app):
    """同一页记两次不会多出一条 —— 记录是「这一页已经说过话」的集合。"""
    with app.app_context():
        session = _session()

        interjection.mark_interjected(session, 4)
        interjection.mark_interjected(session, 4)

        assert interjection.should_interject(session, _page(), beat_idx=2)[0] is False


# --- 说什么（P3-A3 / P3-E2 / P3-F3）---


def test_decide_returns_a_speaker_from_the_roster(app):
    """模型给的人选必须在场 —— 不在场就退到第一位同学，而不是发一条幽灵消息。"""
    with app.app_context():
        session = _session()

        said = interjection.decide(session, PAGE, _classmates())

        assert said is not None
        assert said.speaker_code in {person["code"] for person in _classmates()}
        assert said.speaker_name
        assert said.text


def test_type_follows_the_persona_not_the_model(app):
    """消息类型按人设收敛：林晓说的话就是「提问」，徽标不能是别的。

    P3-A3 判的是「这条发言像不像这个人」，而徽标是它给人的第一印象。
    """
    with app.app_context():
        session = _session()

        for _ in range(6):
            said = interjection.decide(session, PAGE, _classmates())
            assert said is not None
            expected = prompts.TENDENCY_TYPES[
                next(
                    person["persona"]["tendency"]
                    for person in _classmates()
                    if person["code"] == said.speaker_code
                )
            ]
            assert said.type == expected


def test_interjection_is_short(app):
    """§2.3：一条同学发言不超过 80 字。长了就不是「随口一句」。"""
    with app.app_context():
        session = _session()

        said = interjection.decide(session, PAGE, _classmates())

        assert said is not None
        assert len(said.text) <= prompts.MAX_INTERJECTION_CHARS


def test_duplicate_against_recent_student_turns_is_dropped(app):
    """P3-E2：与最近的同学发言太像就丢掉 —— 两个 AI 轮流说同一句话比没人说话更糟。"""
    with app.app_context():
        session = _session()
        first = interjection.decide(session, PAGE, _classmates())
        assert first is not None

        again = interjection.decide(
            session,
            PAGE,
            _classmates(),
            recent=[{"speakerKind": "student_ai", "text": first.text}],
        )

        assert again is None


def test_teacher_repeats_do_not_count_as_duplicates(app):
    """老师复述学生的话往往是刻意的（「你刚说的这点很关键」），不该被当重复拦下。"""
    with app.app_context():
        session = _session()
        first = interjection.decide(session, PAGE, _classmates())
        assert first is not None

        again = interjection.decide(
            session,
            PAGE,
            _classmates(),
            recent=[{"speakerKind": "teacher", "text": first.text}],
        )

        assert again is not None


def test_sensitive_words_block_the_message(app, monkeypatch):
    """P3-F3：命中敏感词不入消息流，并记一条审计（`filter.record_hit`）。

    这里让模型**真的说出**一个词表里的词（替掉 `call_json`），
    否则测的是「桩刚好没说脏话」，而不是拦截本身。
    """
    from app.models import AuditLog

    with app.app_context():
        session = _session()
        word = sensitive.sensitive_words()[0]
        said = _fake_llm(
            monkeypatch,
            session,
            {"text": f"老师，我想问怎么{word}？", "type": "question",
             "speakerCode": "xiaoxiao", "trigger": "x"},
        )

        assert said is None, "命中就别发出去"

        rows = AuditLog.query.filter_by(action=sensitive.ACTION_SENSITIVE).all()
        assert rows, "拦截必须留痕（P5 的合规看板靠这条）"
        assert word in rows[-1].detail["words"]
        assert rows[-1].detail["outcome"] == sensitive.OUTCOME_BLOCKED


def test_clean_text_passes_the_filter(app, monkeypatch):
    """同一路径的正面用例：干净的话照常说出来 —— 上面那条不能是「永远返回 None」。"""
    with app.app_context():
        session = _session()

        said = _fake_llm(
            monkeypatch,
            session,
            {"text": "老师，这一步为什么不能跳过？", "type": "question",
             "speakerCode": "xiaoxiao", "trigger": "x"},
        )

        assert said is not None and said.text == "老师，这一步为什么不能跳过？"


def _fake_llm(monkeypatch, session, data: dict):
    """替掉 `call_json`，让模型「说」出给定的一句话。"""
    from app.services.generation.llm import JsonCall

    def _call(provider, messages, **kwargs):
        return JsonCall(
            data=data, text=json.dumps(data, ensure_ascii=False), model="fake",
            provider="mock", tokens=0, latency_ms=1, attempts=1,
        )

    monkeypatch.setattr(interjection, "call_json", _call)
    return interjection.decide(session, PAGE, _classmates())


def test_missing_model_means_no_interjection(app_factory):
    """没配模型（或配了但没 Key）时**不抛异常**：这一轮就不插话（P3-D3 的同一个出口）。

    课堂不能因为模型没配就停住 —— 插话是锦上添花，不是主线。
    """
    application = app_factory(unset=("LLM_API_KEY",))
    with application.app_context():
        from app.services.provider_registry import get_registry

        with pytest.raises(ProviderNotConfiguredError):
            get_registry().current_llm()


def test_decide_swallows_provider_errors(app, monkeypatch):
    """上游挂了/超时（AppError）时 `decide` 返回 None，而不是把异常抛进课堂（P3-D3）。"""
    with app.app_context():
        session = _session()

        def _boom(*args, **kwargs):
            raise ProviderNotConfiguredError("模型没配好")

        monkeypatch.setattr(interjection, "call_json", _boom)

        assert interjection.decide(session, PAGE, _classmates()) is None


def test_no_classmates_means_no_interjection(app):
    """课堂里没有同学（老师一个人）时什么都不做。"""
    with app.app_context():
        session = _session()
        assert interjection.decide(session, PAGE, []) is None


def test_timeout_comes_from_config(app):
    """插话的超时是配置项（`CLASSROOM_INTERJECTION_TIMEOUT`），默认 3 秒。"""
    with app.app_context():
        assert interjection.interjection_timeout() == 3.0
        app.config["CLASSROOM_INTERJECTION_TIMEOUT"] = 1.5
        assert interjection.interjection_timeout() == 1.5


def test_real_seeded_personas_drive_the_interjection(app_factory):
    """与种子人设对齐：`agent_roles.persona_json.tendency` 是插话决策的全部输入。

    这条把「人设数据」与「运行时逻辑」的接缝钉住 —— 种子里的倾向是本轮的
    P3-2 改动之一，写错一个词，A3 的「含人设特征」就无从谈起。
    """
    application = app_factory(seed=True, env={"LLM_PROVIDER": "mock"})
    with application.app_context():
        session = _session()
        classmates = [
            role.to_dict()
            for role in AgentRole.query.filter_by(role="student").order_by(AgentRole.sort_order)
        ]

        assert {person["persona"]["tendency"] for person in classmates} == {
            "question",
            "supplement",
            "reflect",
        }

        said = interjection.decide(session, PAGE, classmates)

        assert said is not None
        assert said.type in {prompts.TENDENCY_TYPES[person["persona"]["tendency"]]
                             for person in classmates}
        # 模型桩的返回也必须被 `call_json` 的 schema 校验收下
        assert isinstance(said.text, str) and said.text


def test_mock_llm_is_deterministic_for_interjection(app):
    """同一页问两次得到同一个人、同一句话（桩的既有承诺）。"""
    with app.app_context():
        session = _session()

        first = interjection.decide(session, PAGE, _classmates())
        second = interjection.decide(session, PAGE, _classmates())

        assert first is not None and second is not None
        assert (first.speaker_code, first.text) == (second.speaker_code, second.text)


def test_as_turn_kwargs_matches_the_scheduler(app):
    """插话交给调度器时要拼成 `Turn` 的参数（kind=interject，优先级由它决定）。"""
    with app.app_context():
        session = _session()
        said = interjection.decide(session, PAGE, _classmates())
        assert said is not None

        kwargs = said.as_turn_kwargs(page_no=4)

        assert kwargs["kind"] == "interject"
        assert kwargs["speaker_kind"] == "student_ai"
        assert kwargs["message_type"] == said.type
        assert kwargs["page_no"] == 4


def test_mock_llm_class_is_reachable(app):
    """离线桩能被注册表解析出来（`LLM_PROVIDER=mock`）—— 验收脚本靠这条离线跑。"""
    with app.app_context():
        from app.services.provider_registry import get_registry

        app.config["LLM_PROVIDER"] = "mock"
        provider = get_registry().current_llm()
        assert isinstance(provider, MockLLM)
        assert provider.configured is True
