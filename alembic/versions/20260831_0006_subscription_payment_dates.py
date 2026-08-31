"""Add canonical subscription and payment dates.

Revision ID: 20260831_0006
Revises: 20260830_0005
Create Date: 2026-08-31 12:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20260831_0006"
down_revision = "20260830_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("suscription_date", sa.String(length=50), nullable=True))
    op.add_column("subscriptions", sa.Column("canceled_at", sa.String(length=50), nullable=True))
    op.add_column("payments", sa.Column("payment_date", sa.String(length=50), nullable=True))
    op.execute(
        """
        UPDATE subscriptions AS subscription
        SET suscription_date = NULLIF(source.payload ->> 'suscription_date', ''),
            canceled_at = NULLIF(source.payload ->> 'canceled_at', '')
        FROM source_records AS source
        WHERE subscription.source_record_id = source.id
        """
    )
    op.execute(
        """
        UPDATE payments AS payment
        SET payment_date = COALESCE(
            NULLIF(source.payload ->> 'payment_date', ''),
            NULLIF(source.payload -> 'order' ->> 'authorized_at', ''),
            NULLIF(source.payload -> 'order' ->> 'created_at', '')
        )
        FROM source_records AS source
        WHERE payment.source_record_id = source.id
        """
    )


def downgrade() -> None:
    op.drop_column("payments", "payment_date")
    op.drop_column("subscriptions", "canceled_at")
    op.drop_column("subscriptions", "suscription_date")
