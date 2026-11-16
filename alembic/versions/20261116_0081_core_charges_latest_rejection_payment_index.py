"""d223: indice en `core_charges.latest_rejection_payment_id` (FK hacia `core_payments`).

Sin indice, cada fila borrada de `core_payments` obliga a Postgres a recorrer `core_charges` entera para revisar la FK
`fk_core_charges_latest_rejection_payment`. El 16/11, la poda de los 1,47 M pagos TCH con clave antigua (ETL Core
tras la recarga de d223) llevaba 1 h 36 min en un solo DELETE y hubo que cancelarla.

Se crea con CONCURRENTLY para no bloquear escrituras en `core_charges` mientras se construye (fuera de la
transaccion de Alembic). IF NOT EXISTS permite reintentar si una corrida anterior se corto. Sin cambios de datos.
Probada solo por pytest en la base `*_test` y medida en `crm_sandbox`; la aplica el usuario.

Revision ID: 20261116_0081
Revises: 20261114_0080
Create Date: 2026-11-16 08:00:00
"""

from alembic import op

revision = "20261116_0081"
down_revision = "20261114_0080"
branch_labels = None
depends_on = None

_INDEX = "ix_core_charges_latest_rejection_payment_id"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} ON core_charges (latest_rejection_payment_id)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
