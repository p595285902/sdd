"""Add development message duration

Revision ID: ae51c90f273b
Revises: 8c4b1e7a2d93

"""

import sqlalchemy as sa
from alembic import op

revision = "ae51c90f273b"
down_revision = "8c4b1e7a2d93"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "developmentmessage",
        sa.Column("duration_seconds", sa.Float(), nullable=True),
    )
    op.create_check_constraint(
        "ck_developmentmessage_duration_nonnegative",
        "developmentmessage",
        "duration_seconds >= 0",
    )


def downgrade():
    op.drop_constraint(
        "ck_developmentmessage_duration_nonnegative",
        "developmentmessage",
        type_="check",
    )
    op.drop_column("developmentmessage", "duration_seconds")