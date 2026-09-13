"""课程术语表：**一份数据，两处消费**（P2-A20）。

同一个词在两条链路上各有用处，但要的形态不同：

- 合成（TTS）：`pronunciation_dict` —— 告诉它这个词怎么念（讲座里「卷积」念 juǎn jī）
- 识别（ASR / 实时语音）：`hotwords` —— 告诉它注意听这个词（学生说得再快也别听成别的）

如果两处各攒一份词表，迟早会出现「讲稿里念对了、学生问的时候却听错了」——
而排查时要在两个地方找原因。所以这里只回答一个问题：
**这门课有哪些术语**，两种形态都从它投出来。

术语从哪儿来（不改生成管线，只读已有产物）：
1. `course.dsl.meta.glossary` 里手工/后续补录的 `{词: 读音}`（可选，优先级最高）；
2. 每页标题 —— 一页讲什么，标题就是那个词；
3. 要点里作者标了 `emphasis` 的词 —— 生成时就认定它是本页的关键词。

读音**不猜**：`reading` 为空就只当热词，不塞一个自造的拼音进纠音表。
上游收到一个错的读音，比不纠更糟。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.models.course import CoursePage

#: 术语表上限。直传热词限 100 tokens（§5.3-C5），两边共用同一个上限 ——
#: 让「同一份表」这件事在数量上也成立，而不是一个 100 一个 200。
MAX_TERMS = 100

#: 单个术语的长度上限。短词是术语，长句是句子；句子塞进热词表只会稀释权重。
MAX_TERM_CHARS = 12


@dataclass(frozen=True)
class GlossaryTerm:
    """一个术语。`reading` 为空表示「只当热词，不纠音」。"""

    term: str
    reading: str = ""

    @property
    def has_reading(self) -> bool:
        return bool(self.reading)


def glossary_terms(course_meta: Mapping[str, Any] | None, pages: Iterable[CoursePage]) -> list[GlossaryTerm]:
    """把一门课摊成一张术语表（去重、保序：先补录的，再按页序）。

    `pages` 只传**已就绪**的页：还没生成出来的页没有标题也没有要点，
    传进来只会得到空字符串。
    """
    out: list[GlossaryTerm] = []
    seen: set[str] = set()

    def _add(term: str, reading: str = "") -> None:
        text = str(term or "").strip()
        if not text or text in seen:
            return
        if len(text) > MAX_TERM_CHARS:
            return
        seen.add(text)
        out.append(GlossaryTerm(term=text, reading=str(reading or "").strip()))

    # 1) 补录的读音表：有读音的术语从这里进来
    declared = (course_meta or {}).get("glossary")
    if isinstance(declared, Mapping):
        for term, reading in declared.items():
            _add(str(term), str(reading or ""))
    elif isinstance(declared, Sequence) and not isinstance(declared, (str, bytes)):
        for item in declared:
            if isinstance(item, Mapping):
                _add(str(item.get("term") or ""), str(item.get("reading") or ""))
            else:
                _add(str(item))

    # 2) 页标题
    for page in pages:
        _add(page.title or "")

    # 3) 要点里标了 emphasis 的词
    for page in pages:
        for bullet in (page.dsl or {}).get("bullets") or []:
            if not isinstance(bullet, Mapping):
                continue
            for word in bullet.get("emphasis") or []:
                _add(str(word))

    return out[:MAX_TERMS]


def pronunciation(terms: Sequence[GlossaryTerm]) -> dict[str, str]:
    """术语表 → `{词: 读音}`，喂给 TTS 的 `pronunciation_dict`。

    没有读音的术语不进这里（见模块 docstring 最后一段）。
    """
    return {item.term: item.reading for item in terms if item.has_reading}


def hotwords(terms: Sequence[GlossaryTerm]) -> list[str]:
    """术语表 → 热词列表，喂给 ASR / 实时语音。

    与 `pronunciation()` 是同一张表的两个投影：有读音的词照样要进热词表 ——
    识别端要的是「注意听这个词」，跟它怎么念没有关系。
    """
    return [item.term for item in terms]


def glossary_of(course_meta: Mapping[str, Any] | None, pages: Iterable[CoursePage]) -> dict:
    """一次算出两个投影，供一次调用同时传给两条链路（避免两边各算一遍）。"""
    terms = glossary_terms(course_meta, pages)
    return {
        "terms": terms,
        "pronunciation": pronunciation(terms),
        "hotwords": hotwords(terms),
    }


__all__ = [
    "MAX_TERMS",
    "MAX_TERM_CHARS",
    "GlossaryTerm",
    "glossary_of",
    "glossary_terms",
    "hotwords",
    "pronunciation",
]
