"""P5 导出与成本：exports / daily_usage / budgets 三张新表 + 账本两表扩列

Revision ID: b114a4cb8453
Revises: e81d7febf2ff
Create Date: 2026-09-13 22:41:07.518204

三张新表 + 两张既有表扩列。**不重建任何表**（P1 那两条迁移是重建，这里不是），
几处值得写下来的决定：

1. **新列的默认值写在 `server_default` 上，而不是只靠模型的 `default=`。**
   这是与 P2 那条迁移（`preview_url` / `params_json` 用 `nullable=True`）不一样的地方，
   理由是**数据的含义不同**：那两个字段是「可能有、可能没有」的字符串，NULL 是有意义的；
   这里加的是**记账用的数**（token 数、金额、单位），`NULL` 只会让所有读它的地方
   都得写一遍 `or 0`，而漏写一处就是 `None + 5` 崩在成本看板上。
   `0` / 空串在这里的意思是「这列是 P5 才有的，这次调用发生在它能被填上之前」——
   老数据在升级后原地变成 0，不需要额外回填。

2. **既有表不加新的 CHECK 约束。** SQLite 加不了 CHECK，要加就得整表重建，
   而这里是 `model_calls`（账本）与 `audit_logs`（审计）—— P1 起就在写热的表。
   为几条防御性约束去重建账本不划算，所以非负性改由**唯一的写入点**保证
   （`app/services/usage/ledger.py`，那里有单测）。新表不受此限，约束照写。
   `kind` 那条 P1 的约束原样留着 —— 它没有变化，也就不需要动。

3. **`model_calls.tokens` 的含义不变**（仍是输入+输出的**总数**）。
   P1-D4 的 `_ledger_tokens()` 按 `job_id` 对它求和来对账，扩列扩出来的是
   「贵在哪一半」（`prompt_tokens`/`completion_tokens`），不是把总数拆了。
   这条口径写在 `app/models/telemetry.py` 的头注释里。

4. **`daily_usage` 是派生数据**：把 `model_calls`（LLM）与 `usage_records`（语音）
   按天重算一遍就能重建。存它只为让看板不必每次扫全表，删了不丢事实。

5. 降级只删 P5 加的东西，**不动磁盘上的导出产物**（同 P2/P3/P4）。
   `data/exports/` 下的文件由服务层的清理任务负责，迁移不管文件系统。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b114a4cb8453'
down_revision = 'e81d7febf2ff'
branch_labels = None
depends_on = None

#: `model_calls` 扩的八列。迁移里显式写死，**不引用当前模型** ——
#: 迁移描述的是「那一刻的表结构」，跟着模型走会让历史版本随模型演进而变样。
_MODEL_CALL_COLUMNS = (
    ("prompt_tokens", sa.Integer(), "0"),
    ("completion_tokens", sa.Integer(), "0"),
    ("units", sa.Integer(), "0"),
    ("unit_name", sa.String(length=16), ""),
    ("est_cost", sa.Float(), "0"),
    ("ref_type", sa.String(length=16), ""),
    ("ref_id", sa.String(length=32), ""),
    ("step_id", sa.String(length=32), ""),
)

#: `audit_logs` 扩的两列（P5-A14：审计要能回答「从哪儿、用什么来的」）
_AUDIT_COLUMNS = (
    ("ip", sa.String(length=64), ""),
    ("ua", sa.String(length=255), ""),
)


def upgrade():
    # --- 既有表扩列：纯 ADD COLUMN，SQLite 原生支持，不重建 ---
    with op.batch_alter_table('model_calls', schema=None) as batch_op:
        for name, type_, default in _MODEL_CALL_COLUMNS:
            batch_op.add_column(sa.Column(name, type_, nullable=False, server_default=default))
        # 单课明细（GET /api/usage/courses/{id}）与课堂用量都按这一对查
        batch_op.create_index('ix_model_calls_ref', ['ref_type', 'ref_id'], unique=False)
        # 任务时间线按步骤聚合（F5-10）
        batch_op.create_index('ix_model_calls_step', ['step_id'], unique=False)

    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        for name, type_, default in _AUDIT_COLUMNS:
            batch_op.add_column(sa.Column(name, type_, nullable=False, server_default=default))
        batch_op.create_index('ix_audit_logs_owner_created', ['owner_id', 'created_at'], unique=False)

    # --- 导出任务与产物（F5-6 / P5-C1）---
    op.create_table('exports',
    sa.Column('course_id', sa.String(length=32), nullable=False),
    sa.Column('session_id', sa.String(length=32), nullable=True),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('format', sa.String(length=8), nullable=False),
    sa.Column('scope', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('progress', sa.Integer(), nullable=False),
    sa.Column('file_path', sa.String(length=512), nullable=True),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('options_json', sa.Text(), nullable=True),
    sa.Column('error', sa.String(length=512), nullable=False),
    sa.Column('expires_at', sa.String(length=32), nullable=False),
    sa.Column('finished_at', sa.String(length=32), nullable=False),
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.String(length=32), nullable=False),
    sa.Column('updated_at', sa.String(length=32), nullable=False),
    sa.CheckConstraint("format IN ('pptx', 'html', 'pdf', 'md')", name=op.f('ck_exports_export_format_valid')),
    sa.CheckConstraint("scope IN ('course', 'record')", name=op.f('ck_exports_export_scope_valid')),
    sa.CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name=op.f('ck_exports_export_status_valid')),
    sa.CheckConstraint('progress >= 0 AND progress <= 100', name=op.f('ck_exports_export_progress_in_range')),
    sa.CheckConstraint('size_bytes >= 0', name=op.f('ck_exports_export_size_non_negative')),
    # P5-C1：产物必须在 data/exports/ 下、必须相对、且不许用 `..` 走出去
    sa.CheckConstraint("file_path IS NULL OR (file_path LIKE 'data/exports/%' AND file_path NOT LIKE '%..%')", name=op.f('ck_exports_export_file_path_relative')),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], name=op.f('fk_exports_course_id_courses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_exports'))
    )
    with op.batch_alter_table('exports', schema=None) as batch_op:
        batch_op.create_index('ix_exports_course_created', ['course_id', 'created_at'], unique=False)
        # 清理任务按到期时间扫（P5-C1）
        batch_op.create_index('ix_exports_expires', ['expires_at'], unique=False)
        batch_op.create_index('ix_exports_owner_created', ['owner_id', 'created_at'], unique=False)

    # --- 成本日聚合（F5-7）---
    op.create_table('daily_usage',
    sa.Column('date', sa.String(length=10), nullable=False),
    sa.Column('owner_id', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('total_tokens', sa.Integer(), nullable=False),
    sa.Column('total_units', sa.Integer(), nullable=False),
    sa.Column('est_cost', sa.Float(), nullable=False),
    sa.Column('calls', sa.Integer(), nullable=False),
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.String(length=32), nullable=False),
    sa.Column('updated_at', sa.String(length=32), nullable=False),
    sa.CheckConstraint("kind IN ('llm', 'tts', 'asr', 'realtime')", name=op.f('ck_daily_usage_daily_usage_kind_valid')),
    sa.CheckConstraint('total_tokens >= 0', name=op.f('ck_daily_usage_daily_usage_tokens_non_negative')),
    sa.CheckConstraint('total_units >= 0', name=op.f('ck_daily_usage_daily_usage_units_non_negative')),
    sa.CheckConstraint('est_cost >= 0', name=op.f('ck_daily_usage_daily_usage_cost_non_negative')),
    sa.CheckConstraint('calls >= 0', name=op.f('ck_daily_usage_daily_usage_calls_non_negative')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_daily_usage')),
    sa.UniqueConstraint('date', 'owner_id', 'kind', name='uq_daily_usage_date_owner_kind')
    )
    with op.batch_alter_table('daily_usage', schema=None) as batch_op:
        batch_op.create_index('ix_daily_usage_date', ['date'], unique=False)

    # --- 预算上限（F5-8）---
    op.create_table('budgets',
    sa.Column('scope', sa.String(length=16), nullable=False),
    sa.Column('ref_id', sa.String(length=32), nullable=False),
    sa.Column('limit_tokens', sa.Integer(), nullable=False),
    sa.Column('limit_cost', sa.Float(), nullable=False),
    sa.Column('alert_ratio', sa.Float(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.String(length=32), nullable=False),
    sa.Column('updated_at', sa.String(length=32), nullable=False),
    sa.CheckConstraint("scope IN ('global', 'course', 'day')", name=op.f('ck_budgets_budget_scope_valid')),
    sa.CheckConstraint('limit_tokens >= 0', name=op.f('ck_budgets_budget_limit_tokens_non_negative')),
    sa.CheckConstraint('limit_cost >= 0', name=op.f('ck_budgets_budget_limit_cost_non_negative')),
    sa.CheckConstraint('alert_ratio >= 0 AND alert_ratio <= 1', name=op.f('ck_budgets_budget_alert_ratio_in_range')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_budgets')),
    # 一个作用域一条：设置页改的是这一条，不是再插一条
    sa.UniqueConstraint('scope', 'ref_id', name='uq_budgets_scope_ref')
    )


def downgrade():
    op.drop_table('budgets')
    with op.batch_alter_table('daily_usage', schema=None) as batch_op:
        batch_op.drop_index('ix_daily_usage_date')

    op.drop_table('daily_usage')
    with op.batch_alter_table('exports', schema=None) as batch_op:
        batch_op.drop_index('ix_exports_owner_created')
        batch_op.drop_index('ix_exports_expires')
        batch_op.drop_index('ix_exports_course_created')

    op.drop_table('exports')
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.drop_index('ix_audit_logs_owner_created')
        for name, _type, _default in reversed(_AUDIT_COLUMNS):
            batch_op.drop_column(name)

    with op.batch_alter_table('model_calls', schema=None) as batch_op:
        batch_op.drop_index('ix_model_calls_step')
        batch_op.drop_index('ix_model_calls_ref')
        for name, _type, _default in reversed(_MODEL_CALL_COLUMNS):
            batch_op.drop_column(name)
