"""Add stg_toku_webhook_events staging table for incoming Toku webhooks.

Revision ID: 20261020_0029
Revises: 20261007_0028
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261020_0029"
down_revision = "20261007_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stg_toku_webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("toku_event_id", sa.String(100), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("signature_t", sa.String(20), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("source_ip", sa.String(45), nullable=True),
        sa.Column("process_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.UniqueConstraint("toku_event_id", name="uq_stg_toku_webhook_toku_event_id"),
    )
    op.create_index("ix_stg_toku_webhook_events_toku_event_id", "stg_toku_webhook_events", ["toku_event_id"])
    op.create_index("ix_stg_toku_webhook_events_event_type", "stg_toku_webhook_events", ["event_type"])
    op.create_index("ix_stg_toku_webhook_events_process_status", "stg_toku_webhook_events", ["process_status"])


def downgrade() -> None:
    op.drop_table("stg_toku_webhook_events")
