"""Add canonical Toku payment methods and client relationships.

Revision ID: 20260911_0010
Revises: 20260911_0009
Create Date: 2026-09-11 16:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "20260911_0010"
down_revision = "20260911_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("charges", sa.Column("client_external_id", sa.String(length=255), nullable=True))
    op.create_index("ix_charges_client_external_id", "charges", ["client_external_id"])
    op.add_column("payments", sa.Column("client_external_id", sa.String(length=255), nullable=True))
    op.create_index("ix_payments_client_external_id", "payments", ["client_external_id"])
    op.create_table(
        "payment_methods",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("source_record_id", UUID(as_uuid=True), sa.ForeignKey("source_records.id"), unique=True),
        sa.Column("raw_payload", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("client_external_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.UniqueConstraint("source", "external_id", name="uq_payment_method_source_external_id"),
    )
    op.create_index("ix_payment_methods_client_external_id", "payment_methods", ["client_external_id"])
    op.create_index("ix_payment_methods_status", "payment_methods", ["status"])


def downgrade() -> None:
    op.drop_table("payment_methods")
    op.drop_index("ix_payments_client_external_id", table_name="payments")
    op.drop_column("payments", "client_external_id")
    op.drop_index("ix_charges_client_external_id", table_name="charges")
    op.drop_column("charges", "client_external_id")
