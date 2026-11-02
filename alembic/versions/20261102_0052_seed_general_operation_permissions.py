"""Permisos `general.*` de Operación: Recuperador general por pestaña y Cambios de cobro (UX-12, REC-04, REC-06).

Inserta `general.recovery.view`, `general.recovery.toku.view`, `general.recovery.tch.view` y
`general.billing_changes.view`. La asignación es por datos (sin nombres de rol), para que nadie gane ni pierda acceso:

* `general.recovery.view`        -> roles que ya tienen `virtualpos.recovery.view`.
* `general.billing_changes.view` -> roles que ya tienen `virtualpos.billing_changes.view`.
* `general.recovery.toku.view`   -> roles con `virtualpos.recovery.view` y `toku.subscriptions.view`.
* `general.recovery.tch.view`    -> roles con `virtualpos.recovery.view` y `tch.suscripciones.view`.

Idempotente (ON CONFLICT DO NOTHING). No crea tablas ni toca otros datos. Reversible: el downgrade borra las
asignaciones y los cuatro permisos. La aplica el usuario (ningún agente corre Alembic).

Revision ID: 20261102_0052
Revises: 20261029_0051
Create Date: 2026-11-02 10:00:00
"""

import uuid

import sqlalchemy as sa

from alembic import op

revision = "20261102_0052"
down_revision = "20261029_0051"
branch_labels = None
depends_on = None

PERMISSIONS = {
    "general.recovery.view": "Ver el Recuperador general (Operación)",
    "general.recovery.toku.view": "Ver la pestaña Toku del Recuperador general",
    "general.recovery.tch.view": "Ver la pestaña TCH del Recuperador general (solo lectura)",
    "general.billing_changes.view": "Ver Cambios de cobro en Operación",
}

# permiso nuevo -> permisos que el rol debe tener TODOS para recibirlo (copia de rbac.GENERAL_GRANT_RULES).
GRANT_RULES = {
    "general.recovery.view": ("virtualpos.recovery.view",),
    "general.billing_changes.view": ("virtualpos.billing_changes.view",),
    "general.recovery.toku.view": ("virtualpos.recovery.view", "toku.subscriptions.view"),
    "general.recovery.tch.view": ("virtualpos.recovery.view", "tch.suscripciones.view"),
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
    for code, required in GRANT_RULES.items():
        bind.execute(
            sa.text(
                """
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT rp.role_id, target.id
                FROM role_permissions rp
                JOIN permissions p ON p.id = rp.permission_id
                CROSS JOIN permissions target
                WHERE target.code = :code AND p.code = ANY(:required)
                GROUP BY rp.role_id, target.id
                HAVING COUNT(DISTINCT p.code) = :n
                ON CONFLICT DO NOTHING
                """
            ),
            {"code": code, "required": list(required), "n": len(required)},
        )


def revoke(bind) -> None:
    codes = list(PERMISSIONS)
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code = ANY(:codes))"
        ),
        {"codes": codes},
    )
    bind.execute(sa.text("DELETE FROM permissions WHERE code = ANY(:codes)"), {"codes": codes})


def upgrade() -> None:
    grant(op.get_bind())


def downgrade() -> None:
    revoke(op.get_bind())
