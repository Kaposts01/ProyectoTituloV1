"""Store local subscription RUT relationships and recurring amounts.

Revision ID: 20260911_0008
Revises: 20260911_0007
Create Date: 2026-09-11 15:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20260911_0008"
down_revision = "20260911_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("client_social_id", sa.String(length=50), nullable=True))
    op.create_index("ix_subscriptions_client_social_id", "subscriptions", ["client_social_id"])
    op.add_column("subscriptions", sa.Column("amount", sa.String(length=50), nullable=True))
    op.add_column("subscriptions", sa.Column("currency", sa.String(length=10), nullable=True))
    op.execute(
        """
        UPDATE subscriptions
        SET client_social_id = NULLIF(raw_payload -> 'client' ->> 'social_id', ''),
            amount = NULLIF(raw_payload ->> 'amount', ''),
            currency = NULLIF(raw_payload ->> 'currency', '')
        WHERE raw_payload IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "currency")
    op.drop_column("subscriptions", "amount")
    op.drop_index("ix_subscriptions_client_social_id", table_name="subscriptions")
    op.drop_column("subscriptions", "client_social_id")
