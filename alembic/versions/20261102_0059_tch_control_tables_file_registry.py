"""TCH-PAR-10 y TCH-PAR-11: tablas de control adicionales del reporte TCH y registro de archivos cargados.

TCH-PAR-10 (tablas nuevas, solo agregados del reporte, sin datos personales):
* `tch_flujo_mandatos`: hojas FLUJO MANDATOS CANT/MONTO (vigentes, altas y bajas por entidad y mes).
* `tch_rechazos_motivo`: hojas RECHAZOS y ENT RECHAZOS (motivos de rechazo, con entidad cuando la hoja la trae).
* `tch_kpi_reporte`: hoja KPI (indicador -> valor) por mes del reporte.
Se llenan al cargar o recargar reportes: no hay backfill.

TCH-PAR-11: columnas nuevas en `tch_file_loads` (SYNC-O-08) para el registro por archivo: `report_period`, `result`
('cargado' por defecto, que es lo que significa toda fila existente; o 'fallido'), `error_message` (texto generico)
y `etl_run_id`. Las filas existentes quedan 'cargado' sin mes: no se toca ningun dato.

Reversible: el downgrade quita las cuatro columnas (se pierden los registros 'fallido', que primero se borran para
que no bloqueen el reintento del mismo archivo con el codigo anterior) y borra las tres tablas. La aplica el usuario.

Revision ID: 20261102_0059
Revises: 20261102_0063
Create Date: 2026-11-02 18:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261102_0059"
down_revision = "20261102_0063"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "tch_flujo_mandatos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("periodo", sa.String(7), nullable=False),
        sa.Column("entidad", sa.String(150), nullable=False),
        sa.Column("concepto", sa.String(150), nullable=False),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=True),
        sa.Column("monto", sa.String(20), nullable=True),
        sa.Column("archivo_origen", sa.String(255), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("periodo", "entidad", "concepto", name="uq_tch_flujo_mandatos_clave"),
    )
    op.create_index("ix_tch_flujo_mandatos_periodo", "tch_flujo_mandatos", ["periodo"])

    op.create_table(
        "tch_rechazos_motivo",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reporte_periodo", sa.String(7), nullable=False),
        sa.Column("hoja", sa.String(20), nullable=False),
        sa.Column("entidad", sa.String(150), nullable=False, server_default=""),
        sa.Column("motivo", sa.String(255), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=True),
        sa.Column("monto", sa.String(20), nullable=True),
        sa.Column("archivo_origen", sa.String(255), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("reporte_periodo", "hoja", "entidad", "motivo", name="uq_tch_rechazos_motivo_clave"),
    )
    op.create_index("ix_tch_rechazos_motivo_reporte_periodo", "tch_rechazos_motivo", ["reporte_periodo"])

    op.create_table(
        "tch_kpi_reporte",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reporte_periodo", sa.String(7), nullable=False),
        sa.Column("indicador", sa.String(255), nullable=False),
        sa.Column("valor", sa.String(30), nullable=True),
        sa.Column("archivo_origen", sa.String(255), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("reporte_periodo", "indicador", name="uq_tch_kpi_reporte_clave"),
    )
    op.create_index("ix_tch_kpi_reporte_reporte_periodo", "tch_kpi_reporte", ["reporte_periodo"])

    op.add_column("tch_file_loads", sa.Column("report_period", sa.String(7), nullable=True))
    op.add_column(
        "tch_file_loads", sa.Column("result", sa.String(12), nullable=False, server_default="cargado")
    )
    op.add_column("tch_file_loads", sa.Column("error_message", sa.String(500), nullable=True))
    op.add_column("tch_file_loads", sa.Column("etl_run_id", postgresql.UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    op.execute("DELETE FROM tch_file_loads WHERE result = 'fallido'")
    op.drop_column("tch_file_loads", "etl_run_id")
    op.drop_column("tch_file_loads", "error_message")
    op.drop_column("tch_file_loads", "result")
    op.drop_column("tch_file_loads", "report_period")
    op.drop_index("ix_tch_kpi_reporte_reporte_periodo", table_name="tch_kpi_reporte")
    op.drop_table("tch_kpi_reporte")
    op.drop_index("ix_tch_rechazos_motivo_reporte_periodo", table_name="tch_rechazos_motivo")
    op.drop_table("tch_rechazos_motivo")
    op.drop_index("ix_tch_flujo_mandatos_periodo", table_name="tch_flujo_mandatos")
    op.drop_table("tch_flujo_mandatos")
