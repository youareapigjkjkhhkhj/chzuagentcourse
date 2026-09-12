"""迁移契约测试（P0-C2）。

要求：Alembic 必须能 upgrade / downgrade 双向迁移，且迁移结果与模型定义一致。
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from app.extensions import db

pytestmark = pytest.mark.contract

#: P0 的初始版本号。写死是对的：历史不可重写，这个 id 一旦生成就不会变。
P0_REVISION = "3375f280213f"

#: P0 建的八张表（含 alembic_version）
EXPECTED_TABLES = {
    "users",
    "settings_kv",
    "providers",
    "voice_profiles",
    "agent_roles",
    "courses",
    "course_pages",
}


def _tables() -> set[str]:
    return set(inspect(db.engine).get_table_names())


def test_migrations_are_reversible(app_factory):
    """upgrade → downgrade → upgrade 全链路走通。"""
    from flask_migrate import downgrade, upgrade

    app_factory(create_tables=False)
    assert not (EXPECTED_TABLES & _tables()), "迁移前不该有业务表"

    upgrade()
    assert _tables() >= EXPECTED_TABLES, "upgrade 后缺表"
    assert "alembic_version" in _tables()

    downgrade(revision="base")
    leftover = EXPECTED_TABLES & _tables()
    assert not leftover, f"downgrade 后仍残留：{leftover}"

    upgrade()
    assert _tables() >= EXPECTED_TABLES, "二次 upgrade 失败"


def test_migration_matches_model_definition(app_factory):
    """迁移建出来的表和模型定义必须一致 —— 否则以后 autogenerate 会一直有噪音 diff。

    做法：先在空库上 upgrade，再让 SQLAlchemy 对比 metadata 与实际库结构。
    """
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from flask_migrate import upgrade

    app_factory(create_tables=False)
    upgrade()

    with db.engine.connect() as connection:
        context = MigrationContext.configure(connection)
        diff = compare_metadata(context, db.metadata)

    # 过滤掉 alembic 自己的版本表噪声
    meaningful = [
        item
        for item in diff
        if "alembic_version" not in str(item)
    ]
    assert not meaningful, "迁移与模型不一致：\n" + "\n".join(str(i) for i in meaningful)


def _seed_a_page(kind: str) -> None:
    """在 course_pages 里塞一页，用于验证「带数据的迁移」。"""
    db.session.execute(
        text(
            "INSERT INTO courses (id, title, status, page_count, duration_min,"
            " created_at, updated_at) VALUES ('c1', '测试课', 'ready', 1, 10, 'x', 'x')"
        )
    )
    db.session.execute(
        text(
            "INSERT INTO course_pages (id, course_id, chapter_no, page_no, kind, title,"
            " status, rev, created_at, updated_at)"
            " VALUES ('p1', 'c1', 1, 1, :kind, '第一页', 'ready', 1, 'x', 'x')"
        ),
        {"kind": kind},
    )
    db.session.commit()


def _insert_course(course_id: str) -> None:
    """塞一门课 + 一页，用于验证「带数据的迁移」对整门课做了什么。"""
    db.session.execute(
        text(
            "INSERT INTO courses (id, title, status, page_count, duration_min,"
            " created_at, updated_at) VALUES (:id, '测试课', 'ready', 1, 10, 'x', 'x')"
        ),
        {"id": course_id},
    )
    db.session.execute(
        text(
            "INSERT INTO course_pages (id, course_id, chapter_no, page_no, kind, title,"
            " status, rev, created_at, updated_at)"
            " VALUES (:pid, :id, 0, 1, 'summary', '第一页', 'ready', 1, 'x', 'x')"
        ),
        {"id": course_id, "pid": f"{course_id}-p1"},
    )
    db.session.commit()


def _course_ids() -> set[str]:
    return {row[0] for row in db.session.execute(text("SELECT id FROM courses"))}


def _page() -> tuple[str, str]:
    row = db.session.execute(text("SELECT kind, title FROM course_pages")).one()
    return row[0], row[1]


def test_upgrade_remaps_p0_content_pages(app_factory):
    """P0 的 content 页在升级时要就地变成 concept，而不是让迁移整个失败。

    为什么单拎出来测：上面那些用例都从空库开始走迁移，空表里没有
    「旧约束允许、新约束不允许」的值，于是这条路径永远绿 ——
    真正装了数据的库才会炸，而那正是用户手上那个库。
    """
    from flask_migrate import upgrade

    app_factory(create_tables=False)
    upgrade(revision=P0_REVISION)
    _seed_a_page("content")

    upgrade()

    kind, title = _page()
    assert kind == "concept", "P0 的 content 页没有被改写成 concept"
    assert title == "第一页", "迁移把页面标题弄丢了"


def test_upgrade_keeps_page_kinds_that_both_versions_accept(app_factory):
    """两个版本都认的页型必须原样搬过去，不能被顺手改掉。"""
    from flask_migrate import upgrade

    app_factory(create_tables=False)
    upgrade(revision=P0_REVISION)
    _seed_a_page("summary")

    upgrade()

    assert _page()[0] == "summary"


def test_downgrade_collapses_p1_only_kinds_without_losing_rows(app_factory):
    """降级有损但不该失败、也不该删数据：P1 独有的页型收敛为 content。"""
    from flask_migrate import downgrade, upgrade

    app_factory(create_tables=False)
    upgrade()  # 先到 P1：debate 这个页型只有 P1 认
    _seed_a_page("debate")

    downgrade(revision=P0_REVISION)

    assert _page()[0] == "content", "P1 独有的页型没有被收敛"
    assert db.session.execute(text("SELECT count(*) FROM course_pages")).scalar() == 1


def test_upgrade_drops_the_old_demo_course_only(app_factory):
    """P0 那份示例课要**整门**删掉，且不能碰到用户自己的课（P1-7）。

    P0 的示例课页面是旧形状：`narration` 是一整段字符串，而 P1 按 beat 切数组。
    两者不兼容 —— 工作台按 beat 渲染、`rebuild_dsl` 按 beat 计时，旧页面一进
    P1 就把大纲树和课程时长算崩。删掉是让 `flask seed` 按新形状重装，
    课程 id 不变，用户看到的还是同一门课。

    这条用例必须从 P0 修订版起步：空库升级不会经过「带着旧形状数据」这条路，
    那正是这个迁移唯一存在的理由。
    """
    from flask_migrate import upgrade

    app_factory(create_tables=False)
    upgrade(revision=P0_REVISION)
    _insert_course("course_demo_photosynthesis")  # P0 装的那门示例课
    _insert_course("c1")  # 用户自己生成的课

    upgrade()

    remaining = _course_ids()
    assert "course_demo_photosynthesis" not in remaining, "旧形状的示例课没被删掉"
    assert "c1" in remaining, "只该删示例课，用户自己的课不能动"
    orphans = db.session.execute(
        text("SELECT count(*) FROM course_pages WHERE course_id = 'course_demo_photosynthesis'")
    ).scalar()
    assert orphans == 0, "删课要连页面一起删干净（P1-C3）"


def test_seed_reason_is_accepted_by_the_new_constraint(app_factory):
    """升级后的 `reason` 约束要认 seed，而旧的三个值照样能用。"""
    from flask_migrate import upgrade

    app_factory(create_tables=False)
    upgrade()
    _insert_course("c1")

    for reason in ("generate", "rewrite", "manual", "seed"):
        db.session.execute(
            text(
                "INSERT INTO course_page_versions (id, page_id, rev, reason, tokens,"
                " created_at, updated_at) VALUES (:id, 'c1-p1', :rev, :reason, 0, 'x', 'x')"
            ),
            {"id": f"v-{reason}", "rev": len(reason), "reason": reason},
        )
    db.session.commit()

    assert db.session.execute(text("SELECT count(*) FROM course_page_versions")).scalar() == 4


def test_migration_files_are_committed():
    """迁移脚本必须进版本库，否则别人拉下来 upgrade 无事发生。"""
    from app.config import BACKEND_DIR

    versions = BACKEND_DIR / "migrations" / "versions"
    assert versions.is_dir(), "缺少 migrations/versions 目录"

    scripts = [p for p in versions.glob("*.py") if not p.name.startswith("__")]
    assert scripts, "没有任何迁移脚本"


def test_course_pages_cascade_declared_in_migration(app_factory):
    """级联删除必须写在迁移里，而不只是模型里。"""
    from flask_migrate import upgrade

    from app.config import BACKEND_DIR

    app_factory(create_tables=False)
    upgrade()

    inspector = inspect(db.engine)
    fks = inspector.get_foreign_keys("course_pages")
    course_fk = next((fk for fk in fks if fk["referred_table"] == "courses"), None)

    assert course_fk is not None, "course_pages 缺少指向 courses 的外键"
    assert course_fk["options"].get("ondelete") == "CASCADE", course_fk

    versions = BACKEND_DIR / "migrations" / "versions"
    text = "\n".join(p.read_text(encoding="utf-8") for p in versions.glob("*.py"))
    assert "CASCADE" in text
