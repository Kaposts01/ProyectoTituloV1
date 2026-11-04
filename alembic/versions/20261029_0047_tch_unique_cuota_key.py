"""tch_unique_cuota_key: columnas para la clave estable de cargos TCH (ficha, periodo real, cuota) y la moneda (TCH-PAR-03/04/05).

Decision D13: en la fuente cada cuota tiene UN estado final; el cargo se identifica por (ficha, periodo real, cuota) con
el ULTIMO estado, y el rechazo previo se conserva como atributo de la misma fila.

Solo AGREGA columnas nulas a `tch_transacciones` y `tch_suscripciones`: no borra ni reescribe datos existentes, no crea
indices ni cambia la unicidad de `dedupe_key`. Las filas actuales conservan su clave antigua (ficha|periodo|cuota|estado|monto);
el reordenamiento a la clave nueva ocurre en la recarga completa `scripts/etl_tch.py --mode full` (la ejecuta el usuario,
con respaldo previo). Sin datos personales. La aplica el usuario (ningun agente corre Alembic).

Revision ID: 20261029_0047
Revises: 20261029_0046
Create Date: 2026-10-29 19:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20261029_0047"
down_revision = "20261029_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Origen de la fila: 'cargo' (hojas CARGOS ACEPTADOS/RECHAZADOS, con fecha) o 'historial' (estado mensual sin fecha).
    op.add_column("tch_transacciones", sa.Column("origen", sa.String(10), nullable=True))
    # Mes del reporte que trajo la fila: "el ultimo reporte gana".
    op.add_column("tch_transacciones", sa.Column("reporte_periodo", sa.String(7), nullable=True))
    op.add_column("tch_transacciones", sa.Column("rechazo_previo", sa.Boolean(), nullable=True))
    op.add_column("tch_transacciones", sa.Column("rechazo_previo_motivo", sa.String(500), nullable=True))
    op.add_column("tch_transacciones", sa.Column("rechazo_previo_en", sa.String(20), nullable=True))
    # Moneda del mandato desde "Moneda Vigente" (quedo pendiente en TCH-PAR-05).
    op.add_column("tch_suscripciones", sa.Column("moneda", sa.String(3), nullable=True))


def downgrade() -> None:
    op.drop_column("tch_suscripciones", "moneda")
    op.drop_column("tch_transacciones", "rechazo_previo_en")
    op.drop_column("tch_transacciones", "rechazo_previo_motivo")
    op.drop_column("tch_transacciones", "rechazo_previo")
    op.drop_column("tch_transacciones", "reporte_periodo")
    op.drop_column("tch_transacciones", "origen")
