"""Make core_charges.subscription_id nullable.

Charges without a matched parent subscription (e.g. VP charges whose
subscription_external_id has no Core counterpart) were silently skipped
during ETL. Making the column nullable lets the ETL persist them with
subscription_id=NULL instead of dropping them.

Revision ID: 20261020_0034
Revises: 20261020_0033
Create Date: 2026-10-20
"""

from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261020_0034"
down_revision = "20261020_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "core_charges",
        "subscription_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    # Rows with NULL subscription_id must be removed or backfilled before rolling back.
    op.execute("DELETE FROM core_charges WHERE subscription_id IS NULL")
    op.alter_column(
        "core_charges",
        "subscription_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
