"""P5 生成可观测：gen_steps 扩 attempts / error_code 两列

Revision ID: 9f2c1ad6b7e3
Revises: b114a4cb8453
Create Date: 2026-09-13 23:58:12.004913

两列，都加在 `gen_steps` 上（P5-F5-10：工作台任务卡展开要看得见
「每步耗时、重试次数、失败原因、上游错误码」）。耗时与 tokens 早就有了，
缺的正是后两样 —— 它们回答的是两个不同的问题：

    attempts    这一步**跑了几次**（断点续跑/重试会在同一行上再跑一遍）
    error_code  这一步**为什么失败**，归类后的（rate_limit / timeout / …）

三处值得写下来的决定：

1. **`server_default`，不是 `nullable=True`。** 与 P5-1 那条迁移同一条理由：
   它们是计数与归类码，不是「可能有、可能没有」的内容，NULL 只会让每个读它的
   地方都补一遍 `or 0` / `or ""`，漏一处就是时间线上一个 `None` 渲染成
   「null 次」。老数据升级后原地变成 `0` / `""`，不需要回填 ——
   含义是「这列是 P5 才有的，这行发生在它能被填上之前」。

2. **`attempts` 是「重置后累计」，不是「本次运行次数」。** 断点续跑把失败的那一步
   放回 `wait` 再跑，计数**不清零**（见 `pipeline._run_step`）：
   清零的话「重试三次才成」看起来和「一次就成」一模一样，
   而前者恰恰是用户要去查上游的那个信号。

3. **既有表不加新 CHECK 约束。** 同 P5-1：SQLite 要重建表才能加约束，
   而 `gen_steps` 是生成过程中写得最勤的一张表之一。`attempts >= 0` 由
   唯一的写入点保证（`pipeline._run_step` 只会 +1）。

降级只删这两列，不动任何行 —— 它们是可观测数据，删掉只是少一份视图。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f2c1ad6b7e3'
down_revision = 'b114a4cb8453'
branch_labels = None
depends_on = None

#: 显式写死列定义，不引用当前模型 —— 迁移描述的是「那一刻的表结构」。
_STEP_COLUMNS = (
    ("attempts", sa.Integer(), "0"),
    ("error_code", sa.String(length=32), ""),
)


def upgrade():
    with op.batch_alter_table('gen_steps', schema=None) as batch_op:
        for name, type_, default in _STEP_COLUMNS:
            batch_op.add_column(sa.Column(name, type_, nullable=False, server_default=default))


def downgrade():
    with op.batch_alter_table('gen_steps', schema=None) as batch_op:
        for name, _type, _default in reversed(_STEP_COLUMNS):
            batch_op.drop_column(name)
