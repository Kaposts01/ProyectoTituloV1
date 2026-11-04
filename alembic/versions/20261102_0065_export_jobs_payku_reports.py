"""export_jobs_payku_reports: exportaciones en segundo plano y reportes de Payku (EXP-06, PK-PAR-10, PK-PAR-11).

* EXP-06 (d114 b): tabla `export_jobs` (estado, filtros AUDITABLES sin PII, filas, archivo y caducidad).
* PK-PAR-10 (d115 b): tablas `p_report_files`, `p_report_transactions` y `p_report_settlements` para los reportes
  descargados del portal de Payku (sin nombre, correo, telefono ni 4 ultimos digitos).
* PK-PAR-11: columnas nuevas `p_transactions.commission`, `net_amount`, `payment_method`, `installment_number` y
  `p_subscriptions.next_charge_date` (todas NULL; las completa el importador de reportes).

Solo agrega (tablas y columnas nulas); no toca datos existentes. Reversible: el downgrade borra columnas y tablas. La
aplica el usuario (ningun agente corre Alembic contra `crm` ni `crm_sandbox`).

Revision ID: 20261102_0065
Revises: 20261102_0064
Create Date: 2026-11-02 18:30:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261102_0065"
down_revision = "20261102_0064"
branch_labels = None
depends_on = None


def _ts(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "export_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "requested_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("entity", sa.String(20), nullable=False),
        sa.Column("channel", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("include_pii", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("filters", postgresql.JSONB(), nullable=True),
        sa.Column("rows_estimated", sa.Integer(), nullable=True),
        sa.Column("rows_written", sa.Integer(), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("file_bytes", sa.BigInteger(), nullable=True),
        sa.Column("error_label", sa.String(100), nullable=True),
        _ts("created_at"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'expired')", name="ck_export_jobs_status"
        ),
    )
    op.create_index("ix_export_jobs_user_created", "export_jobs", ["requested_by_user_id", "created_at"])
    op.create_index("ix_export_jobs_status_expires", "export_jobs", ["status", "expires_at"])

    op.create_table(
        "p_report_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_type", sa.String(30), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("sheets", sa.String(255), nullable=True),
        sa.Column("rows_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("error_label", sa.String(100), nullable=True),
        sa.Column(
            "uploaded_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _ts("started_at"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _ts("created_at"),
        sa.UniqueConstraint("report_type", "file_sha256", name="uq_p_report_files_type_sha"),
        sa.CheckConstraint(
            "report_type IN ('transacciones', 'liquidaciones', 'suscripciones', 'consolidado')",
            name="ck_pkr_files_report_type",
        ),
        sa.CheckConstraint("status IN ('running', 'completed', 'failed')", name="ck_pkr_files_status"),
        sa.CheckConstraint("file_sha256 ~ '^[0-9a-f]{64}$'", name="ck_pkr_files_sha256"),
    )

    op.create_table(
        "p_report_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("row_key", sa.String(64), nullable=False),
        sa.Column("transaction_external_id", sa.String(64), nullable=False),
        sa.Column("order_ref", sa.String(100), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_installment", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("installment_number", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("commission", sa.Numeric(14, 2), nullable=True),
        sa.Column("net_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("payment_provider", sa.String(50), nullable=True),
        sa.Column("payment_type", sa.String(50), nullable=True),
        sa.Column("payment_method", sa.String(50), nullable=True),
        sa.Column("settlement_external_id", sa.String(64), nullable=True),
        sa.Column("source_layout", sa.String(20), nullable=False),
        sa.Column("last_file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("p_report_files.id"), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("row_key", name="uq_p_report_transactions_row_key"),
        sa.CheckConstraint("source_layout IN ('data_transacciones', 'consolidado')", name="ck_pkr_tx_layout"),
        sa.CheckConstraint("installment_number IS NULL OR installment_number >= 0", name="ck_pkr_tx_installment"),
    )
    op.create_index("ix_p_report_transactions_external_id", "p_report_transactions", ["transaction_external_id"])
    op.create_index("ix_p_report_transactions_occurred_at", "p_report_transactions", ["occurred_at"])

    op.create_table(
        "p_report_settlements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("settlement_external_id", sa.String(64), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("status", sa.String(30), nullable=True),
        sa.Column("deposit_date", sa.Date(), nullable=True),
        sa.Column("last_file_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("p_report_files.id"), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("settlement_external_id", name="uq_p_report_settlements_external_id"),
    )

    op.add_column("p_transactions", sa.Column("commission", sa.Numeric(14, 2), nullable=True))
    op.add_column("p_transactions", sa.Column("net_amount", sa.Numeric(14, 2), nullable=True))
    op.add_column("p_transactions", sa.Column("payment_method", sa.String(50), nullable=True))
    op.add_column("p_transactions", sa.Column("installment_number", sa.Integer(), nullable=True))
    op.add_column("p_subscriptions", sa.Column("next_charge_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("p_subscriptions", "next_charge_date")
    for column in ("installment_number", "payment_method", "net_amount", "commission"):
        op.drop_column("p_transactions", column)
    op.drop_table("p_report_settlements")
    op.drop_index("ix_p_report_transactions_occurred_at", table_name="p_report_transactions")
    op.drop_index("ix_p_report_transactions_external_id", table_name="p_report_transactions")
    op.drop_table("p_report_transactions")
    op.drop_table("p_report_files")
    op.drop_index("ix_export_jobs_status_expires", table_name="export_jobs")
    op.drop_index("ix_export_jobs_user_created", table_name="export_jobs")
    op.drop_table("export_jobs")
