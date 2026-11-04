"""Permiso payku.reports.import (L7-IMPORT, d151): cargar los reportes .xlsx del portal de Payku. Solo `admin`.

Inserta el permiso y lo asigna SOLO al rol `admin` (si no existe, no falla ni lo crea). Mismo patron que la 0046
(`virtualpos.reports.import`). No crea tablas ni toca otros datos; el downgrade quita la asignacion y el permiso.
La aplica el usuario (ningun agente corre Alembic).

Revision ID: 20261104_0071
Revises: 20261103_0068
Create Date: 2026-11-04 10:00:00
"""

import uuid

import sqlalchemy as sa

from alembic import op

revision = "20261104_0071"
down_revision = "20261103_0068"
branch_labels = None
depends_on = None

CODE = "payku.reports.import"
DESCRIPTION = "Importar reportes descargados del portal de Payku"


def grant(bind) -> None:
    bind.execute(
        sa.text(
            "INSERT INTO permissions (id, code, description) VALUES (:id, :code, :description) "
            "ON CONFLICT (code) DO NOTHING"
        ),
        {"id": uuid.uuid4(), "code": CODE, "description": DESCRIPTION},
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
        {"code": CODE},
    )


def revoke(bind) -> None:
    bind.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code = :code)"),
        {"code": CODE},
    )
    bind.execute(sa.text("DELETE FROM permissions WHERE code = :code"), {"code": CODE})


def upgrade() -> None:
    grant(op.get_bind())


def downgrade() -> None:
    revoke(op.get_bind())
