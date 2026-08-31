"""Create canonical CRM entities from VirtualPOS staging.

Revision ID: 20260830_0002
Revises: 20260830_0001
Create Date: 2026-08-30 01:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260830_0002"
down_revision = "20260830_0001"
branch_labels = None
depends_on = None


def _canonical_columns() -> list[sa.Column]:
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("source_record_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["source_record_id"], ["source_records.id"]),
    ]


def upgrade() -> None:
    op.create_table(
        "clients",
        *_canonical_columns(),
        sa.Column("first_name", sa.String(length=255)),
        sa.Column("last_name", sa.String(length=255)),
        sa.Column("email", sa.String(length=320)),
        sa.Column("phone_number", sa.String(length=50)),
        sa.Column("status", sa.String(length=50)),
        sa.UniqueConstraint("source", "external_id", name="uq_client_source_external_id"),
    )
    op.create_index("ix_clients_email", "clients", ["email"])
    op.create_index("ix_clients_status", "clients", ["status"])
    op.create_table(
        "subscriptions",
        *_canonical_columns(),
        sa.Column("client_external_id", sa.String(length=255)),
        sa.Column("plan_external_id", sa.String(length=255)),
        sa.Column("service_id", sa.String(length=255)),
        sa.Column("status", sa.String(length=50)),
        sa.Column("automatic_renewal", sa.String(length=10)),
        sa.UniqueConstraint("source", "external_id", name="uq_subscription_source_external_id"),
    )
    for column in ("client_external_id", "plan_external_id", "service_id", "status"):
        op.create_index(f"ix_subscriptions_{column}", "subscriptions", [column])
    op.create_table(
        "charges",
        *_canonical_columns(),
        sa.Column("subscription_external_id", sa.String(length=255)),
        sa.Column("amount", sa.String(length=50)),
        sa.Column("currency", sa.String(length=10)),
        sa.Column("status", sa.String(length=50)),
        sa.Column("charge_date", sa.String(length=50)),
        sa.UniqueConstraint("source", "external_id", name="uq_charge_source_external_id"),
    )
    op.create_index("ix_charges_subscription_external_id", "charges", ["subscription_external_id"])
    op.create_index("ix_charges_status", "charges", ["status"])
    op.create_table(
        "payments",
        *_canonical_columns(),
        sa.Column("charge_external_id", sa.String(length=255)),
        sa.Column("amount", sa.String(length=50)),
        sa.Column("currency", sa.String(length=10)),
        sa.Column("status", sa.String(length=50)),
        sa.UniqueConstraint("source", "external_id", name="uq_payment_source_external_id"),
    )
    op.create_index("ix_payments_charge_external_id", "payments", ["charge_external_id"])
    op.create_index("ix_payments_status", "payments", ["status"])


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("charges")
    op.drop_table("subscriptions")
    op.drop_table("clients")
