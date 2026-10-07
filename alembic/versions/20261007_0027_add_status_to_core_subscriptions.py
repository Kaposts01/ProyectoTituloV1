"""Add status column to core_subscriptions.

Revision ID: 20261007_0027
Revises: 20261007_0026
"""

import sqlalchemy as sa

from alembic import op

revision = "20261007_0027"
down_revision = "20261007_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("core_subscriptions", sa.Column("status", sa.String(50), nullable=True))
    op.create_index("ix_core_subscriptions_status", "core_subscriptions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_core_subscriptions_status", table_name="core_subscriptions")
    op.drop_column("core_subscriptions", "status")
