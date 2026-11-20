"""REP-02: tabla `report_dispatches` (idempotencia de los reportes programados por correo).

Una fila por (`report_kind`, `period_key`), unica: el programador inserta `sending` con ON CONFLICT DO NOTHING antes de
enviar y pasa a `sent` o `failed`. Guarda la cantidad de destinatarios y el nombre de la clase del error; nunca
direcciones ni mensajes. Tabla nueva y vacia: no hay datos que rellenar.

`downgrade` elimina la tabla (se pierde el historial de envios; el programador reenviaria el ultimo periodo solo si las
banderas estan encendidas y el periodo sigue dentro de la ventana de envio tardio).

Revision ID: 20261120_0085
Revises: 20261119_0084
Create Date: 2026-11-20 10:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261120_0085"
down_revision = "20261119_0084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_dispatches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_kind", sa.String(length=20), nullable=False),
        sa.Column("period_key", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="sending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recipients_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_class", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("report_kind", "period_key", name="uq_report_dispatches_kind_period"),
        sa.CheckConstraint("status IN ('sending', 'sent', 'failed')", name="ck_report_dispatches_status"),
    )


def downgrade() -> None:
    op.drop_table("report_dispatches")
