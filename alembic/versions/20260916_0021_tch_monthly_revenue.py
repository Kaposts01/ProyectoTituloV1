"""Store official TCH monthly revenue controls.

Revision ID: 20260916_0021
Revises: 20260913_0020
"""

import sqlalchemy as sa

from alembic import op

revision = "20260916_0021"
down_revision = "20260913_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tch_recaudacion_mensual",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("periodo", sa.String(length=7), nullable=False),
        sa.Column("aceptadas_cantidad", sa.Integer(), nullable=False),
        sa.Column("aceptadas_monto", sa.String(length=20), nullable=False),
        sa.Column("rechazadas_cantidad", sa.Integer(), nullable=False),
        sa.Column("rechazadas_monto", sa.String(length=20), nullable=False),
        sa.Column("archivo_origen", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("periodo", name="uq_tch_recaudacion_mensual_periodo"),
    )
    op.create_index("ix_tch_recaudacion_mensual_periodo", "tch_recaudacion_mensual", ["periodo"])


def downgrade() -> None:
    op.drop_index("ix_tch_recaudacion_mensual_periodo", table_name="tch_recaudacion_mensual")
    op.drop_table("tch_recaudacion_mensual")
