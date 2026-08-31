"""Create canonical plans from VirtualPOS staging.

Revision ID: 20260830_0004
Revises: 20260830_0003
Create Date: 2026-08-30 03:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260830_0004"
down_revision = "20260830_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("source_record_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("name", sa.String(length=255)),
        sa.Column("description", sa.String(length=2000)),
        sa.Column("amount", sa.String(length=50)),
        sa.Column("currency", sa.String(length=10)),
        sa.Column("plan_type", sa.String(length=50)),
        sa.Column("is_active", sa.String(length=10)),
        sa.Column("status", sa.String(length=50)),
        sa.ForeignKeyConstraint(["source_record_id"], ["source_records.id"]),
        sa.UniqueConstraint("source", "external_id", name="uq_plan_source_external_id"),
    )
    op.create_index("ix_plans_name", "plans", ["name"])
    op.create_index("ix_plans_is_active", "plans", ["is_active"])
    op.create_index("ix_plans_status", "plans", ["status"])


def downgrade() -> None:
    op.drop_table("plans")
