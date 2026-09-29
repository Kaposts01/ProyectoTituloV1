"""Add durable VirtualPOS charge recovery cycles.

Revision ID: 20260923_0022
Revises: 20260916_0021
Create Date: 2026-09-23 12:00:00
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20260923_0022"
down_revision = "20260916_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "charge_recoveries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("charge_external_id", sa.String(length=255), nullable=False),
        sa.Column("subscription_external_id", sa.String(length=255), nullable=True),
        sa.Column("write_run_id", UUID(as_uuid=True), sa.ForeignKey("write_runs.id"), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_charge_status", sa.String(length=50), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_charge_recoveries_source", "charge_recoveries", ["source"])
    op.create_index("ix_charge_recoveries_charge_external_id", "charge_recoveries", ["charge_external_id"])
    op.create_index("ix_charge_recoveries_subscription_external_id", "charge_recoveries", ["subscription_external_id"])
    op.create_index("ix_charge_recoveries_status", "charge_recoveries", ["status"])
    op.create_index("ix_charge_recoveries_closes_at", "charge_recoveries", ["closes_at"])
    bind = op.get_bind()
    for code, description in (
        ("virtualpos.recovery.view", "Ver Recuperador de Socios VirtualPOS"),
        ("virtualpos.recovery.export", "Exportar suscripciones canceladas VirtualPOS"),
        ("virtualpos.cards.change", "Generar links de cambio de tarjeta VirtualPOS"),
    ):
        bind.execute(
            sa.text(
                "INSERT INTO permissions (id, code, description) VALUES (:id, :code, :description) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"id": uuid.uuid4(), "code": code, "description": description},
        )
        bind.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT roles.id, permissions.id FROM roles CROSS JOIN permissions "
                "WHERE roles.name = 'admin' AND permissions.code = :code ON CONFLICT DO NOTHING"
            ),
            {"code": code},
        )


def downgrade() -> None:
    op.drop_table("charge_recoveries")
