"""Toku downloaded-report tables (tk_report_*), without personal data.

Revision ID: 20261028_0039
Revises: 20261028_0038
Create Date: 2026-10-28 13:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20261028_0039"
down_revision = "20261028_0038"
branch_labels = None
depends_on = None

REPORT_TYPES = "('productos', 'intentos', 'medios_pago', 'deudas', 'inscripciones', 'clientes', 'pagos')"
FILE_STATUSES = "('running', 'completed', 'failed')"
CODE_SEVERITIES = "('SU', 'TE', 'PE', 'UE')"
SEVERITIES = "('SU', 'TE', 'PE', 'UE', 'UNKNOWN')"

TABLES_DOWN = (
    "tk_report_inscriptions",
    "tk_report_debts",
    "tk_report_attempts",
    "tk_report_payment_methods",
    "tk_report_products",
    "tk_report_response_codes",
    "tk_report_files",
)


def _id() -> sa.Column:
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _tz(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _file_fk() -> sa.Column:
    return sa.Column("last_file_id", UUID(as_uuid=True), sa.ForeignKey("tk_report_files.id"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "tk_report_files",
        _id(),
        sa.Column("report_type", sa.String(30), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        _tz("generated_at"),
        sa.Column("window_start", sa.Date()),
        sa.Column("window_end", sa.Date()),
        sa.Column("rows_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("error_label", sa.String(100)),
        sa.Column("etl_run_id", UUID(as_uuid=True), sa.ForeignKey("etl_runs.id")),
        sa.Column("uploaded_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        _ts("started_at"),
        _tz("finished_at"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("report_type", "file_sha256", name="uq_tk_report_files_type_sha"),
        sa.CheckConstraint(f"report_type IN {REPORT_TYPES}", name="ck_tkr_files_report_type"),
        sa.CheckConstraint(f"status IN {FILE_STATUSES}", name="ck_tkr_files_status"),
        sa.CheckConstraint("file_sha256 ~ '^[0-9a-f]{64}$'", name="ck_tkr_files_sha256"),
        sa.CheckConstraint(
            "rows_total >= 0 AND rows_new >= 0 AND rows_updated >= 0 AND rows_skipped >= 0",
            name="ck_tkr_files_rows",
        ),
    )

    op.create_table(
        "tk_report_response_codes",
        _id(),
        sa.Column("code", sa.String(4), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("source_file_id", UUID(as_uuid=True), sa.ForeignKey("tk_report_files.id")),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("code", name="uq_tk_report_response_codes_code"),
        sa.CheckConstraint("code ~ '^[0-9]{4}$'", name="ck_tkr_codes_code"),
        sa.CheckConstraint(f"severity IN {CODE_SEVERITIES}", name="ck_tkr_codes_severity"),
    )

    op.create_table(
        "tk_report_products",
        _id(),
        sa.Column("subscription_external_id", sa.String(255), nullable=False),
        sa.Column("product_key_hash", sa.String(64), nullable=False),
        sa.Column("customer_external_id", sa.String(255), nullable=False),
        sa.Column("payment_method_external_id", sa.String(255)),
        sa.Column("payment_method_status", sa.String(100)),
        sa.Column("payment_processor", sa.String(100)),
        sa.Column("amount", sa.Numeric(14, 2)),
        sa.Column("due_day", sa.SmallInteger()),
        sa.Column("is_recurring", sa.Boolean()),
        _tz("created_at_source"),
        _tz("deleted_at_source"),
        _tz("source_generated_at", nullable=False),
        _file_fk(),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("subscription_external_id", name="uq_tk_report_products_subscription"),
        sa.CheckConstraint("due_day IS NULL OR due_day BETWEEN 1 AND 31", name="ck_tkr_products_due_day"),
    )
    op.create_index("ix_tk_report_products_product_key_hash", "tk_report_products", ["product_key_hash"])
    op.create_index("ix_tk_report_products_customer", "tk_report_products", ["customer_external_id"])
    op.create_index("ix_tk_report_products_payment_method", "tk_report_products", ["payment_method_external_id"])

    op.create_table(
        "tk_report_payment_methods",
        _id(),
        sa.Column("payment_method_external_id", sa.String(255), nullable=False),
        sa.Column("product_key_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(100)),
        sa.Column("card_type", sa.String(50)),
        sa.Column("card_brand", sa.String(50)),
        sa.Column("issuer_bank", sa.String(100)),
        sa.Column("processor", sa.String(100)),
        sa.Column("last_response_code", sa.String(10)),
        sa.Column("last_response_message", sa.Text()),
        _tz("deleted_at_source"),
        _tz("created_at_source"),
        _tz("source_generated_at", nullable=False),
        _file_fk(),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint(
            "payment_method_external_id", "product_key_hash", name="uq_tk_report_payment_methods_pm_product"
        ),
    )
    op.create_index("ix_tk_report_payment_methods_pm", "tk_report_payment_methods", ["payment_method_external_id"])
    op.create_index(
        "ix_tk_report_payment_methods_product_key_hash", "tk_report_payment_methods", ["product_key_hash"]
    )

    op.create_table(
        "tk_report_attempts",
        _id(),
        sa.Column("attempt_external_id", sa.String(255), nullable=False),
        sa.Column("debt_external_id", sa.String(255), nullable=False),
        sa.Column("customer_external_id", sa.String(255), nullable=False),
        sa.Column("subscription_external_id", sa.String(255)),
        sa.Column("product_key_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("due_date", sa.Date()),
        _tz("attempted_at"),
        sa.Column("status", sa.String(50)),
        sa.Column("response_code", sa.String(4)),
        sa.Column("severity", sa.String(10)),
        sa.Column("amount", sa.Numeric(14, 2)),
        sa.Column("processor", sa.String(100)),
        sa.Column("has_mandate", sa.Boolean()),
        _tz("deleted_at_source"),
        _tz("source_generated_at", nullable=False),
        _file_fk(),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("attempt_external_id", name="uq_tk_report_attempts_attempt"),
        sa.CheckConstraint(f"severity IS NULL OR severity IN {SEVERITIES}", name="ck_tkr_attempts_severity"),
    )
    op.create_index("ix_tk_report_attempts_debt", "tk_report_attempts", ["debt_external_id"])
    op.create_index("ix_tk_report_attempts_customer", "tk_report_attempts", ["customer_external_id"])
    op.create_index("ix_tk_report_attempts_subscription", "tk_report_attempts", ["subscription_external_id"])
    op.create_index("ix_tk_report_attempts_product_key_hash", "tk_report_attempts", ["product_key_hash"])
    op.create_index(
        "ix_tk_report_attempts_sub_attempted", "tk_report_attempts", ["subscription_external_id", "attempted_at"]
    )

    op.create_table(
        "tk_report_debts",
        _id(),
        sa.Column("debt_external_id", sa.String(255), nullable=False),
        sa.Column("subscription_external_id", sa.String(255)),
        sa.Column("product_key_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("customer_external_id", sa.String(255)),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("paid", sa.Boolean(), nullable=False),
        sa.Column("voided", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(50)),
        _tz("deleted_at_source"),
        _tz("source_generated_at", nullable=False),
        _file_fk(),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("debt_external_id", name="uq_tk_report_debts_debt"),
    )
    op.create_index("ix_tk_report_debts_subscription", "tk_report_debts", ["subscription_external_id"])
    op.create_index("ix_tk_report_debts_product_key_hash", "tk_report_debts", ["product_key_hash"])

    op.create_table(
        "tk_report_inscriptions",
        _id(),
        sa.Column("inscription_external_id", sa.String(255), nullable=False),
        sa.Column("payment_method_external_id", sa.String(255)),
        sa.Column("subscription_external_id", sa.String(255)),
        sa.Column("transaction_status", sa.String(100)),
        sa.Column("response_code_full", sa.String(30)),
        sa.Column("severity", sa.String(10)),
        sa.Column("payment_method_status", sa.String(100)),
        _tz("last_attempt_at"),
        sa.Column("last_attempt_status", sa.String(100)),
        _tz("deleted_at_source"),
        _tz("source_generated_at", nullable=False),
        _file_fk(),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("inscription_external_id", name="uq_tk_report_inscriptions_inscription"),
        sa.CheckConstraint(f"severity IS NULL OR severity IN {SEVERITIES}", name="ck_tkr_inscriptions_severity"),
    )
    op.create_index("ix_tk_report_inscriptions_subscription", "tk_report_inscriptions", ["subscription_external_id"])


def downgrade() -> None:
    for table in TABLES_DOWN:
        op.drop_table(table)
