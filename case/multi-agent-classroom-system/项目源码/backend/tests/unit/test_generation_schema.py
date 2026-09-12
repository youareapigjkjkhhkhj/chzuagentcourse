"""页面 DSL 的 Schema 校验与规范化（P1 §3.2 / §3.3 / P1-F1）。

这一层要挡的是「模型写得像那么回事、但前端渲染不出来」的输出：
少一条要点、选项只有三个、讲稿一句话 120 个字。
校验信息会**原样回喂给模型**让它重写（P1-12 输出校验与自动重试），
所以每条 reason 都要是「说清楚哪儿不对、怎么改」的中文，
而不是 pydantic 那种 "List should have at least 3 items"。

另一条同样重要的路径是**容忍**：模型包了 Markdown 围栏、多写了一层
它自认为有用的字段，都不该让整页作废 —— 能救的救回来。
"""

from __future__ import annotations

import json

import pytest

from app.services.generation.schema import (
    MAX_BEAT_CHARS,
    PAGE_KINDS,
    SchemaInvalid,
    load_json,
    parse_page,
    schema_for_kind,
)

pytestmark = pytest.mark.unit


# --- 合法输出 ---


def test_concept_page_passes_validation():
    page = parse_page("concept", json.dumps(_concept()), page_no=7, chapter_no=3)

    assert page["kind"] == "concept"
    assert page["pageNo"] == 7
    assert page["chapterNo"] == 3
    assert page["title"] == "3.2 梯度下降法"
    assert len(page["bullets"]) == 3
    assert len(page["narration"]) == 3


def test_every_kind_has_a_working_sample():
    """九种页型每种都要有一个能过校验的样例。

    这是「Schema 与页面类型表同步」的守门人：新增页型却忘了写校验规则，
    或者规则写成了不可能满足的条件，都会在这里露出来。
    """
    for kind in PAGE_KINDS:
        page = parse_page(kind, json.dumps(_sample(kind)), page_no=1)
        assert page["kind"] == kind, kind
        assert page["title"], kind


# --- 必填项：少一个就判失败 ---


def test_concept_requires_at_least_three_bullets():
    data = _concept()
    data["bullets"] = data["bullets"][:2]

    with pytest.raises(SchemaInvalid) as excinfo:
        parse_page("concept", json.dumps(data), page_no=7)

    assert "bullets" in str(excinfo.value)
    assert "3" in str(excinfo.value)


def test_concept_requires_at_least_three_beats():
    data = _concept()
    data["narration"] = data["narration"][:1]

    with pytest.raises(SchemaInvalid) as excinfo:
        parse_page("concept", json.dumps(data), page_no=7)

    assert "narration" in str(excinfo.value)


def test_quiz_requires_exactly_four_options():
    data = _sample("quiz")
    data["quiz"]["options"] = ["A", "B", "C"]

    with pytest.raises(SchemaInvalid) as excinfo:
        parse_page("quiz", json.dumps(data), page_no=9)

    assert "4" in str(excinfo.value), "理由要说清是选项数量不对"


def test_debate_requires_topic_and_both_sides():
    data = _sample("debate")
    del data["topic"]

    with pytest.raises(SchemaInvalid) as excinfo:
        parse_page("debate", json.dumps(data), page_no=12)

    assert "topic" in str(excinfo.value)


def test_code_requires_language_and_content():
    data = _sample("code")
    data["code"] = {"lang": "python", "content": "   "}

    with pytest.raises(SchemaInvalid):
        parse_page("code", json.dumps(data), page_no=5)


def test_unknown_kind_is_rejected():
    with pytest.raises(SchemaInvalid) as excinfo:
        parse_page("poem", json.dumps({"kind": "poem", "title": "静夜思"}), page_no=1)

    assert "poem" in str(excinfo.value)


def test_missing_title_is_rejected():
    data = _concept()
    data["title"] = "  "

    with pytest.raises(SchemaInvalid) as excinfo:
        parse_page("concept", json.dumps(data), page_no=7)

    assert "title" in str(excinfo.value)


# --- 容忍：能救的救回来 ---


def test_markdown_fence_is_stripped():
    """模型经常把 JSON 包在 ```json 围栏里 —— 这不是错误，是习惯。"""
    text = "```json\n" + json.dumps(_concept(), ensure_ascii=False) + "\n```"

    page = parse_page("concept", text, page_no=7)

    assert page["title"] == "3.2 梯度下降法"


def test_json_objects_survive_a_chatty_prefix():
    """围栏之外还会带一句「好的，以下是 JSON：」，同样不该判失败。"""
    text = "好的，以下是第 7 页的 JSON：\n" + json.dumps(_concept(), ensure_ascii=False)

    assert parse_page("concept", text, page_no=7)["kind"] == "concept"


def test_non_json_text_is_rejected_with_a_readable_reason():
    with pytest.raises(SchemaInvalid) as excinfo:
        parse_page("concept", "抱歉，我无法完成这个请求。", page_no=7)

    reason = str(excinfo.value)
    assert "JSON" in reason
    # 理由要能让模型照着改，所以不能把整段原文抄进去（AGENTS §19：不记材料正文）
    assert "抱歉" not in reason


def test_json_array_is_not_a_page():
    """顶层必须是对象，不能是数组 —— 否则后面每一步都要判一次类型。"""
    with pytest.raises(SchemaInvalid):
        load_json("[1, 2, 3]")


# --- 讲稿 beat 化（技术方案 §3.3）---


def test_beats_get_sequential_ids():
    page = parse_page("concept", json.dumps(_concept()), page_no=7)

    assert [b["beatId"] for b in page["narration"]] == ["p7-b1", "p7-b2", "p7-b3"]


def test_long_beats_are_split_to_the_limit():
    """一句 150 字的讲稿必须被切开 —— 它是语音合成的最小单位。"""
    data = _concept()
    data["narration"] = [{"text": "梯度下降是一种迭代优化方法，" * 10}]

    page = parse_page("concept", json.dumps(data), page_no=7)

    assert len(page["narration"]) >= 3
    for beat in page["narration"]:
        assert len(beat["text"]) <= MAX_BEAT_CHARS, beat["text"]


def test_unpunctuated_text_is_hard_cut():
    """没有标点可断的长句也必须切开 —— 「≤60 字」是硬上限，不是尽量。"""
    data = _concept()
    data["narration"] = [{"text": "梯度" * 90}]  # 180 字，一个标点都没有

    page = parse_page("concept", json.dumps(data), page_no=7)

    assert len(page["narration"]) == 3, "180 字应切成 3 句 60 字"
    assert all(len(beat["text"]) <= MAX_BEAT_CHARS for beat in page["narration"])
    assert sum(len(beat["text"]) for beat in page["narration"]) == 180, "不能把内容切丢"


def test_wrong_field_type_is_reported_in_chinese():
    """模型把数组写成了字符串（很常见），理由要能读、能照着改。"""
    data = _concept()
    data["bullets"] = "梯度方向是最陡上升方向；学习率决定步长"

    with pytest.raises(SchemaInvalid) as excinfo:
        parse_page("concept", json.dumps(data), page_no=7)

    reason = str(excinfo.value)
    assert "bullets" in reason
    assert "List" not in reason and "string_type" not in reason, "不要把 pydantic 的英文原文回喂"


def test_est_sec_is_computed_by_the_server():
    """estSec 一律服务端算：模型给的时间戳不可靠，而且没必要花 token 去要。"""
    data = _concept()
    data["narration"][0] = {"text": "我们先看一个直觉", "estSec": 999}

    page = parse_page("concept", json.dumps(data), page_no=7)

    assert 0 < page["narration"][0]["estSec"] < 60


def test_empty_beats_are_dropped():
    """模型偶尔会吐出空 beat，留着会让语音合成卡在一个空字符串上。"""
    data = _concept()
    data["narration"] = [
        {"text": "第一句有内容"},
        {"text": "   "},
        {"text": "第二句有内容"},
        {"text": "第三句有内容"},
    ]

    page = parse_page("concept", json.dumps(data), page_no=7)

    assert all(beat["text"].strip() for beat in page["narration"])
    assert [b["beatId"] for b in page["narration"]] == ["p7-b1", "p7-b2", "p7-b3"]


# --- 发给模型的 Schema ---


def test_schema_for_kind_declares_the_required_fields():
    """提示词里的 Schema 必须与校验规则同源 —— 否则模型照着写也会被判失败。"""
    schema = schema_for_kind("concept")

    assert set(schema["required"]) >= {"title", "bullets", "narration"}
    assert schema["properties"]["kind"]["enum"] == ["concept"]
    assert schema["properties"]["bullets"]["minItems"] == 3
    assert schema["properties"]["narration"]["minItems"] == 3


def test_schema_for_kind_is_json_serializable():
    """它要被塞进提示词，必须能 json.dumps。"""
    for kind in PAGE_KINDS:
        assert json.dumps(schema_for_kind(kind), ensure_ascii=False)


def test_schema_for_unknown_kind_is_rejected():
    with pytest.raises(SchemaInvalid):
        schema_for_kind("poem")


# --- 样例 ---


def _concept() -> dict:
    return {
        "kind": "concept",
        "title": "3.2 梯度下降法",
        "subtitle": "GRADIENT DESCENT — 如何找到最低点",
        "bullets": [
            {"text": "梯度方向是最陡上升方向，取负即下降"},
            {"text": "学习率决定每一步走多远"},
            {"text": "步长过大会震荡，过小则收敛慢"},
        ],
        "narration": [
            {"text": "我们先看一个直觉：站在山坡上，往哪个方向走下降最快？"},
            {"text": "答案是把梯度取反。"},
            {"text": "学习率则决定了每一步迈多大。"},
        ],
        "visual": {"type": "diagram", "desc": "梯度下降曲线与最优点"},
        "interaction": {"askAtEnd": True, "allowFreeChat": True},
        "boardPlan": [{"tool": "curve", "desc": "画出损失曲线", "atBeat": "p7-b2"}],
    }


def _with_universal(page: dict) -> dict:
    """补上「每一页都要有」的那一层（schema.UNIVERSAL_RULE）。

    样例必须是可以**真的过校验**的页面，否则 `test_every_kind_has_a_working_sample`
    就守不住「Schema 与页型表同步」这件事了。各页型各自特有的字段仍由下面的
    分支给 —— 这一层只补共性的那几项，不替页型说话。
    """
    title = str(page.get("title") or "示例页")
    page.setdefault("subtitle", "本节要点")
    page.setdefault("visual", {"type": "diagram", "desc": f"{title}的图示"})
    if len(page.get("bullets") or []) < 3:
        page["bullets"] = [{"text": f"{title}的要点 {index}"} for index in (1, 2, 3)]
    if len(page.get("narration") or []) < 3:
        page["narration"] = [{"text": f"{title}讲稿第 {index} 句。"} for index in (1, 2, 3)]
    return page


def _sample(kind: str) -> dict:
    """每种页型的最小合法样例。"""
    common = {"kind": kind, "title": f"{kind} 页"}
    if kind == "cover":
        return _with_universal({
            **common,
            "title": "机器学习入门",
            "subtitle": "从零开始理解模型如何学习",
            "meta": {"lecturer": "沈老师", "durationMin": 25, "audience": "大一新生"},
        })
    if kind == "outline":
        return _with_universal({
            **common,
            "title": "课程大纲",
            "chapters": [
                {"no": 1, "title": "绪论", "pages": [1, 4]},
                {"no": 2, "title": "线性回归", "pages": [5, 9]},
            ],
        })
    if kind == "concept":
        return _concept()
    if kind == "figure":
        return _with_universal({
            **common,
            "visual": {"type": "diagram", "desc": "神经网络三层结构示意"},
        })
    if kind == "example":
        return _with_universal({
            **common,
            "title": "例题：预测房价",
            "steps": ["收集历史成交数据", "拟合线性模型", "用模型预测新房价"],
            "narration": [{"text": "我们先看一个真实场景。"}],
        })
    if kind == "code":
        return _with_universal({
            **common,
            "title": "用 numpy 实现梯度下降",
            "code": {"lang": "python", "content": "w -= lr * grad"},
            "explanation": ["这一行就是全部的核心"],
        })
    if kind == "quiz":
        return _with_universal({
            **common,
            "title": "随堂测验",
            "quiz": {
                "stem": "梯度下降中学习率过大最可能导致什么？",
                "options": ["收敛变慢", "震荡不收敛", "梯度消失", "过拟合"],
                "answer": "B",
                "explain": "步长过大会跨过最低点来回震荡。",
                "conceptTag": "学习率",
            },
        })
    if kind == "summary":
        return _with_universal({
            **common,
            "title": "本章小结",
            "question": "如果学习率设为 0 会发生什么？",
        })
    if kind == "debate":
        return _with_universal({
            **common,
            "title": "研讨：模型越大越好吗",
            "topic": "参数量是否是决定模型能力的唯一因素",
            "sides": [
                {"stance": "正方", "points": ["参数越多表达能力越强"]},
                {"stance": "反方", "points": ["数据和训练策略同样关键"]},
            ],
        })
    raise AssertionError(f"未知页型 {kind}")
