"""Add development chats and messages

Revision ID: 2f6a8d7b4c91
Revises: fe56fa70289e
Create Date: 2026-09-24 00:00:00.000000

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision = "2f6a8d7b4c91"
down_revision = "fe56fa70289e"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "developmentchat",
        sa.Column(
            "title", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_developmentchat_owner_updated_id",
        "developmentchat",
        ["owner_id", "updated_at", "id"],
    )
    op.create_table(
        "developmentmessage",
        sa.Column(
            "role",
            sa.Enum("user", "assistant", name="developmentmessagerole"),
            nullable=False,
        ),
        sa.Column(
            "content", sqlmodel.sql.sqltypes.AutoString(length=100000), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["developmentchat.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_developmentmessage_chat_created_id",
        "developmentmessage",
        ["chat_id", "created_at", "id"],
    )


def downgrade():
    op.drop_index(
        "ix_developmentmessage_chat_created_id",
        table_name="developmentmessage",
    )
    op.drop_table("developmentmessage")
    op.drop_index(
        "ix_developmentchat_owner_updated_id", table_name="developmentchat"
    )
    op.drop_table("developmentchat")