"""P6.1 学情：新建 review_pages 表（动态插入的复习页）

Revision ID: a7f3c1e9d4b2
Revises: 9f2c1ad6b7e3
Create Date: 2026-09-14 10:30:00.000000

同章连错 ≥2 题时，系统自动生成一页复习内容并插入课堂时间线。
这一页的内容（DSL JSON）、触发原因、关联概念都落在这张表里，
课后「学情总览」从这里读。

降级只删表：复习页是增量信息，删掉不影响课堂记录本身的完整性。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7f3c1e9d4b2'
down_revision = '9f2c1ad6b7e3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'review_pages',
        sa.Column('id', sa.String(length=32), primary_key=True),
        sa.Column('session_id', sa.String(length=32), sa.ForeignKey('classroom_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('course_id', sa.String(length=32), sa.ForeignKey('courses.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_page_no', sa.Integer(), nullable=False),
        sa.Column('inserted_after_page_no', sa.Integer(), nullable=False),
        sa.Column('dsl_json', sa.Text(), nullable=False),
        sa.Column('trigger_reason', sa.String(length=64), nullable=False),
        sa.Column('concept_tag', sa.String(length=128)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index('ix_review_pages_session', 'review_pages', ['session_id'])
    op.create_index('ix_review_pages_course', 'review_pages', ['course_id'])


def downgrade():
    op.drop_index('ix_review_pages_course', table_name='review_pages')
    op.drop_index('ix_review_pages_session', table_name='review_pages')
    op.drop_table('review_pages')
