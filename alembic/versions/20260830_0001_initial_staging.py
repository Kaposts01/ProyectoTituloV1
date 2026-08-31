"""Create VirtualPOS staging and synchronization tables.

Revision ID: 20260830_0001
Revises:
Create Date: 2026-08-30 00:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260830_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_sync_runs_source", "sync_runs", ["source"])
    op.create_index("ix_sync_runs_status", "sync_runs", ["status"])
    op.create_table(
        "source_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("source", "resource_type", "external_id", name="uq_source_record"),
    )
    op.create_index("ix_source_records_source", "source_records", ["source"])
    op.create_index("ix_source_records_resource_type", "source_records", ["resource_type"])


def downgrade() -> None:
    op.drop_index("ix_source_records_resource_type", table_name="source_records")
    op.drop_index("ix_source_records_source", table_name="source_records")
    op.drop_table("source_records")
    op.drop_index("ix_sync_runs_status", table_name="sync_runs")
    op.drop_index("ix_sync_runs_source", table_name="sync_runs")
    op.drop_table("sync_runs")
