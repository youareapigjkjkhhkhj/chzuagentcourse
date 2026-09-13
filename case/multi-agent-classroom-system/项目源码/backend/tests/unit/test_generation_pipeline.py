"""三段式生成管线：状态机、幂等、失败隔离与内容合规（P1 §3.1 / §4 / P1-F2）。

这套用例回答的是同一件事的很多面：**一次生成跑到一半出事，会留下什么**。

- 单页写不出来 → 那一页失败，其余照常（A8 / F1-10）
- 用户取消 → 已写好的页面留着，课程回到 draft（A9）
- 断点续跑 → 已经有成功版本的页面不再重写（幂等）
- 命中敏感词 → 整页重生成一次并留审计（F2）
- 大纲确认 → 停在 paused，等用户点了「确认」再继续（A3）

桩（`StubLLM`）不是 MockLLM 换个名字：管线的每条断言都要求
「第 3 页失败、其余 8 页照常」这种**可指名**的输入输出，
所以它按任务头分派、按页号造内容，并且能被测试指定某一页写坏。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import pytest

from app.models import (
    STEP_TYPES,
    AuditLog,
    CoursePageVersion,
    GenEvent,
    GenJob,
    ModelCall,
)
from app.providers.base import LLMProvider, LLMResult, ProbeResult
from app.providers.tts.mock import MockTTS
from app.services.courses import store
from app.services.generation.llm import OutputInvalidError
from app.services.generation.pipeline import (
    DEFAULT_OPTIONS,
    PIPELINE,
    job_progress,
    request_cancel,
    retry_step,
    run_job,
    start_job,
    step_of,
)
from app.services.generation.prompts import page_budget

pytestmark = pytest.mark.unit

_HEADER = re.compile(r"【任务】(\{[^\n]*\})")


# --- 管线声明 ---


def test_the_declaration_covers_every_step_type_and_sums_to_100(app):
    assert [step.type for step in PIPELINE] == list(STEP_TYPES)
    assert sum(step.weight for step in PIPELINE) == 100, "总进度要能走到 100%"
    assert all(step.title and step.fn for step in PIPELINE)


def test_write_step_declares_its_parallelism_and_the_pause_point(app):
    write = _declared("write")
    assert write.parallel == 3, "技术方案 §3.1：默认并发 3"
    assert _declared("outline").pause_after, "大纲确认落在 outline 之后（P1-A3）"
    assert _declared("tts").optional, "P1 不接语音，tts 是可跳过的"


def test_concurrency_is_configurable(app_factory):
    from app.services.generation.pipeline import concurrency

    app_factory(env={"GEN_CONCURRENCY": "5"})
    assert concurrency() == 5


# --- 任务与步骤 ---


def test_start_job_creates_one_step_per_pipeline_entry(app):
    rig = _rig(app)

    assert [step.type for step in rig.job.steps] == [step.type for step in PIPELINE]
    assert all(step.status == "wait" for step in rig.job.steps)
    assert rig.job.status == "queued"
    assert rig.course.status == "generating", "生成中的课程要能立刻在列表里看到"
    assert rig.job.options["pageCount"] == 12


# --- 一次跑完 ---


def test_a_full_run_produces_every_page_and_finishes(app):
    rig = _rig(app)

    run_job(rig.job.id, llm=rig.llm)

    pages = store.pages_of(rig.course)
    assert rig.job.status == "done"
    assert rig.job.progress == 100
    assert [page.page_no for page in pages] == list(range(1, len(pages) + 1))
    assert all(page.status == "ready" for page in pages)
    assert rig.course.status == "ready"
    assert rig.course.page_count == len(pages)
    # 25 = 封面页 meta 里写的设计时长（讲稿秒数合计另记在 dsl.meta.narrationSec）
    assert rig.course.duration_min == 25, "课程时长应取封面页的设计时长"


def test_a_plain_twelve_page_request_comes_out_as_twelve_pages(app):
    """P1-A1 的口径：库里最终是 12 页，系统补齐的那几页也算在内。

    桩按提示词给出的正文页数写（真模型也该这么做），所以这里量的是
    「预算 → 实际页数」这条链闭没闭：多算几页，A1 量的就是这个差。
    """
    plan = page_budget(DEFAULT_OPTIONS)
    rig = _rig(
        app,
        llm=StubLLM(chapters=plan["chapters"], pages_per_chapter=plan["content"] // plan["chapters"]),
    )

    run_job(rig.job.id, llm=rig.llm)

    pages = store.pages_of(rig.course)
    assert len(pages) == plan["total"] == 12
    assert rig.course.page_count == 12
    assert [page.kind for page in pages[:2]] == ["cover", "outline"]
    assert pages[-1].kind == "summary"


def test_every_page_satisfies_the_dsl_contract(app):
    """P1-A5 的口径：**每一页**都要有标题/副标题/要点/讲稿/图示描述。"""
    rig = _rig(app)

    run_job(rig.job.id, llm=rig.llm)

    for page in store.ready_pages(rig.course):
        dsl = page.dsl
        assert dsl["title"].strip()
        assert dsl["subtitle"].strip()
        assert len(dsl["bullets"]) >= 3, f"第 {page.page_no} 页要点不足"
        assert len(dsl["narration"]) >= 3, f"第 {page.page_no} 页讲稿不足"
        assert dsl["visual"]["desc"].strip()
        assert [beat["beatId"] for beat in dsl["narration"]] == [
            f"p{page.page_no}-b{i}" for i in range(1, len(dsl["narration"]) + 1)
        ]


def test_each_page_gets_a_version_row(app):
    """P1-C4：每次生成都追加版本，不覆盖。"""
    rig = _rig(app)

    run_job(rig.job.id, llm=rig.llm)

    pages = store.pages_of(rig.course)
    versions = CoursePageVersion.query.all()
    assert len(versions) == len(pages)
    assert {version.reason for version in versions} == {"generate"}
    assert {version.rev for version in versions} == {1}
    assert all(version.meta["promptVersion"] for version in versions)
    # 版本链上的内容与页面行上的一致：读页面不必 join 版本表（§5）
    for page in pages:
        version = CoursePageVersion.query.filter_by(page_id=page.id).one()
        assert version.dsl == page.dsl
        assert version.rev == page.rev


def test_steps_record_model_tokens_and_latency(app):
    """P1-B4：detail_json 里要能看到模型、token 与耗时。"""
    rig = _rig(app)

    run_job(rig.job.id, llm=rig.llm)

    write = step_of(rig.job, "write")
    assert write.detail["model"] == "stub-1"
    assert write.detail["latencyMs"] >= 0
    assert write.tokens > 0
    assert rig.job.total_tokens == sum(call.tokens for call in ModelCall.query.all())
    assert step_of(rig.job, "parse").detail["tokens"] > 0


def test_progress_grows_monotonically_to_100(app):
    rig = _rig(app)

    run_job(rig.job.id, llm=rig.llm)

    seen = [
        event.payload["progress"]
        for event in GenEvent.query.order_by(GenEvent.seq)
        if event.event in {"step.done", "job.done"}
    ]
    assert seen == sorted(seen), f"进度回退了：{seen}"
    assert seen[-1] == 100
    assert rig.job.progress == job_progress(rig.job) == 100


def test_events_are_archived_with_a_contiguous_seq(app):
    """AGENTS §17：SSE 的 seq 单调且可补发，依据是落库的那一份。"""
    rig = _rig(app)

    run_job(rig.job.id, llm=rig.llm)

    events = GenEvent.query.order_by(GenEvent.seq).all()
    assert [event.seq for event in events] == list(range(1, len(events) + 1))
    kinds = {event.event for event in events}
    assert {"job.start", "step.start", "step.done", "page.ready", "job.done"} <= kinds
    assert len([event for event in events if event.event == "page.ready"]) == len(
        store.pages_of(rig.course)
    )


def test_write_step_exposes_batches_for_the_sub_rows(app):
    """原型上 write 那一行下面是两行子步骤，按批次分组（技术方案 §4.1）。"""
    rig = _rig(app)

    run_job(rig.job.id, llm=rig.llm)

    batches = step_of(rig.job, "write").detail["batches"]
    assert len(batches) == 2, "9 页正文按 6 页一批分成两批"
    assert all(batch["label"].startswith("撰写第") for batch in batches)
    assert all(batch["status"] == "done" for batch in batches)
    assert sum(batch["total"] for batch in batches) == len(store.pages_of(rig.course))


# --- 语音合成（P2-A2 / P2-G3）---

#: 种子里老师那一档音色要的上游音色 ID。音色 ID 一律走配置注入，
#: 代码里不出现字面量（AGENTS §4.1）。
VOICE_ENV = {
    "VOLC_TTS_VOICE_TEACHER": "vendor-teacher",
    "VOLC_TTS_VOICE_HISTORY": "",
    "VOLC_TTS_VOICE_SCIENCE": "vendor-science",
}


def _seeded_rig(app_factory, *, env: dict | None = None):
    """一台灌过种子（内置音色 + 老师角色）的机器上跑一遍整条管线。

    种子是必须的：音色档来自 `voice_profiles` 表，没有它连「用哪个音色」都
    定不下来 —— 那不是语音这一步的问题，是「这台机器还没初始化」。
    """
    application = app_factory(seed=True, env={**VOICE_ENV, **(env or {})})
    return _rig(application)


def test_tts_is_skipped_when_no_voice_is_configured(app):
    """没有可用音色＝这节课没有声音，**不是失败**（P2-G3）。"""
    rig = _rig(app)

    run_job(rig.job.id, llm=rig.llm)

    tts = step_of(rig.job, "tts")
    assert tts.status == "skipped"
    assert "音色" in tts.detail["reason"]
    assert rig.job.status == "done", "语音缺席不该拖垮整课"


def test_tts_is_skipped_when_the_switch_is_off(app_factory):
    """`VOICE_ENABLED=false`：部署方关掉语音，课堂退化成纯文字（P2-G3）。"""
    rig = _seeded_rig(app_factory)
    rig.app.config["VOICE_ENABLED"] = False

    run_job(rig.job.id, llm=rig.llm)

    tts = step_of(rig.job, "tts")
    assert tts.status == "skipped"
    assert "VOICE_ENABLED" in tts.detail["reason"]
    assert rig.job.status == "done"


def test_the_tts_step_synthesizes_every_beat(app_factory):
    """音色配好了就真合成，且这一步只占 5% —— 页面的进度不受它影响。"""
    from app.models import AudioAsset

    rig = _seeded_rig(app_factory)

    run_job(rig.job.id, llm=rig.llm)

    tts = step_of(rig.job, "tts")
    assert tts.status == "done", tts.error
    assert tts.detail["beats"] > 0
    assert tts.detail["failed"] == 0
    assert tts.detail["synthesized"] == tts.detail["beats"]
    assert AudioAsset.query.count() == tts.detail["beats"]


def test_the_tts_step_reuses_the_audio_it_already_has(app_factory):
    """幂等：第二次跑同一门课，一句都不重合成（缓存命中，不重复花钱）。"""
    rig = _seeded_rig(app_factory)

    run_job(rig.job.id, llm=rig.llm)
    first = step_of(rig.job, "tts").detail

    retry_step(rig.job.id, step_of(rig.job, "tts").id, llm=rig.llm)

    again = step_of(rig.job, "tts").detail
    assert again["cached"] == first["synthesized"]
    assert again["synthesized"] == 0


def test_a_tts_that_fails_on_every_beat_is_reported_but_does_not_block(app_factory):
    """一句都没合出来是真失败（配错了），但**课照常交付**（P1-F1）。"""
    from app.services.provider_registry import get_registry

    rig = _seeded_rig(app_factory)
    get_registry().register(BrokenTTS())

    run_job(rig.job.id, llm=rig.llm)

    tts = step_of(rig.job, "tts")
    assert tts.status == "failed"
    assert "一句都没合成" in (tts.error or "")
    # 任务 failed、课程 ready、页面一页不少 —— 这三件事说的不是同一件事：
    # 「这次跑完了没有」/「这门课能不能上」/「内容写出来了没有」。
    # 语音一句都没合出来是要人去修配置的，所以任务该红；但它不该让学生没课上。
    assert rig.job.status == "failed"
    assert rig.course.status == "ready"
    assert store.pages_of(rig.course)
    assert all(page.status == "ready" for page in store.pages_of(rig.course))


# --- 大纲确认（P1-A3）---


def test_the_job_pauses_after_the_outline_until_confirmed(app):
    rig = _rig(app, options={"confirmOutline": True})

    run_job(rig.job.id, llm=rig.llm)

    assert rig.job.status == "paused"
    assert step_of(rig.job, "outline").status == "done"
    assert step_of(rig.job, "write").status == "wait"
    assert rig.llm.page_calls == [], "暂停期间不该写正文"
    pages = store.pages_of(rig.course)
    assert pages and all(page.status == "pending" for page in pages)

    run_job(rig.job.id, llm=rig.llm, resume=True)

    assert rig.job.status == "done"
    assert all(page.status == "ready" for page in store.pages_of(rig.course))


def test_page_numbers_are_allocated_by_the_server(app):
    """页号在**大纲阶段**就定死：工作台要显示「哪几页还没生成」（P1-A4）。"""
    rig = _rig(app, options={"confirmOutline": True})

    run_job(rig.job.id, llm=rig.llm)

    pages = store.pages_of(rig.course)
    assert [page.page_no for page in pages] == list(range(1, len(pages) + 1))
    assert [page.kind for page in pages[:2]] == ["cover", "outline"]
    assert pages[-1].kind == "summary"


# --- 页型与模式 ---


def test_each_chapter_ends_with_a_quiz_page(app):
    """P1-A6：每章末存在 quiz 页且含至少一题。"""
    rig = _rig(app)

    run_job(rig.job.id, llm=rig.llm)

    for chapter in store.outline_tree(rig.course)["chapters"]:
        kinds = [page["kind"] for page in chapter["pages"]]
        assert kinds[-1] == "quiz", f"第 {chapter['no']} 章末不是测验页：{kinds}"
        last = store.page_by_no(rig.course, chapter["pages"][-1]["pageNo"])
        assert len(last.dsl["quiz"]["options"]) == 4
        assert last.dsl["quiz"]["answer"]


def test_quiz_pages_are_absent_when_the_switch_is_off(app):
    rig = _rig(app, options={"quizPerChapter": False})

    run_job(rig.job.id, llm=rig.llm)

    assert all(page.kind != "quiz" for page in store.pages_of(rig.course))


def test_seminar_mode_allocates_a_debate_page(app):
    """P1-A12：研讨模式至少要有一页 debate。"""
    rig = _rig(app, options={"mode": "seminar"})

    run_job(rig.job.id, llm=rig.llm)

    debates = [page for page in store.pages_of(rig.course) if page.kind == "debate"]
    assert debates
    assert debates[0].dsl["topic"]
    assert len(debates[0].dsl["sides"]) >= 2


def test_discussion_questions_are_attached_to_chapters(app):
    rig = _rig(app)

    run_job(rig.job.id, llm=rig.llm)

    chapters = store.outline_tree(rig.course)["chapters"]
    assert chapters
    assert all(chapter["discussion"] for chapter in chapters)
    assert not [page for page in store.pages_of(rig.course) if page.kind == "discussion"]


# --- dsl_json ↔ 页面（P1-C1）---


def test_the_course_dsl_and_the_pages_agree_in_both_directions(app):
    rig = _rig(app)

    run_job(rig.job.id, llm=rig.llm)

    dsl = rig.course.dsl
    page_numbers = [page["pageNo"] for page in dsl["pages"]]
    assert page_numbers == [page.page_no for page in store.ready_pages(rig.course)]

    listed = {number for chapter in dsl["chapters"] for number in chapter["pages"]}
    front = {page.page_no for page in store.pages_of(rig.course) if page.chapter_no == 0}
    assert listed | front == set(page_numbers), "章里的页号与页面列表对不上"
    assert dsl["meta"]["pageCount"] == len(page_numbers)
    assert dsl["meta"]["audienceProfile"]["audience"]


# --- 失败隔离与重试 ---


def test_a_page_that_cannot_be_written_does_not_block_the_rest(app):
    rig = _rig(app, llm=StubLLM(fail_pages={3}))

    run_job(rig.job.id, llm=rig.llm)

    pages = {page.page_no: page for page in store.pages_of(rig.course)}
    assert pages[3].status == "failed"
    assert pages[3].dsl["error"]
    assert all(page.status == "ready" for number, page in pages.items() if number != 3)

    write = step_of(rig.job, "write")
    assert write.status == "failed"
    assert "第 3 页" in write.error
    assert rig.job.status == "failed"
    assert step_of(rig.job, "assemble").status == "done", "后面的步骤照跑"
    assert rig.course.status == "ready"


def test_retry_re_runs_only_the_pages_that_failed(app):
    rig = _rig(app, llm=StubLLM(fail_pages={3}))
    run_job(rig.job.id, llm=rig.llm)

    healthy = StubLLM()
    retry_step(rig.job.id, step_of(rig.job, "write").id, llm=healthy)

    assert healthy.page_calls == [3], "已经成功的页面不该重写（幂等）"
    assert store.page_by_no(rig.course, 3).status == "ready"
    assert rig.job.status == "done"
    assert rig.job.progress == 100


def test_retrying_a_finished_run_rewrites_nothing(app):
    rig = _rig(app)
    run_job(rig.job.id, llm=rig.llm)
    before = list(rig.llm.page_calls)

    retry_step(rig.job.id, step_of(rig.job, "write").id, llm=rig.llm)

    assert rig.llm.page_calls == before, "断点续跑：一页都不该重发"
    assert CoursePageVersion.query.count() == len(store.pages_of(rig.course))
    assert rig.job.status == "done"


# --- 取消（P1-A9）---


def test_cancel_stops_scheduling_and_keeps_what_is_written(app):
    rig = _rig(app, options={"concurrency": 1})
    rig.llm.on_call = lambda task: (
        request_cancel(rig.job.id) if task.get("pageNo") == 4 else None
    )

    run_job(rig.job.id, llm=rig.llm)

    assert rig.job.status == "canceled"
    assert rig.course.status == "draft", "取消后课程回到草稿（P1-A9）"
    ready = [page.page_no for page in store.pages_of(rig.course) if page.status == "ready"]
    assert ready == [1, 2, 3, 4], "取消前写好的页面要留着"
    assert rig.llm.page_calls == [1, 2, 3, 4], "取消后不该再发新的写页请求"


def test_an_unconfigured_generation_fails_the_first_step(app):
    """Key 填错了：第一步就得失败并说清原因，而不是停在「进行中」（P1-A2）。"""
    from app.providers.base import ProviderError

    rig = _rig(app)
    rig.llm.error = ProviderError(
        "上游返回 401", details={"ok": False, "error": "unauthorized"}
    )

    run_job(rig.job.id, llm=rig.llm)

    parse = step_of(rig.job, "parse")
    assert parse.status == "failed"
    assert parse.error
    assert rig.job.status == "failed"
    assert rig.job.error


# --- 内容合规（P1-F2）---


def test_a_sensitive_page_is_regenerated_once_and_audited(app):
    rig = _rig(app, llm=StubLLM(page_factory=_sensitive_once(3)))

    run_job(rig.job.id, llm=rig.llm)

    page = store.page_by_no(rig.course, 3)
    assert page.status == "ready", "重生成之后是干净的内容，应当发布"
    assert "制作炸弹" not in json.dumps(page.dsl, ensure_ascii=False)

    audit = AuditLog.query.one()
    assert audit.action == "sensitive_hit"
    assert audit.detail["outcome"] == "regenerated"
    assert "制作炸弹" in audit.detail["words"]
    assert audit.target == f"page:{page.id}"
    assert rig.llm.page_calls.count(3) == 2, "整页重生成一次，不是无限重试"


def test_a_page_that_stays_sensitive_is_not_published(app):
    rig = _rig(app, llm=StubLLM(page_factory=_sensitive_always(3)))

    run_job(rig.job.id, llm=rig.llm)

    page = store.page_by_no(rig.course, 3)
    assert page.status == "failed"
    assert "制作炸弹" not in json.dumps(page.dsl, ensure_ascii=False)
    audit = AuditLog.query.one()
    assert audit.detail["outcome"] == "blocked"
    assert step_of(rig.job, "write").status == "failed"


# --- 桩 ---


@dataclass
class Rig:
    course: Any
    job: GenJob
    llm: "StubLLM"
    options: dict = field(default_factory=dict)
    #: 跑这一趟的 app。少数用例要改配置（比如关掉语音总开关），
    #: 而配置是 app 级的 —— 顺手带着，省得每个用例再各拿一次 `current_app`。
    app: Any = None


def _rig(app, *, options: dict | None = None, llm: "StubLLM | None" = None) -> Rig:
    from app.services.generation.pipeline import DEFAULT_OPTIONS

    merged = {**DEFAULT_OPTIONS, **(options or {})}
    course = store.create_course(title="机器学习入门", topic="机器学习入门", options=merged)
    job = start_job(course, options=merged)
    return Rig(
        course=course,
        job=job,
        llm=llm or StubLLM(mode=merged.get("mode", "lecture")),
        options=merged,
        app=app,
    )


def _declared(step_type: str):
    return next(step for step in PIPELINE if step.type == step_type)


def _task_of(messages) -> dict:
    text = "\n".join(str(message.get("content", "")) for message in messages)
    found = _HEADER.search(text)
    if not found:
        raise AssertionError(f"提示词里没有任务头：{text[:200]}")
    return json.loads(found.group(1))


def _page_dsl(task: dict) -> dict:
    """一种页型的最小合法内容，每页的文案都不重样（便于定位是哪一页）。"""
    number = int(task["pageNo"])
    kind = task["kind"]
    data: dict = {
        "kind": kind,
        "title": str(task.get("title") or f"第 {number} 页"),
        "subtitle": f"PAGE {number}",
        "bullets": [{"text": f"第 {number} 页的要点 {index}"} for index in (1, 2, 3)],
        "narration": [{"text": f"第 {number} 页讲稿第 {index} 句。"} for index in (1, 2, 3)],
        "visual": {"type": "diagram", "desc": f"第 {number} 页的图示"},
    }
    if kind == "cover":
        data["meta"] = {"lecturer": "沈老师", "durationMin": 25, "audience": "大一新生"}
    elif kind == "outline":
        data["chapters"] = [{"no": 1, "title": "绪论", "pages": [2, 3]}]
    elif kind == "example":
        data["steps"] = [f"第 {number} 页的第一步", "第二步"]
    elif kind == "code":
        data["code"] = {"lang": "python", "content": "w -= lr * grad"}
    elif kind == "quiz":
        data["quiz"] = {
            "stem": f"第 {number} 页的题目",
            "options": ["选项甲", "选项乙", "选项丙", "选项丁"],
            "answer": "B",
            "explain": "因为步长过大。",
            "conceptTag": "学习率",
        }
    elif kind == "summary":
        data["question"] = "这节课最关键的结论是什么？"
    elif kind == "debate":
        data["topic"] = f"第 {number} 页的辩题"
        data["sides"] = [
            {"stance": "正方", "points": ["参数多表达强"]},
            {"stance": "反方", "points": ["数据同样关键"]},
        ]
    return data


def _sensitive_once(page_no: int) -> Callable[[dict, int], dict]:
    def factory(task: dict, count: int) -> dict:
        data = _page_dsl(task)
        if int(task["pageNo"]) == page_no and count == 1:
            data["bullets"][0]["text"] = "这里教你制作炸弹的完整步骤"
        return data

    return factory


def _sensitive_always(page_no: int) -> Callable[[dict, int], dict]:
    def factory(task: dict, count: int) -> dict:
        data = _page_dsl(task)
        if int(task["pageNo"]) == page_no:
            data["bullets"][0]["text"] = "这里教你制作炸弹的完整步骤"
        return data

    return factory


class StubLLM(LLMProvider):
    """按任务头作答的文本模型。

    比 `MockLLM` 多的三件事：按页号造**可指名**的内容、能指定某一页写坏、
    能在被调用时回调（测试借此在生成途中取消任务）。
    """

    def __init__(
        self,
        *,
        chapters: int = 2,
        pages_per_chapter: int = 2,
        mode: str = "lecture",
        fail_pages: set[int] | None = None,
        page_factory: Callable[[dict, int], dict] | None = None,
        on_call: Callable[[dict], None] | None = None,
    ) -> None:
        super().__init__("stub", configured=True, default_model="stub-1")
        self.chapters = chapters
        self.pages_per_chapter = pages_per_chapter
        self.mode = mode
        self.fail_pages = set(fail_pages or ())
        self.page_factory = page_factory
        self.on_call = on_call
        self.error: Exception | None = None
        self.calls: list[dict] = []
        self.page_calls: list[int] = []
        self.counts: dict[int, int] = {}

    def chat(self, messages, *, model=None, json_schema=None, timeout=None, **options) -> LLMResult:
        task = _task_of(messages)
        self.calls.append({**task, "timeout": timeout})
        if self.on_call is not None:
            self.on_call(task)
        if self.error is not None:
            raise self.error

        payload = self._payload(task)
        text = json.dumps(payload, ensure_ascii=False)
        return LLMResult(
            text=text,
            model=self.default_model,
            provider=self.name,
            usage={"prompt_tokens": 120, "completion_tokens": 200, "total_tokens": 320},
            finish_reason="stop",
        )

    def test(self) -> ProbeResult:
        return ProbeResult(ok=True, provider=self.name)

    # --- 内部 ---

    def _payload(self, task: dict) -> dict:
        name = task.get("task")
        if name == "profile":
            return {
                "audience": "大一新生",
                "difficulty": "入门",
                "durationMin": 25,
                "chapterCount": self.chapters,
                "style": "口语化、多举例",
                "objectives": ["理解梯度下降", "能写出一次迭代"],
            }
        if name == "outline":
            return {
                "title": "机器学习入门",
                "subtitle": "从零开始理解模型如何学习",
                "chapters": [self._chapter(no) for no in range(1, self.chapters + 1)],
            }
        if name == "discussion":
            number = int(task.get("chapterNo") or 1)
            return {"questions": [f"第 {number} 章的讨论问题一", f"第 {number} 章的讨论问题二"]}
        return self._page(task)

    def _chapter(self, no: int) -> dict:
        kinds = ("concept", "example", "figure", "code")
        return {
            "no": no,
            "title": f"第 {no} 章",
            "summary": f"第 {no} 章要讲的东西",
            "points": [f"第 {no} 章的讨论点"],
            "pages": [
                {
                    "title": f"第 {no} 章的第 {index} 页",
                    "kind": kinds[(no + index) % len(kinds)],
                    "points": [f"第 {no}-{index} 页的要点"],
                }
                for index in range(1, self.pages_per_chapter + 1)
            ],
        }

    def _page(self, task: dict) -> dict:
        number = int(task["pageNo"])
        self.page_calls.append(number)
        self.counts[number] = self.counts.get(number, 0) + 1
        if number in self.fail_pages:
            raise OutputInvalidError(f"第 {number} 页连续两次都不符合 Schema")
        if self.page_factory is not None:
            return self.page_factory(task, self.counts[number])
        return _page_dsl(task)


class BrokenTTS(MockTTS):
    """占住默认那个名字，但每次合成都炸。

    用来验「音色配了、服务商也在，就是一合就错」——真实世界里的样子是
    上游欠费、音色 ID 被停用。它必须是**逐句**炸（不是 `configured=False`）：
    这两种故障在管线里走的是两条完全不同的路（跳过 vs 失败）。
    """

    def __init__(self, name: str = "mock") -> None:
        super().__init__(name)

    def synthesize(self, *args, **kwargs):
        raise RuntimeError("上游拒绝了这次合成（测试桩）")
