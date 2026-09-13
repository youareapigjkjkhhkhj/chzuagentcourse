"""课 → 课堂时间线（P3-2 / F3-2 / F3-10）。

P1 产出的是一份**文档**（页面、讲稿、板书计划、测验），课堂要的是**一条时间线**：
第 1 页念 42 秒、第 2 页 51 秒……合计 25:00。这个换算只做一次，结果落在
`classroom_sessions.total_ms` 与 `current_page_no / current_beat_idx` 上。

四个决定：

1. **时长优先取真实音频**（P2 合成的 `audio_assets.duration_ms`），没有音频才退回
   `estSec` 估算。进度条上那个「07:32 / 25:00」要和耳朵听到的一致 ——
   用估算值会在讲到一半时对不上，而那是学生判断「还剩多久」的唯一依据。
2. **beat 的 id 用 P1 的 `normalize_beats` 编好的 `p{pageNo}-b{n}`**，这里不重编：
   `audio_assets.beat_id`、`boardPlan.atBeat`、前端字幕三处都按这个 id 对齐，
   重编一次就会让板书出现在错误的 beat 上。
3. **时间是累加的绝对偏移**（`start_ms`），不是每页各自的相对值。
   跳页、拖进度条、断线重连后算「现在讲到哪」都是同一个减法。
4. **章末讨论点跟着章走**（`chapters[].discussion`，P1 的 quiz 步产出），
   挂在**这一章最后一页**上：它是「讲完这一章才讨论」，不是「翻到某页就讨论」。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.models import Course, CoursePage

#: 没有音频时，一个 beat 至少算这么长。取 1 秒而不是 0：
#: 0 时长的 beat 会让进度条在快速翻页时一动不动，看着像卡死了。
MIN_BEAT_MS = 1000


@dataclass(frozen=True)
class Beat:
    """讲稿的一个发言单元。`start_ms` 是它在整条时间线上的绝对起点。"""

    id: str
    text: str
    duration_ms: int
    start_ms: int

    def to_dict(self) -> dict:
        return {
            "beatId": self.id,
            "text": self.text,
            "durationMs": self.duration_ms,
            "startMs": self.start_ms,
        }


@dataclass(frozen=True)
class TimelinePage:
    page_no: int
    chapter_no: int
    kind: str
    title: str
    beats: tuple[Beat, ...]
    quiz: Mapping[str, Any] | None
    board_plan: tuple[Mapping[str, Any], ...]
    discussion: tuple[str, ...]
    start_ms: int
    duration_ms: int

    @property
    def is_last_of_chapter(self) -> bool:
        return bool(self.discussion)

    def to_dict(self) -> dict:
        return {
            "pageNo": self.page_no,
            "chapterNo": self.chapter_no,
            "kind": self.kind,
            "title": self.title,
            "beats": [beat.to_dict() for beat in self.beats],
            "quiz": dict(self.quiz) if self.quiz else None,
            "boardPlan": [dict(item) for item in self.board_plan],
            "discussion": list(self.discussion),
            "startMs": self.start_ms,
            "durationMs": self.duration_ms,
        }


@dataclass(frozen=True)
class Timeline:
    pages: tuple[TimelinePage, ...]
    total_ms: int

    def page(self, page_no: int) -> TimelinePage | None:
        for item in self.pages:
            if item.page_no == page_no:
                return item
        return None

    def index_of(self, page_no: int) -> int:
        """页号 → 时间线上的下标。找不到返回 0（退回第一页，而不是崩）。"""
        for index, item in enumerate(self.pages):
            if item.page_no == page_no:
                return index
        return 0

    def position_at(self, elapsed_ms: int) -> tuple[int, int]:
        """时间点 → (页号, 页内 beat 下标)。

        `elapsed_ms` 超过总时长时停在最后一个 beat 上 —— 而不是回绕到开头：
        重连的客户端报上一个很大的 `elapsedMs` 不该让课堂从头再讲一遍。
        """
        if not self.pages:
            return (0, 0)
        clamped = max(0, int(elapsed_ms))
        for page in self.pages:
            if clamped < page.start_ms + page.duration_ms or page is self.pages[-1]:
                if not page.beats:
                    return (page.page_no, 0)
                for index, beat in enumerate(page.beats):
                    if clamped < beat.start_ms + beat.duration_ms:
                        return (page.page_no, index)
                return (page.page_no, len(page.beats) - 1)
        last = self.pages[-1]
        return (last.page_no, max(0, len(last.beats) - 1))

    def offset_of(self, page_no: int, beat_idx: int = 0) -> int:
        """(页号, beat 下标) → 绝对时间。跳页与快照恢复都走它。"""
        page = self.page(page_no)
        if page is None:
            return 0
        if not page.beats:
            return page.start_ms
        index = max(0, min(int(beat_idx), len(page.beats) - 1))
        return page.beats[index].start_ms

    def to_dict(self) -> dict:
        return {
            "pages": [page.to_dict() for page in self.pages],
            "totalMs": self.total_ms,
            "pageCount": len(self.pages),
        }


def build(
    course: Course,
    pages: Sequence[CoursePage] | None = None,
    *,
    asset_durations: Mapping[tuple[int, str], int] | None = None,
) -> Timeline:
    """把一门课摊成一条时间线。

    Args:
        course: 课程行（`dsl.chapters` 里的讨论点从这里读）。
        pages: 已就绪的页面行；不传就现查（只取 `status=ready`）。
        asset_durations: `{(page_no, beat_id): 毫秒}`。不传就现查音频资产。
            传进来是为了让测试能构造确定的时间线，不必真的合成一遍音频。
    """
    rows = list(pages) if pages is not None else _ready_pages(course)
    durations = dict(asset_durations) if asset_durations is not None else _asset_durations(course)

    discussions = _chapter_discussions(course, rows)
    last_of_chapter = _last_page_of_each_chapter(rows)

    built: list[TimelinePage] = []
    cursor = 0  # 已排到的时间线绝对位置：一页接一页累加
    for row in sorted(rows, key=lambda item: item.page_no):
        dsl = row.dsl or {}
        start = cursor
        beats: list[Beat] = []
        for raw in _beats_of(dsl):
            beat_id = str(raw.get("beatId") or "")
            if not beat_id:
                continue
            duration = max(
                MIN_BEAT_MS,
                int(durations.get((row.page_no, beat_id)) or 0)
                or int(raw.get("estSec") or 0) * 1000,
            )
            beats.append(Beat(beat_id, str(raw.get("text") or ""), duration, cursor))
            cursor += duration

        chapter_no = int(row.chapter_no or 0)
        built.append(
            TimelinePage(
                page_no=row.page_no,
                chapter_no=chapter_no,
                kind=row.kind,
                title=row.title or "",
                beats=tuple(beats),
                quiz=_quiz_of(dsl),
                board_plan=tuple(dict(item) for item in (dsl.get("boardPlan") or []) if item),
                # 讨论点只挂在章末那一页上；中间页即使章里有讨论点也不触发
                discussion=(
                    tuple(discussions.get(chapter_no, ()))
                    if row.page_no in last_of_chapter.get(chapter_no, set())
                    else ()
                ),
                start_ms=start,
                # 讲稿为空的一页时长为 0：它不占讲课时间，翻过去就完了
                duration_ms=cursor - start,
            )
        )

    return Timeline(pages=tuple(built), total_ms=cursor)


def _ready_pages(course: Course) -> list[CoursePage]:
    return (
        CoursePage.query.filter_by(course_id=course.id, status="ready")
        .order_by(CoursePage.page_no)
        .all()
    )


def _asset_durations(course: Course) -> dict[tuple[int, str], int]:
    """已合成音频的时长。只认 `status=ready` 的资产（P2 的 `available` 口径）。"""
    from app.models import AudioAsset

    rows = AudioAsset.query.filter_by(course_id=course.id, status="ready").all()
    return {
        (int(row.page_no), row.beat_id): int(row.duration_ms or 0)
        for row in rows
        if row.beat_id and row.duration_ms
    }


def _beats_of(dsl: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """页面 DSL 里的讲稿。

    `narration` 是 P1 归一后的对象数组；但**还没过 `normalize_beats` 的页面**
    （种子课、手写页、旧版本）里可能是一串字符串。两种都收 ——
    课堂读的是「这门课现在是什么样」，不是「它本该是什么样」。
    """
    raw = dsl.get("narration") or []
    items: list[Mapping[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, Mapping):
            items.append(item)
        elif str(item).strip():
            text = str(item).strip()
            items.append({"beatId": f"p{dsl.get('pageNo') or 0}-b{index}", "text": text})
    return items


def _quiz_of(dsl: Mapping[str, Any]) -> Mapping[str, Any] | None:
    quiz = dsl.get("quiz")
    if not isinstance(quiz, Mapping):
        return None
    options = [str(option) for option in (quiz.get("options") or [])]
    if not quiz.get("stem") or not options:
        return None
    return {
        "stem": str(quiz.get("stem") or ""),
        "options": options,
        "answer": str(quiz.get("answer") or ""),
        "explain": str(quiz.get("explain") or ""),
        "conceptTag": str(quiz.get("conceptTag") or ""),
    }


def _chapter_discussions(
    course: Course, rows: Sequence[CoursePage]
) -> dict[int, list[str]]:
    """章号 → 讨论点。以 `dsl.chapters[].discussion` 为准（P1 的 quiz 步写进去的）。"""
    chapters = (course.dsl or {}).get("chapters") or []
    result: dict[int, list[str]] = {}
    for chapter in chapters:
        no = int(chapter.get("no") or 0)
        points = [str(item).strip() for item in (chapter.get("discussion") or [])]
        if no and points:
            result[no] = [point for point in points if point]
    return result


def _last_page_of_each_chapter(rows: Sequence[CoursePage]) -> dict[int, set[int]]:
    """每章最后一页的页号。有重复章号时取最大的那个页号。"""
    latest: dict[int, int] = {}
    for row in rows:
        no = int(row.chapter_no or 0)
        latest[no] = max(latest.get(no, 0), int(row.page_no))
    return {no: {page_no} for no, page_no in latest.items()}


__all__ = [
    "MIN_BEAT_MS",
    "Beat",
    "Timeline",
    "TimelinePage",
    "build",
]
