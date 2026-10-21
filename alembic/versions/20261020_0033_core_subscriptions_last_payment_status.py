"""Add last_payment_status to core_subscriptions (PK-2 gap fix).

Revision ID: 20261020_0033
Revises: 20261020_0032
"""

import sqlalchemy as sa

from alembic import op

revision = "20261020_0033"
down_revision = "20261020_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "core_subscriptions",
        sa.Column("last_payment_status", sa.String(100), nullable=True),
    )
    op.create_index("ix_core_subscriptions_last_payment_status", "core_subscriptions", ["last_payment_status"])


def downgrade() -> None:
    op.drop_index("ix_core_subscriptions_last_payment_status", table_name="core_subscriptions")
    op.drop_column("core_subscriptions", "last_payment_status")
