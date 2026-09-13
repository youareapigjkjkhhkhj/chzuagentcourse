"""P4-3 材料接口契约：§3.1 那九条路由的一份账本（F4-1~F4-9）。

每条路由至少出现一次，成功与失败都落到具体业务码上。四件事是这个文件真正要守住的：

1. **上传之后是一份完整的材料**（P4-A1）：`status=ready`、`charCount>0`、
   分块带章节路径 —— 解析本身走的是真实管线（PyMuPDF/jieba 都是真的），
   只有「后台线程」这一层被换成同步执行（见 `sync_parse` 夹具）。
2. **不可见的资源是 404**（P4-F4 / AGENTS §4.1）：别人的材料、不对的 chunk id、
   别人的课程，答复都是同一句话。403 等于承认「这个 id 存在，只是不给你看」。
3. **删除要二次确认**（P4-A13 / F4-9）：有页面引用它时先回 40901 与影响面，
   带 `force=1` 再来才真删。
4. **检索只搜得到自己的材料**（P4-A3/F4-5）：材料检索是工作台的能力，
   不能变成「搜全库」。

解析失败、进度轮询那些更细的分支在 `tests/unit/test_material_store.py` 里，
这里只走用户真的会走的那条路。
"""

from __future__ import annotations

import io

import pytest
from sqlalchemy import func, select

from app.common.identity import OWNER_HEADER
from app.extensions import db
from app.models import Course, CoursePage, Material, PageSource, User
from app.services.materials import policy, store
from tests.contract.test_p1_api import data_of, envelope

pytestmark = pytest.mark.contract

ME = "u1"
GUEST = "u2"
OWNER = {OWNER_HEADER: ME}
OTHER = {OWNER_HEADER: GUEST}

#: 一份看得见章节结构、也看得见页码的讲义。分块要跨章节才能验目录树。
LECTURE = """# 第一章 检索
检索的第一步是把问题变成词。把问题变成词之后，才能在索引里找得到东西。
问题变成词之后，同一个意思的两种说法会落到同一个词上。

## 1.1 倒排索引
倒排索引把词映射到文档。倒排索引是搜索引擎的基石，也是排序的前提。
构建倒排索引要先分词，再统计每个词出现在哪些文档里。

# 第二章 排序
BM25 是一种经典的排序函数，它同时考虑词频与文档长度，
是对倒排索引结果的打分。词频高的块不一定排前面，因为长度也要归一化。
"""


@pytest.fixture()
def app(app_factory):
    """一台刚部署好的机器 + 两个用户（不跑生成，所以不需要模型替身）。"""
    application = app_factory()
    with application.app_context():
        db.session.add_all(
            [User(id=ME, name="小明", role="student"), User(id=GUEST, name="小红", role="student")]
        )
        db.session.commit()
    return application


@pytest.fixture()
def sync_parse(monkeypatch):
    """解析在请求里同步跑完。

    契约测试要判的是「上传之后库里是什么样」，不是「线程池有没有把任务接住」
    （那是 unit 的事）。异步那一版在 `test_material_store.py` 里跑真线程验过。
    """

    def _parse(material_id: str) -> bool:
        return store.parse_material(material_id)

    monkeypatch.setattr(store, "submit_parse", _parse)
    return _parse


def _upload(client, text: str = LECTURE, name: str = "讲义.md", headers: dict | None = None):
    return client.post(
        "/api/materials",
        data={"file": (io.BytesIO(text.encode("utf-8")), name)},
        headers=headers or OWNER,
        content_type="multipart/form-data",
    )


def _ready(client, *, headers: dict | None = None, text: str = LECTURE, name: str = "讲义.md") -> str:
    """上传一份并等它就绪，返回 fileId。"""
    body = data_of(_upload(client, text=text, name=name, headers=headers), 0)
    assert body["status"] == "ready", body
    return body["fileId"]


# --- 上传与列表 ---


def test_upload_parses_and_lists(client, sync_parse):
    """P4-A1：上传一份 .md → 就绪、有字数、有分块，列表里看得到。"""
    response = _upload(client)
    assert response.status_code == 201
    data = data_of(response)
    assert data["status"] == "ready" and data["ext"] == ".md"
    assert data["charCount"] > 0 and data["chunkCount"] > 0
    assert data["duplicated"] is False

    listing = data_of(client.get("/api/materials", headers=OWNER))
    assert [item["fileId"] for item in listing["items"]] == [data["fileId"]]
    assert listing["hasMore"] is False


def test_uploading_the_same_file_twice_reuses_the_first(client, sync_parse):
    """P4-C4：同样的内容再传一次不重新解析 —— 块与索引一模一样，等待却是白等。"""
    first = data_of(_upload(client), 0)["fileId"]
    again = _upload(client)
    assert again.status_code == 200
    data = data_of(again)
    assert data["duplicated"] is True and data["fileId"] == first


def test_the_same_file_from_another_user_is_a_different_material(client, sync_parse):
    """P4-C4 的去重是**按人**的：两个人各自传同一份讲义，各是各的材料。"""
    mine = data_of(_upload(client), 0)["fileId"]
    theirs = data_of(_upload(client, headers=OTHER), 0)["fileId"]

    assert mine != theirs
    assert [item["fileId"] for item in data_of(client.get("/api/materials", headers=OTHER))["items"]] == [
        theirs
    ]


# --- 详情与分块 ---


def test_detail_carries_the_tree(client, sync_parse):
    """F4-6：详情里带目录树（抽屉按它显示章节），根节点是两章。"""
    file_id = _ready(client)
    data = data_of(client.get(f"/api/materials/{file_id}", headers=OWNER))

    assert [node["title"] for node in data["tree"]] == ["第一章 检索", "第二章 排序"]
    nested = data["tree"][0]["children"]
    assert [node["title"] for node in nested] == ["1.1 倒排索引"]
    assert data["impact"]["pages"] == 0 and data["oversized"] is False


def test_chunks_page_by_page_and_by_section(client, sync_parse):
    """F4-6：分块可以分页看，也可以只看某一节（连子节点一起）。"""
    file_id = _ready(client)

    page = data_of(client.get(f"/api/materials/{file_id}/chunks?size=2", headers=OWNER))
    assert page["total"] > 2 and len(page["items"]) == 2
    assert [item["chunkNo"] for item in page["items"]] == [1, 2]

    section = data_of(
        client.get(
            f"/api/materials/{file_id}/chunks?section=第一章 检索", headers=OWNER
        )
    )
    assert section["items"]
    assert all(item["sectionPath"].startswith("第一章 检索") for item in section["items"])


def test_a_single_chunk_comes_back_with_its_text(client, sync_parse):
    """P4-A6：溯源跳转要的那一段原文，按 chunkId 取得到。"""
    file_id = _ready(client)
    first = data_of(client.get(f"/api/materials/{file_id}/chunks?size=1", headers=OWNER))["items"][0]

    chunk = data_of(
        client.get(f"/api/materials/{file_id}/chunks/{first['chunkId']}", headers=OWNER)
    )
    assert chunk["text"] == first["text"]
    assert chunk["sectionPath"] == first["sectionPath"]


# --- 检索 ---


def test_search_finds_the_source_and_says_what_matched(client, sync_parse):
    """P4-A3/A4：用讲义里的术语检索 → top-1 就是真正提到它的那一段，并带回命中词。"""
    _ready(client)
    data = data_of(client.get("/api/materials/search?q=倒排索引", headers=OWNER))

    assert data["query"] == "倒排索引" and data["items"]
    top = data["items"][0]
    assert "倒排索引" in top["text"]
    assert set(top["matched"]) >= {"倒排", "索引"}
    assert 0 < top["score"] <= 1
    # 溯源徽标要的两样东西（文件名 + 材料里的第几页）跟着结果一起回来
    assert top["fileName"] == "讲义.md" and "chunkId" in top


def test_an_unrelated_query_returns_nothing(client, sync_parse):
    """P4-A3：无关词不硬凑（否则前端永远显示「相关度 100%」）。"""
    _ready(client)
    data = data_of(client.get("/api/materials/search?q=量子纠缠光合作用", headers=OWNER))

    assert data["items"] == []


def test_search_can_be_narrowed_to_one_file(client, sync_parse):
    """F4-5：`fileIds` 指哪搜哪；指一份不属于自己的，就当作没有。"""
    mine = _ready(client)
    _ready(client, headers=OTHER, text="# 别人的\n内容是别的。", name="别人的.md")

    only_mine = data_of(
        client.get(f"/api/materials/search?q=倒排索引&fileIds={mine}", headers=OWNER)
    )
    assert only_mine["items"] and all(item["fileId"] == mine for item in only_mine["items"])

    stranger = data_of(
        client.get(f"/api/materials/search?q=倒排索引&fileIds={mine}", headers=OTHER)
    )
    assert stranger["items"] == []


def test_a_blank_query_is_an_empty_result_not_an_error(client, sync_parse):
    """工作台的搜索框是边打边搜的：清空输入不该弹错误提示。"""
    _ready(client)
    data = data_of(client.get("/api/materials/search?q=", headers=OWNER))
    assert data["items"] == []


# --- 与课程的关联 ---


def _course(owner: str = ME, pages: int = 0) -> tuple[str, list[str]]:
    """建一门课，返回 (courseId, [pageId…])。"""
    course = Course(owner_id=owner, title="检索入门", status="ready", page_count=pages or 1)
    db.session.add(course)
    db.session.flush()
    page_ids = []
    for index in range(pages or 1):
        page = CoursePage(course_id=course.id, page_no=index + 1, kind="concept", status="ready")
        db.session.add(page)
        db.session.flush()
        page_ids.append(page.id)
    db.session.commit()
    return course.id, page_ids


def test_attach_then_detach(client, sync_parse):
    """F4-7/F4-14：材料关联到课程，重复关联不报错，移除时报告影响面。"""
    file_id = _ready(client)
    course_id, _pages = _course()

    first = data_of(
        client.post(f"/api/courses/{course_id}/materials", json={"fileIds": [file_id]}, headers=OWNER)
    )
    assert first["added"] == [file_id] and first["skipped"] == []

    again = data_of(
        client.post(f"/api/courses/{course_id}/materials", json={"fileIds": [file_id]}, headers=OWNER)
    )
    assert again["added"] == [] and again["skipped"] == [file_id]

    linked = data_of(client.get(f"/api/courses/{course_id}/materials", headers=OWNER))
    assert [item["fileId"] for item in linked["items"]] == [file_id]

    removed = data_of(client.delete(f"/api/courses/{course_id}/materials/{file_id}", headers=OWNER))
    assert removed["affectedCitations"] == 0
    assert data_of(client.get(f"/api/courses/{course_id}/materials", headers=OWNER))["items"] == []


def test_attaching_someone_elses_material_is_404(client, sync_parse):
    """P4-F4：拿别人的 fileId 往自己课里加，答的是「材料不存在」。"""
    file_id = _ready(client)  # 我的
    course_id, _pages = _course(owner=GUEST)  # 他的课

    response = client.post(
        f"/api/courses/{course_id}/materials", json={"fileIds": [file_id]}, headers=OTHER
    )
    assert response.status_code == 404
    envelope(response, 40401)


# --- 删除 ---


def test_delete_asks_before_dropping_cited_material(client, sync_parse):
    """P4-A13：有页面引用了它 → 先回 40901 与影响面，`force=1` 才真删。"""
    file_id = _ready(client)
    course_id, page_ids = _course(pages=1)
    # 先关联再引用：`impact` 里的 `courses` 数的是「关联在几门课里」，
    # 与「有几页引用了它」是两笔账（关联了但不引用、引用过但已解除关联都可能）
    data_of(
        client.post(f"/api/courses/{course_id}/materials", json={"fileIds": [file_id]}, headers=OWNER)
    )
    with client.application.app_context():
        chunk = store.list_chunks(file_id, owner_id=ME, size=1)["items"][0]
        db.session.add(
            PageSource(
                page_id=page_ids[0],
                material_id=file_id,
                chunk_id=chunk["chunkId"],
                page_no=1,
                section_path=chunk["sectionPath"],
                quote=chunk["text"][:20],
            )
        )
        db.session.commit()

    asked = client.delete(f"/api/materials/{file_id}", headers=OWNER)
    assert asked.status_code == 409 and asked.get_json()["code"] == 40901
    impact = asked.get_json()["data"]["details"]["impact"]
    assert impact["pages"] == 1 and impact["citations"] == 1
    assert impact["courses"] == [course_id]

    gone = data_of(client.delete(f"/api/materials/{file_id}?force=1", headers=OWNER))
    assert gone["fileId"] == file_id
    assert data_of(client.get("/api/materials", headers=OWNER))["items"] == []

    # 引用它的那一行跟着外键走，页面本身留着（用户没说要改页面内容）。
    # `expire_all()` 是因为这一条断言要走一遍库：外层会话的身份映射里还留着
    # 请求写入之前的快照（真实请求每请求一个 session，不存在这个问题）。
    with client.application.app_context():
        db.session.expire_all()
        assert db.session.scalar(select(func.count()).select_from(PageSource)) == 0
        assert db.session.get(CoursePage, page_ids[0]) is not None


# --- 拒绝 ---


def test_unsupported_and_disguised_files_are_refused(client, sync_parse):
    """P4-F1/B2：白名单之外的格式 415；改了后缀的（内容与后缀不符）也是 415。"""
    old_doc = _upload(client, text="内容", name="讲义.doc")
    assert old_doc.status_code == 415
    envelope(old_doc, 40003)

    # 内容与后缀不符：一份纯文本叫「.pdf」，在门口就被拒（不是等解析器报「打不开」）
    disguised = _upload(client, text="这是一份纯文本，却起了个 .pdf 的名字。", name="假.pdf")
    assert disguised.status_code == 415
    envelope(disguised, 40003)

    # 反过来，**头对得上**的坏文件是收下的：它进得来，然后在解析阶段失败 ——
    # 「像不像 PDF」在这一层判，「读不读得开」是解析器的事，报错也各说各的话
    broken = _upload(client, text="%PDF-1.7 但不是真的 pdf", name="坏.pdf")
    assert broken.status_code == 201
    assert data_of(broken)["status"] == "failed" and "PDF" in data_of(broken)["error"]


def test_oversized_upload_is_413(client, monkeypatch, sync_parse):
    """P4-B1：超过上限回 413（这里把上限改小，免得真传一个 50MB 的文件）。"""
    monkeypatch.setitem(client.application.config, "MATERIAL_MAX_BYTES", 2048)
    response = _upload(client, text="啊" * 4096, name="大文件.txt")
    assert response.status_code == 413
    envelope(response, 40002)


def test_material_disabled_answers_40303(client, monkeypatch, sync_parse):
    """P4-G3：总开关关掉 → 40303 + 平铺的 `{ok:false, error:"material_disabled"}`。"""
    monkeypatch.setitem(client.application.config, "MATERIAL_ENABLED", False)
    response = _upload(client)
    assert response.status_code == 403
    body = envelope(response, policy.MATERIAL_DISABLED_CODE)
    assert body["data"] == {"ok": False, "error": "material_disabled"}


# --- 越权一律 404 ---


def test_another_users_material_is_404_everywhere(client, sync_parse):
    """P4-F4：别人的材料，四条读接口与删除都答 404 —— 不泄露「这个 id 存在」。"""
    mine = _ready(client)
    chunk_id = data_of(client.get(f"/api/materials/{mine}/chunks", headers=OWNER))["items"][0][
        "chunkId"
    ]

    for response in (
        client.get(f"/api/materials/{mine}", headers=OTHER),
        client.get(f"/api/materials/{mine}/chunks", headers=OTHER),
        client.get(f"/api/materials/{mine}/chunks/{chunk_id}", headers=OTHER),
        client.delete(f"/api/materials/{mine}?force=1", headers=OTHER),
    ):
        assert response.status_code == 404
        envelope(response, 40401)

    # 我的那一份还在（越权删除不能真的删掉东西）
    with client.application.app_context():
        db.session.expire_all()
        assert db.session.get(Material, mine) is not None


def test_a_chunk_of_another_material_is_404(client, sync_parse):
    """chunk id 与材料 id 必须成对：拿 A 的 id 去 B 里取块，是 404 不是「取到了」。"""
    first = _ready(client, name="甲.md")
    second = _ready(client, text="# 别的\n另一个话题。", name="乙.md")
    chunk_id = data_of(client.get(f"/api/materials/{first}/chunks", headers=OWNER))["items"][0][
        "chunkId"
    ]

    response = client.get(f"/api/materials/{second}/chunks/{chunk_id}", headers=OWNER)
    assert response.status_code == 404
    envelope(response, 40401)
