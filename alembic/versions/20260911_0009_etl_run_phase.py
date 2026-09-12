"""Add phase column to etl_runs.

Revision ID: 20260911_0009
Revises: 20260911_0008
Create Date: 2026-09-11 16:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20260911_0009"
down_revision = "20260911_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("etl_runs", sa.Column("phase", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("etl_runs", "phase")
