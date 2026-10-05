"""Create Toku payments and the Payku columns missing from the chain.

Revision ID: 20260930_0022b
Revises: 20260923_0022
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260930_0022b"
down_revision = "20260923_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tk_payments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("customer_id", sa.String(length=255), nullable=True),
        sa.Column("invoice_id", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.String(length=50), nullable=True),
        sa.Column("transaction_date", sa.String(length=50), nullable=True),
        sa.Column("government_id", sa.String(length=50), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id", name="uq_tk_payment_external_id"),
    )
    op.create_index("ix_tk_payments_external_id", "tk_payments", ["external_id"])
    op.create_index("ix_tk_payments_customer_id", "tk_payments", ["customer_id"])
    op.create_index("ix_tk_payments_invoice_id", "tk_payments", ["invoice_id"])
    op.create_index("ix_tk_payments_transaction_date", "tk_payments", ["transaction_date"])
    op.create_index("ix_tk_payments_government_id", "tk_payments", ["government_id"])

    op.add_column("p_plans", sa.Column("code", sa.String(length=100), nullable=True))
    op.add_column("p_plans", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("p_plans", sa.Column("total_suscription", sa.Integer(), nullable=True))
    op.add_column("p_plans", sa.Column("total_suscription_active", sa.Integer(), nullable=True))

    op.add_column("p_subscriptions", sa.Column("last_status_current_payment", sa.String(length=50), nullable=True))
    op.add_column("p_subscriptions", sa.Column("start_date", sa.String(length=50), nullable=True))
    op.add_column("p_subscriptions", sa.Column("end_date", sa.String(length=50), nullable=True))

    op.alter_column(
        "tch_tipos_mandato",
        "codigo",
        existing_type=sa.String(length=10),
        type_=sa.String(length=50),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "tch_tipos_mandato",
        "codigo",
        existing_type=sa.String(length=50),
        type_=sa.String(length=10),
        existing_nullable=False,
    )

    op.drop_column("p_subscriptions", "end_date")
    op.drop_column("p_subscriptions", "start_date")
    op.drop_column("p_subscriptions", "last_status_current_payment")

    op.drop_column("p_plans", "total_suscription_active")
    op.drop_column("p_plans", "total_suscription")
    op.drop_column("p_plans", "description")
    op.drop_column("p_plans", "code")

    op.drop_index("ix_tk_payments_government_id", table_name="tk_payments")
    op.drop_index("ix_tk_payments_transaction_date", table_name="tk_payments")
    op.drop_index("ix_tk_payments_invoice_id", table_name="tk_payments")
    op.drop_index("ix_tk_payments_customer_id", table_name="tk_payments")
    op.drop_index("ix_tk_payments_external_id", table_name="tk_payments")
    op.drop_table("tk_payments")
