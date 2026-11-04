"""SYNC-O-08: tablas `sync_cursors` (marcas de agua por fuente/recurso/modo) y `tch_file_loads` (sha256 por archivo).

* `sync_cursors`: una fila por (fuente, recurso, modo, inicio de ventana); `window_start` NULL = marca de agua del modo.
  La clave unica usa NULLS NOT DISTINCT (PostgreSQL 15+).
* `tch_file_loads`: registro de reportes Excel TCH cargados. Se MUEVE aqui el registro que vivia en `source_records`
  (`source='tch_report'`, `resource_type='file'`, TCH-PAR-15): se copian las filas y se borran del origen. La marca de
  consolidacion (`resource_type='consolidation_mark'`) se queda en `source_records`.

Reversible: el downgrade devuelve las filas a `source_records` y borra ambas tablas. La aplica el usuario.

Revision ID: 20261102_0053
Revises: 20261102_0055
Create Date: 2026-11-02 12:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261102_0053"
down_revision = "20261102_0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sync_cursors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("resource", sa.String(40), nullable=False),
        sa.Column("mode", sa.String(12), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=True),
        sa.Column("window_end", sa.Date(), nullable=True),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("records_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("requests_made", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("locked_by", sa.String(60), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "source", "resource", "mode", "window_start", name="uq_sync_cursors_key", postgresql_nulls_not_distinct=True
        ),
    )
    op.create_index("ix_sync_cursors_source", "sync_cursors", ["source"])

    op.create_table(
        "tch_file_loads",
        sa.Column("file_sha256", sa.String(64), primary_key=True),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("rows_loaded", sa.Integer(), nullable=True),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("consolidated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        INSERT INTO tch_file_loads (file_sha256, file_name, size_bytes, loaded_at)
        SELECT left(external_id, 64),
               left(coalesce(payload->>'filename', ''), 255),
               CASE WHEN payload->>'size_bytes' ~ '^[0-9]+$' THEN (payload->>'size_bytes')::bigint END,
               coalesce(first_seen_at, now())
        FROM source_records
        WHERE source = 'tch_report' AND resource_type = 'file'
        ON CONFLICT (file_sha256) DO NOTHING
        """
    )
    op.execute("DELETE FROM source_records WHERE source = 'tch_report' AND resource_type = 'file'")


def downgrade() -> None:
    op.execute(
        """
        INSERT INTO source_records (id, source, resource_type, external_id, payload, first_seen_at, last_seen_at)
        SELECT gen_random_uuid(), 'tch_report', 'file', file_sha256,
               jsonb_build_object('filename', file_name, 'size_bytes', size_bytes),
               loaded_at, loaded_at
        FROM tch_file_loads
        ON CONFLICT ON CONSTRAINT uq_source_record DO NOTHING
        """
    )
    op.drop_table("tch_file_loads")
    op.drop_index("ix_sync_cursors_source", table_name="sync_cursors")
    op.drop_table("sync_cursors")
