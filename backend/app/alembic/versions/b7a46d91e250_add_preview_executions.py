"""Add durable chat-owned preview executions and events.

Revision ID: b7a46d91e250
Revises: ae51c90f273b
"""

import sqlalchemy as sa
from alembic import op

revision = "b7a46d91e250"
down_revision = "ae51c90f273b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "previewexecution",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("ready", sa.Boolean(), nullable=False),
        sa.Column("workflow_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column("controller_cursor", sa.BigInteger(), nullable=False),
        sa.Column("retained_output_bytes", sa.BigInteger(), nullable=False),
        sa.Column("truncated_bytes", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "status IN ('starting', 'running', 'failed', 'stopped', 'interrupted')",
            name="ck_previewexecution_status",
        ),
        sa.CheckConstraint(
            "last_sequence >= 0 AND controller_cursor >= 0 "
            "AND retained_output_bytes >= 0 AND truncated_bytes >= 0",
            name="ck_previewexecution_counters",
        ),
        sa.CheckConstraint("NOT ready OR status = 'running'", name="ck_previewexecution_ready"),
        sa.ForeignKeyConstraint(["chat_id"], ["developmentchat.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_previewexecution_chat_created_id",
        "previewexecution",
        ["chat_id", "created_at", "id"],
    )
    op.create_index(
        "uq_previewexecution_active_chat",
        "previewexecution",
        ["chat_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('starting', 'running')"),
        sqlite_where=sa.text("status IN ('starting', 'running')"),
    )
    op.create_table(
        "previewexecutionevent",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("controller_cursor", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("output_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sequence > 0 AND (controller_cursor IS NULL OR controller_cursor > 0) "
            "AND output_bytes >= 0",
            name="ck_previewexecutionevent_counters",
        ),
        sa.ForeignKeyConstraint(["execution_id"], ["previewexecution.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", "sequence", name="uq_previewexecutionevent_sequence"),
        sa.UniqueConstraint("execution_id", "controller_cursor", name="uq_previewexecutionevent_cursor"),
    )


def downgrade():
    op.drop_table("previewexecutionevent")
    op.drop_index("uq_previewexecution_active_chat", table_name="previewexecution")
    op.drop_index("ix_previewexecution_chat_created_id", table_name="previewexecution")
    op.drop_table("previewexecution")
