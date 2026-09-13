"""离线桩的课堂那一半（P3 §2.3 / §2.4 / P3-G2）。

`fixture.py` 原本只为 P1 生成课程。P3 又往它上面挂了**四类课堂调用** ——
插话、讨论一轮、答疑、板书 —— 它们与 P1 那五类不是同一拨：

| | 何时调用 | 慢一点行不行 |
|---|---|---|
| P1 的 | 生成一门课时 | 行（分钟级） |
| 课堂的 | **讲课当中** | 不行（P3-D3：3 秒不回来就跳过） |

所以桩必须答得上来。答不上来，`scripts/accept_p3.py` 的离线验收就只能测到
「超时被跳过」那一条路 —— 那是验收的失败，不是桩的失败。

这里同时钉住桩的四条**可判**性质：说话的人在场（A3）、话里带本页标题（E1）、
不出戏（E4）、相邻两页不像（E2）。
"""

from __future__ import annotations

from difflib import SequenceMatcher

import pytest

from app.providers.llm import fixture
from app.services.classroom import prompts as classroom_prompts

pytestmark = pytest.mark.unit


def _classmates() -> list[dict]:
    """三个同学的人设卡（与 `seeds/roles.py` 的倾向一致）。"""
    return [
        {"code": "xiaoxiao", "name": "林晓", "role": "student",
         "persona": {"tendency": "question", "style": "好奇、爱提问"}},
        {"code": "chenmo", "name": "陈默", "role": "student",
         "persona": {"tendency": "supplement", "style": "沉稳、爱较真"}},
        {"code": "suyu", "name": "苏雨", "role": "student",
         "persona": {"tendency": "reflect", "style": "活泼、慢半拍"}},
    ]


def _page(page_no: int = 4, title: str = "梯度下降") -> dict:
    return {
        "pageNo": page_no,
        "kind": "concept",
        "title": title,
        "bullets": [{"text": "先定目标"}, {"text": "再往下走"}],
        "narration": [{"text": "这一页只讲一件事。"}, {"text": "记住结论。"}],
        "boardPlan": [
            {"tool": "polyline", "desc": "画一条下降曲线", "atBeat": f"p{page_no}-b1"},
            {"tool": "text", "desc": "标出最低点", "atBeat": f"p{page_no}-b2"},
        ],
    }


def _interjection(page: dict | None = None) -> dict:
    said = fixture.answer(
        classroom_prompts.interjection_messages(page or _page(), _classmates()),
        {"type": "object"},
    )
    assert said is not None
    return said


# --- 分派 ---


def test_all_four_classroom_tasks_are_handled():
    """课堂上会问的四件事，桩都得答得上来。"""
    cases = {
        "interjection": classroom_prompts.interjection_messages(_page(), _classmates()),
        "discussion_turn": classroom_prompts.discussion_turn_messages(
            "为什么先定标准再动手？", _classmates()[0], _page()
        ),
        "answer": classroom_prompts.answer_messages(
            "为什么要先定目标？", _page(), {"code": "shen", "name": "沈老师"}
        ),
        "board": classroom_prompts.board_messages(_page(), _page()["boardPlan"]),
    }
    for name, messages in cases.items():
        assert fixture.answer(messages, {"type": "object"}) is not None, name


# --- 插话（P3-A3 / P3-E1 / P3-E2 / P3-E4）---


def test_speaker_comes_from_the_roster():
    """人选必须在场，且**倾向说了算**：林晓说话就是提问。"""
    people = _classmates()

    said = _interjection()

    assert said["speakerCode"] in {person["code"] for person in people}
    assert said["type"] in {"question", "supplement", "reflect"}
    assert 0 < len(said["text"]) <= 80, "§2.3 的长短上限"


def test_speaker_rotates_with_the_page():
    """换一页就换个人说 —— 三页都由林晓开口，人工抽检时一眼就看出来是桩。"""
    speakers = {_interjection(_page(page_no))["speakerCode"] for page_no in range(1, 10)}

    assert len(speakers) >= 2


def test_the_interjection_mentions_the_page():
    """P3-E1 判的是「与当前页内容相关」—— 桩的话里至少要有本页标题。"""
    assert "梯度下降" in _interjection()["text"]


def test_the_interjection_does_not_out_itself():
    """P3-E4：同学发言里不许出现「作为一个 AI」这类出戏表述。"""
    for page_no in range(1, 8):
        text = _interjection(_page(page_no))["text"]
        for phrase in ("AI", "人工智能", "语言模型", "助手"):
            assert phrase not in text, text


def test_two_pages_do_not_say_the_same_thing():
    """相邻两页的插话不像同一条（P3-E2 的离线版）。"""
    first = _interjection(_page(4, "第 4 页的主题"))["text"]
    second = _interjection(_page(7, "第 7 页的主题"))["text"]

    assert SequenceMatcher(None, first, second).ratio() <= 0.8


def test_the_interjection_is_deterministic():
    """同一页问两次得到同一句话 —— 验收脚本要能复现「第几页该谁说话」。"""
    assert _interjection() == _interjection()


# --- 讨论的一轮（P3-A4）---


def test_student_and_teacher_sound_different():
    """讨论里两种口吻要能分出来：老师收尾，同学发表看法。"""
    student = fixture.answer(
        classroom_prompts.discussion_turn_messages("为什么先定标准再动手？", _classmates()[0], _page()),
        {"type": "object"},
    )
    teacher = fixture.answer(
        classroom_prompts.discussion_turn_messages(
            "为什么先定标准再动手？",
            {"code": "shen", "name": "沈老师", "role": "teacher",
             "persona": {"systemHint": "你是主讲老师，负责讲解知识点、回答学生提问。"}},
            _page(),
        ),
        {"type": "object"},
    )

    assert student is not None and teacher is not None
    assert student["text"] != teacher["text"]
    assert 0 < len(student["text"]) <= 80


def test_discussion_turns_are_not_all_identical():
    """连着几轮不同样 —— P3-A4 要的是「有来有回」，不是同一句复读四遍。"""
    texts = {
        fixture.answer(
            classroom_prompts.discussion_turn_messages(
                "为什么先定标准再动手？", person, _page(), round_no=round_no
            ),
            {"type": "object"},
        )["text"]
        for round_no in (1, 2, 3)
        for person in _classmates()
        if person["role"] == "student"
    }

    assert len(texts) >= 3


# --- 答疑（P3-E3）---


def test_the_answer_picks_up_the_question():
    """答疑要**带上学生问的那件事**，否则人工评分无从谈起。"""
    said = fixture.answer(
        classroom_prompts.answer_messages(
            "为什么不能跳过定目标这一步？", _page(), {"code": "shen", "name": "沈老师"}
        ),
        {"type": "object"},
    )

    assert said is not None
    assert "为什么不能跳过定目标这一步" in said["text"]
    assert said.get("followUp")


def test_the_answer_is_not_a_wall_of_text():
    """两三句话说清（§2.3 的口径），别变成又一段讲稿。"""
    said = fixture.answer(
        classroom_prompts.answer_messages("为什么要先定目标？", _page(), {"code": "shen"}),
        {"type": "object"},
    )

    assert said is not None
    assert len(said["text"]) <= classroom_prompts.MAX_ANSWER_CHARS


# --- 板书（§2.4 / P3-A8）---


def test_one_stroke_per_plan_item():
    """计划里有几笔就给几笔，顺序保持（`atBeat` 的对齐靠下标）。"""
    plan = _page()["boardPlan"]

    said = fixture.answer(classroom_prompts.board_messages(_page(), plan), {"type": "object"})

    assert said is not None
    assert [item["tool"] for item in said["strokes"]] == ["polyline", "text"]


def test_strokes_are_inside_the_canvas_and_apart():
    """坐标都在 0~1 内，而且错开排 —— 叠在一起的板书看着像没画。"""
    said = fixture.answer(
        classroom_prompts.board_messages(_page(), _page()["boardPlan"]), {"type": "object"}
    )

    assert said is not None
    rows = []
    for stroke in said["strokes"]:
        assert stroke["points"], "每一笔都得有点"
        for x, y in stroke["points"]:
            assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
        rows.append(stroke["points"][0][1])

    assert len(set(rows)) == len(rows)


def test_the_text_stroke_carries_its_label():
    """写字的那一笔要有字（§5 的 `text` 列就是为它加的）。"""
    said = fixture.answer(
        classroom_prompts.board_messages(_page(), _page()["boardPlan"]), {"type": "object"}
    )

    assert said is not None
    written = [item for item in said["strokes"] if item["tool"] == "text"]
    assert written and written[0]["text"]


def test_a_page_without_a_plan_has_no_strokes():
    """没有板书计划的页给空的，而不是让桩自由发挥。"""
    said = fixture.answer(classroom_prompts.board_messages(_page(), []), {"type": "object"})

    assert said == {"strokes": []}
