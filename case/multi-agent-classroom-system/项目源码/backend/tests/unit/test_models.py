"""数据模型测试（P0 §5 / P0-C1 ~ P0-C4）。

约定：
- 7 张基础表，时间统一存 UTC ISO8601 字符串
- courses.owner_id → users.id；course_pages.course_id → courses.id（ON DELETE CASCADE）
- course_pages(course_id, page_no) 唯一
"""

from __future__ import annotations

import re
import time
from datetime import datetime

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.extensions import db

pytestmark = pytest.mark.unit

ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$")

EXPECTED_TABLES = {
    "users",
    "settings_kv",
    "providers",
    "voice_profiles",
    "agent_roles",
    "courses",
    "course_pages",
}


def test_all_seven_base_tables_exist(app):
    with app.app_context():
        names = set(inspect(db.engine).get_table_names())

    missing = EXPECTED_TABLES - names
    assert not missing, f"缺少表：{missing}"


def test_every_table_has_created_at_and_updated_at(app):
    """时间戳是审计与增量同步的基础，每张表都要有。"""
    with app.app_context():
        inspector = inspect(db.engine)

        for table in EXPECTED_TABLES:
            columns = {c["name"] for c in inspector.get_columns(table)}
            assert "created_at" in columns, f"{table} 缺少 created_at"
            assert "updated_at" in columns, f"{table} 缺少 updated_at"


def test_primary_keys_are_strings(app):
    """主键统一用字符串：种子数据用可读 slug，运行时用 uuid，避免自增 id 在导入导出时漂移。"""
    with app.app_context():
        inspector = inspect(db.engine)

        for table in EXPECTED_TABLES:
            pk = inspector.get_pk_constraint(table)
            for column in pk["constrained_columns"]:
                col_type = next(
                    c["type"] for c in inspector.get_columns(table) if c["name"] == column
                )
                assert "VARCHAR" in str(col_type).upper() or "CHAR" in str(col_type).upper(), (
                    f"{table}.{column} 不是字符串类型：{col_type}"
                )


# --- users / courses / course_pages 关系 ---


def test_course_owner_foreign_key(app):
    from app.models import Course, User

    with app.app_context():
        user = User(name="张老师", role="teacher")
        db.session.add(user)
        db.session.commit()

        course = Course(title="光合作用", topic="生物", owner_id=user.id)
        db.session.add(course)
        db.session.commit()

        assert course.owner_id == user.id
        assert db.session.get(User, course.owner_id).name == "张老师"


def test_course_owner_is_set_null_when_user_removed(app):
    """删用户不能连带删课程 —— 课程是教学内容，比账号重要。"""
    from app.models import Course, User

    with app.app_context():
        user = User(name="张老师", role="teacher")
        db.session.add(user)
        db.session.flush()

        course = Course(title="光合作用", topic="生物", owner_id=user.id)
        db.session.add(course)
        db.session.commit()
        course_id = course.id

        db.session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
        db.session.commit()
        db.session.expire_all()

        assert db.session.get(Course, course_id).owner_id is None


def test_course_page_unique_per_course(app):
    """同一门课里 page_no 不能重复（否则翻页顺序不确定）。"""
    from app.models import Course, CoursePage, User

    with app.app_context():
        user = User(name="张老师", role="teacher")
        db.session.add(user)
        db.session.flush()

        course = Course(title="光合作用", topic="生物", owner_id=user.id)
        db.session.add(course)
        db.session.flush()

        db.session.add(CoursePage(course_id=course.id, page_no=1, title="封面"))
        db.session.commit()

        db.session.add(CoursePage(course_id=course.id, page_no=1, title="重复页"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_deleting_course_cascades_to_pages_at_db_level(app):
    """必须由数据库外键保证级联 —— 绕过 ORM 直接删也要生效。"""
    from app.models import Course, CoursePage, User

    with app.app_context():
        user = User(name="张老师", role="teacher")
        db.session.add(user)
        db.session.flush()

        course = Course(title="光合作用", topic="生物", owner_id=user.id)
        db.session.add(course)
        db.session.flush()

        db.session.add_all(
            [
                CoursePage(course_id=course.id, page_no=no, title=f"第{no}页")
                for no in (1, 2, 3)
            ]
        )
        db.session.commit()
        course_id = course.id

        # 绕过 ORM，直接走 SQL —— 验证的是 FK 声明，不是 Python 层 cascade
        db.session.execute(text("DELETE FROM courses WHERE id = :id"), {"id": course_id})
        db.session.commit()

        remaining = db.session.execute(
            text("SELECT COUNT(*) FROM course_pages WHERE course_id = :id"), {"id": course_id}
        ).scalar()
        assert remaining == 0


def test_page_no_is_positive(app):
    """页码从 1 开始，0 与负数说明上游算错了。"""
    from app.models import Course, CoursePage, User

    with app.app_context():
        user = User(name="张老师", role="teacher")
        db.session.add(user)
        db.session.flush()
        course = Course(title="光合作用", topic="生物", owner_id=user.id)
        db.session.add(course)
        db.session.flush()

        db.session.add(CoursePage(course_id=course.id, page_no=0, title="第0页"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


# --- 时间戳 ---


def test_timestamps_are_utc_iso8601(app):
    from app.models import User

    with app.app_context():
        user = User(name="张老师", role="teacher")
        db.session.add(user)
        db.session.commit()

        assert ISO_UTC.match(user.created_at), user.created_at
        assert ISO_UTC.match(user.updated_at), user.updated_at


def test_updated_at_advances_on_update(app):
    """改了就得看得见：`updated_at` 是「这行什么时候被动过」的唯一答案。

    醒来这一下是必须的。本机（Windows）`datetime.now()` 的粒度约 15.6ms ——
    连续取两万次只有 87 个不同的值，两次 commit 落在同一个时钟滴答里就会写到
    一模一样的 ISO 串，于是「必须前进」这条断言会随机器快慢时红时绿。
    睡过一个滴答，测的就还是「更新会推进 updated_at」，而不是时钟分辨率。
    """
    from app.models import User

    with app.app_context():
        user = User(name="张老师", role="teacher")
        db.session.add(user)
        db.session.commit()
        first = user.updated_at

        time.sleep(0.02)

        user.name = "李老师"
        db.session.commit()

        assert user.updated_at > first, "updated_at 必须随更新前进"


def test_created_at_is_not_rewritten_on_update(app):
    from app.models import User

    with app.app_context():
        user = User(name="张老师", role="teacher")
        db.session.add(user)
        db.session.commit()
        created = user.created_at

        user.name = "李老师"
        db.session.commit()

        assert user.created_at == created


def test_created_at_is_parseable(app):
    from app.models import User

    with app.app_context():
        user = User(name="张老师", role="teacher")
        db.session.add(user)
        db.session.commit()

        parsed = datetime.fromisoformat(user.created_at.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0


# --- 主键生成 ---


def test_ids_are_autogenerated_when_omitted(app):
    from app.models import SettingsKV, User

    with app.app_context():
        a = User(name="甲", role="student")
        b = User(name="乙", role="student")
        db.session.add_all([a, b, SettingsKV(key="k", value_json="{}")])
        db.session.commit()

        assert a.id and b.id and a.id != b.id


def test_explicit_seed_ids_are_preserved(app):
    """种子数据用可读 slug 作为 id，重复灌种子才能幂等。"""
    from app.models import AgentRole

    with app.app_context():
        role = AgentRole(id="role_teacher_shen", code="shen", name="沈老师", role="teacher")
        db.session.add(role)
        db.session.commit()

        assert AgentRole.query.filter_by(id="role_teacher_shen").one().name == "沈老师"


# --- 业务约束 ---


def test_course_defaults_to_draft(app):
    from app.models import Course

    with app.app_context():
        course = Course(title="光合作用", topic="生物")
        db.session.add(course)
        db.session.commit()

        assert course.status == "draft"
        assert course.page_count == 0
        assert course.duration_min == 0


def test_course_status_rejects_unknown_value(app):
    """状态机只认这 4 个值，写错要在落库时就报错。"""
    from app.models import Course

    with app.app_context():
        db.session.add(Course(title="光合作用", topic="生物", status="不存在的状态"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_user_role_rejects_unknown_value(app):
    from app.models import User

    with app.app_context():
        db.session.add(User(name="甲", role="god"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_provider_kind_rejects_unknown_value(app):
    from app.models import Provider

    with app.app_context():
        db.session.add(Provider(id="p1", name="X", kind="telepathy"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_settings_kv_key_is_unique(app):
    from app.models import SettingsKV

    with app.app_context():
        db.session.add(SettingsKV(key="active_provider", value_json='"deepseek"'))
        db.session.commit()

        db.session.add(SettingsKV(key="active_provider", value_json='"openai"'))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


# --- JSON 字段 ---


def test_settings_kv_roundtrips_json(app):
    """settings_kv 存的是 JSON 字符串，读写都要能自动转换。"""
    from app.models import SettingsKV

    with app.app_context():
        row = SettingsKV(key="generation", value_json=None)
        row.value = {"pageCount": 12, "classmateCount": 3, "whiteboard": True}
        db.session.add(row)
        db.session.commit()

        loaded = SettingsKV.query.filter_by(key="generation").one()
        assert loaded.value == {"pageCount": 12, "classmateCount": 3, "whiteboard": True}


def test_provider_extra_json_roundtrips(app):
    from app.models import Provider

    with app.app_context():
        provider = Provider(id="deepseek", name="DeepSeek", kind="llm")
        provider.extra = {"region": "cn", "tags": ["default"]}
        db.session.add(provider)
        db.session.commit()

        loaded = Provider.query.filter_by(id="deepseek").one()
        assert loaded.extra == {"region": "cn", "tags": ["default"]}


def test_agent_role_persona_roundtrips(app):
    from app.models import AgentRole

    with app.app_context():
        role = AgentRole(id="role_xiaoxiao", code="xiaoxiao", name="林晓", role="student")
        role.persona = {"tone": "爱提问", "traits": ["好奇", "打断"]}
        db.session.add(role)
        db.session.commit()

        loaded = AgentRole.query.filter_by(id="role_xiaoxiao").one()
        assert loaded.persona["tone"] == "爱提问"


def test_json_column_tolerates_malformed_input(app):
    """手工改库改坏了不能让整个接口 500 —— 退化成 None。"""
    from app.models import SettingsKV

    with app.app_context():
        db.session.add(SettingsKV(key="broken", value_json="{不是 JSON"))
        db.session.commit()

        loaded = SettingsKV.query.filter_by(key="broken").one()
        assert loaded.value is None


# --- 密钥不落明文 ---


def test_provider_api_key_is_encrypted_at_rest(app):
    """providers.api_key_enc 落库必须是密文，且能解回明文（AGENTS.md §4.1）。"""
    from app.common.crypto import decrypt
    from app.models import Provider

    plain = "sk-9f2c4a1b7e8d4f6a0011223344556677"

    with app.app_context():
        provider = Provider(id="deepseek", name="DeepSeek", kind="llm")
        provider.api_key = plain
        db.session.add(provider)
        db.session.commit()

        raw = db.session.execute(
            text("SELECT api_key_enc FROM providers WHERE id = 'deepseek'")
        ).scalar()

        assert raw, "api_key_enc 不该为空"
        assert plain not in raw, "落库的是明文 Key"
        assert decrypt(raw) == plain

        # 读回来时也不该出现明文
        loaded = Provider.query.filter_by(id="deepseek").one()
        assert plain not in repr(loaded.__dict__)


def test_provider_masked_key_is_exposed_for_display(app):
    """设置页回显用 maskedKey，接口层不允许拿到明文。"""
    from app.models import Provider

    with app.app_context():
        provider = Provider(id="deepseek", name="DeepSeek", kind="llm")
        provider.api_key = "sk-9f2c4a1b7e8d4f6a"
        db.session.add(provider)
        db.session.commit()

        assert provider.masked_key == "sk-****4f6a"
        assert provider.configured is True


def test_provider_without_key_is_not_configured(app):
    from app.models import Provider

    with app.app_context():
        provider = Provider(id="openai", name="OpenAI", kind="llm")
        db.session.add(provider)
        db.session.commit()

        assert provider.masked_key == ""
        assert provider.configured is False
