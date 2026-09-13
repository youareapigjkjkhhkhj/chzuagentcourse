"""课堂时间线（P3-2 / F3-2 / F3-10）。

时间线是「07:32 / 25:00」这个进度条的唯一依据，也是跳页、断线重连后
「现在讲到哪」的唯一答案。所以这里钉的是**换算**：

- 时长优先取真实音频（P2 合成的 `audio_assets.duration_ms`），没有才退回 `estSec`；
- beat 的 id 沿用 P1 编好的 `p{pageNo}-b{n}`（`boardPlan.atBeat`、字幕、音频三处对齐它）；
- 时间是绝对偏移，`position_at` 与 `offset_of` 互为逆运算；
- 章末讨论只挂在**这一章最后一页**上。
"""

from __future__ import annotations

import pytest

from app.extensions import db
from app.models import AudioAsset, Course, CoursePage
from app.services.classroom import timeline

pytestmark = pytest.mark.unit


def _course(chapters: list[dict] | None = None) -> Course:
    course = Course(
        title="机器学习入门",
        topic="机器学习入门",
        status="ready",
        dsl={"chapters": chapters or []},
    )
    db.session.add(course)
    db.session.commit()
    return course


def _page(
    course: Course,
    page_no: int,
    *,
    chapter_no: int = 1,
    kind: str = "concept",
    beats: list | None = None,
    status: str = "ready",
    quiz: dict | None = None,
    board_plan: list | None = None,
) -> CoursePage:
    dsl = {
        "pageNo": page_no,
        "chapterNo": chapter_no,
        "kind": kind,
        "title": f"第 {page_no} 页",
        "narration": beats if beats is not None else [f"第 {page_no} 页的第一句", "第二句"],
        "quiz": quiz,
        "boardPlan": board_plan or [],
    }
    page = CoursePage(
        course_id=course.id,
        page_no=page_no,
        chapter_no=chapter_no,
        kind=kind,
        title=f"第 {page_no} 页",
        status=status,
        dsl=dsl,
    )
    db.session.add(page)
    db.session.commit()
    return page


def _audio(
    course: Course, page_no: int, beat_id: str, duration_ms: int, *, status: str = "ready"
) -> None:
    db.session.add(
        AudioAsset(
            course_id=course.id,
            page_no=page_no,
            beat_id=beat_id,
            status=status,
            file_path=f"data/assets/audio/{course.id}/{beat_id}.mp3",
            duration_ms=duration_ms,
        )
    )
    db.session.commit()


def test_beats_are_laid_out_end_to_end(app):
    """三页各两条 beat，绝对时间首尾相接 —— 进度条的总长就是最后一个 beat 的尾巴。"""
    with app.app_context():
        course = _course()
        _page(course, 1, beats=[{"beatId": "p1-b1", "text": "一", "estSec": 3},
                                {"beatId": "p1-b2", "text": "二", "estSec": 2}])
        _page(course, 2, beats=[{"beatId": "p2-b1", "text": "三", "estSec": 4}])

        line = timeline.build(course)

        assert [page.page_no for page in line.pages] == [1, 2]
        first, second = line.pages
        assert first.start_ms == 0
        assert [beat.start_ms for beat in first.beats] == [0, 3000]
        assert first.duration_ms == 5000
        # 第二页从第一页的尾巴开始，不是从 0
        assert second.start_ms == 5000
        assert line.total_ms == 9000


def test_real_audio_duration_wins_over_estimate(app):
    """有音频就用音频的时长（P2 合成的结果），估算值只在没有音频时兜底。

    这条是「进度条和耳朵听到的一致」的全部依据：`estSec` 是生成时拍脑袋写的，
    真实音频可能 8 秒也可能是 13 秒。
    """
    with app.app_context():
        course = _course()
        _page(course, 1, beats=[{"beatId": "p1-b1", "text": "一", "estSec": 3}])
        _audio(course, 1, "p1-b1", 8800)

        line = timeline.build(course)

        assert line.pages[0].beats[0].duration_ms == 8800
        assert line.total_ms == 8800


def test_missing_or_unready_audio_falls_back_to_estimate(app):
    """音频没合成完（`status != ready`）时用估算值 —— 课堂不能等音频。"""
    with app.app_context():
        course = _course()
        _page(course, 1, beats=[{"beatId": "p1-b1", "text": "一", "estSec": 5}])
        _audio(course, 1, "p1-b1", 9999, status="failed")

        line = timeline.build(course)

        assert line.pages[0].beats[0].duration_ms == 5000


def test_every_beat_gets_a_floor_of_one_second(app):
    """估算为 0（或压根没写）的 beat 至少算 1 秒。

    0 会让进度条在翻页时一动不动，看着像卡死 —— 这是能一眼看出来的坏。
    """
    with app.app_context():
        course = _course()
        _page(course, 1, beats=[{"beatId": "p1-b1", "text": "一"}])

        line = timeline.build(course)

        assert line.pages[0].beats[0].duration_ms == timeline.MIN_BEAT_MS


def test_legacy_string_narration_still_gets_beat_ids(app):
    """还没过 `normalize_beats` 的页面（种子课、手写页）里讲稿是一串字符串。

    课堂读的是「这门课现在是什么样」，所以它照样要能被讲出来 ——
    beatId 按 `p{pageNo}-b{n}` 现编，与归一后的页面同一套命名。
    """
    with app.app_context():
        course = _course()
        _page(course, 3, beats=["第一句", "第二句"])

        line = timeline.build(course)

        assert [beat.id for beat in line.pages[0].beats] == ["p3-b1", "p3-b2"]


def test_page_without_narration_takes_no_time(app):
    """没有讲稿的页（大纲页常常如此）时长为 0：翻过去就完了，不占讲课时间。"""
    with app.app_context():
        course = _course()
        _page(course, 1, beats=[{"beatId": "p1-b1", "text": "一", "estSec": 2}])
        _page(course, 2, kind="outline", beats=[])

        line = timeline.build(course)

        assert line.pages[1].duration_ms == 0
        assert line.total_ms == 2000


def test_pending_pages_are_not_in_the_timeline(app):
    """只排 `status=ready` 的页：还在生成的页不该出现在时间线上（会在中途凭空多出一页）。"""
    with app.app_context():
        course = _course()
        _page(course, 1)
        _page(course, 2, status="pending")

        line = timeline.build(course)

        assert [page.page_no for page in line.pages] == [1]


def test_position_and_offset_are_inverse(app):
    """`offset_of` 与 `position_at` 互为逆运算 —— 跳页与断线重连各走一边。"""
    with app.app_context():
        course = _course()
        _page(course, 1, beats=[{"beatId": "p1-b1", "text": "一", "estSec": 3},
                                {"beatId": "p1-b2", "text": "二", "estSec": 3}])
        _page(course, 2, beats=[{"beatId": "p2-b1", "text": "三", "estSec": 3}])

        line = timeline.build(course)

        for page_no, beat_idx in [(1, 0), (1, 1), (2, 0)]:
            offset = line.offset_of(page_no, beat_idx)
            assert line.position_at(offset) == (page_no, beat_idx)
        # beat 中间的时刻也落在同一个 beat 上
        assert line.position_at(line.offset_of(1, 1) + 500) == (1, 1)


def test_position_at_beyond_the_end_stops_at_the_last_beat(app):
    """超过总时长的 `elapsedMs` 停在最后一个 beat，**不回绕到开头**。

    重连的客户端报一个很大的数（比如断线期间本地播放器一直在走），
    回绕意味着整门课从头再讲一遍。
    """
    with app.app_context():
        course = _course()
        _page(course, 1, beats=[{"beatId": "p1-b1", "text": "一", "estSec": 3}])
        _page(course, 2, beats=[{"beatId": "p2-b1", "text": "二", "estSec": 3}])

        line = timeline.build(course)

        assert line.position_at(10**9) == (2, 0)


def test_chapter_discussion_hangs_on_the_last_page_of_the_chapter(app):
    """章末讨论点挂在**这一章最后一页**上（§2.3 规则一：章末讨论点必触发）。

    挂在「章里第一页」或「每一页」都是错的：讨论是讲完这一章才做的事。
    """
    with app.app_context():
        course = _course(
            chapters=[
                {"no": 1, "title": "第一章", "discussion": ["为什么先定标准再动手？"]},
                {"no": 2, "title": "第二章", "discussion": ["换个场景还成立吗？"]},
            ]
        )
        _page(course, 1, chapter_no=1)
        _page(course, 2, chapter_no=1)
        _page(course, 3, chapter_no=2)

        line = timeline.build(course)

        assert line.pages[0].discussion == ()
        assert line.pages[1].discussion == ("为什么先定标准再动手？",)
        assert line.pages[2].discussion == ("换个场景还成立吗？",)


def test_chapter_without_discussion_points_stays_quiet(app):
    """章里没写讨论点就什么都不触发 —— 不要给每一章都补一个「大家有什么想法」。"""
    with app.app_context():
        course = _course(chapters=[{"no": 1, "title": "第一章", "discussion": []}])
        _page(course, 1, chapter_no=1)

        line = timeline.build(course)

        assert line.pages[0].discussion == ()


def test_quiz_is_normalised_into_a_question(app):
    """测验页的题要被摊平成 `{stem, options, answer, explain}`（前端照它渲染）。"""
    with app.app_context():
        course = _course()
        _page(
            course,
            1,
            kind="quiz",
            quiz={
                "stem": "下面哪个说法对？",
                "options": ["甲", "乙", "丙", "丁"],
                "answer": "甲",
                "explain": "因为……",
                "conceptTag": "标准化",
            },
        )

        line = timeline.build(course)

        quiz = line.pages[0].quiz
        assert quiz is not None
        assert quiz["stem"] == "下面哪个说法对？"
        assert quiz["options"] == ["甲", "乙", "丙", "丁"]
        assert quiz["answer"] == "甲"


def test_broken_quiz_is_treated_as_no_quiz(app):
    """缺字段的题当没题：半道题放出去，学生点了没有反馈，比没有题更糟。"""
    with app.app_context():
        course = _course()
        _page(course, 1, kind="quiz", quiz={"stem": "只有题干"})

        line = timeline.build(course)

        assert line.pages[0].quiz is None


def test_to_dict_carries_the_whole_timeline(app):
    """`POST /sessions` 要把整条时间线一次性发给前端（P3-4），形状在这里钉住。"""
    with app.app_context():
        course = _course()
        _page(course, 1, beats=[{"beatId": "p1-b1", "text": "一", "estSec": 3}])

        payload = timeline.build(course).to_dict()

        assert payload["totalMs"] == 3000
        assert payload["pageCount"] == 1
        assert payload["pages"][0]["beats"][0]["beatId"] == "p1-b1"
        assert payload["pages"][0]["startMs"] == 0


def test_asset_durations_can_be_injected(app):
    """传进 `asset_durations` 时不去查音频表 —— 测试与预演都要能构造确定的时间线。"""
    with app.app_context():
        course = _course()
        _page(course, 1, beats=[{"beatId": "p1-b1", "text": "一", "estSec": 3}])
        _audio(course, 1, "p1-b1", 8800)

        line = timeline.build(course, asset_durations={(1, "p1-b1"): 1234})

        assert line.pages[0].beats[0].duration_ms == 1234
