"""Add channels_failed column to etl_runs.

Stores the list of channels that encountered errors during a sync run,
enabling the retry job to re-attempt only the failed channels.

Revision ID: 20261021_0035
Revises: 20261020_0034
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261021_0035"
down_revision = "20261020_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "etl_runs",
        sa.Column("channels_failed", postgresql.ARRAY(postgresql.VARCHAR()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("etl_runs", "channels_failed")
