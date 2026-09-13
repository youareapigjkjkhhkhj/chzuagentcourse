"""生成链路里的材料注入与溯源校验（P4-4 / F4-7 / F4-8 / P4-A5/A7/A8）。

一次生成要用上材料，要串起四段：**关联**（这门课有哪些材料）→ **检索**（这一页该看哪几块）
→ **注入**（围栏 + 真实 chunkId + 引用规矩）→ **核对**（引文逐字比对、落 `page_sources`）。
这个文件按用户的走法把四段连起来跑一遍：上传讲义 → 关联到课程 → 生成 → 出处在库里。

桩模型（`QuotingLLM`）演的是一个**守规矩的模型**：它从提示词给它的那几片材料里抄引文。
于是「引了哪一块、抄了哪一句」全由注入的内容决定 —— 这条链通没通，看一眼落库的
`page_sources` 就知道。另外几条路验的是「模型不守规矩」时用户的观感：

- 编了一条引文 → 带着**具体是哪一条不对**重试一次（§5）；
- 还是对不上 → 内容留着、标 `sourceMissing`、只留能核对的出处（P4-A8）；
- 这门课压根没材料 → 一个出处都不留（否则前端会出现点不开的徽标，P4-G3）。

真实解析（PyMuPDF / jieba）与真实 BM25 检索都照跑，只有模型那一层是桩 ——
所以这组用例同时在验「检索词取对了没有」：桩抄不到材料，多半是查询词压根没命中。
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import select

from app.common.identity import OWNER_HEADER
from app.extensions import db
from app.models import CoursePageVersion, MaterialChunk, PageSource, User
from app.services.courses import library, store
from app.services.generation import prompts
from app.services.generation.pipeline import DEFAULT_OPTIONS, run_job, start_job
from app.services.materials import citations
from app.services.materials import store as material_store
from tests.unit.test_generation_pipeline import StubLLM

pytestmark = pytest.mark.unit

ME = "u1"
OWNER = {OWNER_HEADER: ME}

#: 一份和课程主题对得上的讲义 —— 检索要命中，材料就得真的讲这件事。
#: 段落之间不共用词，这样「引了哪一块」是可指名的。
LECTURE = """# 第一章 检索

倒排索引把词映射到文档，是搜索引擎的基石，也是后续排序的前提。
构建倒排索引要先分词，再统计每个词出现在哪些文档里，这一步决定了检索的召回。

## 1.1 词频

词频是一块内容里某个词出现的次数，它是打分公式里最先被想到的那个因子。
只按词频排序会让长文档占便宜，因为长文档本来就有更多机会重复同一个词。

# 第二章 排序

BM25 是一种经典的排序函数，它同时考虑词频与文档长度，把两者都做了归一化。
长度为一块的词语分布做了归一，于是长块不会因为词多就自动排到前面去。
"""

#: 模型编出来的那种引文：读着像讲义，其实原文里一个字都找不到。
FABRICATED = "这段话读起来很像讲义里的原话，但材料里其实一个字都没有写过它。"

#: 提示词里的材料围栏（`prompts.material_block` 的格式）。
_FENCE = re.compile(r"<<<MATERIAL chunk:(?P<id>\S+)>>>\n(?P<body>.*?)\n<<<END>>>", re.S)
#: 出处小字那一行是**给模型的线索**，不属于材料正文，抄引文时要跳过它。
_CAPTION = "（出处："


class QuotingLLM(StubLLM):
    """会照着材料抄引文的桩模型。

    `honest=False` 时它第一版编一条对不上的引文（用来验重试）；
    `retry_honest=False` 连重试那一版也编（用来验 `sourceMissing`）；
    `always_quote=True` 时哪怕提示词里一片材料都没有，它也硬编一条出来 ——
    现实里模型确实会这么干（它凭常识写内容，再给内容配个像样的出处）。
    """

    def __init__(
        self,
        *,
        honest: bool = True,
        retry_honest: bool = True,
        always_quote: bool = False,
        per_page: int = 1,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.honest = honest
        self.retry_honest = retry_honest
        self.always_quote = always_quote
        self.per_page = per_page
        self.prompts: list[str] = []

    def chat(self, messages, **options):
        # 桩模型「读材料」就是读提示词里那几片围栏 —— 记下来给断言用
        self.prompts.append("\n".join(str(item.get("content", "")) for item in messages))
        return super().chat(messages, **options)

    def _page(self, task: dict) -> dict:
        data = super()._page(task)
        data["sources"] = self._sources(self.prompts[-1], self.counts[int(task["pageNo"])])
        return data

    def _sources(self, prompt: str, count: int) -> list[dict]:
        blocks = _chunks_of(prompt)
        if self.honest or (count > 1 and self.retry_honest):
            return [
                {"chunkId": chunk_id, "quote": _quote_of(text)}
                for chunk_id, text in blocks[: self.per_page]
            ]
        if not blocks and not self.always_quote:
            return []
        # 编一条：chunkId 用真给过的那一块（换一块材料、换个页面的场景），
        # 一片都没给过时才连 id 一起编。
        chunk_id = blocks[0][0] if blocks else "chunk:made-up"
        return [{"chunkId": chunk_id, "quote": FABRICATED}]

    def _chapter(self, no: int) -> dict:
        """大纲的章节与页标题要贴着讲义写 —— 写页时的检索词就是它们。

        桩默认那套「第 N 章的第 M 页」查不倒任何材料，那样这组用例验的
        就不是「注入通没通」，而是「查询词恰好没命中」。
        """
        kinds = ("concept", "example", "figure", "code")
        return {
            "no": no,
            "title": f"检索与排序（第 {no} 章）",
            "summary": "倒排索引怎么建、BM25 怎么给结果排序",
            "points": ["倒排索引把词映射到文档", "BM25 同时考虑词频与文档长度"],
            "pages": [
                {
                    "title": f"倒排索引与 BM25 排序（第 {no} 章第 {index} 节）",
                    "kind": kinds[(no + index) % len(kinds)],
                    "points": ["倒排索引", "词频与文档长度归一化"],
                }
                for index in range(1, self.pages_per_chapter + 1)
            ],
        }


def _chunks_of(prompt: str) -> list[tuple[str, str]]:
    """提示词里那几片材料（chunkId, 正文）。"""
    blocks: list[tuple[str, str]] = []
    for found in _FENCE.finditer(prompt):
        body = "\n".join(
            line for line in found.group("body").splitlines() if not line.startswith(_CAPTION)
        ).strip()
        if body:
            blocks.append((found.group("id"), body))
    return blocks


def _quote_of(text: str) -> str:
    """从材料正文里抄一段 —— 逐字，不改写。"""
    return text[:60].strip()


def _squeeze(text: str) -> str:
    return citations._squeeze(text)


def _calls(llm: QuotingLLM, task: str) -> list[str]:
    """这一类调用的提示词（按任务头里的 `"task": "page"` 认）。"""
    return [prompt for prompt in llm.prompts if f'"task": "{task}"' in prompt]


# --- 场景 ---


@dataclass
class Scene:
    app: Any
    client: Any
    course: Any
    job: Any
    file_id: str
    llm: QuotingLLM

    def pages(self) -> list:
        return store.pages_of(self.course)

    def sources(self) -> list[PageSource]:
        return list(db.session.scalars(select(PageSource).order_by(PageSource.chunk_id)))


@pytest.fixture()
def sync_parse(monkeypatch):
    """上传后同步解析完（后台线程那一层在 `test_material_store.py` 里验过）。"""
    monkeypatch.setattr(material_store, "submit_parse", material_store.parse_material)


def _scene(app, client, *, llm: QuotingLLM | None = None, attach: bool = True) -> Scene:
    db.session.add(User(id=ME, name="小明", role="teacher"))
    db.session.commit()

    options = {**DEFAULT_OPTIONS, "pageCount": 8, "concurrency": 1}
    course = store.create_course(
        title="检索与排序", topic="检索与排序", options=options, owner_id=ME
    )
    job = start_job(course, options=options, owner_id=ME)

    model = llm or QuotingLLM()
    file_id = _upload(client)
    if attach:
        _attach(client, course.id, file_id)
    return Scene(app=app, client=client, course=course, job=job, file_id=file_id, llm=model)


def _upload(client, text: str = LECTURE, name: str = "讲义.md") -> str:
    response = client.post(
        "/api/materials",
        data={"file": (io.BytesIO(text.encode("utf-8")), name)},
        headers=OWNER,
        content_type="multipart/form-data",
    )
    body = response.get_json()["data"]
    assert body["status"] == "ready", body
    return body["fileId"]


def _attach(client, course_id: str, file_id: str) -> None:
    response = client.post(
        f"/api/courses/{course_id}/materials", json={"fileIds": [file_id]}, headers=OWNER
    )
    assert response.get_json()["data"]["added"] == [file_id]


# --- 一次完整的生成 ---


def test_every_citation_points_back_at_the_material(app, client, sync_parse):
    """P4-A8：页面上每一处出处都能在材料原文里**逐字**找到，且指得回那一块。"""
    scene = _scene(app, client)

    run_job(scene.job.id, llm=scene.llm)

    rows = scene.sources()
    assert rows, "讲义就在课程里，生成出来的出处不该是空的"
    chunks = {row.id: row for row in db.session.scalars(select(MaterialChunk))}
    for row in rows:
        assert row.material_id == scene.file_id
        chunk = chunks[row.chunk_id]
        assert _squeeze(row.quote) in _squeeze(chunk.text), "出处必须是原文里的连续片段"
        assert row.score > 0, "出处带着它那次的检索分"
        assert row.page_id

    for page in scene.pages():
        if page.status != "ready":
            continue
        # 页面上那份与 page_sources 那份是同一批：一个用来渲染，一个用来跳转
        mine = [row for row in rows if row.page_id == page.id]
        assert [item["chunkId"] for item in page.dsl["sources"]] == [row.chunk_id for row in mine]
        # 不光是同一批，**字段名也得一样**：`page.rewritten` 推的是 `to_dict()`
        # 那一份，前端两处读同一种形状，改名时两边一起改才不会漏（`fileId` →
        # `materialId` 就是这么漏过一次的）。`pageId` 是那一份多的，前端用不到。
        if mine:
            assert set(page.dsl["sources"][0]) == set(mine[0].to_dict()) - {"pageId"}
        assert page.dsl["sourceMissing"] is False


def test_the_material_is_injected_with_its_real_chunk_ids(app, client, sync_parse):
    """F4-8 的前半段：围栏里给的是**真实 chunkId**，且引用要求跟在材料后面。

    模型回填的 id 必须是这一块的 id，而不是「第几片」—— 重新解析之后片号会变，
    已经落库的出处就全指错了。
    """
    scene = _scene(app, client)

    run_job(scene.job.id, llm=scene.llm)

    real = {row.id for row in db.session.scalars(select(MaterialChunk))}
    seen: set[str] = set()
    for prompt in scene.llm.prompts:
        seen.update(chunk_id for chunk_id, _text in _chunks_of(prompt))
    assert seen, "提示词里一片材料都没有 —— 检索没命中（多半是检索词取错了）"
    assert seen <= real, "围栏里的 chunkId 必须来自真实的材料分块"
    # 引用规矩只跟写页/重写说（出大纲、出讨论题那几步不产出处），
    # 且**有材料才说** —— 一片都没给的时候讲「引用材料」只会把模型带偏
    pages = _calls(scene.llm, "page")
    assert pages
    with_material = [prompt for prompt in pages if "【参考资料】" in prompt]
    assert with_material, "写页时也该带上材料（不只是出大纲那一步）"
    assert all(prompts.MATERIAL_CITATION_RULES in prompt for prompt in with_material)


def test_the_outline_also_runs_on_the_material(app, client, sync_parse):
    """出大纲时也带上材料（P4-A5）：章节要贴着讲义走，不是生成完再让用户手动改。"""
    scene = _scene(app, client)

    run_job(scene.job.id, llm=scene.llm)

    outline = _calls(scene.llm, "outline")
    assert outline and "【参考资料】" in outline[0]
    assert _chunks_of(outline[0]), "大纲的提示词里要看得到材料片段"


# --- 模型不守规矩的三条路 ---


def test_a_fabricated_quote_is_retried_with_the_reason(app, client, sync_parse):
    """§5：引文核不过 → 带着「哪一条不对」重试一次，第二次对了就照常发布。"""
    scene = _scene(app, client, llm=QuotingLLM(honest=False))

    run_job(scene.job.id, llm=scene.llm)

    quoted = [page for page in scene.pages() if page.dsl.get("sources")]
    assert quoted, "重试之后应当留下一批能核对的出处"
    page = quoted[0]
    assert page.dsl["sourceMissing"] is False
    assert scene.llm.counts[page.page_no] == 2, "编的引文要触发一次重试"
    retries = [prompt for prompt in scene.llm.prompts if "quote 必须是材料原文里" in prompt]
    assert retries, "回喂的文案要说清怎么改"
    # 重试是同一条对话的续写：材料还在上下文里，模型才改得动
    assert "【参考资料】" in retries[0] and _chunks_of(retries[0])


def test_a_quote_that_never_matches_keeps_the_page_but_flags_it(app, client, sync_parse, caplog):
    """P4-A7/A8：两次都对不上 → 内容留着（用户要能用的课件）、标 `sourceMissing`、
    只留通过的那些出处，并把原因写进日志（用户看不到，排障要靠它）。"""
    scene = _scene(
        app, client, llm=QuotingLLM(honest=False, retry_honest=False, always_quote=True)
    )

    with caplog.at_level("WARNING", logger="app.generation.sourcing"):
        run_job(scene.job.id, llm=scene.llm)

    pages = [page for page in scene.pages() if page.status == "ready"]
    assert pages and all(page.dsl["sources"] == [] for page in pages), "对不上的出处一条都不留"
    assert any(page.dsl["sourceMissing"] for page in pages)
    assert scene.sources() == []
    assert "source_mismatch" in caplog.text


def test_a_course_without_materials_keeps_its_pages_clean(app, client, sync_parse):
    """P4-G3：没关联材料时模型就算硬编出处，也一个都不留 ——
    否则页面上会出现一个点不开的徽标，那比没有出处更难发现。"""
    scene = _scene(app, client, llm=QuotingLLM(always_quote=True, honest=False), attach=False)

    run_job(scene.job.id, llm=scene.llm)

    assert scene.sources() == []
    pages = [page for page in scene.pages() if page.status == "ready"]
    assert pages and all(page.dsl["sources"] == [] for page in pages)
    assert all(page.dsl["sourceMissing"] is False for page in pages), "没材料不算「引文对不上」"
    assert all("【参考资料】" not in prompt for prompt in scene.llm.prompts)


def test_the_switch_off_falls_back_to_a_plain_lesson(app, client, sync_parse):
    """`MATERIAL_ENABLED=false`（P4-G3）：关联还在，但生成回到「只凭主题」那条路。

    开关是在部署时关的 —— 课与材料都已经在库里，所以这里先建好再关，
    验的是「关掉之后那门课照样生成得出来」，而不是「关掉之后传不上东西」。
    """
    scene = _scene(app, client)
    app.config["MATERIAL_ENABLED"] = False

    run_job(scene.job.id, llm=scene.llm)

    assert scene.sources() == []
    assert all("【参考资料】" not in prompt for prompt in scene.llm.prompts)
    assert scene.job.status == "done"


# --- 重写（P1-A7 × F4-8）---


def test_rewriting_a_page_replaces_its_citations(app, client, sync_parse):
    """重写一页也要走同一条注入与核对：旧引文先清掉 ——
    留着的话页面上会出现「这一版已经不存在的出处」。"""
    scene = _scene(app, client)
    run_job(scene.job.id, llm=scene.llm)
    target = next(page for page in scene.pages() if page.dsl.get("sources"))
    before = {row.chunk_id for row in scene.sources() if row.page_id == target.id}
    assert before

    rewritten = QuotingLLM(honest=True)
    library.rewrite_page(scene.course, target, "讲得更口语一点，多举一个例子", llm=rewritten)

    rows = [row for row in scene.sources() if row.page_id == target.id]
    assert rows, "重写之后出处要重新落一份"
    assert all(_squeeze(row.quote) in _squeeze(_chunk_text(row.chunk_id)) for row in rows)
    # 版本链上多了一条重写，且它也记了这次用了几片材料
    version = CoursePageVersion.query.filter_by(page_id=target.id).order_by(
        CoursePageVersion.rev.desc()
    ).first()
    assert version.reason == "rewrite"
    assert version.meta["sources"]["injected"] > 0


def _chunk_text(chunk_id: str) -> str:
    return str(db.session.get(MaterialChunk, chunk_id).text)
