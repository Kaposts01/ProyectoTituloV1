"""Seed billing change request/approval permissions.

Revision ID: 20261028_0037
Revises: 20261021_0036
Create Date: 2026-10-28 09:00:00
"""

import uuid

import sqlalchemy as sa

from alembic import op

revision = "20261028_0037"
down_revision = "20261021_0036"
branch_labels = None
depends_on = None

PERMISSIONS = {
    "virtualpos.billing_changes.request": "Solicitar cambios de cobro VirtualPOS",
    "virtualpos.billing_changes.approve": "Aprobar o rechazar cambios de cobro VirtualPOS",
    "virtualpos.billing_changes.view": "Ver bandeja e historial de cambios de cobro VirtualPOS",
    "virtualpos.billing_policy.manage": "Configurar aprobadores de cambios de cobro VirtualPOS",
}


def upgrade() -> None:
    bind = op.get_bind()
    for code, description in PERMISSIONS.items():
        bind.execute(
            sa.text(
                """
                INSERT INTO permissions (id, code, description)
                VALUES (:id, :code, :description)
                ON CONFLICT (code) DO NOTHING
                """
            ),
            {"id": uuid.uuid4(), "code": code, "description": description},
        )
        bind.execute(
            sa.text(
                """
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT roles.id, permissions.id
                FROM roles CROSS JOIN permissions
                WHERE roles.name = 'admin' AND permissions.code = :code
                ON CONFLICT DO NOTHING
                """
            ),
            {"code": code},
        )


def downgrade() -> None:
    for code in PERMISSIONS:
        op.execute(sa.text("DELETE FROM permissions WHERE code = :code").bindparams(code=code))
