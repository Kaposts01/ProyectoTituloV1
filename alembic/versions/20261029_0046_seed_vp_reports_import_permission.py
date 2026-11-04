"""Permiso virtualpos.reports.import (VP-PAR-02): importar los reportes PAT de VirtualPOS. Solo `admin`.

Inserta el permiso y lo asigna SOLO al rol `admin` (si no existe, no falla ni lo crea). No crea tablas ni toca otros
datos. La aplica el usuario (ningun agente corre Alembic).

Revision ID: 20261029_0046
Revises: 20261029_0045
Create Date: 2026-10-29 17:30:00
"""

import uuid

import sqlalchemy as sa

from alembic import op

revision = "20261029_0046"
down_revision = "20261029_0045"
branch_labels = None
depends_on = None

CODE = "virtualpos.reports.import"
DESCRIPTION = "Importar reportes PAT descargados del portal de VirtualPOS"


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


def upgrade() -> None:
    grant(op.get_bind())


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM permissions WHERE code = :code").bindparams(code=CODE))
