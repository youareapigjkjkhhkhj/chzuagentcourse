"""课程级 PPT 模板：courses.template 列

Revision ID: b8e2f4c71a05
Revises: a7f3c1e9d4b2
Create Date: 2026-09-14 14:10:00.000000

模板过去只在导出那一刻选（`exports.options_json` 里的一项），是**一次性**的：
每导一次都要重选，工作台预览也无从跟随。这一列把它提到**课程级** —— 首页
「开始生成」时选定，存到课程上，预览与导出默认都用它（导出面板仍可单次覆盖）。

值是 `exports/theme.py` 里的 key（default / swiss / tech）。给已有课程补
`server_default='default'`：老课程重导时仍是「品牌蓝」，样子不会悄悄变
（与 `theme.get()` 认不出就退回缺省是同一条向后兼容的退路）。

降级只删这一列：模板退回「导出时临时选」，不影响课程与页面本身。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8e2f4c71a05'
down_revision = 'a7f3c1e9d4b2'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite 的 ADD COLUMN 带 NOT NULL 必须给 server_default，否则已有行没值可填。
    op.add_column(
        'courses',
        sa.Column('template', sa.String(length=16), nullable=False, server_default='default'),
    )


def downgrade():
    # 原生删列，**不要**用 batch（重建表）—— 理由与 fd6cc663b1c6 里那段一字不差：
    # courses 是 course_pages / gen_jobs 的外键父表，batch 重建在 foreign_keys=ON
    # 时等价于「建新表 → 搬数据 → DROP TABLE courses → 改名」，那次 DROP 的隐式
    # DELETE 会顺着 CASCADE 把页面、版本、任务全带走 —— 降级一次就清空课程内容，
    # 而且不报任何错。需要 SQLite ≥ 3.35（venv 内置 3.38，同 fd6cc663b1c6）。
    op.execute('ALTER TABLE courses DROP COLUMN template')
