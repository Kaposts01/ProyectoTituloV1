"""Permisos de las vistas unificadas de Cartera: Suscripciones y Cobros (UX-08, UX-09; d124 opcion c).

Inserta `general.subscriptions.view` y `general.charges.view`. Misma regla por datos que la 0052 (sin nombres de rol):
cada permiso se otorga a los roles que ya tienen TODOS los permisos de vista de canal equivalentes, asi que nadie gana
acceso a datos que no veia y nadie lo pierde (los permisos de canal siguen valiendo para roles parciales).

* `general.subscriptions.view` -> roles con `virtualpos.subscriptions.view`, `toku.subscriptions.view`,
  `payku.subscriptions.view` y `tch.suscripciones.view`.
* `general.charges.view`       -> roles con `virtualpos.charges.view`, `toku.invoices.view`, `tch.transacciones.view`,
  `virtualpos.payments.view`, `toku.transactions.view` y `payku.transactions.view`.

Idempotente (ON CONFLICT DO NOTHING). No crea tablas ni toca otros datos. Reversible: el downgrade borra las
asignaciones y los dos permisos. La aplica el usuario (ningun agente corre Alembic contra `crm` ni `crm_sandbox`).

Revision ID: 20261102_0064
Revises: 20261102_0066
Create Date: 2026-11-02 18:00:00
"""

import uuid

import sqlalchemy as sa

from alembic import op

revision = "20261102_0064"
down_revision = "20261102_0066"
branch_labels = None
depends_on = None

PERMISSIONS = {
    "general.subscriptions.view": "Ver Suscripciones unificadas de todos los canales (Cartera)",
    "general.charges.view": "Ver Cobros y pagos unificados de todos los canales (Cartera)",
}

# Copia de rbac.UNIFIED_VIEW_GRANT_RULES (la prueba verifica que coincidan).
GRANT_RULES = {
    "general.subscriptions.view": (
        "virtualpos.subscriptions.view", "toku.subscriptions.view", "payku.subscriptions.view", "tch.suscripciones.view",
    ),
    "general.charges.view": (
        "virtualpos.charges.view", "toku.invoices.view", "tch.transacciones.view",
        "virtualpos.payments.view", "toku.transactions.view", "payku.transactions.view",
    ),
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
