"""Add stg_vpos_webhook_events and stg_payku_webhook_events staging tables.

Revision ID: 20261020_0030
Revises: 20261020_0029
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261020_0030"
down_revision = "20261020_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stg_vpos_webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("event_kind", sa.String(30), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("source_ip", sa.String(45), nullable=True),
        sa.Column("signature_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("process_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_stg_vpos_webhook_events_event_kind", "stg_vpos_webhook_events", ["event_kind"])
    op.create_index("ix_stg_vpos_webhook_events_process_status", "stg_vpos_webhook_events", ["process_status"])

    op.create_table(
        "stg_payku_webhook_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("event_kind", sa.String(30), nullable=False),
        sa.Column("payku_resource_id", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_body", sa.Text(), nullable=False),
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_ip", sa.String(45), nullable=True),
        sa.Column("process_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_stg_payku_webhook_events_event_kind", "stg_payku_webhook_events", ["event_kind"])
    op.create_index("ix_stg_payku_webhook_events_process_status", "stg_payku_webhook_events", ["process_status"])


def downgrade() -> None:
    op.drop_table("stg_vpos_webhook_events")
    op.drop_table("stg_payku_webhook_events")
