"""页面 DSL 的 Schema、校验与规范化（P1 §3.2 / §3.3）。

一条流水线，三件事在一处：

    模型输出的一段文本 →（load_json）→ 原始字典 →（校验）→ 规范化后的页面 DSL

**为什么用 pydantic 而不是手写 if**：技术方案 §3.2 的那张表同时是三个东西 ——
发给模型的 JSON Schema、生成后的校验器、管线里的类型。写三份就一定会漂移，
写一份最多漂一处。`KindRule` 那张表是唯一的事实来源：Schema 里的
`required` / `minItems` 与运行期的检查都从它读。

两条贯穿全篇的取向：

- **能救的救**：Markdown 围栏、「好的，以下是 JSON：」的开场白、多写的字段，
  都不是错误。JSON 模式下的模型仍然会这么写，判失败只会让重试白花一次 token。
- **该拦的拦死**：少一条要点、选项只有三个、讲稿一句 120 字，都是前端渲染
  不出来或者语音合成会卡住的东西 —— 这些必须回喂给模型重写。

回喂的理由（`SchemaInvalid.reason`）只由**字段名与数量**拼成，**绝不包含生成
内容** —— 它会被写进 `gen_steps.error`、显示给用户、也可能进日志（AGENTS §19）。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError

from app.services.generation import diagram

#: P1 §3.2 的九种页型。与 app/models/course.py 的 PAGE_KINDS 必须一致 ——
#: 那边是数据库 CHECK，这边是生成约束，两边对不上就会出现「生成得出、存不进」。
PAGE_KINDS: tuple[str, ...] = (
    "cover",
    "outline",
    "concept",
    "figure",
    "example",
    "code",
    "quiz",
    "summary",
    "debate",
)

#: 由管线按排版规则补齐的页型（`store.allocate_pages`）：封面、大纲页、
#: 研讨页、测验页、小结。用户改大纲时只管**正文页** —— 这几类提交上来也只会
#: 再被补一遍，于是「删掉的那页又回来了」看起来就像个 bug。
SYSTEM_KINDS: tuple[str, ...] = ("cover", "outline", "quiz", "summary", "debate")

#: 大纲里由模型（或用户）安排的页型 = 九种减去上面那五类。
CONTENT_KINDS: tuple[str, ...] = tuple(kind for kind in PAGE_KINDS if kind not in SYSTEM_KINDS)

#: 一个 beat 的字数上限。beat 是语音合成、字幕切换、白板对齐的最小单位
#: （技术方案 §3.3），超长必须切开，否则一句合成要等十几秒才出声。
MAX_BEAT_CHARS = 60

#: 中文讲稿语速约 5 字/秒，用于估算 estSec（60 字 ≈ 12 秒，与文档一致）。
CHARS_PER_SECOND = 5

#: 一门课的章节数上限。课堂要在 25 分钟内讲完，超过 6 章每章就只剩三四分钟，
#: 再多的章只是标题。它是**大纲**的限制，不是页数的限制（页数见 MAX_PAGE_COUNT）。
MAX_CHAPTERS = 6

#: 断句用的标点。强标点优先 —— 宁可这一句短一点，也不要在一句话中间断开。
_STRONG_MARKS = "。！？!?；;…"
_SOFT_MARKS = "，,、：:"

#: ```json … ``` 围栏
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class SchemaInvalid(ValueError):
    """模型输出不符合页面 Schema。

    reason 会**原样回喂给模型**让它重写，因此必须是「说清哪儿不对、怎么改」
    的中文短句，且不含生成内容、不含提示词、不含材料（AGENTS §19）。
    """

    def __init__(self, reason: str, *, kind: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.kind = kind


# --- 类型 ---


class Bullet(BaseModel):
    """一条要点。emphasis 是要高亮的词，前端据此加粗。"""

    text: str = ""
    emphasis: list[str] = Field(default_factory=list)


class Beat(BaseModel):
    """讲稿的一句。

    beatId 与 estSec 都是**服务端算的**，模型给什么都不作数 ——
    它算不准时长，而编号必须与页码对齐（见 normalize_beats）。
    """

    beatId: str = ""
    text: str = ""
    estSec: int = 0


class DiagramNode(BaseModel):
    """示意图里的一个节点。text 是节点上的字，一行放不下会自动折行。"""

    text: str = ""
    shape: str = "box"  # box | ellipse | diamond
    accent: bool = False  # 强调（这一页的主角）

    @model_validator(mode="before")
    @classmethod
    def _from_text(cls, value: Any) -> Any:
        """节点写成一句光字（`"收集资料"`）也认 —— 模型省事时的常见写法。"""
        return {"text": value} if isinstance(value, str) else value


class DiagramEdge(BaseModel):
    """一条箭头。`from` / `to` 是 `[行号, 列号]`（从 0 开始），指向 rows 里的节点。"""

    model_config = ConfigDict(populate_by_name=True)

    from_: tuple[int, int] = Field(default=(0, 0), alias="from")
    to: tuple[int, int] = Field(default=(0, 0))
    label: str = ""


class DiagramSpec(BaseModel):
    """结构化示意图：节点摆成网格，箭头连它们。服务端按这个渲染成 SVG。

    坐标由服务端算（模型画不准自由坐标，但「谁指向谁」说得准），
    所以这里只要**结构**：最多 4 行 ×3 列、最多 12 条箭头。
    """

    rows: list[list[DiagramNode]] = Field(
        default_factory=list, max_length=diagram.MAX_ROWS, description="节点网格，一行一个流程阶段"
    )
    edges: list[DiagramEdge] = Field(
        default_factory=list, max_length=diagram.MAX_EDGES, description="箭头，用 [行号,列号] 指节点"
    )


class Visual(BaseModel):
    """图示。`desc` 是给人看的描述，`spec` 是能真画出图的结构（服务端据此出 SVG）。"""

    type: str = ""
    desc: str = ""
    spec: DiagramSpec | None = None

    @field_validator("spec", mode="before")
    @classmethod
    def _salvage_spec(cls, value: Any) -> Any:
        """图画不出来不该拖垮整页：spec 不合格就当没给，desc 照旧留着。"""
        if value is None:
            return None
        try:
            return DiagramSpec.model_validate(value)
        except PydanticValidationError:
            return None


class Interaction(BaseModel):
    askAtEnd: bool = True
    allowFreeChat: bool = True


class BoardItem(BaseModel):
    """白板上的一个动作，atBeat 指向某个 beat。"""

    tool: str = ""
    desc: str = ""
    atBeat: str = ""


class CodeBlock(BaseModel):
    lang: str = ""
    content: str = ""


class Quiz(BaseModel):
    """随堂测验。四个选项是硬约束 —— 前端按 2×2 排布，三个会塌。"""

    stem: str = ""
    options: list[str] = Field(default_factory=list, min_length=4, max_length=4)
    answer: str = ""
    explain: str = ""
    conceptTag: str = ""


class Chapter(BaseModel):
    no: int = 0
    title: str = ""
    pages: list[int] = Field(default_factory=list)


class Side(BaseModel):
    """研讨的一方：立场 + 论据。"""

    stance: str = ""
    points: list[str] = Field(default_factory=list)


class CoverMeta(BaseModel):
    """封面要交代的三件事：谁讲、讲多久、讲给谁听（P1 §3.2）。

    它最终落在页面的 `meta` 字段里 —— `meta` 的语义是「关于这一页的元信息」，
    封面页的「元信息」正是这些；管线随后会把 model / tokens / generatedAt
    并进同一个字典（技术方案 §3.3 的例子）。
    """

    lecturer: str = ""
    durationMin: int = 0
    audience: str = ""


class AudienceProfile(BaseModel):
    """受众画像（P1 §4.2 的第一步产物）。

    它是后面每一步的上下文起点：写页时要照着它选例子与深度，出测验要照着它
    定难度。字段取成这些而不是「一大段画像描述」，是因为它要进**每一次**写页的
    提示词 —— 一段 300 字的散文会被重复 12 次，而这些字段只花几十个 token。
    """

    audience: str = ""
    difficulty: str = ""
    durationMin: int = 0
    chapterCount: int = 0
    style: str = ""
    objectives: list[str] = Field(default_factory=list)


class OutlinePage(BaseModel):
    """大纲里的一页：先定页型与要点，正文留到 write 步（P1 §3.1）。"""

    title: str = ""
    kind: str = ""
    points: list[str] = Field(default_factory=list)


class OutlineChapter(BaseModel):
    no: int = 0
    title: str = ""
    summary: str = ""
    #: 本章的讨论点。它是 quiz 步出讨论问题的输入（§4.2 大纲行的「讨论点」）。
    points: list[str] = Field(default_factory=list)
    pages: list[OutlinePage] = Field(default_factory=list)


class OutlineDraft(BaseModel):
    """大纲（P1 §3.1 的第二步产物）。

    它**不含**封面页、章节测验页与小结页：那三类由管线按规则补齐
    （见 pipeline 的 `allocate_pages`），模型只需要安排正文。
    让模型去记「每章末要插一页测验」这类排版规则，它总会在某一章漏掉。
    """

    title: str = ""
    subtitle: str = ""
    chapters: list[OutlineChapter] = Field(default_factory=list)


class DiscussionDraft(BaseModel):
    """一章的课堂讨论问题（P1 §3.1 的「讨论问题（章末，开关控制）」）。

    讨论问题**不是选择题**：它挂在章节上、不占页面。随堂测验的选择题
    是章末 quiz 页的内容，由 write 步按 quiz 页型写。
    """

    questions: list[str] = Field(default_factory=list)


class SourceRef(BaseModel):
    """一条出处（F4-8）：这一页的哪句话出自材料的哪一块。

    `chunkId` 是**材料分块的 id**（检索给模型看的那一段），不是页号 ——
    页号会因为重新解析而变，分块 id 不会。`quote` 必须是原文的连续片段，
    它由 `services/materials/citations.py` 逐字核对（P4-C2）。
    """

    chunkId: str = ""
    quote: str = ""


class PageDraft(BaseModel):
    """一页的全部可能字段。哪种页型要哪些，由 KindRule 说了算。"""

    kind: str = ""
    title: str = ""
    subtitle: str = ""

    bullets: list[Bullet] = Field(default_factory=list)
    narration: list[Beat] = Field(default_factory=list)
    visual: Visual | None = None
    interaction: Interaction | None = None
    boardPlan: list[BoardItem] = Field(default_factory=list)
    #: 出处（P4-4）。`gaps` 是「材料里没有、这一页又必须讲」的部分（P4-A8）——
    #: 显式列出来，好过让模型凭常识编一段看不出来的话。
    sources: list[SourceRef] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    #: 这一页有出处没核对上（§5）。由管线在校验后**重写**，不是模型的自我评价 ——
    #: 放在 Schema 里是为了让 DSL 的形状在一处说清（前端据此标黄提示）。
    sourceMissing: bool = False

    @field_validator("sources", mode="before")
    @classmethod
    def _drop_legacy_sources(cls, value: Any) -> Any:
        """P1 时代 `sources` 是一串自由文本（「参考《讲义》第三章」）。

        那种串没有 chunkId，无从核对，留着只会在界面上显示一个点不开的出处。
        在这里丢掉，而不是报错：旧课程重新生成时不该因为一个老字段整页失败。
        """
        if isinstance(value, list):
            return [item for item in value if isinstance(item, (dict, SourceRef))]
        return value

    #: outline
    chapters: list[Chapter] = Field(default_factory=list)
    #: example
    steps: list[str] = Field(default_factory=list)
    #: code
    code: CodeBlock | None = None
    explanation: list[str] = Field(default_factory=list)
    #: quiz
    quiz: Quiz | None = None
    hintScript: str = ""
    #: summary
    question: str = ""
    #: debate
    topic: str = ""
    sides: list[Side] = Field(default_factory=list)
    arbiterSummary: str = ""
    #: cover
    meta: CoverMeta | None = None


#: 人工编辑允许改的字段（P1 §4 的 PUT /pages/{pageNo}）。
#: 结构性的那一项 `kind` 不在其中：改了页型就是另一页了，不是「编辑」。
#: 这份清单**从模型字段推导**，不手写 —— 手写的那份会在加字段时忘了跟上，
#: 于是新字段要么改不了，要么能改出一个模型不认识的键。
EDITABLE_FIELDS: tuple[str, ...] = tuple(
    name for name in PageDraft.model_fields if name != "kind"
)


# --- 每种页型要什么（唯一事实来源）---


@dataclass(frozen=True)
class KindRule:
    """一种页型的必填要求（P1 §3.2 表格的代码形态）。

    required  —— 字段必须存在且非空（字符串要有内容 / 数组要有元素 / 子对象非 None）
    min_items —— 数组字段的最小长度，同时蕴含「这个字段必须存在」
    """

    required: tuple[str, ...] = ()
    min_items: Mapping[str, int] = field(default_factory=dict)

    @property
    def json_schema_required(self) -> list[str]:
        """发给模型的 Schema 里的 required —— minItems≥1 的字段也等于必填。"""
        return sorted(set(self.required) | {k for k, n in self.min_items.items() if n >= 1})

    def merged_with(self, extra: KindRule) -> KindRule:
        """并上另一份要求。同名字段取**更严**的那个（required 取并集、min_items 取大）。"""
        items = dict(self.min_items)
        for name, count in extra.min_items.items():
            items[name] = max(count, items.get(name, 0))
        return KindRule(required=tuple({*self.required, *extra.required}), min_items=items)


#: 每一种页都要有的东西，与页型无关。
#:
#: §3.2 的表格给的是**每种页型**的下限，这里是**每一页**的下限，两者是叠加关系。
#: 之所以加这一层，是因为 P1-A5 要求「12 页里字段齐全的 ≥ 12×95%」——
#: 那是「每一页」的口径，光靠 §3.2 的分页型要求做不到：封面页按表格只需
#: title/subtitle/meta，量出来就是「字段不全」。
#:
#: 而且这几项本来就是课堂要用的，不是凑指标：每一页都要能讲（narration）、
#: 都要有可扫读的要点（bullets）、都要有视觉锚点（visual）——
#: P2 的语音合成与白板会**逐页**消费它们，缺一页就是上课时的一处空白。
UNIVERSAL_RULE = KindRule(
    required=("subtitle", "visual"),
    min_items={"bullets": 3, "narration": 3},
)

KIND_RULES: dict[str, KindRule] = {
    "cover": KindRule(required=("title", "subtitle", "meta")),
    "outline": KindRule(required=("title",), min_items={"chapters": 1}),
    "concept": KindRule(required=("title",), min_items={"bullets": 3, "narration": 3}),
    "figure": KindRule(required=("title", "visual")),
    "example": KindRule(required=("title",), min_items={"steps": 1, "narration": 1}),
    "code": KindRule(required=("title", "code")),
    "quiz": KindRule(required=("title", "quiz")),
    "summary": KindRule(required=("title", "question"), min_items={"bullets": 1}),
    "debate": KindRule(required=("title", "topic"), min_items={"sides": 2}),
}


# --- 入口 ---


def parse_page(kind: str, text: str, *, page_no: int = 0, chapter_no: int = 0) -> dict:
    """把模型输出的一段文本解析成规范化后的页面 DSL。

    失败抛 `SchemaInvalid`，理由可直接回喂给模型（见模块 docstring）。
    """
    return validate_page(kind, load_json(text), page_no=page_no, chapter_no=chapter_no)


def validate_page(kind: str, data: Mapping[str, Any], *, page_no: int = 0, chapter_no: int = 0) -> dict:
    """校验一个已经是字典的页面，返回规范化后的 DSL。"""
    _require_kind(kind)

    # kind 以调用方为准：提示词里说的是「生成一个 concept 页」，
    # 模型偶尔会把 kind 抄成别的，那不是重写一遍的理由。
    payload = {**data, "kind": kind}
    try:
        draft = PageDraft.model_validate(payload)
    except PydanticValidationError as exc:
        raise SchemaInvalid(_translate(exc), kind=kind) from exc

    page = _to_dsl(kind, draft, page_no=page_no, chapter_no=chapter_no)
    _check(kind, page)
    return page


def schema_for_kind(kind: str) -> dict:
    """发给模型的 JSON Schema：`PageDraft` 的结构 + 这种页型的必填要求。"""
    rule = _rule(kind)
    schema = PageDraft.model_json_schema()
    schema["properties"]["kind"] = {"enum": [kind], "type": "string"}
    schema["required"] = rule.json_schema_required
    for name, count in rule.min_items.items():
        prop = schema["properties"].get(name)
        if isinstance(prop, dict):
            prop["minItems"] = count
    # 固定 4 个选项这类嵌套约束由 pydantic 自己生成（Field(min_length/max_length)
    # 在列表上就是 minItems/maxItems），不必在这里再写一遍。
    return schema


# --- 大纲与受众画像 ---
#
# 这两样不是「页」，但同样是一次结构化输出，同样要过校验才能用。
# 它们与页共用一套错误约定（SchemaInvalid + 中文理由回喂），
# 所以放在同一个模块里 —— 分成两个文件只会让 `load_json` 之类的工具两边各放一份。


def parse_profile(text: str) -> dict:
    """解析受众画像。只要求「讲给谁听」有答案 —— 这是画像存在的理由。

    其余字段（章节数、时长）宁可留空由管线按用户的设置补，也不判失败：
    为了让模型多写两个数字而把整门课判失败，是拿一次重试换一次更差的体验。
    """
    data = _validate_model(AudienceProfile, load_json(text), label="受众画像")
    profile = {
        "audience": data.audience.strip(),
        "difficulty": data.difficulty.strip(),
        "durationMin": max(0, data.durationMin),
        "chapterCount": max(0, data.chapterCount),
        "style": data.style.strip(),
        "objectives": [item.strip() for item in data.objectives if item.strip()],
    }
    if not profile["audience"]:
        raise SchemaInvalid("受众画像缺少 audience（这门课讲给谁听）")
    return profile


def parse_outline(text: str, *, max_pages: int = 20) -> dict:
    """解析课程大纲，并把章节号规范化成 1..n。"""
    data = _validate_model(OutlineDraft, load_json(text), label="课程大纲")
    chapters = [_chapter(chapter, index) for index, chapter in enumerate(data.chapters, 1) if _has_pages(chapter)]
    if not chapters:
        raise SchemaInvalid("课程大纲至少需要一个带页面的章节")

    total = sum(len(chapter["pages"]) for chapter in chapters)
    if len(chapters) > MAX_CHAPTERS:
        raise SchemaInvalid(f"课程大纲最多 {MAX_CHAPTERS} 章（当前 {len(chapters)} 章）")
    if total > max_pages:
        raise SchemaInvalid(f"课程大纲的正文页最多 {max_pages} 页（当前 {total} 页）")

    return {
        "title": data.title.strip(),
        "subtitle": data.subtitle.strip(),
        "chapters": chapters,
        "pageCount": total,
    }


def parse_discussion(text: str, *, min_items: int = 2, max_items: int = 5) -> dict:
    """解析章末讨论问题。

    要 2~3 个而不是「至少 1 个」：一场研讨课只有一个问题，讨论五分钟就没了；
    `minItems` 也写在 Schema 里，模型照着填就不会踩这条线。
    """
    data = _validate_model(DiscussionDraft, load_json(text), label="讨论问题")
    questions = [item.strip() for item in data.questions if item.strip()]
    if len(questions) < min_items:
        raise SchemaInvalid(f"讨论问题至少需要 {min_items} 个（当前 {len(questions)} 个）")
    return {"questions": questions[:max_items]}


def schema_for_profile() -> dict:
    """受众画像的 JSON Schema。"""
    schema = AudienceProfile.model_json_schema()
    schema["required"] = ["audience", "objectives"]
    schema["properties"]["objectives"]["minItems"] = 1
    return schema


def schema_for_outline(*, max_chapters: int = MAX_CHAPTERS, max_pages: int = 20) -> dict:
    """大纲的 JSON Schema。

    上限写进 Schema 而不是等它超了再判失败：模型自己会数数，
    给它一个 maxItems 比事后回喂一次「你写多了」便宜得多。
    """
    schema = OutlineDraft.model_json_schema()
    chapter = _resolve(schema, schema["properties"]["chapters"])
    chapter["minItems"] = 1
    chapter["maxItems"] = max_chapters
    # 数组的 items 也是一个 $ref（指向 $defs/OutlineChapter），要再解一层
    chapter_fields = _resolve(schema, chapter["items"]).get("properties") or {}
    page = _resolve(schema, chapter_fields.get("pages"))
    page["minItems"] = 1
    page_item = _resolve(schema, page.get("items"))
    page_item["properties"]["kind"] = {"enum": list(PAGE_KINDS), "type": "string"}
    schema["required"] = ["chapters"]
    # 正文页总数的上限落在**每章**上（Schema 没法表达「各章相加不超过 N」），
    # 由出题时的提示词再声明一次总量，parse_outline 兜底。
    page["maxItems"] = max(1, max_pages // max(1, max_chapters))
    return schema


def schema_for_discussion(*, min_items: int = 2, max_items: int = 5) -> dict:
    """讨论问题的 JSON Schema。"""
    schema = DiscussionDraft.model_json_schema()
    questions = schema["properties"]["questions"]
    questions["minItems"] = min_items
    questions["maxItems"] = max_items
    schema["required"] = ["questions"]
    return schema


def load_json(text: str) -> dict:
    """把一段文本读成 JSON 对象。模型的花式写法在这里被抹平。"""
    raw = (text or "").strip()
    if not raw:
        raise SchemaInvalid("输出为空，没有返回任何 JSON 内容")

    fenced = _FENCE.search(raw)
    if fenced:
        raw = fenced.group(1).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = _loads_by_slice(raw)
        if data is None:
            raise SchemaInvalid("输出不是合法的 JSON，无法解析") from None

    if not isinstance(data, dict):
        raise SchemaInvalid("输出的顶层必须是 JSON 对象")
    return data


def normalize_beats(beats: Sequence[Beat | Mapping[str, Any]], *, page_no: int) -> list[dict]:
    """把讲稿切成一页内的顺序 beat，编号与页号对齐。

    - 空 beat 丢掉：留着会让语音合成停在一个空字符串上；
    - 超过 MAX_BEAT_CHARS 的切开：它是合成与字幕的最小单位；
    - beatId 一律重排（p{pageNo}-b{n}），因为模型会漏编号、重号、跳号。
    """
    texts: list[str] = []
    for beat in beats:
        # 两种入参：校验后的 Beat，和还没过校验的原始字典（重写页面时用后者）
        raw = beat.get("text") if isinstance(beat, Mapping) else beat.text
        texts.extend(split_beat(str(raw or "")))
    return [
        {"beatId": f"p{page_no}-b{index}", "text": text, "estSec": estimate_sec(text)}
        for index, text in enumerate(texts, start=1)
    ]


def split_beat(text: str, limit: int = MAX_BEAT_CHARS) -> list[str]:
    """把一句话切成不超过 limit 字的若干句。"""
    rest = " ".join(str(text).split())
    if not rest:
        return []

    parts: list[str] = []
    while len(rest) > limit:
        cut = _cut_point(rest, limit)
        head = rest[:cut].strip()
        if head:
            parts.append(head)
        rest = rest[cut:].strip()
    if rest:
        parts.append(rest)
    return parts


def estimate_sec(text: str) -> int:
    """按语速估算朗读时长（秒）。宁可略短：估长了会让进度条走不满。"""
    return max(1, math.ceil(len(text) / CHARS_PER_SECOND))


# --- 内部 ---


def _rule(kind: str) -> KindRule:
    """这种页型的完整要求 = 分页型的要求 + 每一页都要有的要求。"""
    return KIND_RULES[_require_kind(kind)].merged_with(UNIVERSAL_RULE)


def _require_kind(kind: str) -> str:
    if kind not in KIND_RULES:
        raise SchemaInvalid(
            f"未知页型 {kind}；可选：{'、'.join(PAGE_KINDS)}", kind=str(kind)
        )
    return kind


def _resolve(schema: Mapping[str, Any], node: Any) -> dict:
    """顺着 `$ref` 走到真正的那个 Schema 节点。

    pydantic 会把嵌套模型抽到 `$defs` 里、在原处只留一个 `$ref`，
    所以「改大纲里 chapters 那一层的约束」不能直接下标取 ——
    拿到的是一个 `{"$ref": ...}`，上面既没有 properties 也没有 items。
    """
    defs = schema.get("$defs") or schema.get("definitions") or {}
    current = node
    walked = 0
    while isinstance(current, dict) and "$ref" in current and walked < 8:
        current = defs.get(str(current["$ref"]).rsplit("/", 1)[-1]) or {}
        walked += 1
    return current if isinstance(current, dict) else {}


def _validate_model(model: type[BaseModel], data: Mapping[str, Any], *, label: str) -> Any:
    """把一份字典按模型校验。失败理由翻译成中文（与页面同一套回喂约定）。"""
    try:
        return model.model_validate(data)
    except PydanticValidationError as exc:
        raise SchemaInvalid(f"{label}不符合要求：{_translate(exc)}") from exc


def _chapter(chapter: Any, no: int) -> dict:
    """一章的规范化。

    页型不认识的页**丢掉**而不是判失败：大纲里有 8 个页型，模型把某一页写成
    它自己发明的 `table` 很正常，为这一页把整份大纲判失败、重写一遍 8 页，
    代价远大于收益。丢掉的痕迹留在 chapters[].dropped 里，供排查。
    """
    pages: list[dict] = []
    dropped = 0
    for page in chapter.pages:
        kind = page.kind.strip()
        if kind not in KIND_RULES or not page.title.strip():
            dropped += 1
            continue
        pages.append(
            {
                "title": page.title.strip(),
                "kind": kind,
                "points": [item.strip() for item in page.points if item.strip()],
            }
        )
    return {
        "no": no,
        "title": chapter.title.strip() or f"第 {no} 章",
        "summary": chapter.summary.strip(),
        "points": [item.strip() for item in chapter.points if item.strip()],
        "pages": pages,
        "dropped": dropped,
    }


def _has_pages(chapter: Any) -> bool:
    return any(
        page.kind.strip() in KIND_RULES and page.title.strip() for page in chapter.pages
    )


def _cut_point(text: str, limit: int) -> int:
    """在 limit 附近找一个断句点，返回切分下标。

    强标点 → 弱标点 → 硬切。只在前半段之后找：在「，梯度」这种位置断开
    会切出一个三五个字的碎片，合成出来像被掐断。
    """
    window = text[:limit]
    floor = limit // 2
    for marks in (_STRONG_MARKS, _SOFT_MARKS):
        for index in range(len(window) - 1, floor - 1, -1):
            if window[index] in marks:
                return index + 1
    return limit


def _loads_by_slice(raw: str) -> dict | None:
    """去掉首尾废话再试一次：模型爱写「好的，以下是 JSON：{…}，希望有帮助」。"""
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _translate(exc: PydanticValidationError) -> str:
    """把 pydantic 的英文报错翻成能回喂给模型的中文。

    只保留前三条：全都拼上去会让提示词在一堆细节里淹掉主要原因。
    """
    parts: list[str] = []
    for error in exc.errors()[:3]:
        location = ".".join(str(item) for item in error["loc"]) or "顶层"
        ctx = error.get("ctx") or {}
        kind = error["type"]
        if kind == "too_short":
            parts.append(
                f"{location} 至少需要 {ctx.get('min_length')} 项（当前 {ctx.get('actual_length')} 项）"
            )
        elif kind == "too_long":
            parts.append(
                f"{location} 最多 {ctx.get('max_length')} 项（当前 {ctx.get('actual_length')} 项）"
            )
        elif kind in {"missing", "value_error"}:
            parts.append(f"{location} 不符合要求")
        else:
            parts.append(f"{location} 的类型或取值不符合 Schema（{kind}）")
    return "；".join(parts) or "输出结构不符合 Schema"


def _to_dsl(kind: str, draft: PageDraft, *, page_no: int, chapter_no: int) -> dict:
    """校验通过的类型 → 页面 DSL。

    这里同时做**归一**：模型写了但等于没写的东西（空白标题、没有正文的代码块、
    没有题干的选择题）一律收敛成 None / 空，好让「必填字段」这**一条**通用规则
    就能拦住它们 —— 不必给每种页型再写一套特例。
    """
    return {
        "pageNo": page_no,
        "chapterNo": chapter_no,
        "kind": kind,
        "title": draft.title.strip(),
        "subtitle": draft.subtitle.strip(),
        "bullets": [
            {"text": bullet.text.strip(), "emphasis": [e for e in bullet.emphasis if e.strip()]}
            for bullet in draft.bullets
            if bullet.text.strip()
        ],
        "narration": normalize_beats(draft.narration, page_no=page_no),
        "visual": _visual(draft.visual),
        "interaction": (
            draft.interaction.model_dump() if draft.interaction is not None else None
        ),
        "boardPlan": [
            {"tool": item.tool.strip(), "desc": item.desc.strip(), "atBeat": item.atBeat.strip()}
            for item in draft.boardPlan
            if item.desc.strip()
        ],
        # 出处：只留两端都有内容的（缺 chunkId 的点不开，缺 quote 的核不了）。
        # **对不对**不在这里判 —— 那要拿材料原文比，属于 citations 的事（P4-C2）。
        "sources": [
            {"chunkId": item.chunkId.strip(), "quote": item.quote.strip()}
            for item in draft.sources
            if item.chunkId.strip() and item.quote.strip()
        ],
        # 材料缺口（P4-A8）：写成一句能直接显示给学生看的话
        "gaps": [gap.strip() for gap in draft.gaps if gap.strip()],
        # 出处的核对结果由管线写（见 PageDraft.sourceMissing）；这里先把模型
        # 自己写的那个值带过来，免得它凭空消失
        "sourceMissing": bool(draft.sourceMissing),
        "chapters": [
            {"no": chapter.no, "title": chapter.title.strip(), "pages": list(chapter.pages)}
            for chapter in draft.chapters
            if chapter.title.strip()
        ],
        "steps": [step.strip() for step in draft.steps if step.strip()],
        "code": _code(draft.code),
        "explanation": [item.strip() for item in draft.explanation if item.strip()],
        "quiz": _quiz(draft.quiz),
        "hintScript": draft.hintScript.strip(),
        "question": draft.question.strip(),
        "topic": draft.topic.strip(),
        "sides": [
            {"stance": side.stance.strip(), "points": [p.strip() for p in side.points if p.strip()]}
            for side in draft.sides
            if side.stance.strip() and any(p.strip() for p in side.points)
        ],
        "arbiterSummary": draft.arbiterSummary.strip(),
        "meta": _meta(draft.meta),
    }


def _visual(visual: Visual | None) -> dict | None:
    """没有 desc 的图示描述是空话 —— 前端画不出来，当作没给。

    有 `spec` 就顺带把 SVG 画出来存进 DSL：渲染是**确定性**的，落库后
    导出三格式与网页放映用的是同一份字节，不必各自再画一遍。画不出来
    （节点太少、结构认不出）就只留 desc，退回「文字描述 + 占位」的老样子。
    """
    if visual is None or not visual.desc.strip():
        return None
    page_visual: dict[str, Any] = {"type": visual.type.strip() or "diagram", "desc": visual.desc.strip()}
    if visual.spec is not None:
        spec = visual.spec.model_dump(by_alias=True)
        svg = diagram.render(spec)
        if svg:
            page_visual["spec"] = spec
            page_visual["svg"] = svg
    return page_visual


def _code(code: CodeBlock | None) -> dict | None:
    """代码页没有代码就不算代码页（哪怕模型把语言写对了）。"""
    if code is None or not code.content.strip():
        return None
    return {
        "lang": code.lang.strip() or "text",
        "content": code.content.strip("\n").rstrip(),
    }


def _quiz(quiz: Quiz | None) -> dict | None:
    """题干或答案缺一个，这道题就没法判对错。"""
    if quiz is None or not quiz.stem.strip() or not quiz.answer.strip():
        return None
    return {
        "stem": quiz.stem.strip(),
        "options": [option.strip() for option in quiz.options],
        "answer": quiz.answer.strip(),
        "explain": quiz.explain.strip(),
        "conceptTag": quiz.conceptTag.strip(),
    }


def _meta(meta: CoverMeta | None) -> dict:
    if meta is None:
        return {}
    payload: dict[str, Any] = {}
    if meta.lecturer.strip():
        payload["lecturer"] = meta.lecturer.strip()
    if meta.audience.strip():
        payload["audience"] = meta.audience.strip()
    if meta.durationMin > 0:
        payload["durationMin"] = meta.durationMin
    return payload


def _check(kind: str, page: Mapping[str, Any]) -> None:
    """按 KindRule 检查必填项。检查的是**规范化之后**的 DSL。

    这一点是有意的：一条 150 字的讲稿被切成 3 个 beat 之后，讲稿就是合格的 ——
    判定标准应该是「最终存下来的长什么样」，不是「模型一次写成了什么样」。
    """
    rule = _rule(kind)

    for name in rule.required:
        if not _filled(page.get(name)):
            raise SchemaInvalid(f"{kind} 页缺少必填字段 {name}", kind=kind)

    for name, count in rule.min_items.items():
        actual = len(page.get(name) or [])
        if actual < count:
            raise SchemaInvalid(
                f"{kind} 页的 {name} 至少需要 {count} 项（当前 {actual} 项）", kind=kind
            )


def _filled(value: Any) -> bool:
    """「写了等于没写」一律算没写。"""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping | Sequence):
        return bool(value)
    return True


__all__ = [
    "CONTENT_KINDS",
    "EDITABLE_FIELDS",
    "KIND_RULES",
    "MAX_BEAT_CHARS",
    "MAX_CHAPTERS",
    "PAGE_KINDS",
    "SYSTEM_KINDS",
    "UNIVERSAL_RULE",
    "AudienceProfile",
    "DiscussionDraft",
    "KindRule",
    "OutlineDraft",
    "SchemaInvalid",
    "estimate_sec",
    "load_json",
    "normalize_beats",
    "parse_discussion",
    "parse_outline",
    "parse_page",
    "parse_profile",
    "schema_for_discussion",
    "schema_for_kind",
    "schema_for_outline",
    "schema_for_profile",
    "split_beat",
    "validate_page",
]
