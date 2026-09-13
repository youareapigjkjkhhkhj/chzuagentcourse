"""材料库测试（F4-1~F4-6 / P4-A1 A3 C1 C3 C4 C5 F1 F4 B2 B3 G3）。

这一层测的是**一条上传要走完的那条路**：校验 → 落盘 → 解析 → 分块 → 建索引 →
可检索 → 可删除。每一步都要能说清「错了会怎样」，所以断言大多落在那些**静默的
错**上：

- 校验失败之后，库里不留行、盘上不留临时文件（否则用户会看到一条永远
  `uploading` 的记录，而且没人知道它是怎么来的）；
- 重复上传同一份文件返回「已存在」而不是再解析一遍，但**上次失败过**的可以重试；
- 删材料要连盘上的目录一起删（库里干净了、盘上留着 50MB 的原文件）；
- 越权一律 404（P4-F4）—— 换个人来查，这份材料**不存在**。

解析走的是真实管线（真 jieba、真 parser），只有后台线程在多数用例里被换掉：
`submit_parse` 一提交，断言就得跟线程赛跑。需要解析的地方显式调
`parse_material()`，只在最后一条用例里验一次「上传后确实进了线程池」。
"""

from __future__ import annotations

import io

import pytest
from werkzeug.datastructures import FileStorage

from app.extensions import db

pytestmark = pytest.mark.unit

#: 一份带标题结构的讲义。检索与目录树（F4-6）都靠它。
#: **必须是 `.md`**：`#` 是 Markdown 的标记，`.txt` 走的是纯文本的编号启发式
#: （`第一章 检索` 那种），两种后缀认的标题不是同一套规则。
LECTURE = (
    "# 第一章 检索\n\n"
    "检索的第一步是把问题变成词。倒排索引把词映射到文档，BM25 给这些文档打分。\n\n"
    "## 1.1 倒排索引\n\n"
    "倒排索引是搜索引擎的基石。每一个词都指向含有它的那些文档。\n\n"
    "# 第二章 排序\n\n"
    "排序决定哪一份文档排在最前面。词频与文档长度都会影响这个顺序。\n"
)

LECTURE_NAME = "讲义.md"


def _file(content: bytes | str, name: str = LECTURE_NAME) -> FileStorage:
    data = content.encode("utf-8") if isinstance(content, str) else content
    return FileStorage(stream=io.BytesIO(data), filename=name)


@pytest.fixture()
def no_background(monkeypatch):
    """把「丢给线程池」换成一句空话：解析改成显式调用，断言才不看运气。

    真实的那条路（submit_parse → 线程池 → parse_material）由
    `test_an_upload_parses_in_the_background` 单独走一遍。
    """
    from app.services.materials import store

    monkeypatch.setattr(store, "submit_parse", lambda material_id: True)


def _owner(name: str = "沈老师"):
    from app.models import User

    user = User(name=name, role="teacher")
    db.session.add(user)
    db.session.commit()
    return user.id


def _course(*, owner_id: str = "", title: str = "材料测试课"):
    from app.models import Course

    course = Course(title=title, topic=title, status="ready", owner_id=owner_id or None)
    db.session.add(course)
    db.session.commit()
    return course


def _upload(content, *, name: str = LECTURE_NAME, owner_id: str = ""):
    """上传 → (材料, 是否已存在)。调用方负责在需要时显式解析。"""
    from app.services.materials import store

    return store.create_from_upload(_file(content, name), owner_id=owner_id)


def _parse(material_id: str) -> bool:
    from app.services.materials import store

    return store.parse_material(material_id)


def _ready(content=LECTURE, *, name: str = LECTURE_NAME, owner_id: str = "") -> str:
    """上传并解析完，返回材料 id（大多数用例要的是「一份能用的材料」）。"""
    from app.services.materials import store

    material, _ = _upload(content, name=name, owner_id=owner_id)
    assert store.parse_material(material.id)
    return material.id


def _tmp_files():
    from app.services.materials import policy

    root = policy.materials_root()
    return sorted(item.name for item in root.glob(f"{policy.TMP_PREFIX}*"))


# --- 上传与落盘（P4-C3 / F4-1）---


def test_an_upload_lands_under_the_material_id(app, no_background):
    """盘上的路径完全由我们生成：用户给的名字一个字节都不进路径。"""
    from app.services.materials import policy, store

    owner = _owner()
    material, existed = _upload(LECTURE, name="../../第三章 检索.md", owner_id=owner)

    assert existed is False
    assert material.status == "parsing"

    row = store.get_material(material.id, owner_id=owner)
    path = policy.file_of(row)
    assert path is not None and path.is_file()
    assert path.parent.name == material.id
    assert path.name == "source.md"
    assert ".." not in row.file_path
    assert row.file_path == policy.rel_path(material.id, ".md")
    # 用户给的名字只进库：只清掉路径分隔符，中文与空格原样留着
    assert row.name == "第三章 检索.md"
    assert _tmp_files() == []


def test_an_upload_parses_in_the_background(app):
    """真走一遍线程池：上传返回后解析在后台跑完，材料变成 ready（P4-B1）。"""
    from app.common.tasks import get_runner
    from app.services.materials import store

    owner = _owner()
    material, _ = _upload(LECTURE, owner_id=owner)
    assert get_runner().wait(f"material:{material.id}", timeout=30)

    # 后台线程用的是它自己的 session：我们这边还留着「刚上传完」那一版的快照，
    # 不刷新就会读到 `parsing`（真实请求里每次都是新 session，不存在的这个问题）
    db.session.expire_all()
    row = store.get_material(material.id, owner_id=owner)
    assert row.status == "ready"
    assert row.chunk_count > 0
    # char_count 数的是**解析出来的正文**：`#` 与空行这些标记不算在内（F4-13
    # 用它判「材料过大」），所以它一定小于原文件的字节数
    assert 0 < row.char_count < len(LECTURE)
    assert row.error == ""


def test_parsing_writes_chunks_and_an_index(app, no_background):
    """解析的产物：块（含章节路径与页码字段）+ 倒排 + 语料统计（F4-3/F4-4）。"""
    from sqlalchemy import select

    from app.models import ChunkKeyword, MaterialChunk, MaterialStats
    from app.services.materials import store

    owner = _owner()
    material_id = _ready(owner_id=owner)
    detail = store.detail(material_id, owner_id=owner)

    assert detail["status"] == "ready"
    assert detail["tree"]  # 有权重的标题才进目录树
    listed = store.list_chunks(material_id, owner_id=owner, size=200)
    assert listed["total"] == detail["chunkCount"]
    assert [item["chunkNo"] for item in listed["items"]] == list(
        range(1, listed["total"] + 1)
    )
    assert any("倒排索引" in item["text"] for item in listed["items"])
    assert db.session.query(ChunkKeyword).count() > 0
    assert db.session.query(MaterialChunk).count() == listed["total"]
    stats = db.session.scalars(select(MaterialStats)).one()
    assert stats.doc_count == listed["total"]
    assert stats.keyword_df_json  # `df` 落库了：检索时不用重扫全表（P4-D3）


def test_the_directory_tree_follows_the_headings(app, no_background):
    """目录树按 `section_path` 拆（F4-6 的抽屉用它）：两级标题要套起来。"""
    from app.services.materials import store

    material_id = _ready()
    tree = store.tree_of(material_id)

    assert [node["title"] for node in tree] == ["第一章 检索", "第二章 排序"]
    assert [child["title"] for child in tree[0]["children"]] == ["1.1 倒排索引"]
    assert tree[0]["chunkCount"] >= 2  # 父节点把自己与子节点的块都算上
    assert store.list_chunks(material_id, section="第一章 检索")["total"] >= 2


def test_a_material_can_be_searched_after_parsing(app, no_background):
    """端到端：上传 → 解析 → 检索命中（P4-A1/A3）。"""
    from app.services.materials import store

    owner = _owner()
    material_id = _ready(owner_id=owner)
    hits = store.search_materials("倒排索引", owner_id=owner)

    assert hits
    assert hits[0].material_id == material_id
    assert "倒排索引" in hits[0].text
    assert set(hits[0].matched) >= {"倒排", "索引"}


def test_a_parsed_material_carries_page_and_section_info(app, no_background):
    """溯源要用到的两样东西：章节路径与页码范围（F4-8 / P4-A6）。"""
    from app.services.materials import store

    material_id = _ready()
    item = store.list_chunks(material_id)["items"][0]

    assert item["sectionPath"] == "第一章 检索"
    assert item["pageFrom"] is None  # 纯文本不编页码


# --- 校验（P4-B2 / P4-B3 / P4-F1）---


def test_the_same_file_is_only_parsed_once(app, no_background):
    """P4-C4：内容相同就是同一份材料，再传一次只回「已存在」。"""
    from app.services.materials import store

    owner = _owner()
    first, existed = _upload(LECTURE, owner_id=owner)
    assert existed is False
    _parse(first.id)

    second, existed = _upload(LECTURE, name="换个名字.md", owner_id=owner)

    assert existed is True
    assert second.id == first.id
    assert len(store.list_materials(owner_id=owner)) == 1
    assert second.status == "ready"  # 没有被打回 parsing 再拆一遍


def test_a_failed_upload_can_be_retried_with_the_same_file(app, no_background):
    """上一次解析失败的那一条**复用**：用户再传一次就是想重试，不该被自己挡住。"""
    from app.models import Material
    from app.services.materials import store

    owner = _owner()
    first, _ = _upload("   \n\t  ", name="空白.txt", owner_id=owner)
    assert _parse(first.id) is False
    assert store.get_material(first.id, owner_id=owner).status == "failed"

    again, existed = _upload("   \n\t  ", name="空白.txt", owner_id=owner)

    assert existed is False
    assert again.id == first.id  # 同一行，不是新建一条
    assert db.session.query(Material).count() == 1


def test_two_people_can_upload_the_same_file(app, no_background):
    """去重看的是「谁的同一份内容」：两个人各存一份，互不影响。"""
    from app.services.materials import store

    teacher = _owner("沈老师")
    other = _owner("李老师")
    mine, _ = _upload(LECTURE, owner_id=teacher)
    theirs, existed = _upload(LECTURE, owner_id=other)

    assert existed is False
    assert theirs.id != mine.id
    assert len(store.list_materials(owner_id=teacher)) == 1
    assert len(store.list_materials(owner_id=other)) == 1


def test_a_file_that_is_too_large_is_rejected_before_it_is_stored(app_factory):
    """P4-B3 的 413：边收边数，超限立刻停 —— 不留行、不留临时文件。"""
    from app.common.errors import PayloadTooLargeError
    from app.models import Material

    app = app_factory(env={"MATERIAL_MAX_BYTES": 2048})
    with app.app_context():
        with pytest.raises(PayloadTooLargeError) as info:
            _upload("讲义" * 1000)
        assert info.value.http_status == 413
        assert db.session.query(Material).count() == 0
        assert _tmp_files() == []


def test_an_unknown_extension_is_rejected(app, no_background):
    """P4-B3 的 415：白名单之外一律不收，且提示要能指向下一步。"""
    from app.common.errors import UnsupportedMediaError
    from app.models import Material

    with pytest.raises(UnsupportedMediaError) as info:
        _upload("随便什么内容", name="讲义.doc")
    assert info.value.http_status == 415
    assert "docx" in info.value.message  # 「请另存为 .docx」
    assert db.session.query(Material).count() == 0
    assert _tmp_files() == []


def test_content_that_does_not_match_the_extension_is_rejected(app, no_background):
    """P4-F1 的魔数校验：改后缀是最低成本的伪装，按文件头拒掉。"""
    from app.common.errors import UnsupportedMediaError

    # 一份 PDF 改成 .docx：提示要说清「它其实是什么」，用户才知道下一步做什么
    with pytest.raises(UnsupportedMediaError) as info:
        _upload(b"%PDF-1.7\nnot a real pdf", name="讲义.docx")
    assert "PDF" in info.value.message

    with pytest.raises(UnsupportedMediaError):
        _upload(LECTURE, name="讲义.pdf")  # 文本改成 pdf 后缀

    # 老式 Office（OLE2）改后缀是最常见的一种，提示要指向「另存为」
    with pytest.raises(UnsupportedMediaError) as info:
        _upload(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1old doc", name="讲义.docx")
    assert "老式" in info.value.message


def test_a_binary_file_cannot_pretend_to_be_text(app, no_background):
    """`.txt` 没有头可认，但带 NUL 的二进制一律不收。"""
    from app.common.errors import UnsupportedMediaError

    with pytest.raises(UnsupportedMediaError):
        _upload(b"MZ\x90\x00\x00\x00binary", name="讲义.txt")


def test_an_empty_file_is_rejected(app, no_background):
    """空文件既没有名字也没有内容，报一句能懂的话，而不是留一条空记录。"""
    from app.common.errors import ValidationError

    with pytest.raises(ValidationError):
        _upload(b"")
    assert _tmp_files() == []


def test_an_upload_without_a_filename_is_rejected(app, no_background):
    """没有文件名就无从判断格式（F4-1 的白名单是按后缀走的）。"""
    from app.common.errors import ValidationError
    from app.services.materials import store

    with pytest.raises(ValidationError):
        store.create_from_upload(FileStorage(stream=io.BytesIO(b"x"), filename=""))


def test_the_switch_turns_uploads_off(app_factory):
    """P4-G3：`MATERIAL_ENABLED=false` 时上传立刻拒绝，且带 40303 这个码。"""
    from app.models import Material
    from app.services.materials import policy, store

    app = app_factory(env={"MATERIAL_ENABLED": "false"})
    with app.app_context():
        assert policy.enabled() is False
        with pytest.raises(policy.MaterialDisabledError) as info:
            store.create_from_upload(_file(LECTURE, "讲义.txt"))
        assert info.value.code == policy.MATERIAL_DISABLED_CODE == 40303
        # 前端按「平铺的 ok/error」处理这个错误（与 40302 同形）
        assert info.value.details == {"ok": False, "error": "material_disabled"}
        assert db.session.query(Material).count() == 0


# --- 解析失败（P4-B2）---


def test_a_file_that_vanished_from_disk_fails_with_a_readable_reason(app, no_background):
    """「行在而文件不在」是正常会发生的（有人清了 data/），要给人话而不是堆栈。"""
    from app.services.materials import policy, store

    material_id = _ready()
    path = policy.physical_path(store.get_material(material_id).file_path)
    path.unlink()
    assert _parse(material_id) is False

    row = store.get_material(material_id)
    assert row.status == "failed"
    assert "重新上传" in row.error


def test_a_failed_parse_leaves_no_half_index(app, no_background):
    """失败时清掉派生数据：留着半份索引比没有索引更糟 —— 它看起来是好的。"""
    from app.models import MaterialChunk
    from app.services.materials import store

    material_id = _ready()
    assert db.session.query(MaterialChunk).count() > 0
    # 把文件换成一段解析不出东西的内容，再解析一次
    from app.services.materials import policy

    path = policy.physical_path(store.get_material(material_id).file_path)
    path.write_bytes("   \n\n  ".encode())

    assert _parse(material_id) is False
    assert db.session.query(MaterialChunk).count() == 0
    row = store.get_material(material_id)
    assert row.status == "failed" and row.chunk_count == 0


def test_reparsing_replaces_the_old_chunks(app, no_background):
    """P4-C5：重新解析先删后写 —— 不能出现两代块混在一起（块号还会撞唯一约束）。"""
    from app.models import MaterialChunk
    from app.services.materials import store

    material_id = _ready()
    before = store.list_chunks(material_id, size=200)["total"]

    # 塞一条「上一代」的块进去，再解析一次：它必须消失
    db.session.add(
        MaterialChunk(material_id=material_id, chunk_no=99, text="上一代的残留", char_count=7)
    )
    db.session.commit()
    assert _parse(material_id) is True

    listed = store.list_chunks(material_id, size=200)
    assert [item["chunkNo"] for item in listed["items"]] == list(range(1, before + 1))
    assert db.session.query(MaterialChunk).filter_by(material_id=material_id).count() == before


# --- 删除（P4-C1 / P4-C3）---


def test_deleting_a_material_takes_its_chunks_and_files(app, no_background):
    """P4-C1/C3：库里的派生数据与盘上的目录一起走，一份都不留。"""
    from app.models import ChunkKeyword, MaterialChunk, MaterialStats
    from app.services.materials import policy, store

    material_id = _ready()
    folder = policy.physical_path(store.get_material(material_id).file_path).parent
    assert folder.is_dir()

    report = store.delete_material(material_id)

    assert report["fileId"] == material_id
    assert report["removedFiles"] >= 1
    assert not folder.exists()
    assert db.session.query(MaterialChunk).filter_by(material_id=material_id).count() == 0
    assert db.session.query(MaterialStats).filter_by(material_id=material_id).count() == 0
    assert db.session.query(ChunkKeyword).count() == 0


def test_deleting_a_material_takes_the_citations_that_pointed_at_it(app, no_background):
    """引用它的那几行（page_sources）跟着走 —— 否则课的页面上会留下悬空的徽标。"""
    from app.models import CoursePage, PageSource
    from app.services.materials import store

    material_id = _ready()
    course = _course()
    page = CoursePage(course_id=course.id, chapter_no=1, page_no=1, status="ready")
    db.session.add(page)
    db.session.commit()
    chunk = store.list_chunks(material_id)["items"][0]
    db.session.add(
        PageSource(
            page_id=page.id,
            material_id=material_id,
            chunk_id=chunk["chunkId"],
            quote="倒排索引",
        )
    )
    db.session.commit()

    store.delete_material(material_id)
    assert db.session.query(PageSource).count() == 0


def test_a_misspelled_file_id_is_a_plain_404(app, no_background):
    """不存在的 id 与别人的 id 走同一个出口（P4-F4）。"""
    from app.common.errors import NotFoundError
    from app.services.materials import store

    with pytest.raises(NotFoundError):
        store.get_material("nope")
    with pytest.raises(NotFoundError):
        store.detail("nope")
    with pytest.raises(NotFoundError):
        store.list_chunks("nope")
    with pytest.raises(NotFoundError):
        store.delete_material("nope")


# --- 越权（P4-F4）---


def test_another_persons_material_is_not_found(app, no_background):
    """越权返回**404**（不是 403）：403 等于承认「这个 id 存在，只是不给你看」。"""
    from app.common.errors import NotFoundError
    from app.services.materials import store

    mine = _owner("沈老师")
    other = _owner("李老师")
    material_id = _ready(owner_id=mine)

    assert store.get_material(material_id, owner_id=mine).id == material_id
    with pytest.raises(NotFoundError):
        store.get_material(material_id, owner_id=other)
    with pytest.raises(NotFoundError):
        store.detail(material_id, owner_id=other)
    with pytest.raises(NotFoundError):
        store.list_chunks(material_id, owner_id=other)
    with pytest.raises(NotFoundError):
        store.delete_material(material_id, owner_id=other)


def test_search_never_reaches_another_persons_materials(app, no_background):
    """检索的入口也要收敛：`file_ids` 里塞别人的 id 搜不出来（P4-F4）。"""
    from app.services.materials import store

    mine = _owner("沈老师")
    other = _owner("李老师")
    theirs = _ready(owner_id=other)

    assert store.search_materials("倒排索引", owner_id=mine) == []
    assert store.search_materials("倒排索引", owner_id=mine, file_ids=[theirs]) == []
    assert store.search_materials("倒排索引", owner_id=other, file_ids=[theirs])


def test_a_material_that_is_not_ready_is_not_searchable(app, no_background):
    """解析还没完的材料不进检索（检索结果里的每一块都得能被引用）。"""
    from app.services.materials import store

    owner = _owner()
    _upload(LECTURE, owner_id=owner)  # 只上传，不解析
    assert store.search_materials("倒排索引", owner_id=owner) == []


# --- 中断的上传（P4-B2）---


def _stale_upload(*, owner_id: str, age_seconds: int, with_file: bool = False) -> str:
    """直接插一条「很久以前卡在 uploading」的记录。

    绕开 ORM 的 `onupdate`：它会在 UPDATE 时把 `updated_at` 刷成现在，
    而这条用例要的正是「很久以前」。
    """
    from datetime import datetime, timedelta, timezone

    from app.models import Material, new_id
    from app.services.materials import policy

    # 与 `utcnow_iso()` 同一种字符串（`_sweep_stale` 是拿字符串比的）
    stamp = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
    material_id = new_id()
    row = {
        "id": material_id,
        "owner_id": owner_id or None,
        "name": "半截.txt",
        "ext": ".txt",
        "size_bytes": 0,
        "sha256": new_id(),
        "status": "uploading",
        "file_path": policy.rel_path(material_id, ".txt"),
        "error": "",
        "created_at": stamp,
        "updated_at": stamp,
    }
    if with_file:
        target = policy.physical_path(row["file_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes("半截".encode())
    db.session.execute(Material.__table__.insert(), [row])
    db.session.commit()
    return material_id


def test_a_stale_upload_is_marked_failed_on_the_next_upload(app, no_background):
    """连响应都没发出去就断掉的那条（进程被杀、网线被拔）要有归宿。"""
    from app.services.materials import store

    owner = _owner()
    stale = _stale_upload(owner_id=owner, age_seconds=store.STALE_UPLOAD_SECONDS + 60)
    _upload(LECTURE, owner_id=owner)

    row = store.get_material(stale, owner_id=owner)
    assert row.status == "failed"
    assert "上传中断" in row.error


def test_a_slow_upload_in_progress_is_not_swept(app, no_background):
    """判据要**同时**满足「停了很久」与「盘上没有文件」。

    正在慢速上传的那一条在收字节期间不会更新 `updated_at`，只看时间会把它误杀。
    """
    from app.services.materials import store

    owner = _owner()
    recent = _stale_upload(owner_id=owner, age_seconds=1)
    slow = _stale_upload(
        owner_id=owner, age_seconds=store.STALE_UPLOAD_SECONDS + 60, with_file=True
    )
    _upload(LECTURE, owner_id=owner)

    assert store.get_material(recent, owner_id=owner).status == "uploading"
    assert store.get_material(slow, owner_id=owner).status == "uploading"


def test_another_persons_stale_upload_is_left_alone(app, no_background):
    """一个人的上传不该被另一个人的请求改掉（清理也要按归属收敛）。"""
    from app.services.materials import store

    other = _owner("李老师")
    stale = _stale_upload(owner_id=other, age_seconds=store.STALE_UPLOAD_SECONDS + 60)
    _upload(LECTURE, owner_id=_owner("沈老师"))

    assert store.get_material(stale, owner_id=other).status == "uploading"


# --- 关联与影响面（P4-A13 / F4-14）---


def test_impact_counts_the_pages_that_cite_a_material(app, no_background):
    """P4-A13：「3 页引用将失效」这句话是数出来的，不是猜的。"""
    from app.models import CoursePage, PageSource
    from app.services.materials import store

    material_id = _ready()
    course = _course()
    pages = [
        CoursePage(course_id=course.id, chapter_no=1, page_no=no, status="ready")
        for no in (1, 2, 3)
    ]
    db.session.add_all(pages)
    db.session.commit()
    chunks = store.list_chunks(material_id)["items"][:2]
    db.session.add_all(
        [
            PageSource(page_id=pages[0].id, material_id=material_id,
                       chunk_id=chunks[0]["chunkId"], quote="倒排索引"),
            PageSource(page_id=pages[1].id, material_id=material_id,
                       chunk_id=chunks[1]["chunkId"], quote="排序"),
            # 同一页引用两段：页数只算一次，引用条数算两次
            PageSource(page_id=pages[1].id, material_id=material_id,
                       chunk_id=chunks[0]["chunkId"], quote="词频"),
        ]
    )
    db.session.commit()

    report = store.impact(material_id)

    assert report["pages"] == 2
    assert report["citations"] == 3
    assert report["courses"] == []
    assert report["name"] == LECTURE_NAME


def test_materials_can_be_attached_to_a_course(app, no_background):
    """F4-14：同一份材料关联两次是「已关联」而不是重复写一行。"""
    from app.models import CourseSource
    from app.services.materials import store

    owner = _owner()
    material_id = _ready(owner_id=owner)
    course = _course(owner_id=owner)

    first = store.attach_to_course(course.id, [material_id], owner_id=owner)
    assert first["added"] == [material_id] and first["skipped"] == []

    again = store.attach_to_course(course.id, [material_id], owner_id=owner)
    assert again["added"] == [] and again["skipped"] == [material_id]
    assert db.session.query(CourseSource).count() == 1
    assert store.material_ids_of_course(course.id) == [material_id]


def test_a_material_that_is_still_parsing_cannot_be_attached(app, no_background):
    """还没 ready 的材料加进课程，生成时检索不到东西 —— 当场拒掉，别让它到那时才炸。"""
    from app.common.errors import ValidationError
    from app.services.materials import store

    owner = _owner()
    material, _ = _upload(LECTURE, owner_id=owner)
    course = _course(owner_id=owner)

    with pytest.raises(ValidationError):
        store.attach_to_course(course.id, [material.id], owner_id=owner)


def test_detaching_reports_how_many_citations_it_breaks(app, no_background):
    """F4-14：移除材料要说出「会影响几条引用」，前端才能问一句「确定吗」。"""
    from app.models import CoursePage, PageSource
    from app.services.materials import store

    owner = _owner()
    material_id = _ready(owner_id=owner)
    course = _course(owner_id=owner)
    store.attach_to_course(course.id, [material_id], owner_id=owner)
    page = CoursePage(course_id=course.id, chapter_no=1, page_no=1, status="ready")
    db.session.add(page)
    db.session.commit()
    chunk = store.list_chunks(material_id)["items"][0]
    db.session.add(
        PageSource(page_id=page.id, material_id=material_id, chunk_id=chunk["chunkId"])
    )
    db.session.commit()

    report = store.detach_from_course(course.id, material_id, owner_id=owner)

    assert report["affectedCitations"] == 1
    assert store.material_ids_of_course(course.id) == []
    # 材料本身留着 —— 它属于用户，不属于这门课
    assert store.get_material(material_id, owner_id=owner).status == "ready"


def test_detaching_something_that_is_not_attached_is_a_404(app, no_background):
    from app.common.errors import NotFoundError
    from app.services.materials import store

    owner = _owner()
    material_id = _ready(owner_id=owner)
    course = _course(owner_id=owner)

    with pytest.raises(NotFoundError):
        store.detach_from_course(course.id, material_id, owner_id=owner)


def test_deleting_a_course_leaves_the_materials_alone(app, no_background):
    """删课只是解开关联：材料还在材料库里（F4-14）。"""
    from app.models import CourseSource
    from app.services.materials import store

    owner = _owner()
    material_id = _ready(owner_id=owner)
    course = _course(owner_id=owner)
    store.attach_to_course(course.id, [material_id], owner_id=owner)

    assert store.purge_course(course.id) == 1
    assert db.session.query(CourseSource).count() == 0
    assert store.get_material(material_id, owner_id=owner).status == "ready"


def test_an_oversized_material_is_flagged_in_the_detail(app_factory, no_background):
    """F4-13：超长的材料在详情里挂一句「建议拆分」，前端不用自己记阈值。"""
    from app.services.materials import store

    app = app_factory(env={"MATERIAL_MAX_CHARS": 100})
    with app.app_context():
        long_text = "这是一句会被重复很多次的讲义正文。" * 40
        material_id = _ready(long_text)

    with app.app_context():
        detail = store.detail(material_id)
        assert detail["charCount"] >= 100
        assert detail["oversized"] is True


def test_stats_counts_what_is_in_the_library(app, no_background):
    """`stats()` 是验收脚本与调试页要看的一眼数字。"""
    from app.services.materials import store

    _ready()
    numbers = store.stats()

    assert numbers["materials"] == 1
    assert numbers["chunks"] > 0
    assert numbers["keywords"] > 0
