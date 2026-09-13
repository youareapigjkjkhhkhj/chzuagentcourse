"""离线课程桩（P1-G2）的用例。

桩是整个离线验收的地基：`LLM_PROVIDER=mock` 时，P1 的 A 类验收、以及 P2/P3
的两门示例课演示，全靠它产出一门**像样的课**。所以这里钉的

不是「桩写得好不好」，而是三件会悄悄坏掉的事：

1. **分派只认任务头**。认不出就返回 None，由 `MockLLM` 回落到 `_fill` ——
   P0 的老用例（拿一个任意 schema 要 JSON）靠这条活着。
   只有工作台那一轮是例外：那句提示词是手写的、没有任务头，桩按形状认
   （`fixture._PLAN_MARK`）—— 它还认不出来时，离线跑工作台永远只出 `reply`、
   一个技能都不调，`agent.skill` 那两帧就没人验过。
2. **确定性**。同一个输入永远同一个输出，且不许用内置 `hash()`
   （它对 str 每个进程加一次随机盐，会让验收脚本「昨天过、今天不过」）。
3. **大纲跟着提示词走**。章数与正文页数读的是提示词自己许下的预算
   （`prompts.page_budget` 算出来那句话），而不是桩里另写一份。
   哪天那句话改了措辞，这里会当场报 —— 而不是让离线课悄悄退化成 3 章 2 页。

写的断言尽量走**真提示词 + 真校验器**：桩的产物要能过 `schema.parse_*`，
才算「管线拿它当模型用不会炸」。
"""

from __future__ import annotations

import builtins
import json
import zlib
from typing import ClassVar

import pytest

from app.providers.llm import fixture
from app.providers.llm.mock import MockLLM
from app.services.generation import prompts, schema

pytestmark = pytest.mark.unit

TOPIC = "机器学习入门"

#: 12 页的讲授模式课堂，每章一页测验 —— 工作台与验收脚本的默认设置。
OPTIONS = {"pageCount": 12, "mode": "lecture", "quizPerChapter": True}

PROFILE = {
    "audience": "大一新生",
    "difficulty": "入门",
    "durationMin": 25,
    "chapterCount": 3,
    "style": "口语化、多举例",
    "objectives": ["知道什么是机器学习"],
}


def _page_task(kind: str, number: int = 3, title: str = "梯度下降") -> dict:
    return {"pageNo": number, "chapterNo": 1, "kind": kind, "title": title}


def _page_messages(kind: str, **kwargs) -> list[dict]:
    return prompts.page_messages(
        _page_task(kind, **kwargs), profile=PROFILE, outline={"title": TOPIC, "chapters": []}
    )


# --- 分派 ---


def test_an_unrecognised_call_returns_none():
    """认不出就交给上层回落 —— 这条是 P0 老用例的活路。"""
    plain = [{"role": "user", "content": "随便问一句，要一段 JSON"}]
    assert fixture.answer(plain, {"type": "object"}) is None

    unknown = [{"role": "user", "content": prompts.task_header(task="summarize")}]
    assert fixture.answer(unknown, {"type": "object"}) is None


def test_without_a_schema_there_is_nothing_to_fill():
    """不要 JSON 的调用根本不走桩（那是普通对话）。"""
    assert fixture.answer(_page_messages("concept"), None) is None


def test_every_task_the_pipeline_asks_for_is_handled():
    """四步的提示词各问一次，桩都得答得上来。"""
    cases = {
        "profile": prompts.profile_messages(TOPIC, OPTIONS),
        "outline": prompts.outline_messages(TOPIC, PROFILE, OPTIONS),
        "page": _page_messages("concept"),
        "rewrite": prompts.rewrite_messages(
            {"pageNo": 3, "kind": "concept", "title": "梯度下降"}, "讲得更口语一些", profile=PROFILE
        ),
        "discussion": prompts.discussion_messages(
            {"no": 1, "title": "认识机器学习"},
            [{"title": "什么是机器学习", "points": ["分界线在哪"]}],
            PROFILE,
        ),
    }
    for name, messages in cases.items():
        assert fixture.answer(messages, {"type": "object"}) is not None, name


# --- 输出是能用的课，而不只是合法 JSON ---


def test_the_outline_matches_the_budget_in_the_prompt():
    """章数与正文页数照着提示词许下的预算来，并且能过 `parse_outline`。"""
    plan = prompts.page_budget(OPTIONS)
    messages = prompts.outline_messages(TOPIC, PROFILE, OPTIONS)

    data = fixture.answer(messages, schema.schema_for_outline())
    assert data is not None

    chapters = data["chapters"]
    assert len(chapters) == plan["chapters"], f"提示词说 {plan['chapters']} 章"
    assert sum(len(chapter["pages"]) for chapter in chapters) >= plan["content"]
    assert all(chapter["pages"] for chapter in chapters), "不许有只有标题的空章"
    assert [chapter["no"] for chapter in chapters] == list(range(1, len(chapters) + 1))

    # 真校验器说了算：章数上限、正文页上限、页型枚举都在它手里
    parsed = schema.parse_outline(json.dumps(data, ensure_ascii=False))
    assert len(parsed["chapters"]) == plan["chapters"]
    for chapter in parsed["chapters"]:
        for page in chapter["pages"]:
            assert page["kind"] in schema.CONTENT_KINDS, page["kind"]


def test_the_outline_changes_with_the_requested_size():
    """12 页和 6 页要给出不同的章数 —— 桩如果永远回同一个大纲，验收就等于没测。"""
    small = prompts.outline_messages(TOPIC, PROFILE, {"pageCount": 6})
    large = prompts.outline_messages(TOPIC, PROFILE, {"pageCount": 18})

    small_data = fixture.answer(small, schema.schema_for_outline())
    large_data = fixture.answer(large, schema.schema_for_outline())

    assert len(large_data["chapters"]) > len(small_data["chapters"])


@pytest.mark.parametrize("kind", schema.PAGE_KINDS)
def test_every_page_kind_passes_the_validator(kind):
    """九种页型各来一页，页页都要过 `parse_page`（含通用规则）。

    这条是离线验收的成本底线：桩少给一个字段，A 类验收就会在「第 7 页生成
    失败」上停下，而那时真正的原因在桩里、报错却落在管线里。
    """
    messages = _page_messages(kind)
    data = fixture.answer(messages, schema.schema_for_kind(kind))
    assert data is not None, kind

    page = schema.parse_page(kind, json.dumps(data, ensure_ascii=False), page_no=3, chapter_no=1)

    assert page["kind"] == kind
    assert len(page["bullets"]) >= 3, "每页至少 3 条要点（UNIVERSAL_RULE）"
    assert len(page["narration"]) >= 3, "每页至少 3 句讲稿"
    assert page["visual"] and page["visual"]["desc"], "每页都要有图示描述"
    for index, beat in enumerate(page["narration"], start=1):
        assert beat["beatId"] == f"p3-b{index}", "beat 编号要与页号对齐"
        assert beat["estSec"] > 0


def test_the_page_keeps_the_title_the_pipeline_asked_for():
    """页标题由管线定，桩不能自己换一个 —— 大纲树与页面内容就靠它对上。"""
    data = fixture.answer(_page_messages("figure", title="光饱和点"), {"type": "object"})
    assert data["title"] == "光饱和点"
    assert "光饱和点" in data["visual"]["desc"]


def test_the_quiz_has_four_options_and_a_matching_answer():
    """四选一：前端按 2×2 排布，答案必须是四个选项之一（P1-A6 / P1-E4）。"""
    data = fixture.answer(_page_messages("quiz"), {"type": "object"})
    quiz = data["quiz"]

    assert len(quiz["options"]) == 4
    assert quiz["answer"] in quiz["options"]
    assert quiz["explain"], "有答案就得有解析"


def test_the_discussion_questions_land_on_the_chapter():
    """讨论问题要挂在**这一章**上，不能换成别的章。"""
    chapter = {"no": 2, "title": "核心方法"}
    messages = prompts.discussion_messages(
        chapter, [{"title": "梯度下降", "points": ["学习率决定什么"]}], PROFILE
    )

    data = fixture.answer(messages, {"type": "object"})
    parsed = schema.parse_discussion(json.dumps(data, ensure_ascii=False))

    assert len(parsed["questions"]) >= 2
    assert any("核心方法" in question for question in parsed["questions"]), parsed


# --- 重写（P1-A7）---


def test_the_rewrite_changes_the_script_and_keeps_the_title():
    """重写要「换一种说法」，不是把原话再吐一遍。

    如果桩把讲稿原样回一遍，A7 的「重写后讲稿变化率」就永远是绿的 ——
    等于这条验收没测。标题相反**必须**保持：重写的是同一页。
    """
    page = {"pageNo": 3, "chapterNo": 1, "kind": "concept", "title": "梯度下降"}
    draft = fixture.answer(_page_messages("concept"), {"type": "object"})
    rewritten = fixture.answer(
        prompts.rewrite_messages(page, "讲得更口语一些", profile=PROFILE), {"type": "object"}
    )

    assert rewritten["title"] == draft["title"]
    old = {beat["text"] for beat in draft["narration"]}
    new = {beat["text"] for beat in rewritten["narration"]}
    assert not (old & new), f"重写后的讲稿与原来重复：{old & new}"
    schema.parse_page("concept", json.dumps(rewritten, ensure_ascii=False), page_no=3)


def test_the_rewrite_reads_the_instruction():
    """换个指令要换一种说法，但同一个指令永远得到同一版（确定性）。"""
    page = {"pageNo": 3, "chapterNo": 1, "kind": "concept", "title": "梯度下降"}
    spoken = prompts.rewrite_messages(page, "讲得更口语一些", profile=PROFILE)
    formal = prompts.rewrite_messages(page, "换成书面语，写给论文用", profile=PROFILE)

    first = fixture.answer(spoken, {"type": "object"})
    again = fixture.answer(spoken, {"type": "object"})
    other = fixture.answer(formal, {"type": "object"})

    assert first == again
    assert first != other


# --- 确定性 ---


def test_the_same_input_gives_the_same_content():
    messages = _page_messages("concept")
    assert fixture.answer(messages, {"type": "object"}) == fixture.answer(
        messages, {"type": "object"}
    )


def test_the_fixture_never_uses_the_builtin_hash(monkeypatch):
    """不许用内置 `hash()`。

    `hash("x")` 在每个进程里都不一样（PYTHONHASHSEED 加盐），而验收脚本、
    种子、管线经常是三个进程 —— 用它会做出「同一个主题、两台机器上两门课」。
    这条把 `hash()` 换成一个会炸的桩：只要有人写回去，用例当场报。
    """

    def _boom(*_args: object) -> int:
        raise AssertionError("离线桩用了内置 hash()：换个进程就会产出另一门课")

    monkeypatch.setattr(builtins, "hash", _boom)

    for kind in schema.PAGE_KINDS:
        assert fixture.answer(_page_messages(kind), {"type": "object"}) is not None
    assert fixture.answer(
        prompts.outline_messages(TOPIC, PROFILE, OPTIONS), schema.schema_for_outline()
    )


def test_the_stable_index_is_crc32():
    """索引由 CRC32 算出来 —— 与 `hash()` 无关，跨进程一致。"""
    assert fixture._stable_index("机器学习", 3) == zlib.crc32("机器学习".encode()) % 3
    assert fixture._stable_index("任意输入", 1) == 0


# --- 与 MockLLM 的接线 ---


def test_mock_llm_turns_the_fixture_into_a_page():
    """桩是「另一半」，接线在 `MockLLM.chat` 上：给 schema 就该拿回一页。"""
    result = MockLLM().chat(_page_messages("concept"), json_schema=schema.schema_for_kind("concept"))
    page = schema.parse_page("concept", result.text)

    assert page["title"]
    assert result.model and result.provider == "mock"


def test_mock_llm_still_fills_an_unknown_schema():
    """认不出的调用回落 `_fill`：P0 的老用例（任意 schema）照样能过。"""
    llm = MockLLM()
    result = llm.chat(
        [{"role": "user", "content": "给我一段 JSON"}],
        json_schema={"type": "object", "properties": {"name": {"type": "string"}}},
    )
    assert json.loads(result.text) == {"name": "示例文本"}


# --- 材料在场时的出处与缺口（P4-A5 / P4-A8 的离线那一半）---


#: 一片材料的正文（`material_block` 里那段就是它）。两段话分属两个主题，
#: 用来区分「材料里有」与「材料里没有」。
CHUNK_GRADIENT = (
    "梯度下降是沿着当前点的负梯度方向走一小步，步长由学习率决定。"
    "学习率太大会来回震荡，太小则收敛得很慢。"
)
CHUNK_MATERIAL = [
    {
        "chunkId": "k_0001",
        "text": CHUNK_GRADIENT,
        "fileName": "讲义.md",
        "page": 12,
        "section": "第三章 > 3.2 梯度下降",
        "score": 0.82,
    }
]


def _page_with_material(kind: str, chunks=CHUNK_MATERIAL, **kwargs) -> list[dict]:
    return prompts.page_messages(
        _page_task(kind, **kwargs),
        profile=PROFILE,
        outline={"title": TOPIC, "chapters": []},
        materials=chunks,
    )


def test_a_page_about_material_quotes_it_verbatim():
    """标题在材料里找得到 → 出处是**那一块的原文连续片段**，不是拼出来的句子。"""
    from app.services.materials import citations

    messages = _page_with_material("concept", title="梯度下降")
    data = fixture.answer(messages, schema.schema_for_kind("concept"))

    assert [item["chunkId"] for item in data["sources"]] == ["k_0001"]
    quote = data["sources"][0]["quote"]
    # 用产品那把尺子核对：归一化后必须是原文的子串（P4-C2）
    assert citations._squeeze(quote) in citations._squeeze(CHUNK_GRADIENT)
    assert len(citations._squeeze(quote)) >= 20
    assert data["gaps"] == []


def test_a_page_the_material_does_not_cover_says_so():
    """材料里没有这一页讲的词 → 说缺口，而不是编一段看不出来的话（P4-A8）。"""
    messages = _page_with_material("concept", title="马尔可夫链")
    data = fixture.answer(messages, schema.schema_for_kind("concept"))

    assert data["sources"] == []
    assert data["gaps"] and "马尔可夫链" in data["gaps"][0]


def test_structural_pages_carry_no_citations_in_the_material_mode():
    """封面 / 大纲页 / 测验页不产出处也不说缺口：它们本来就没有依据（§5）。"""
    for kind in ("cover", "outline", "quiz"):
        data = fixture.answer(
            _page_with_material(kind, title="梯度下降"), schema.schema_for_kind(kind)
        )
        assert data["sources"] == [] and data["gaps"] == [], kind


def test_without_material_nothing_is_said_about_gaps():
    """没材料时（P1 的纯主题生成）不说「材料没写」—— 本来就没有材料。"""
    data = fixture.answer(_page_messages("concept"), schema.schema_for_kind("concept"))

    assert data["sources"] == [] and data["gaps"] == []


def test_the_caption_is_not_quoted():
    """围栏里那行「（出处：…）」是给模型看的线索，不是材料原文 —— 抄了就当不了引文。"""
    from app.services.materials import citations

    data = fixture.answer(_page_with_material("concept", title="梯度下降"), schema.schema_for_kind("concept"))
    quote = data["sources"][0]["quote"]

    assert "出处：" not in quote
    assert citations._squeeze(quote) in citations._squeeze(CHUNK_GRADIENT)


# --- 工作台那一轮（P4-F4-10） ---


class _FakeCourse:
    """`_plan_messages` 只从课程上读那么几样（`course_digest`）。"""

    title = "机器学习入门"
    status = "ready"
    dsl: ClassVar[dict] = {"chapters": []}


def _plan_messages(text: str, *, page_no: int = 0, monkeypatch=None) -> list[dict]:
    """**真提示词**：工作台那一轮的拼法（`agent._plan_messages`）。

    课程现状那一行要查库（`store.pages_of`），这里给它一个空课程 ——
    桩认的是提示词的**形状**，而那形状正是要验的东西，所以不能手抄一份。
    """
    from app.services.courses import store
    from app.services.workbench import agent

    if monkeypatch is not None:
        monkeypatch.setattr(store, "pages_of", lambda course: [])
    return agent._plan_messages(
        _FakeCourse(), None, {"text": text, "refPageNo": page_no, "history": []}
    )


def _plan_of(text: str, *, page_no: int = 0, monkeypatch) -> dict:
    """走 `MockLLM` 那一道（桩 → JSON 文本），再过一遍**真的计划校验器**。"""
    from app.services.workbench import agent

    messages = _plan_messages(text, page_no=page_no, monkeypatch=monkeypatch)
    raw = MockLLM().chat(messages, json_schema=agent.PLAN_SCHEMA).text
    return agent._parse_plan(raw)


def test_a_sentence_about_a_page_turns_into_the_matching_skill(monkeypatch):
    """「把这一页说得口语一点」→ change_tone，页号取自「用户正看着」那一页。"""
    plan = _plan_of("把这一页说得口语一点", page_no=3, monkeypatch=monkeypatch)

    assert [item["skill"] for item in plan["actions"]] == ["change_tone"]
    assert plan["actions"][0]["args"]["tone"] == "更口语"
    assert plan["actions"][0]["args"]["pageNos"] == [3]
    assert plan["reply"] and "示例文本" not in plan["reply"]


def test_rewrite_and_delete_carry_the_page_they_mean(monkeypatch):
    """页号是技能参数里最贵的一样东西，桩不许把它写错也不许编。"""
    rewrite = _plan_of("这一页重写一下，讲得再细一点", page_no=5, monkeypatch=monkeypatch)
    delete = _plan_of("删掉这一页", page_no=2, monkeypatch=monkeypatch)

    assert rewrite["actions"][0]["skill"] == "rewrite_page"
    assert rewrite["actions"][0]["args"]["pageNo"] == 5
    assert delete["actions"][0]["skill"] == "remove_page"
    assert delete["actions"][0]["args"]["pageNo"] == 2


def test_without_a_page_number_the_skill_falls_back_to_its_own_default(monkeypatch):
    """「用户正看着」没指定时**不编页号**：技能自己有缺省（当前页 / 第一章）。"""
    plan = _plan_of("重写一下这一页", page_no=0, monkeypatch=monkeypatch)

    assert plan["actions"][0]["skill"] == "rewrite_page"
    assert "pageNo" not in plan["actions"][0]["args"]


def test_a_sentence_that_asks_for_nothing_gets_no_action(monkeypatch):
    """认不出意图就不调技能 —— 提示词里就是这么叮嘱真模型的。"""
    plan = _plan_of("这门课主要讲的是什么？", page_no=3, monkeypatch=monkeypatch)

    assert plan["actions"] == []
    assert plan["reply"]  # 但话还是要说一句，不能空着


def test_the_plan_prompt_is_recognised_by_its_shape_alone(monkeypatch):
    """工作台那一轮没有任务头 —— 桩要是只认任务头，离线就永远调不动技能。"""
    messages = _plan_messages("删掉这一页", page_no=2, monkeypatch=monkeypatch)

    assert fixture._task_of(messages) == {}  # 确实没有任务头
    assert fixture._is_plan(messages)
    data = fixture.answer(messages, {"type": "object"})
    assert data is not None and data["actions"][0]["skill"] == "remove_page"


def test_a_prompt_that_is_not_a_plan_still_falls_through(monkeypatch):
    """别的提示词里偶然出现一句小标题，不算计划（`_is_plan` 要求两个同时在）。"""
    assert fixture.answer([{"role": "user", "content": "【可用技能】就这些"}], {"type": "object"}) is None
    # 两行都在了才是 —— 顺带钉住确定性：同一个输入两次一模一样
    messages = _plan_messages("把这一页说得口语一点", page_no=3, monkeypatch=monkeypatch)
    assert fixture.answer(messages, {"type": "object"}) == fixture.answer(messages, {"type": "object"})


def test_a_pipeline_shaped_title_still_finds_its_material():
    """管线自己拼的页标题（「认识梯度下降：先看整体」）也要能找到依据。

    标题是章标签加页标签拼出来的，材料里不会有这么一句整话 —— 桩要一路退到
    「梯度下降」这种切片。退不到的话，离线跑出来页页都报「材料没写」。
    """
    messages = _page_with_material("concept", title="认识梯度下降：先看整体")
    data = fixture.answer(messages, schema.schema_for_kind("concept"))

    assert [item["chunkId"] for item in data["sources"]] == ["k_0001"]
    assert data["gaps"] == []


def test_short_overlaps_do_not_count_as_evidence():
    """四字以下的重合到处都是，不能拿它当依据 —— 找不到就说找不到。"""
    messages = _page_with_material("concept", title="材料里没有的：核心方法")
    data = fixture.answer(messages, schema.schema_for_kind("concept"))

    assert data["sources"] == []
