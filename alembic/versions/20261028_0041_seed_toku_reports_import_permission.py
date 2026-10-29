"""Seed toku.reports.import permission (admin only).

Revision ID: 20261028_0041
Revises: 20261028_0040
Create Date: 2026-10-28 15:00:00
"""

import uuid

import sqlalchemy as sa

from alembic import op

revision = "20261028_0041"
down_revision = "20261028_0040"
branch_labels = None
depends_on = None

PERMISSIONS = {
    "toku.reports.import": "Importar reportes descargados de Toku",
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
