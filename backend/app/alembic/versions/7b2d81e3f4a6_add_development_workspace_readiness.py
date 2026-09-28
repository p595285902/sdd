"""Add development workspace readiness

Revision ID: 7b2d81e3f4a6
Revises: 2f6a8d7b4c91
Create Date: 2026-09-28 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "7b2d81e3f4a6"
down_revision = "2f6a8d7b4c91"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "developmentchat",
        sa.Column(
            "workspace_ready",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("developmentchat", "workspace_ready", server_default=None)


def downgrade():
    op.drop_column("developmentchat", "workspace_ready")