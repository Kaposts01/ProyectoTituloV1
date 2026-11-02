"""toku_report_customers_payments_settlements: tablas de Clientes, Pagos v2 y Liquidaciones (TK-PAR-07, TK-PAR-09).

Crea `tk_report_customers` (estado del cliente: fechas de creacion/eliminacion y «Silenciado hasta"),
`tk_report_payments` (tipo de pago y cuotas) y `tk_report_settlements` (comision, neto, fecha de deposito), y agrega
`liquidaciones` a los tipos permitidos de `tk_report_files` (`clientes` y `pagos` ya estaban desde la 0039). Sin datos
personales ni payload crudo. No toca datos existentes. Reversible: el downgrade borra las tres tablas, las filas de
`tk_report_files` de tipo `liquidaciones` y restaura el CHECK anterior. La aplica el usuario (ningun agente corre
Alembic).

Revision ID: 20261102_0057
Revises: 20261102_0056
Create Date: 2026-11-02 14:30:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20261102_0057"
down_revision = "20261102_0056"
branch_labels = None
depends_on = None

_OLD_TYPES = "('productos', 'intentos', 'medios_pago', 'deudas', 'inscripciones', 'clientes', 'pagos')"
_NEW_TYPES = "('productos', 'intentos', 'medios_pago', 'deudas', 'inscripciones', 'clientes', 'pagos', 'liquidaciones')"


def _id() -> sa.Column:
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _tz(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _common_tail() -> list:
    return [
        _tz("source_generated_at", nullable=False),
        sa.Column("last_file_id", UUID(as_uuid=True), sa.ForeignKey("tk_report_files.id"), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
    ]


def upgrade() -> None:
    op.drop_constraint("ck_tkr_files_report_type", "tk_report_files", type_="check")
    op.create_check_constraint("ck_tkr_files_report_type", "tk_report_files", f"report_type IN {_NEW_TYPES}")

    op.create_table(
        "tk_report_customers",
        _id(),
        sa.Column("customer_external_id", sa.String(255), nullable=False),
        _tz("created_at_source"),
        _tz("deleted_at_source"),
        _tz("silenced_until"),
        *_common_tail(),
        sa.UniqueConstraint("customer_external_id", name="uq_tk_report_customers_customer"),
    )

    op.create_table(
        "tk_report_payments",
        _id(),
        sa.Column("payment_external_id", sa.String(255), nullable=False),
        sa.Column("customer_external_id", sa.String(255)),
        sa.Column("debt_external_id", sa.String(255)),
        sa.Column("amount", sa.Numeric(14, 2)),
        sa.Column("payment_type", sa.String(50)),
        sa.Column("installments", sa.SmallInteger()),
        sa.Column("status", sa.String(50)),
        sa.Column("processor", sa.String(100)),
        _tz("paid_at"),
        _tz("created_at_source"),
        _tz("deleted_at_source"),
        *_common_tail(),
        sa.UniqueConstraint("payment_external_id", name="uq_tk_report_payments_payment"),
        sa.CheckConstraint("installments IS NULL OR installments >= 0", name="ck_tkr_payments_installments"),
    )
    op.create_index("ix_tk_report_payments_debt", "tk_report_payments", ["debt_external_id"])
    op.create_index("ix_tk_report_payments_customer", "tk_report_payments", ["customer_external_id"])

    op.create_table(
        "tk_report_settlements",
        _id(),
        sa.Column("settlement_external_id", sa.String(255), nullable=False),
        sa.Column("debt_external_id", sa.String(255)),
        sa.Column("customer_external_id", sa.String(255)),
        sa.Column("amount", sa.Numeric(14, 2)),
        sa.Column("commission", sa.Numeric(14, 2)),
        sa.Column("net_amount", sa.Numeric(14, 2)),
        sa.Column("deposit_date", sa.Date()),
        sa.Column("settled", sa.Boolean()),
        *_common_tail(),
        sa.UniqueConstraint("settlement_external_id", name="uq_tk_report_settlements_settlement"),
    )
    op.create_index("ix_tk_report_settlements_debt", "tk_report_settlements", ["debt_external_id"])
    op.create_index("ix_tk_report_settlements_deposit_date", "tk_report_settlements", ["deposit_date"])


def downgrade() -> None:
    op.drop_index("ix_tk_report_settlements_deposit_date", table_name="tk_report_settlements")
    op.drop_index("ix_tk_report_settlements_debt", table_name="tk_report_settlements")
    op.drop_table("tk_report_settlements")
    op.drop_index("ix_tk_report_payments_customer", table_name="tk_report_payments")
    op.drop_index("ix_tk_report_payments_debt", table_name="tk_report_payments")
    op.drop_table("tk_report_payments")
    op.drop_table("tk_report_customers")
    op.execute("DELETE FROM tk_report_files WHERE report_type = 'liquidaciones'")
    op.drop_constraint("ck_tkr_files_report_type", "tk_report_files", type_="check")
    op.create_check_constraint("ck_tkr_files_report_type", "tk_report_files", f"report_type IN {_OLD_TYPES}")
