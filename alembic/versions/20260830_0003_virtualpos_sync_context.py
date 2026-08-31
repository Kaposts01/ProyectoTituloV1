"""Preserve VirtualPOS synchronization context and payment identifiers.

Revision ID: 20260830_0003
Revises: 20260830_0002
Create Date: 2026-08-30 02:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260830_0003"
down_revision = "20260830_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("source_records", sa.Column("sync_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.execute(
        """
        UPDATE source_records
        SET external_id = payload -> 'order' ->> 'uuid'
        WHERE source = 'virtualpos'
          AND resource_type = 'payment'
          AND jsonb_typeof(payload -> 'order') = 'object'
          AND payload -> 'order' ? 'uuid'
        """
    )
    op.execute(
        """
        UPDATE payments
        SET external_id = source_records.external_id
        FROM source_records
        WHERE payments.source_record_id = source_records.id
          AND payments.source = 'virtualpos'
        """
    )


def downgrade() -> None:
    op.drop_column("source_records", "sync_context")
