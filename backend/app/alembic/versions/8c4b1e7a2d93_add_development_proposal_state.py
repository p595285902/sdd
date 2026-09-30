"""Add development proposal state

Revision ID: 8c4b1e7a2d93
Revises: 6a2f9c4d8e10
Create Date: 2026-09-30 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "8c4b1e7a2d93"
down_revision = "6a2f9c4d8e10"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "developmentmessage",
        sa.Column(
            "kind",
            sa.String(length=32),
            nullable=False,
            server_default="message",
        ),
    )
    op.add_column(
        "developmentmessage",
        sa.Column("proposal_state", sa.String(length=32), nullable=True),
    )
    op.alter_column("developmentmessage", "kind", server_default=None)


def downgrade():
    op.drop_column("developmentmessage", "proposal_state")
    op.drop_column("developmentmessage", "kind")
