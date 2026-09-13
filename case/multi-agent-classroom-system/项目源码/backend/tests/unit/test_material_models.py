"""P4 数据模型测试（P4 §4 / P4-C1 / P4-C4）。

材料域与工作台域各有自己的「事实与派生」分界，断言也照这条线分开写：

- `materials` 一行是**事实**（用户传上来的那份东西），`material_chunks` /
  `chunk_keywords` / `material_stats` 是**派生**——删材料时它们一起走，
  不留孤儿（P4-C1）；重新解析一遍就能重建。
- 工作台里 `chat_messages.seq` 是**回退的界**（P4-A12），所以它必须唯一且单调；
  `skill_invocations` 是**可见性**的存档（P4-A10），一次调用一行。

最后几条是横向的：内容去重（P4-C4）、枚举被库里挡住、§4 承诺的列一列不少。
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db

pytestmark = pytest.mark.unit

P4_TABLES = {
    "materials",
    "material_chunks",
    "chunk_keywords",
    "material_stats",
    "course_sources",
    "page_sources",
    "chat_sessions",
    "chat_messages",
    "skill_invocations",
}

#: §4 逐字抄下来的列清单 —— 这张表就是契约本身（同 P3 的做法）。
DOCUMENTED_COLUMNS = {
    "materials": {
        "id",
        "owner_id",
        "name",
        "ext",
        "size_bytes",
        "sha256",
        "pages",
        "char_count",
        "chunk_count",
        "status",
        "file_path",
        "error",
        "created_at",
        "updated_at",
    },
    "material_chunks": {
        "id",
        "material_id",
        "chunk_no",
        "page_from",
        "page_to",
        "section_path",
        "text",
        "char_count",
        "tokens",
        "created_at",
        "updated_at",
    },
    # 倒排表没有 id 也没有 updated_at：一行就是「这个块里有这个词」，没有「自己」
    "chunk_keywords": {"chunk_id", "keyword", "tf"},
    "material_stats": {
        "id",
        "material_id",
        "doc_count",
        "avg_doc_len",
        "keyword_df_json",
        "created_at",
        "updated_at",
    },
    "course_sources": {"course_id", "material_id", "added_at", "created_at", "updated_at"},
    "page_sources": {
        "id",
        "page_id",
        "material_id",
        "chunk_id",
        "page_no",
        "section_path",
        "quote",
        "score",
        "created_at",
        "updated_at",
    },
    "chat_sessions": {
        "id",
        "course_id",
        "owner_id",
        "title",
        "status",
        "last_active_at",
        "created_at",
        "updated_at",
    },
    "chat_messages": {
        "id",
        "session_id",
        "seq",
        "role",
        "content",
        "skill_calls_json",
        "ref_page_no",
        "tokens",
        "created_at",
        "updated_at",
    },
    "skill_invocations": {
        "id",
        "session_id",
        "message_id",
        "skill",
        "args_json",
        "result_json",
        "status",
        "duration_ms",
        "error",
        "created_at",
        "updated_at",
    },
}


def _user(name: str = "张老师"):
    from app.models import User

    user = User(name=name, role="teacher")
    db.session.add(user)
    db.session.commit()
    return user


def _material(**kwargs):
    """一份解析好的材料，返回已提交的 Material。"""
    from app.models import Material

    base = {
        "name": "第三章 检索.pdf",
        "ext": ".pdf",
        "size_bytes": 10240,
        "sha256": "a" * 64,
        "status": "ready",
        "pages": 12,
        "char_count": 8000,
        "chunk_count": 1,
    }
    material = Material(**{**base, **kwargs})
    db.session.add(material)
    db.session.commit()
    return material


def _chunk(material_id: str, chunk_no: int = 1, **kwargs):
    from app.models import MaterialChunk

    chunk = MaterialChunk(
        material_id=material_id,
        chunk_no=chunk_no,
        text="正文" * 30,
        char_count=60,
        tokens=30,
        **kwargs,
    )
    db.session.add(chunk)
    db.session.commit()
    return chunk


def _course(**kwargs):
    from app.models import Course

    base = {"title": "机器学习入门", "topic": "机器学习入门", "status": "ready"}
    course = Course(**{**base, **kwargs})
    db.session.add(course)
    db.session.commit()
    return course


def _page(course_id: str, page_no: int = 1):
    from app.models import CoursePage

    page = CoursePage(
        course_id=course_id, page_no=page_no, chapter_no=1, kind="concept", status="ready"
    )
    db.session.add(page)
    db.session.commit()
    return page


def _chat(course_id: str):
    from app.models import ChatSession

    session = ChatSession(course_id=course_id, title="做一门课")
    db.session.add(session)
    db.session.commit()
    return session


def _names(tables: set[str]) -> set[str]:
    from sqlalchemy import inspect

    return set(inspect(db.engine).get_table_names()) & tables


def test_all_nine_tables_exist(app):
    """§4 的九张表一张都不能少。"""
    with app.app_context():
        assert _names(P4_TABLES) == P4_TABLES


@pytest.mark.parametrize(("table", "columns"), sorted(DOCUMENTED_COLUMNS.items()))
def test_documented_columns_are_present(app, table: str, columns: set[str]):
    """列清单是契约：少一列会让前端拿不到字段，多一列说明文档没跟上。"""
    from sqlalchemy import inspect

    with app.app_context():
        actual = {col["name"] for col in inspect(db.engine).get_columns(table)}
        assert columns <= actual, f"{table} 少了 {columns - actual}"


def test_deleting_a_material_takes_its_derived_rows_with_it(app):
    """P4-C1：删材料级联带走分块/倒排/统计/关联/溯源，不留孤儿。

    走的是迁移里的 `ON DELETE CASCADE` + `PRAGMA foreign_keys=ON`，
    不靠 ORM 逐个删 —— 所以这条同时验证了「级联写进迁移了」与「外键真开着」。
    """
    from app.models import (
        ChunkKeyword,
        CourseSource,
        Material,
        MaterialChunk,
        MaterialStats,
        PageSource,
    )

    with app.app_context():
        material = _material()
        chunk = _chunk(material.id)
        course = _course()
        page = _page(course.id)

        db.session.add(ChunkKeyword(chunk_id=chunk.id, keyword="检索", tf=3))
        db.session.add(
            MaterialStats(material_id=material.id, doc_count=1, avg_doc_len=30.0)
        )
        db.session.add(CourseSource(course_id=course.id, material_id=material.id))
        db.session.add(
            PageSource(
                page_id=page.id,
                material_id=material.id,
                chunk_id=chunk.id,
                page_no=12,
                quote="检索的第一步是把问题变成词",
            )
        )
        db.session.commit()

        db.session.delete(material)
        db.session.commit()

        assert Material.query.count() == 0
        for model in (MaterialChunk, ChunkKeyword, MaterialStats, CourseSource, PageSource):
            assert model.query.count() == 0, f"{model.__name__} 留下了孤儿行"


def test_deleting_a_course_takes_its_sources_and_chat_with_it(app):
    """删课带走溯源引用与工作台会话（材料本身留着 —— 它不属于这门课）。"""
    from app.models import (
        ChatMessage,
        ChatSession,
        CourseSource,
        Material,
        PageSource,
        SkillInvocation,
    )

    with app.app_context():
        material = _material()
        chunk = _chunk(material.id)
        course = _course()
        page = _page(course.id)
        chat = _chat(course.id)

        db.session.add(CourseSource(course_id=course.id, material_id=material.id))
        db.session.add(
            PageSource(
                page_id=page.id, material_id=material.id, chunk_id=chunk.id, quote="引文"
            )
        )
        message = ChatMessage(session_id=chat.id, seq=1, role="user", content="把第三章压成两页")
        db.session.add(message)
        db.session.commit()
        db.session.add(
            SkillInvocation(
                session_id=chat.id, message_id=message.id, skill="revise_outline", status="ok"
            )
        )
        db.session.commit()

        db.session.delete(course)
        db.session.commit()

        for model in (PageSource, CourseSource, ChatSession, ChatMessage, SkillInvocation):
            assert model.query.count() == 0, f"{model.__name__} 留下了孤儿行"
        assert Material.query.count() == 1, "材料是用户的，不该跟着课程走"


def test_the_same_content_cannot_be_uploaded_twice_by_one_person(app):
    """P4-C4：同一个人重复传同一份内容要被库里挡住（接口据此回「已存在」）。

    去重看的是 sha256 而不是文件名 —— 同一个文件改个名还是同一个文件，
    所以第二条故意换了个名字，照样要被挡。
    """
    from app.models import Material

    with app.app_context():
        teacher = _user()
        _material(owner_id=teacher.id, name="讲义.pdf", sha256="b" * 64)

        db.session.add(
            Material(
                owner_id=teacher.id,
                name="讲义(1).pdf",
                ext=".pdf",
                size_bytes=10240,
                sha256="b" * 64,
            )
        )
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_two_people_can_upload_the_same_file(app):
    """唯一约束带 `owner_id`：两个人各自存一份同样的讲义互不影响。

    不带 `owner_id` 的话，第二位老师会收到「这份材料已存在」——
    而他明明从来没传过。
    """
    from app.models import Material

    with app.app_context():
        first = _user("张老师")
        second = _user("李老师")
        _material(owner_id=first.id, name="讲义.pdf", sha256="b" * 64)
        _material(owner_id=second.id, name="讲义.pdf", sha256="b" * 64)
        assert Material.query.count() == 2


def test_materials_without_an_owner_do_not_block_each_other(app):
    """owner 为 NULL（账号已注销留下的材料）时 SQLite 视作互不相同。

    这是迁移 `e81d7febf2ff` 里写下的取舍：注销之后这些行没有主人可比，
    与其让它们互相挡路，不如都放行。
    """
    from app.models import Material

    with app.app_context():
        _material(name="孤儿讲义.pdf", sha256="b" * 64)
        _material(name="孤儿讲义.pdf", sha256="b" * 64)
        assert Material.query.count() == 2


def test_a_different_file_with_the_same_name_is_still_a_new_material(app):
    """反过来：名字一样、内容不同就是两份材料（去重不看名字）。"""
    from app.models import Material

    with app.app_context():
        _material(name="讲义.pdf", sha256="c" * 64)
        _material(name="讲义.pdf", sha256="d" * 64)
        assert Material.query.count() == 2


def test_two_materials_can_hold_the_same_chunk_number(app):
    """`chunk_no` 是「这份材料里的第几块」，所以唯一约束必须带 `material_id`。

    只按 `chunk_no` 唯一的话，第二份材料的第 1 块就写不进去了 ——
    这个错误在只有一份材料的测试里永远看不见。
    """
    from app.models import MaterialChunk

    with app.app_context():
        first = _material(sha256="e" * 64)
        second = _material(name="另一份.pdf", sha256="f" * 64)
        _chunk(first.id, chunk_no=1)
        _chunk(second.id, chunk_no=1)
        assert MaterialChunk.query.count() == 2


def test_chat_seq_is_unique_inside_one_session(app):
    """`seq` 是回退的界（P4-A12）：同一个会话里写两条同号的，回退就会回到两处。"""
    from app.models import ChatMessage

    with app.app_context():
        chat = _chat(_course().id)
        db.session.add(ChatMessage(session_id=chat.id, seq=1, role="user", content="第一句"))
        db.session.commit()

        db.session.add(ChatMessage(session_id=chat.id, seq=1, role="assistant", content="回复"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


@pytest.mark.parametrize(
    ("model_name", "field", "bad_value"),
    [
        ("Material", "status", "done"),  # 是 ready，不是 done
        ("ChatSession", "status", "closed"),
        ("ChatMessage", "role", "tool"),
        ("SkillInvocation", "status", "pending"),
    ],
)
def test_enum_columns_are_enforced(app, model_name: str, field: str, bad_value: str):
    """枚举值写错必须在库里被挡住 —— 这些值的另一端是前端的图标与文案分支。"""
    from app import models

    with app.app_context():
        chat = _chat(_course().id)
        factories = {
            "Material": lambda: models.Material(name="x.pdf", ext=".pdf"),
            "ChatSession": lambda: models.ChatSession(course_id=chat.course_id),
            "ChatMessage": lambda: models.ChatMessage(
                session_id=chat.id, seq=9, role="user", content="嗨"
            ),
            "SkillInvocation": lambda: models.SkillInvocation(
                session_id=chat.id, skill="add_quiz", args={"pageNo": 3}
            ),
        }
        row = factories[model_name]()
        setattr(row, field, bad_value)
        db.session.add(row)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


@pytest.mark.parametrize(
    ("model_name", "kwargs"),
    [
        ("MaterialChunk", {"chunk_no": 0}),
        ("ChunkKeyword", {"tf": 0}),
    ],
)
def test_impossible_numbers_are_rejected(app, model_name: str, kwargs: dict):
    """块号从 1 开始、词频至少 1：这两个数会被用来排序与做除法。"""
    from app import models

    with app.app_context():
        material = _material(sha256="3" * 64)
        chunk = _chunk(material.id)
        base = {
            "MaterialChunk": {"material_id": material.id},
            "ChunkKeyword": {"chunk_id": chunk.id, "keyword": "检索"},
        }[model_name]

        db.session.add(models.__dict__[model_name](**{**base, **kwargs}))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
