"""Add Development Turn settings

Revision ID: 6a2f9c4d8e10
Revises: 4d8f22c19a71
Create Date: 2026-09-30 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "6a2f9c4d8e10"
down_revision = "4d8f22c19a71"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column(
            "concurrent_agent_turn_limit",
            sa.Integer(),
            nullable=False,
            server_default="2",
        ),
    )
    op.add_column(
        "developmentchat",
        sa.Column(
            "presence_mode",
            sa.String(length=32),
            nullable=False,
            server_default="stop_when_i_leave",
        ),
    )
    op.alter_column("user", "concurrent_agent_turn_limit", server_default=None)
    op.alter_column("developmentchat", "presence_mode", server_default=None)


def downgrade():
    op.drop_column("developmentchat", "presence_mode")
    op.drop_column("user", "concurrent_agent_turn_limit")