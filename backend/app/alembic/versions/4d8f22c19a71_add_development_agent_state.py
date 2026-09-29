"""Add development agent state

Revision ID: 4d8f22c19a71
Revises: 7b2d81e3f4a6
Create Date: 2026-09-29 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "4d8f22c19a71"
down_revision = "7b2d81e3f4a6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "developmentchat",
        sa.Column("agent_session_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "developmentmessage",
        sa.Column(
            "activity",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.alter_column("developmentmessage", "activity", server_default=None)


def downgrade():
    op.drop_column("developmentmessage", "activity")
    op.drop_column("developmentchat", "agent_session_id")