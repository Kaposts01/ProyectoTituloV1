"""Reconcile deployed schema with SQLAlchemy metadata.

Revision ID: 20261001_0023
Revises: 20260930_0022b
Create Date: 2026-10-01
"""

import sqlalchemy as sa

from alembic import op

revision = "20261001_0023"
down_revision = "20260930_0022b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.create_index("ix_p_plans_code", "p_plans", ["code"])
    op.execute(sa.text("ALTER INDEX ix_payku_subscriptions_client_id RENAME TO ix_p_subscriptions_client_id"))
    op.create_index("ix_p_subscriptions_end_date", "p_subscriptions", ["end_date"])
    op.create_index("ix_p_subscriptions_last_status_current_payment", "p_subscriptions", ["last_status_current_payment"])
    op.create_index("ix_p_subscriptions_start_date", "p_subscriptions", ["start_date"])
    op.create_index("ix_tch_suscripciones_fecha_activacion", "tch_suscripciones", ["fecha_activacion"])
    op.create_index("ix_tch_suscripciones_numero_mandato", "tch_suscripciones", ["numero_mandato"])
    op.create_index("ix_tch_suscripciones_tipo_mandato", "tch_suscripciones", ["tipo_mandato"])
    op.create_index("ix_vp_payments_client_external_id", "vp_payments", ["client_external_id"])
    op.create_index("ix_vp_subscriptions_service_id", "vp_subscriptions", ["service_id"])

def downgrade() -> None:
    op.drop_index("ix_vp_subscriptions_service_id", table_name="vp_subscriptions")
    op.drop_index("ix_vp_payments_client_external_id", table_name="vp_payments")
    op.drop_index("ix_tch_suscripciones_tipo_mandato", table_name="tch_suscripciones")
    op.drop_index("ix_tch_suscripciones_numero_mandato", table_name="tch_suscripciones")
    op.drop_index("ix_tch_suscripciones_fecha_activacion", table_name="tch_suscripciones")
    op.drop_index("ix_p_subscriptions_start_date", table_name="p_subscriptions")
    op.drop_index("ix_p_subscriptions_last_status_current_payment", table_name="p_subscriptions")
    op.drop_index("ix_p_subscriptions_end_date", table_name="p_subscriptions")
    op.execute(sa.text("ALTER INDEX ix_p_subscriptions_client_id RENAME TO ix_payku_subscriptions_client_id"))
    op.drop_index("ix_p_plans_code", table_name="p_plans")
