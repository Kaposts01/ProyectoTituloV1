"""SYNC-D-13: `last_seen_at` y `removed_at` en las tablas de suscripciones de canal.

* `last_seen_at` (timestamptz, NULL): ultima vez que una lectura del proveedor trajo la fila. La escribe
  `channel_store.upsert_channel` en cada upsert (siempre, aunque el payload no cambie; a diferencia de
  `source_records.last_seen_at`, que solo cambia con el payload).
* `removed_at` (timestamptz, NULL): baja por desaparicion. La pone `channel_removals.detect_removals` tras una sync
  COMPLETA y exitosa (detras de `SYNC_REMOVAL_DETECTION_ENABLED`, apagada); vuelve a NULL si la fila reaparece.

Tablas: `vp_subscriptions`, `tk_subscriptions`, `p_subscriptions`. Solo agrega columnas nulas (sin backfill: las filas
existentes quedan con NULL hasta la siguiente sync completa). Reversible: el downgrade las borra. La aplica el usuario.

Revision ID: 20261102_0062
Revises: 20261102_0054
Create Date: 2026-11-02 15:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20261102_0062"
down_revision = "20261102_0054"
branch_labels = None
depends_on = None

_TABLES = ("vp_subscriptions", "tk_subscriptions", "p_subscriptions")


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_column(table, "removed_at")
        op.drop_column(table, "last_seen_at")
