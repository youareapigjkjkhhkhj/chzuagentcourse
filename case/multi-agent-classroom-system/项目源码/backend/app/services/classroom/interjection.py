"""插话决策：AI 同学什么时候说话（§2.3 / P3-A3 / P3-D3 / P3-E2 / P3-F3）。

不是随机插话。规则先筛（要不要说、轮不轮得到），再由**一次** LLM 调用决定说什么。
这一层守着四件事，每一件都对应一条验收：

- **P3-A3 的次数与时机**：概念页讲到过半才允许、每页最多一位、每 3 页最多一次。
  筛不通过就**不调用模型** —— 省下的不只是钱，还有课堂的安静。
- **P3-D3 不阻塞课堂**：模型 3 秒不回来就当这一轮没有插话。课堂进度不能等模型。
- **P3-E2 不重复**：与最近几条同学发言太像的直接丢掉（相似度 > 0.8）。
  两个 AI 同学轮流说同一句话，比没人说话更像事故。
- **P3-F3 敏感词**：命中就不入消息流，并记一条审计（`filter.record_hit`）。

输出还要过长度与枚举校验：模型给 200 字、给一个不存在的 `speakerCode`、
给一个与人设不符的 `type`，都在这里收敛掉 —— 这些都是「提示词没写好」的表现，
不该变成前端渲染时的意外。
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Mapping, Sequence

from flask import current_app

from app.common.errors import AppError
from app.common.logging import get_logger
from app.models import ClassroomSession
from app.services.classroom import prompts, state
from app.services.classroom.timeline import TimelinePage
from app.services.generation import filter as sensitive
from app.services.generation.llm import call_json
from app.services.provider_registry import get_registry

logger = get_logger("app.classroom.interjection")

#: 相似度上限（P3-E2）。超过就当重复，丢掉这一条。
SIMILARITY_LIMIT = 0.8

#: 概念页插话要求讲过了这个比例。0.5 = 过半（§2.3 规则二）。
MIDWAY_RATIO = 0.5


@dataclass(frozen=True)
class Interjection:
    """一条待播的同学发言。`reason` 是「为什么没播」时才有值。"""

    speaker_code: str
    speaker_name: str
    text: str
    type: str
    trigger: str
    persona: Mapping[str, Any]
    #: 说话人的音色档（`AgentRole.voice_profile_id`）。造 Turn 的那一步拿它去
    #: 合成这一句的声音（`speech.turn_audio`）；空 = 这位同学没配音色，
    #: 那就没有声音 —— 绝不退回老师的嗓子。
    voice_profile_id: str = ""

    def as_turn_kwargs(self, *, page_no: int) -> dict:
        return {
            "speaker_code": self.speaker_code,
            "speaker_name": self.speaker_name,
            "speaker_kind": "student_ai",
            "text": self.text,
            "kind": "interject",
            "message_type": self.type,
            "page_no": page_no,
        }


def should_interject(
    session: ClassroomSession,
    page: TimelinePage,
    *,
    beat_idx: int,
    min_pages: int = 3,
) -> tuple[bool, str]:
    """规则判据（§2.3 规则二）。返回 `(能不能插话, 为什么)`。

    第二个返回值是给排障与人看的：验收脚本里「这次为什么没插话」必须能答上来，
    否则只能靠数消息条数猜。
    """
    if page.kind != "concept":
        return False, "non_concept_page"

    total = len(page.beats)
    if total and int(beat_idx) < int(total * MIDWAY_RATIO):
        return False, "too_early"

    pages = [int(item) for item in (state.get_flag(session, "interjectedPages") or [])]
    if page.page_no in pages:
        return False, "already_on_this_page"
    if pages and page.page_no - max(pages) < int(min_pages):
        return False, "too_soon"

    return True, "concept_midway"


def decide(
    session: ClassroomSession,
    page_row: Mapping[str, Any],
    classmates: Sequence[Mapping[str, Any]],
    *,
    timeline_page: TimelinePage | None = None,
    recent: Sequence[Mapping[str, Any]] = (),
) -> Interjection | None:
    """让一位同学说一句话。任何失败都返回 `None`（不抛异常给课堂）。

    Args:
        page_row: 页面的 DSL（`bullets` / `narration` / `title`）。
        classmates: `AgentRole` 的 `to_dict()` 列表，**只含同学**。
        recent: 最近的消息（`to_dict()`），用于「别重复」与上下文。
    """
    if not classmates:
        return None

    messages = prompts.interjection_messages(page_row, classmates, recent)
    try:
        result = call_json(
            get_registry().current_llm(),
            messages,
            schema=prompts.SCHEMA_INTERJECTION,
            timeout=interjection_timeout(),
        )
    except AppError as exc:
        # 40201（没配模型）/ 50401（超时）/ 50201（上游挂了）：都当「这一轮没有插话」
        logger.info("插话决策跳过：%s", exc.message)
        return None

    data = result.data
    text = " ".join(str(data.get("text") or "").split())
    if not text:
        return None

    speaker = _pick_speaker(data.get("speakerCode"), classmates)
    persona = speaker.get("persona") or {}
    tendency = str(persona.get("tendency") or "supplement")
    # `type` 一律按人设收敛：徽标由它渲染，而 A3 判的是「这条发言像不像这个人」。
    # 让模型写错一个词就把林晓的提问标成「补充」，是没必要付的代价。
    kind = prompts.TENDENCY_TYPES.get(tendency, "comment")
    if str(data.get("type") or "") != kind:
        logger.debug("插话类型按人设收敛：%s → %s", data.get("type"), kind)

    hits = sensitive.scan(text)
    if hits:
        sensitive.record_hit(
            target="classroom_interjection",
            owner_id=str(session.owner_id or ""),
            words=hits,
            outcome=sensitive.OUTCOME_BLOCKED,
            extra={"sessionId": session.id, "speaker": speaker.get("code")},
        )
        logger.warning("同学发言命中敏感词，已拦截：%s", hits)
        return None

    if _too_similar(text, recent):
        logger.info("同学发言与最近的重合度过高，跳过：%s", text[:20])
        return None

    return Interjection(
        speaker_code=str(speaker.get("code") or ""),
        speaker_name=str(speaker.get("name") or ""),
        text=text[: prompts.MAX_INTERJECTION_CHARS],
        type=kind,
        trigger=str(data.get("trigger") or "concept_midway"),
        persona=dict(persona),
        voice_profile_id=str(speaker.get("voiceProfileId") or ""),
    )


def mark_interjected(session: ClassroomSession, page_no: int) -> None:
    """记下「这一页已经有人插过话」。调用方在**真的播出去之后**才记。"""
    pages = [int(item) for item in (state.get_flag(session, "interjectedPages") or [])]
    if page_no not in pages:
        pages.append(int(page_no))
    state.set_flags(session, interjectedPages=pages[-20:])


def interjection_timeout() -> float:
    return float(current_app.config.get("CLASSROOM_INTERJECTION_TIMEOUT") or 3.0)


def _pick_speaker(code: Any, classmates: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """模型给了一个不在场的人（或什么都没给）时，退到第一位同学。"""
    wanted = str(code or "")
    for person in classmates:
        if str(person.get("code") or "") == wanted:
            return person
    logger.debug("插话人选不在课堂里：%r，退到第一位同学", wanted)
    return classmates[0]


def _too_similar(text: str, recent: Sequence[Mapping[str, Any]]) -> bool:
    """与最近的同学发言比相似度（P3-E2）。

    只和**同学**比：老师重复一句学生刚说的话，往往是刻意的（「你刚说的这点很关键」）。
    """
    for item in list(recent)[-5:]:
        if str(item.get("speakerKind") or "") != "student_ai":
            continue
        other = str(item.get("text") or "")
        if other and SequenceMatcher(None, text, other).ratio() > SIMILARITY_LIMIT:
            return True
    return False


__all__ = [
    "MIDWAY_RATIO",
    "SIMILARITY_LIMIT",
    "Interjection",
    "decide",
    "interjection_timeout",
    "mark_interjected",
    "should_interject",
]
