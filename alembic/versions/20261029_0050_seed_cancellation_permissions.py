"""Permisos de baja de suscripciones multicanal (MGT-16) y su asignacion a roles.

Inserta `subscriptions.cancellation.request|approve|view` y los asigna: solicitar y aprobar a `jefatura` y `admin`;
ver a `soporte`, `ejecutivo`, `coordinador`, `jefatura` y `admin` (D12: jefatura solicita; admin o jefatura aprueban;
ejecutivo solo lee). Si un rol no existe en la base, NO falla ni lo crea. Idempotente (ON CONFLICT DO NOTHING).
No crea tablas ni toca otros datos. La aplica el usuario (ningun agente corre Alembic).

Revision ID: 20261029_0050
Revises: 20261029_0049
Create Date: 2026-10-29 20:00:00
"""

import uuid

import sqlalchemy as sa

from alembic import op

revision = "20261029_0050"
down_revision = "20261029_0049"
branch_labels = None
depends_on = None

REQUEST = "subscriptions.cancellation.request"
APPROVE = "subscriptions.cancellation.approve"
VIEW = "subscriptions.cancellation.view"

PERMISSIONS = {
    REQUEST: "Solicitar la baja de suscripciones (todos los canales)",
    APPROVE: "Aprobar, rechazar, aplicar y reabrir solicitudes de baja de suscripciones",
    VIEW: "Ver solicitudes de baja de suscripciones y su historial",
}

ROLE_GRANTS = {
    "admin": (REQUEST, APPROVE, VIEW),
    "jefatura": (REQUEST, APPROVE, VIEW),
    "soporte": (VIEW,),
    "ejecutivo": (VIEW,),
    "coordinador": (VIEW,),
}


def grant(bind) -> None:
    for code, description in PERMISSIONS.items():
        bind.execute(
            sa.text(
                "INSERT INTO permissions (id, code, description) VALUES (:id, :code, :description) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"id": uuid.uuid4(), "code": code, "description": description},
        )
    for role, codes in ROLE_GRANTS.items():
        for code in codes:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO role_permissions (role_id, permission_id)
                    SELECT roles.id, permissions.id
                    FROM roles CROSS JOIN permissions
                    WHERE roles.name = :role AND permissions.code = :code
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"role": role, "code": code},
            )


def upgrade() -> None:
    grant(op.get_bind())


def downgrade() -> None:
    for code in PERMISSIONS:
        op.execute(sa.text("DELETE FROM permissions WHERE code = :code").bindparams(code=code))
