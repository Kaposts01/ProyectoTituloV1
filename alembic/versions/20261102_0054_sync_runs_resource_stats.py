"""SYNC-D-17: columnas de observabilidad por recurso en `sync_runs`.

* `resource_stats` (JSONB, NULL): por recurso, modo de lectura (`full`/`window`), duracion, paginas, registros y
  filas nuevas/actualizadas/sin cambio. Solo nombres, conteos y duraciones.
* `etl_run_id` (UUID, NULL, indexado): id de correlacion con la corrida global (`etl_runs.id`). Sin FK: los jobs de
  facturacion y bajas tambien escriben en `sync_runs` y no tienen `etl_run`.

Solo agrega columnas nulas (sin backfill). Reversible: el downgrade las borra. La aplica el usuario.

Revision ID: 20261102_0054
Revises: 20261102_0053
Create Date: 2026-11-02 12:30:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261102_0054"
down_revision = "20261102_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sync_runs", sa.Column("resource_stats", postgresql.JSONB(), nullable=True))
    op.add_column("sync_runs", sa.Column("etl_run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_sync_runs_etl_run_id", "sync_runs", ["etl_run_id"])


def downgrade() -> None:
    op.drop_index("ix_sync_runs_etl_run_id", table_name="sync_runs")
    op.drop_column("sync_runs", "etl_run_id")
    op.drop_column("sync_runs", "resource_stats")
