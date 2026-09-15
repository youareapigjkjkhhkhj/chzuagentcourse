"""P6 学情：review_pages 的时间戳纠正为 UTC ISO 字符串

Revision ID: c4f1a7b90d3e
Revises: b8e2f4c71a05
Create Date: 2026-09-14 19:20:00.000000

P6.1 手写建表时把 created_at / updated_at 写成了 `sa.DateTime()`，
而这个项目只有一种时间形状：UTC ISO8601 **字符串**
（`app/common/timeutil.py` 的 `utcnow_iso`，形如 `2026-09-14T10:30:00.123456Z`）。
`base.py` 的 TimestampMixin、其余每一张表、以及 `ReviewPage` 模型自己的
声明（`String(32)`）都是字符串 —— 只有这张表在迁移里跑偏了。

SQLite 不校验类型，写进去的仍然是那份文本，所以两边都能跑；露馅的地方是
契约测试：`compare_metadata` 一比就报「迁移建的是 DATETIME、模型写的是
String(32)」，从此 autogenerate 永远带着这两条噪音 diff。噪音会掩盖真问题，
所以补一次纠正，而不是把模型改成 `DateTime` —— 那是让一处笔误去改全项目的口径。

改列类型只有「建新表 → 搬数据 → 换名」一条路（SQLite 没有 ALTER COLUMN），
写法沿用仓库里已有的两处重建（93066cfa72dd 的 course_pages、
b41d7a90c5e2 的 course_page_versions）：列清单写死、不 import 模型 ——
迁移描述的是「那一刻的表结构」，跟着模型走会让回放随模型演进而变样。
数据是**原样搬**的：列里存的本来就是 ISO 字符串，没有要转换的东西。

顺带把两列补成 NOT NULL（模型就是这么声明的，P6.1 建成了可空）。
老行不会是空 —— 建表时两列都带着 `CURRENT_TIMESTAMP` 默认值；
真要是空的，就让迁移当场失败：那说明有人绕过模型手写过这一行，
这时候编一个时间戳填进去，比报错更坏。

重建 review_pages 不会牵动任何 CASCADE —— 它没有子表。反过来才危险：
courses 那种父表一旦重建，就会顺着 CASCADE 带走一整片子表（fd6cc663b1c6）。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4f1a7b90d3e'
down_revision = 'b8e2f4c71a05'
branch_labels = None
depends_on = None

#: 显式写死列清单，不引用当前模型（理由见模块 docstring）。
_COLUMNS = (
    "id", "session_id", "course_id", "source_page_no", "inserted_after_page_no",
    "dsl_json", "trigger_reason", "concept_tag", "created_at", "updated_at",
)


def _review_pages(name: str, *, iso: bool) -> sa.Table:
    """某种时间形状下的 review_pages 结构。name 用于建临时表。

    `iso=True` 是纠正后的形状（String(32)，与模型一致）；
    `iso=False` 是 P6.1 原样（DateTime、可空、带服务端默认值），降级时回到它。
    """
    metadata = sa.MetaData()
    # 外键的目标表要在这个 MetaData 里认得出来，否则建表时解析不了
    # classroom_sessions.id / courses.id。只声明主键列：这里只是给 FK
    # 一个落点，不会真的去建这两张表。
    sa.Table(
        "classroom_sessions", metadata, sa.Column("id", sa.String(32), primary_key=True)
    )
    sa.Table("courses", metadata, sa.Column("id", sa.String(32), primary_key=True))

    if iso:
        created_at = sa.Column("created_at", sa.String(32), nullable=False)
        updated_at = sa.Column("updated_at", sa.String(32), nullable=False)
    else:
        created_at = sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now()
        )
        updated_at = sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(),
            onupdate=sa.func.now(),
        )

    return sa.Table(
        name,
        metadata,
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), nullable=False),
        sa.Column("course_id", sa.String(32), nullable=False),
        sa.Column("source_page_no", sa.Integer(), nullable=False),
        sa.Column("inserted_after_page_no", sa.Integer(), nullable=False),
        sa.Column("dsl_json", sa.Text(), nullable=False),
        sa.Column("trigger_reason", sa.String(64), nullable=False),
        sa.Column("concept_tag", sa.String(128)),
        created_at,
        updated_at,
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["classroom_sessions.id"],
            name="fk_review_pages_session_id_classroom_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name="fk_review_pages_course_id_courses",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_review_pages"),
    )


def _rebuild(*, iso: bool) -> None:
    """把 review_pages 重建成指定时间形状的表，数据原样搬过去。"""
    tmp = "review_pages_rebuild"
    op.execute(f'DROP TABLE IF EXISTS "{tmp}"')
    _review_pages(tmp, iso=iso).create(bind=op.get_bind())

    columns = ", ".join(_COLUMNS)
    op.get_bind().execute(
        sa.text(f'INSERT INTO "{tmp}" ({columns}) SELECT {columns} FROM review_pages')
    )
    op.drop_table("review_pages")
    op.rename_table(tmp, "review_pages")
    # 索引挂在旧表上，随着那次 DROP 一起没了，换名之后补回来。
    op.create_index("ix_review_pages_session", "review_pages", ["session_id"])
    op.create_index("ix_review_pages_course", "review_pages", ["course_id"])


def upgrade():
    _rebuild(iso=True)


def downgrade():
    # 回到 P6.1 建出来的形状。时间戳还是那份 ISO 字符串 —— 降级降的是声明，
    # 不是数据（SQLite 不校验类型，两种声明存的是同一份文本）。
    _rebuild(iso=False)
