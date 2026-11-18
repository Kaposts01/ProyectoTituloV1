"""BUG-VP-03: quita el indice unico parcial `uq_vp_sub_active_plan_client` de `vp_subscriptions`.

Una misma persona (RUT) puede tener varias suscripciones ACTIVAS en el mismo plan con distinto `external_id`
(decision d236). El indice solo actuaba sobre la sincronizacion (omitia filas); nunca protegio el alta del CRM.
La identidad de la fila sigue siendo `uq_vp_subscription_platform_external_id`.

`downgrade` recrea el indice igual que la 0036. ADVERTENCIA: el `CREATE UNIQUE INDEX` falla si ya existen dos
suscripciones ACTIVA/SUSCRIBIENDO con la misma (platform, plan_external_id, client_social_id); hay que resolver esos
duplicados antes de bajar. Probada solo por pytest en la base `*_test`; la aplica el usuario.

Revision ID: 20261117_0082
Revises: 20261116_0081
Create Date: 2026-11-17 10:00:00
"""

from alembic import op

revision = "20261117_0082"
down_revision = "20261116_0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_vp_sub_active_plan_client")


def downgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX uq_vp_sub_active_plan_client
        ON vp_subscriptions (platform, plan_external_id, client_social_id)
        WHERE status IN ('ACTIVA', 'SUSCRIBIENDO')
        """
    )
