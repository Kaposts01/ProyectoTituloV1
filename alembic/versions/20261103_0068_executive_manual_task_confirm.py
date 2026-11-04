"""d136: el rol `ejecutivo` confirma tareas manuales de suscripcion (`subscriptions.manual_tasks.confirm`).

El ejecutivo hace la accion manual en el portal del proveedor y la confirma con su usuario y fecha (d107). Es el UNICO
permiso que gana (cubre confirmar, asignar, descartar y el CSV de mandatos TCH de las tareas, ver
`app/api/v1/routes/manual_tasks.py`); fuera de eso el rol sigue de solo lectura. Mismo patron por datos que la 0052 y la
0064: solo toca el rol si YA existe (nunca lo crea) y el permiso si YA existe (lo sembro la 0066).

Idempotente (ON CONFLICT DO NOTHING). No crea tablas ni toca otros datos. Reversible: el downgrade quita SOLO esa
asignacion del rol `ejecutivo` (el permiso sigue existiendo para admin y jefatura). La aplica el usuario (ningun agente
corre Alembic contra `crm` ni `crm_sandbox`).

Revision ID: 20261103_0068
Revises: 20261102_0065
Create Date: 2026-11-03 10:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20261103_0068"
down_revision = "20261102_0065"
branch_labels = None
depends_on = None

ROLE = "ejecutivo"
PERMISSION = "subscriptions.manual_tasks.confirm"


def grant(bind) -> None:
    bind.execute(
        sa.text(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
            WHERE r.name = :role AND p.code = :code
            ON CONFLICT DO NOTHING
            """
        ),
        {"role": ROLE, "code": PERMISSION},
    )


def revoke(bind) -> None:
    bind.execute(
        sa.text(
            """
            DELETE FROM role_permissions
            WHERE role_id IN (SELECT id FROM roles WHERE name = :role)
              AND permission_id IN (SELECT id FROM permissions WHERE code = :code)
            """
        ),
        {"role": ROLE, "code": PERMISSION},
    )


def upgrade() -> None:
    grant(op.get_bind())


def downgrade() -> None:
    revoke(op.get_bind())
