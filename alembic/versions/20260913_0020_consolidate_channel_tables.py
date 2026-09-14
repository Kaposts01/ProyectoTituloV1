"""Use channel prefixes and preserve VirtualPOS account identity.

Revision ID: 20260913_0020
Revises: 20260912_0019
"""

import sqlalchemy as sa

from alembic import op

revision = "20260913_0020"
down_revision = "20260912_0019"
branch_labels = None
depends_on = None


def _rename_index(old: str, new: str) -> None:
    op.execute(sa.text(f"ALTER INDEX IF EXISTS {old} RENAME TO {new}"))


def upgrade() -> None:
    table_names = {
        "toku_customers": "tk_customers", "toku_subscriptions": "tk_subscriptions",
        "toku_invoices": "tk_invoices", "toku_transactions": "tk_transactions",
        "toku_payment_methods": "tk_payment_methods", "payku_clients": "p_clients",
        "payku_plans": "p_plans", "payku_subscriptions": "p_subscriptions",
        "payku_transactions": "p_transactions",
    }
    for old, new in table_names.items():
        op.rename_table(old, new)

    constraint_names = {
        "tk_customers": ("uq_toku_customer_external_id", "uq_tk_customer_external_id"),
        "tk_subscriptions": ("uq_toku_subscription_external_id", "uq_tk_subscription_external_id"),
        "tk_invoices": ("uq_toku_invoice_external_id", "uq_tk_invoice_external_id"),
        "tk_transactions": ("uq_toku_transaction_external_id", "uq_tk_transaction_external_id"),
        "tk_payment_methods": ("uq_toku_payment_method_external_id", "uq_tk_payment_method_external_id"),
        "p_clients": ("uq_payku_client_external_id", "uq_p_client_external_id"),
        "p_plans": ("uq_payku_plan_external_id", "uq_p_plan_external_id"),
        "p_subscriptions": ("uq_payku_subscription_external_id", "uq_p_subscription_external_id"),
        "p_transactions": ("uq_payku_transaction_external_id", "uq_p_transaction_external_id"),
    }
    for table, (old, new) in constraint_names.items():
        op.execute(sa.text(f"ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new}"))

    for old, new in table_names.items():
        _rename_index(f"ix_{old}_external_id", f"ix_{new}_external_id")
        for suffix in ("email", "status", "government_id", "customer_id", "subscription_id", "due_date", "payment_method_id", "created_at_api", "name", "rut", "plan_id"):
            _rename_index(f"ix_{old}_{suffix}", f"ix_{new}_{suffix}")

    vp_tables = {
        "vp_clients": "client", "vp_plans": "plan", "vp_subscriptions": "subscription",
        "vp_charges": "charge", "vp_payments": "payment",
    }
    bind = op.get_bind()
    for table, label in vp_tables.items():
        if bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one():
            raise RuntimeError(f"{table} contains rows without VirtualPOS platform identity; classify them before upgrade.")
        op.add_column(table, sa.Column("platform", sa.String(length=50), nullable=False))
        op.drop_constraint(f"uq_vp_{label}_external_id", table, type_="unique")
        op.create_unique_constraint(f"uq_vp_{label}_platform_external_id", table, ["platform", "external_id"])
        op.create_index(f"ix_{table}_platform", table, ["platform"])


def downgrade() -> None:
    raise RuntimeError("Channel-table consolidation is intentionally not downgraded after import.")
