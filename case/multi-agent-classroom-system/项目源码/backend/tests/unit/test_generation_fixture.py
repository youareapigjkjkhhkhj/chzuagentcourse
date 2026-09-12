"""离线课程桩（P1-G2）的用例。

桩是整个离线验收的地基：`LLM_PROVIDER=mock` 时，P1 的 A 类验收、以及 P2/P3
的两门示例课演示，全靠它产出一门**像样的课**。所以这里钉的

不是「桩写得好不好」，而是三件会悄悄坏掉的事：

1. **分派只认任务头**。认不出就返回 None，由 `MockLLM` 回落到 `_fill` ——
   P0 的老用例（拿一个任意 schema 要 JSON）靠这条活着。
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
