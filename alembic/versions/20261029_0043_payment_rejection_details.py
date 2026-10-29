"""payment_rejection_details: glosa de rechazo por cobro/pago y canal (RJ-12, decision D3).

Solo crea una tabla nueva: no toca datos existentes. Sin datos personales. La aplica el usuario.

Revision ID: 20261029_0043
Revises: 20261029_0042
Create Date: 2026-10-29 14:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20261029_0043"
down_revision = "20261029_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_rejection_details",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("charge_external_id", sa.String(255)),
        sa.Column("payment_external_id", sa.String(255)),
        sa.Column("subscription_external_id", sa.String(255)),
        sa.Column("code", sa.String(100), nullable=False, server_default=""),
        sa.Column("reason", sa.Text()),
        sa.Column("acquirer_code", sa.String(100)),
        sa.Column("doc_url", sa.Text()),
        sa.Column("amount", sa.Numeric(18, 2)),
        sa.Column("rejected_at", sa.DateTime(timezone=True)),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("capture_source", sa.String(30), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "capture_source IN ('api_charges', 'api_payment', 'report_pat', 'toku_projection')",
            name="ck_prd_capture_source",
        ),
        sa.CheckConstraint(
            "charge_external_id IS NOT NULL OR payment_external_id IS NOT NULL", name="ck_prd_charge_or_payment"
        ),
    )
    op.create_index(
        "uq_prd_dedupe",
        "payment_rejection_details",
        [
            "source",
            sa.text("coalesce(charge_external_id, '')"),
            sa.text("coalesce(payment_external_id, '')"),
            "code",
        ],
        unique=True,
    )
    op.create_index("ix_prd_source_charge", "payment_rejection_details", ["source", "charge_external_id"])
    op.create_index("ix_prd_source_payment", "payment_rejection_details", ["source", "payment_external_id"])
    op.create_index("ix_prd_source_subscription", "payment_rejection_details", ["source", "subscription_external_id"])
    op.create_index("ix_prd_checked_at", "payment_rejection_details", ["checked_at"])


def downgrade() -> None:
    op.drop_table("payment_rejection_details")
