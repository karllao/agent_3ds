"""align tables with ORM models

Revision ID: 002_align_models
Revises: 001_initial
Create Date: 2026-05-23 00:00:00.000000

修复 001_initial 与 ORM 模型间的字段差异：
  - conversations: 新增 title 列
  - messages: 新增 meta 列；删除 token_count；将 role 由 VARCHAR 转为 message_role ENUM
  - jobs: 将 step 由 VARCHAR 转为 job_step ENUM
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "002_align_models"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # ── conversations.title ────────────────────────────────────────────────
    op.add_column(
        "conversations",
        sa.Column("title", sa.Text(), nullable=True),
    )

    # ── messages.meta + drop token_count ───────────────────────────────────
    op.add_column(
        "messages",
        sa.Column("meta", sa.Text(), nullable=True),
    )
    op.drop_column("messages", "token_count")

    # ── messages.role: VARCHAR → message_role ENUM ─────────────────────────
    message_role = postgresql.ENUM(
        "user",
        "assistant",
        "system",
        "tool",
        name="message_role",
        create_type=False,
    )
    message_role.create(bind, checkfirst=True)
    # 清理可能的非法值（防止 USING 失败），开发库为空时也无副作用
    op.execute(
        "UPDATE messages SET role = 'user' "
        "WHERE role NOT IN ('user','assistant','system','tool')"
    )
    op.execute(
        "ALTER TABLE messages ALTER COLUMN role TYPE message_role "
        "USING role::message_role"
    )

    # ── jobs.step: VARCHAR → job_step ENUM ─────────────────────────────────
    job_step = postgresql.ENUM(
        "cad_parse",
        "scene_generate",
        "max_export",
        "render_preview",
        name="job_step",
        create_type=False,
    )
    job_step.create(bind, checkfirst=True)
    op.execute(
        "UPDATE jobs SET step = NULL "
        "WHERE step IS NOT NULL AND step NOT IN "
        "('cad_parse','scene_generate','max_export','render_preview')"
    )
    op.execute(
        "ALTER TABLE jobs ALTER COLUMN step TYPE job_step "
        "USING step::job_step"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE jobs ALTER COLUMN step TYPE VARCHAR(100) "
        "USING step::text"
    )
    op.execute("DROP TYPE IF EXISTS job_step")

    op.execute(
        "ALTER TABLE messages ALTER COLUMN role TYPE VARCHAR(20) "
        "USING role::text"
    )
    op.execute("DROP TYPE IF EXISTS message_role")

    op.add_column(
        "messages",
        sa.Column("token_count", sa.Integer(), nullable=True),
    )
    op.drop_column("messages", "meta")

    op.drop_column("conversations", "title")
