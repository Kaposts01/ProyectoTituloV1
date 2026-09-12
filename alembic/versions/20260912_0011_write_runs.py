"""Add durable records for provider write operations.

Revision ID: 20260912_0011
Revises: 20260911_0010
Create Date: 2026-09-12 12:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "20260912_0011"
down_revision = "20260911_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "write_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("resource_type", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("request_payload", JSONB, nullable=False),
        sa.Column("response_payload", JSONB, nullable=True),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_write_runs_source", "write_runs", ["source"])
    op.create_index("ix_write_runs_external_id", "write_runs", ["external_id"])
    op.create_index("ix_write_runs_status", "write_runs", ["status"])


def downgrade() -> None:
    op.drop_table("write_runs")
