"""Permiso export.pii (EXP-02, decision D22): exportar CSV con datos personales.

Inserta el permiso `export.pii` y lo asigna SOLO a los roles `admin` y `jefatura`. Si un rol no existe en la base,
no falla ni lo crea. `soporte`, `ejecutivo` y `coordinador` NO lo reciben. No toca otros datos ni crea tablas.
La aplica el usuario (ningun agente corre Alembic).

Revision ID: 20261029_0044
Revises: 20261029_0043
Create Date: 2026-10-29 16:00:00
"""

import uuid

import sqlalchemy as sa

from alembic import op

revision = "20261029_0044"
down_revision = "20261029_0043"
branch_labels = None
depends_on = None

CODE = "export.pii"
DESCRIPTION = "Exportar datos personales (RUT, nombre, correo, teléfono, dirección) en las exportaciones CSV"
ROLES = ("admin", "jefatura")


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
            WHERE roles.name IN ('admin', 'jefatura') AND permissions.code = :code
            ON CONFLICT DO NOTHING
            """
        ),
        {"code": CODE},
    )


def upgrade() -> None:
    grant(op.get_bind())


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM permissions WHERE code = :code").bindparams(code=CODE))
