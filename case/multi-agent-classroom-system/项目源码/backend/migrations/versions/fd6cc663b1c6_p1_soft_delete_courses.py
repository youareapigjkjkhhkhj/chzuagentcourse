"""P1 课程软删标记：courses.deleted_at + 列表索引

Revision ID: fd6cc663b1c6
Revises: 93066cfa72dd
Create Date: 2026-09-12 19:48:46.649833

`DELETE /api/courses/{id}` 是**软删**（P1 §4）：`deleted_at` 非空即已删。
为什么不是 `db.session.delete(course)` 一句话了事 —— 那样会把页面、版本、
事件一并带走，而这几张表恰好是「用户点错了想找回」和「这次生成到底怎么回事」
唯一能查的东西。真删（级联清理）留给部署方的运维操作，不摆在一个 HTTP
动词后面。

两处细节：

- 列**可空且无默认值**：升级时已有的课程全部留空，即「都没删」。
  这不需要数据回填，也就没有回填写错的余地。
- 索引 `(owner_id, deleted_at, updated_at)` 对应列表接口唯一的一种查法：
  「我的、没删的、按更新时间倒序」。少了它，课程一多就是全表扫 + 排序。

还有一个只在**降级**时才会踩到的坑，写在这里省得下次又按 batch 的常规写法写一遍：

    `courses` 是所有业务表的外键父表（course_pages 直接挂它，
    页面版本挂 course_pages，任务挂 courses）。而 `batch_alter_table`
    删列在 SQLite 上等于「建新表 → 搬数据 → DROP TABLE courses → 改名」，
    alembic 并不会替你关外键。`foreign_keys=ON` 时 `DROP TABLE` 会先做一次
    隐式 DELETE，这一删就顺着 CASCADE 把页面、版本、任务全带走了 ——
    「退回上一个版本」于是变成「清空课程内容」，而且不报任何错。
    所以下面用原生 `DROP COLUMN`，不重建表。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fd6cc663b1c6'
down_revision = '93066cfa72dd'
branch_labels = None
depends_on = None


def upgrade():
    # 加列、建索引都是 SQLite 原生 DDL，一句一句发就好（见上面的坑：
    # batch 一旦决定重建表，父表的级联就跟着来，而这里根本不需要重建）。
    op.add_column('courses', sa.Column('deleted_at', sa.String(length=32), nullable=True))
    op.create_index(
        'ix_courses_owner_updated', 'courses', ['owner_id', 'deleted_at', 'updated_at'],
        unique=False,
    )


def downgrade():
    # 先摘索引：SQLite 的 DROP COLUMN 不允许列还被索引引用着。
    op.drop_index('ix_courses_owner_updated', table_name='courses')
    # 原生删列，不重建表（重建的代价见模块 docstring）。
    # 需要 SQLite ≥ 3.35 —— 本项目 venv 内置的是 3.38。
    op.execute('ALTER TABLE courses DROP COLUMN deleted_at')
