"""P3 作答：`quiz_attempts.option` 从 16 字符放宽到 255

Revision ID: c3f81b0a5d7e
Revises: d44ccaf4af9c
Create Date: 2026-09-13 18:20:41.006312

**这一版修的是一个会让 P3-A7 直接不过的错**：题面 DSL 里 `quiz.options` 是四句
话、`quiz.answer` 也是其中一句话（§ 技术实现方案 161），判定就是拿两句话比 ——
可这一列只有 16 个字符，而示例课里最短的正确选项有 17 个字。于是
「学生点了正确答案」这件事在库里存不下、在判定里也永远对不上：
**每一道题都判错**。

为什么不是一句 `batch_alter_table` 就完事：SQLite 没有 ALTER COLUMN，改列型
必然整表重建，而重建时表上的两条 CHECK（`page_no > 0`、选项非空的那条）
与三条索引都要跟着搬过去。`batch_alter_table` 的反射会把它们带上，但**反射
拿不到的东西不会自己冒出来** —— 搬完必须让契约测试那一条
`test_migration_matches_model_definition` 说话（它拿 `compare_metadata` 逐列
比对迁移结果与模型定义），不能靠「看起来没问题」。

数据搬过去不做截断：SQLite 本来就不强制 VARCHAR 长度，旧库里更不存在超长值
（旧上限 16 是**写入口**卡的，库里最长的也就 16 个字）。降级也一样不截断 ——
真要在别的库上降级、且库里已经有长选项，那一步会失败而不是悄悄砍掉半句话：
**宁可失败，也不要改坏一份作答记录**。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3f81b0a5d7e'
down_revision = 'd44ccaf4af9c'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('quiz_attempts', schema=None) as batch_op:
        batch_op.alter_column(
            'option',
            existing_type=sa.String(length=16),
            type_=sa.String(length=255),
            existing_nullable=True,
        )


def downgrade():
    with op.batch_alter_table('quiz_attempts', schema=None) as batch_op:
        batch_op.alter_column(
            'option',
            existing_type=sa.String(length=255),
            type_=sa.String(length=16),
            existing_nullable=True,
        )
