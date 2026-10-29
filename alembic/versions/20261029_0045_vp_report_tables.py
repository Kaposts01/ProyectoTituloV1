"""Tablas de los reportes PAT de VirtualPOS (VP-PAR-02 / RJ-04): vp_report_files, vp_report_payments, vp_report_subscriptions.

Solo crea tablas nuevas y vacias (no toca vp_*, core_* ni datos existentes). Sin datos personales ni contenido de
archivo. La aplica el usuario (ningun agente corre Alembic).

Revision ID: 20261029_0045
Revises: 20261029_0044
Create Date: 2026-10-29 17:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20261029_0045"
down_revision = "20261029_0044"
branch_labels = None
depends_on = None

PLATFORM_STATUSES = "('resolved', 'ambiguous', 'unresolved')"
PLATFORM_CONSISTENT = "(platform_status = 'resolved') = (platform IS NOT NULL)"
LAST4 = "card_last4 IS NULL OR card_last4 ~ '^[0-9]{4}$'"
SELLER = "seller_code_hash IS NULL OR seller_code_hash ~ '^[0-9a-f]{64}$'"


def _id() -> sa.Column:
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _tz(name: str, nullable: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _file_fk() -> sa.Column:
    return sa.Column("last_file_id", UUID(as_uuid=True), sa.ForeignKey("vp_report_files.id"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "vp_report_files",
        _id(),
        sa.Column("report_type", sa.String(20), nullable=False),
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
        sa.Column("uploaded_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        _ts("loaded_at"),
        _tz("finished_at"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("file_sha256", name="uq_vp_report_files_sha256"),
        sa.CheckConstraint("report_type IN ('transacciones', 'suscriptores')", name="ck_vpr_files_report_type"),
        sa.CheckConstraint("status IN ('running', 'completed', 'failed')", name="ck_vpr_files_status"),
        sa.CheckConstraint("file_sha256 ~ '^[0-9a-f]{64}$'", name="ck_vpr_files_sha256"),
        sa.CheckConstraint(
            "rows_total >= 0 AND rows_new >= 0 AND rows_updated >= 0 AND rows_skipped >= 0", name="ck_vpr_files_rows"
        ),
    )

    op.create_table(
        "vp_report_payments",
        _id(),
        sa.Column("charge_external_id", sa.String(255), nullable=False),
        sa.Column("payment_external_id", sa.String(255)),
        sa.Column("subscription_external_id", sa.String(255)),
        sa.Column("platform", sa.String(50)),
        sa.Column("platform_status", sa.String(20), nullable=False, server_default="unresolved"),
        sa.Column("charge_status", sa.String(50)),
        sa.Column("scheduled_date", sa.Date()),
        sa.Column("charge_number", sa.SmallInteger()),
        sa.Column("charges_total", sa.SmallInteger()),
        sa.Column("amount", sa.Numeric(18, 2)),
        sa.Column("currency", sa.String(10)),
        sa.Column("response_code", sa.String(100)),
        sa.Column("response_text", sa.Text()),
        sa.Column("payment_medium", sa.String(30)),
        sa.Column("card_last4", sa.String(4)),
        _tz("authorized_at"),
        sa.Column("processing_fee", sa.Numeric(18, 2)),
        sa.Column("payout_amount", sa.Numeric(18, 2)),
        _tz("payout_date"),
        sa.Column("pos_alias", sa.String(255)),
        sa.Column("seller_code_hash", sa.String(64)),
        sa.Column("subscription_origin", sa.String(50)),
        sa.Column("charge_origin", sa.String(100)),
        _tz("source_generated_at", nullable=False),
        _file_fk(),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("charge_external_id", name="uq_vp_report_payments_charge"),
        sa.CheckConstraint(f"platform_status IN {PLATFORM_STATUSES}", name="ck_vpr_pay_platform_status"),
        sa.CheckConstraint(PLATFORM_CONSISTENT, name="ck_vpr_pay_platform_consistent"),
        sa.CheckConstraint(LAST4, name="ck_vpr_pay_last4"),
        sa.CheckConstraint(SELLER, name="ck_vpr_pay_seller_hash"),
    )
    op.create_index("ix_vp_report_payments_payment", "vp_report_payments", ["payment_external_id"])
    op.create_index("ix_vp_report_payments_subscription", "vp_report_payments", ["subscription_external_id"])
    op.create_index("ix_vp_report_payments_platform_status", "vp_report_payments", ["platform_status"])
    op.create_index("ix_vp_report_payments_scheduled", "vp_report_payments", ["scheduled_date"])

    op.create_table(
        "vp_report_subscriptions",
        _id(),
        sa.Column("subscription_external_id", sa.String(255), nullable=False),
        sa.Column("platform", sa.String(50)),
        sa.Column("platform_status", sa.String(20), nullable=False, server_default="unresolved"),
        sa.Column("status", sa.String(50)),
        _tz("subscribed_at"),
        _tz("canceled_at"),
        sa.Column("plan_external_id", sa.String(255)),
        sa.Column("charges_total", sa.SmallInteger()),
        sa.Column("charges_authorized", sa.Integer()),
        sa.Column("charges_rejected", sa.Integer()),
        sa.Column("charges_pending", sa.Integer()),
        sa.Column("charges_processing", sa.Integer()),
        sa.Column("charges_canceled", sa.Integer()),
        sa.Column("channel_origin", sa.String(50)),
        sa.Column("pos_alias", sa.String(255)),
        sa.Column("seller_code_hash", sa.String(64)),
        sa.Column("card_type", sa.String(20)),
        sa.Column("card_brand", sa.String(50)),
        sa.Column("card_last4", sa.String(4)),
        sa.Column("rejection_reason", sa.Text()),
        _tz("source_generated_at", nullable=False),
        _file_fk(),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("subscription_external_id", name="uq_vp_report_subscriptions_subscription"),
        sa.CheckConstraint(f"platform_status IN {PLATFORM_STATUSES}", name="ck_vpr_sub_platform_status"),
        sa.CheckConstraint(PLATFORM_CONSISTENT, name="ck_vpr_sub_platform_consistent"),
        sa.CheckConstraint(LAST4, name="ck_vpr_sub_last4"),
        sa.CheckConstraint(SELLER, name="ck_vpr_sub_seller_hash"),
    )
    op.create_index("ix_vp_report_subscriptions_platform_status", "vp_report_subscriptions", ["platform_status"])
    op.create_index("ix_vp_report_subscriptions_status", "vp_report_subscriptions", ["status"])


def downgrade() -> None:
    op.drop_table("vp_report_subscriptions")
    op.drop_table("vp_report_payments")
    op.drop_table("vp_report_files")
