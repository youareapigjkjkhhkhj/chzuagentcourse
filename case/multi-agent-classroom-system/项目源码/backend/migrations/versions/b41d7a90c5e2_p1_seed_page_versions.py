"""P1-7 示例课：版本来源增加 seed，并清掉 P0 那份旧形状的示例课

Revision ID: b41d7a90c5e2
Revises: fd6cc663b1c6
Create Date: 2026-09-12 21:20:04.118477

两件事，都围绕 P1-7 的示例课。

**一、course_page_versions.reason 增加 seed**

示例课的那 24 页是**手写**的（`app/seeds/courses/`），既不是模型生成、
也不是人工编辑。它们同样要有 V1 —— 否则用户第一次重写示例课的某一页时，
版本表里只有「第 2 版」，既看不到原来那一版，也就没有能退回去的地方。

于是问题只剩：这一条记成什么。generate 会与同一行里空的 `model` 自相矛盾，
manual 又会把「老师手改过的页」这个查询答错。加一个 seed 是最省事的诚实做法。

为什么必须重建整张表：SQLite 没有 ALTER ... CHECK，改约束只有
「建新表 → 搬数据 → 换名」一条路（同 93066cfa72dd 对 course_pages 的处理）。
这次比那次简单 —— 枚举是**扩张**的，旧的三个值在新表里依然合法，
不需要 CASE 映射；只有降级时反过来，seed 收敛成 generate。

重建的是**子表**（course_page_versions 没有任何表引用它），所以 DROP TABLE
的隐式 DELETE 只影响它自己 —— fd6cc663b1c6 里那个「删父表会顺着 CASCADE
带走一堆数据」的坑在这里不成立。

**二、删掉 P0 那份光合作用示例课**

P0 的示例课页面是旧形状：`narration` 是一整段字符串，P1 是按 beat 切的数组
（`normalize_beats`）。两者不兼容 —— 工作台按 beat 渲染、`rebuild_dsl` 按
beat 计时，于是旧页面一进 P1 就把大纲树和课程时长算崩。

为什么是**整门删掉**而不是就地改写：改写要在迁移里复刻一遍切句与估时逻辑
（30 行只属于「那一刻」的代码），删掉则交给已经写好内容的那份种子重装。
丢的也不是用户数据 —— P0 根本没有编辑入口，这些页面只可能来自安装时灌的
种子；课程 id 不变，`flask seed` 之后用户看到的还是同一门课。

子表按顺序显式删，不依赖 `PRAGMA foreign_keys` 是否开着（P1-C3：删完不留孤儿）。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b41d7a90c5e2'
down_revision = 'fd6cc663b1c6'
branch_labels = None
depends_on = None

#: 两个方向的取值集合。与 app/models/page_version.py 的 PAGE_VERSION_REASONS
#: 保持一致 —— 迁移里写死字面量，不 import 模型：它描述的是「那一刻的约束」，
#: 跟着模型走会让历史版本随模型演进而变样，回放就不再可复现。
_REASONS_P1 = "'generate', 'rewrite', 'manual', 'seed'"
_REASONS_P0 = "'generate', 'rewrite', 'manual'"

#: 显式列出列清单，同样不引用当前模型。
_COLUMNS = (
    "id", "page_id", "rev", "dsl_json", "reason", "instruction",
    "model", "tokens", "meta_json", "created_at", "updated_at",
)


def _versions(reasons_sql: str, name: str) -> sa.Table:
    """某个版本下 course_page_versions 的结构。name 用于建临时表。"""
    metadata = sa.MetaData()
    # 外键的目标表要在这个 MetaData 里认得出来，否则建表时解析不了 course_pages.id。
    # 只声明主键列：这里只是给 FK 一个落点，不会真的去建它。
    sa.Table("course_pages", metadata, sa.Column("id", sa.String(32), primary_key=True))
    return sa.Table(
        name,
        metadata,
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("page_id", sa.String(32), nullable=False),
        sa.Column("rev", sa.Integer(), nullable=False),
        sa.Column("dsl_json", sa.Text()),
        sa.Column("reason", sa.String(16), nullable=False),
        sa.Column("instruction", sa.Text()),
        sa.Column("model", sa.String(64)),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("meta_json", sa.Text()),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.CheckConstraint(
            f"reason IN ({reasons_sql})",
            name="ck_course_page_versions_course_page_version_reason_valid",
        ),
        sa.CheckConstraint(
            "rev > 0", name="ck_course_page_versions_course_page_version_rev_positive"
        ),
        sa.ForeignKeyConstraint(
            ["page_id"],
            ["course_pages.id"],
            name="fk_course_page_versions_page_id_course_pages",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("page_id", "rev", name="uq_course_page_versions_page_rev"),
    )


def _rebuild_versions(reasons_sql: str, reason_expr: str, params: dict) -> None:
    """把 course_page_versions 重建成 reasons_sql 约束的表。

    `reason_expr` 是搬数据时对 reason 列的算式：扩张时就是原列，
    降级时把 seed 折叠回 generate。
    """
    tmp = "course_page_versions_rebuild"
    op.execute(f'DROP TABLE IF EXISTS "{tmp}"')
    _versions(reasons_sql, tmp).create(bind=op.get_bind())

    columns = ", ".join(_COLUMNS)
    op.get_bind().execute(
        sa.text(
            f'INSERT INTO "{tmp}" ({columns}) SELECT '
            f"id, page_id, rev, dsl_json, {reason_expr}, instruction, "
            f"model, tokens, meta_json, created_at, updated_at "
            f"FROM course_page_versions"
        ),
        params,
    )
    op.drop_table("course_page_versions")
    op.rename_table(tmp, "course_page_versions")


#: P0 装过的那门示例课。它由 `app/seeds/courses.py`（P1 起已被
#: `app/seeds/courses/` 取代）灌进去，课程 id 与 P1 的新版一致 ——
#: 所以删掉之后重跑种子，装回来的还是同一门课。
_DEMO_COURSES_P0 = ("course_demo_photosynthesis",)

#: 删这门课要带走的子表。顺序是「从叶子到根」：版本挂页面、页面与任务挂课程。
_CHILD_DELETES = (
    "DELETE FROM course_page_versions WHERE page_id IN"
    " (SELECT id FROM course_pages WHERE course_id IN :ids)",
    "DELETE FROM gen_events WHERE job_id IN"
    " (SELECT id FROM gen_jobs WHERE course_id IN :ids)",
    "DELETE FROM gen_steps WHERE job_id IN"
    " (SELECT id FROM gen_jobs WHERE course_id IN :ids)",
    "DELETE FROM gen_jobs WHERE course_id IN :ids",
    "DELETE FROM course_pages WHERE course_id IN :ids",
)


def _delete_in(connection, sql: str, ids: list[str]) -> None:
    """`IN :ids` 要显式声明 expanding，SQLAlchemy 才会把它摊成一组占位符。"""
    connection.execute(
        sa.text(sql).bindparams(sa.bindparam("ids", expanding=True)), {"ids": ids}
    )


def _drop_p0_demo_courses() -> None:
    """删掉旧形状的示例课及其全部子行（新形状由 `flask seed` 重新装）。"""
    connection = op.get_bind()
    ids = list(_DEMO_COURSES_P0)
    for sql in _CHILD_DELETES:
        _delete_in(connection, sql, ids)
    _delete_in(connection, "DELETE FROM courses WHERE id IN :ids", ids)


def upgrade():
    # 纯扩张：已有的三值在新约束下依然合法，原样搬过去即可。
    _rebuild_versions(_REASONS_P1, "reason", {})
    _drop_p0_demo_courses()


def downgrade():
    # 有损但不失败、不删数据：seed 在旧枚举里没有对应物，收敛成 generate
    # （它同样表示「这一条不是用户改的」）。
    # 示例课不在这里恢复 —— 那份内容已经在 upgrade 里换成了 P1 的作者稿，
    # 而 P0 的旧形状已经没人能渲染了。
    _rebuild_versions(_REASONS_P0, "CASE WHEN reason = 'seed' THEN :fallback ELSE reason END",
                      {"fallback": "generate"})
