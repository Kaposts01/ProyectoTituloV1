"""Create per-channel typed tables for VirtualPOS, Toku and Payku.

Revision ID: 20260912_0017
Revises: 20260912_0016
Create Date: 2026-09-12 22:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260912_0017"
down_revision = "20260912_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── VirtualPOS ────────────────────────────────────────────────────────────

    op.create_table(
        "vp_clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("first_name", sa.String(255), nullable=True),
        sa.Column("last_name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone_number", sa.String(50), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("social_id", sa.String(50), nullable=True),
        sa.Column("gender_id", sa.String(50), nullable=True),
        sa.Column("birth_date", sa.String(50), nullable=True),
        sa.Column("provider_created_at", sa.String(50), nullable=True),
        sa.Column("private_note", sa.String(2000), nullable=True),
        sa.Column("cards", postgresql.JSONB(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("external_id", name="uq_vp_client_external_id"),
    )
    op.create_index("ix_vp_clients_external_id", "vp_clients", ["external_id"])
    op.create_index("ix_vp_clients_email", "vp_clients", ["email"])
    op.create_index("ix_vp_clients_status", "vp_clients", ["status"])
    op.create_index("ix_vp_clients_social_id", "vp_clients", ["social_id"])

    op.create_table(
        "vp_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column("amount", sa.String(50), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("plan_type", sa.String(50), nullable=True),
        sa.Column("is_active", sa.String(10), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("external_id", name="uq_vp_plan_external_id"),
    )
    op.create_index("ix_vp_plans_external_id", "vp_plans", ["external_id"])
    op.create_index("ix_vp_plans_name", "vp_plans", ["name"])
    op.create_index("ix_vp_plans_status", "vp_plans", ["status"])
    op.create_index("ix_vp_plans_is_active", "vp_plans", ["is_active"])

    op.create_table(
        "vp_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("client_external_id", sa.String(255), nullable=True),
        sa.Column("client_social_id", sa.String(50), nullable=True),
        sa.Column("plan_external_id", sa.String(255), nullable=True),
        sa.Column("service_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("automatic_renewal", sa.String(10), nullable=True),
        sa.Column("suscription_date", sa.String(50), nullable=True),
        sa.Column("canceled_at", sa.String(50), nullable=True),
        sa.Column("amount", sa.String(50), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("external_id", name="uq_vp_subscription_external_id"),
    )
    op.create_index("ix_vp_subscriptions_external_id", "vp_subscriptions", ["external_id"])
    op.create_index("ix_vp_subscriptions_client_external_id", "vp_subscriptions", ["client_external_id"])
    op.create_index("ix_vp_subscriptions_client_social_id", "vp_subscriptions", ["client_social_id"])
    op.create_index("ix_vp_subscriptions_plan_external_id", "vp_subscriptions", ["plan_external_id"])
    op.create_index("ix_vp_subscriptions_status", "vp_subscriptions", ["status"])

    op.create_table(
        "vp_charges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("subscription_external_id", sa.String(255), nullable=True),
        sa.Column("client_external_id", sa.String(255), nullable=True),
        sa.Column("amount", sa.String(50), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("charge_date", sa.String(50), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("external_id", name="uq_vp_charge_external_id"),
    )
    op.create_index("ix_vp_charges_external_id", "vp_charges", ["external_id"])
    op.create_index("ix_vp_charges_subscription_external_id", "vp_charges", ["subscription_external_id"])
    op.create_index("ix_vp_charges_client_external_id", "vp_charges", ["client_external_id"])
    op.create_index("ix_vp_charges_status", "vp_charges", ["status"])
    op.create_index("ix_vp_charges_charge_date", "vp_charges", ["charge_date"])

    op.create_table(
        "vp_payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("charge_external_id", sa.String(255), nullable=True),
        sa.Column("client_external_id", sa.String(255), nullable=True),
        sa.Column("amount", sa.String(50), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("payment_date", sa.String(50), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("external_id", name="uq_vp_payment_external_id"),
    )
    op.create_index("ix_vp_payments_external_id", "vp_payments", ["external_id"])
    op.create_index("ix_vp_payments_charge_external_id", "vp_payments", ["charge_external_id"])
    op.create_index("ix_vp_payments_status", "vp_payments", ["status"])
    op.create_index("ix_vp_payments_payment_date", "vp_payments", ["payment_date"])

    # ── Toku ─────────────────────────────────────────────────────────────────

    op.create_table(
        "toku_customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone_number", sa.String(50), nullable=True),
        sa.Column("government_id", sa.String(50), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("external_id", name="uq_toku_customer_external_id"),
    )
    op.create_index("ix_toku_customers_external_id", "toku_customers", ["external_id"])
    op.create_index("ix_toku_customers_email", "toku_customers", ["email"])
    op.create_index("ix_toku_customers_government_id", "toku_customers", ["government_id"])
    op.create_index("ix_toku_customers_status", "toku_customers", ["status"])

    op.create_table(
        "toku_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("customer_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("amount", sa.String(50), nullable=True),
        sa.Column("currency_code", sa.String(10), nullable=True),
        sa.Column("anchor", sa.String(50), nullable=True),
        sa.Column("end_date", sa.String(50), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("external_id", name="uq_toku_subscription_external_id"),
    )
    op.create_index("ix_toku_subscriptions_external_id", "toku_subscriptions", ["external_id"])
    op.create_index("ix_toku_subscriptions_customer_id", "toku_subscriptions", ["customer_id"])
    op.create_index("ix_toku_subscriptions_status", "toku_subscriptions", ["status"])

    op.create_table(
        "toku_invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("subscription_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("amount", sa.String(50), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("due_date", sa.String(50), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("external_id", name="uq_toku_invoice_external_id"),
    )
    op.create_index("ix_toku_invoices_external_id", "toku_invoices", ["external_id"])
    op.create_index("ix_toku_invoices_subscription_id", "toku_invoices", ["subscription_id"])
    op.create_index("ix_toku_invoices_status", "toku_invoices", ["status"])
    op.create_index("ix_toku_invoices_due_date", "toku_invoices", ["due_date"])

    op.create_table(
        "toku_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("amount", sa.String(50), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("payment_method_id", sa.String(255), nullable=True),
        sa.Column("created_at_api", sa.String(50), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("external_id", name="uq_toku_transaction_external_id"),
    )
    op.create_index("ix_toku_transactions_external_id", "toku_transactions", ["external_id"])
    op.create_index("ix_toku_transactions_status", "toku_transactions", ["status"])
    op.create_index("ix_toku_transactions_payment_method_id", "toku_transactions", ["payment_method_id"])
    op.create_index("ix_toku_transactions_created_at_api", "toku_transactions", ["created_at_api"])

    op.create_table(
        "toku_payment_methods",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("customer_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("external_id", name="uq_toku_payment_method_external_id"),
    )
    op.create_index("ix_toku_payment_methods_external_id", "toku_payment_methods", ["external_id"])
    op.create_index("ix_toku_payment_methods_customer_id", "toku_payment_methods", ["customer_id"])
    op.create_index("ix_toku_payment_methods_status", "toku_payment_methods", ["status"])

    # ── Payku ─────────────────────────────────────────────────────────────────

    op.create_table(
        "payku_clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("rut", sa.String(20), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("external_id", name="uq_payku_client_external_id"),
    )
    op.create_index("ix_payku_clients_external_id", "payku_clients", ["external_id"])
    op.create_index("ix_payku_clients_email", "payku_clients", ["email"])
    op.create_index("ix_payku_clients_rut", "payku_clients", ["rut"])
    op.create_index("ix_payku_clients_status", "payku_clients", ["status"])

    op.create_table(
        "payku_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("amount", sa.String(50), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("external_id", name="uq_payku_plan_external_id"),
    )
    op.create_index("ix_payku_plans_external_id", "payku_plans", ["external_id"])
    op.create_index("ix_payku_plans_name", "payku_plans", ["name"])
    op.create_index("ix_payku_plans_status", "payku_plans", ["status"])

    op.create_table(
        "payku_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=True),
        sa.Column("plan_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("amount", sa.String(50), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("external_id", name="uq_payku_subscription_external_id"),
    )
    op.create_index("ix_payku_subscriptions_external_id", "payku_subscriptions", ["external_id"])
    op.create_index("ix_payku_subscriptions_client_id", "payku_subscriptions", ["client_id"])
    op.create_index("ix_payku_subscriptions_plan_id", "payku_subscriptions", ["plan_id"])
    op.create_index("ix_payku_subscriptions_status", "payku_subscriptions", ["status"])

    op.create_table(
        "payku_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("subscription_id", sa.String(255), nullable=True),
        sa.Column("amount", sa.String(50), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("created_at_api", sa.String(50), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("external_id", name="uq_payku_transaction_external_id"),
    )
    op.create_index("ix_payku_transactions_external_id", "payku_transactions", ["external_id"])
    op.create_index("ix_payku_transactions_subscription_id", "payku_transactions", ["subscription_id"])
    op.create_index("ix_payku_transactions_status", "payku_transactions", ["status"])
    op.create_index("ix_payku_transactions_created_at_api", "payku_transactions", ["created_at_api"])


def downgrade() -> None:
    for table in [
        "payku_transactions", "payku_subscriptions", "payku_plans", "payku_clients",
        "toku_payment_methods", "toku_transactions", "toku_invoices", "toku_subscriptions", "toku_customers",
        "vp_payments", "vp_charges", "vp_subscriptions", "vp_plans", "vp_clients",
    ]:
        op.drop_table(table)
