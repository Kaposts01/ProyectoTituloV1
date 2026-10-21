"""Add source_status to core_charges (TK-2 gap fix).

Revision ID: 20261020_0032
Revises: 20261020_0031
"""

import sqlalchemy as sa

from alembic import op

revision = "20261020_0032"
down_revision = "20261020_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "core_charges",
        sa.Column("source_status", sa.String(100), nullable=True),
    )
    op.create_index("ix_core_charges_source_status", "core_charges", ["source_status"])


def downgrade() -> None:
    op.drop_index("ix_core_charges_source_status", table_name="core_charges")
    op.drop_column("core_charges", "source_status")
