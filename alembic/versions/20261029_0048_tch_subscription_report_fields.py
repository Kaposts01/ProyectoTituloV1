"""tch_subscription_report_fields: campos del reporte TCH que no se cargaban (TCH-PAR-09).

Solo AGREGA columnas nulas a `tch_suscripciones` y `tch_clientes`: estrategia, lugar de captacion, folio, referencia,
personalidad real, indicador de titular distinto del socio (booleano; NO se guarda el RUT ni el nombre del titular),
primer cobro, aportes acumulados, permanencia y los flags NVO / RECH MES / ELI MES, mas la region del cliente. No
reescribe datos existentes: se poblaran en la recarga completa. La aplica el usuario (ningun agente corre Alembic).

Revision ID: 20261029_0048
Revises: 20261029_0047
Create Date: 2026-10-29 20:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20261029_0048"
down_revision = "20261029_0047"
branch_labels = None
depends_on = None

_SUSCRIPCION_COLUMNS = [
    ("estrategia", sa.String(150)),
    ("lugar_captacion", sa.String(150)),
    ("folio", sa.String(50)),
    ("referencia", sa.String(30)),
    ("personalidad", sa.String(20)),
    ("titular_distinto", sa.Boolean()),
    ("fecha_primer_cobro", sa.String(20)),
    ("monto_primer_cobro", sa.String(20)),
    ("cuotas_cobradas", sa.Integer()),
    ("monto_cobrado", sa.String(20)),
    ("aportes_cuotas", sa.Integer()),
    ("aportes_monto", sa.String(20)),
    ("promedio_donacion", sa.String(20)),
    ("meses_sin_aporte", sa.Integer()),
    ("permanencia_meses", sa.Integer()),
    ("permanencia_anos", sa.Integer()),
    ("nvo_mes", sa.Boolean()),
    ("rech_mes", sa.Boolean()),
    ("eli_mes", sa.Boolean()),
]


def upgrade() -> None:
    for name, type_ in _SUSCRIPCION_COLUMNS:
        op.add_column("tch_suscripciones", sa.Column(name, type_, nullable=True))
    op.add_column("tch_clientes", sa.Column("region", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("tch_clientes", "region")
    for name, _ in reversed(_SUSCRIPCION_COLUMNS):
        op.drop_column("tch_suscripciones", name)
