"""Tablas TCH para mandatos físicos TECHO Chile.

Revision ID: 20260912_0014
Revises: 20260912_0013
Create Date: 2026-09-12 16:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260912_0014"
down_revision = "20260912_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tch_bancos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nombre", sa.String(100), nullable=False),
        sa.Column("codigo_interno", sa.Integer(), nullable=True),
        sa.Column("codigo_grupo", sa.Integer(), nullable=True),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre", name="uq_tch_banco_nombre"),
    )

    op.create_table(
        "tch_tipos_mandato",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("codigo", sa.String(10), nullable=False),
        sa.Column("nombre", sa.String(100), nullable=True),
        sa.Column("descripcion", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("codigo", name="uq_tch_tipo_mandato_codigo"),
    )

    op.create_table(
        "tch_origenes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nombre", sa.String(150), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre", name="uq_tch_origen_nombre"),
    )

    op.create_table(
        "tch_centros_costo",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nombre", sa.String(150), nullable=False),
        sa.Column("estrategia", sa.String(150), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nombre", name="uq_tch_centro_costo_nombre"),
    )

    op.create_table(
        "tch_clientes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rut", sa.String(20), nullable=False),
        sa.Column("nombre", sa.String(150), nullable=True),
        sa.Column("apellido", sa.String(150), nullable=True),
        sa.Column("fecha_nacimiento", sa.String(20), nullable=True),
        sa.Column("profesion", sa.String(100), nullable=True),
        sa.Column("tipo_persona", sa.String(30), nullable=True),
        sa.Column("tipo_socio", sa.String(50), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rut", name="uq_tch_cliente_rut"),
    )
    op.create_index("ix_tch_clientes_rut", "tch_clientes", ["rut"])

    op.create_table(
        "tch_suscripciones",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("numero_ficha", sa.Integer(), nullable=False),
        sa.Column("numero_mandato", sa.Integer(), nullable=True),
        sa.Column("cliente_rut", sa.String(20), nullable=True),
        sa.Column("banco_nombre", sa.String(100), nullable=True),
        sa.Column("tipo_mandato", sa.String(20), nullable=True),
        sa.Column("tipo_cuenta", sa.String(50), nullable=True),
        sa.Column("numero_cuenta", sa.String(50), nullable=True),
        sa.Column("origen", sa.String(150), nullable=True),
        sa.Column("centro_costo", sa.String(150), nullable=True),
        sa.Column("captador", sa.String(150), nullable=True),
        sa.Column("ley", sa.String(50), nullable=True),
        sa.Column("reajuste", sa.String(10), nullable=True),
        sa.Column("firma", sa.String(10), nullable=True),
        sa.Column("monto", sa.String(20), nullable=True),
        sa.Column("fecha_activacion", sa.String(20), nullable=True),
        sa.Column("fecha_ingreso", sa.String(20), nullable=True),
        sa.Column("fecha_entrega_banco", sa.String(20), nullable=True),
        sa.Column("fecha_eliminacion", sa.String(20), nullable=True),
        sa.Column("razon_baja", sa.String(500), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="VIGENTE"),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("numero_ficha", name="uq_tch_suscripcion_ficha"),
    )
    op.create_index("ix_tch_suscripciones_numero_ficha", "tch_suscripciones", ["numero_ficha"])
    op.create_index("ix_tch_suscripciones_estado", "tch_suscripciones", ["estado"])
    op.create_index("ix_tch_suscripciones_cliente_rut", "tch_suscripciones", ["cliente_rut"])
    op.create_index("ix_tch_suscripciones_banco_nombre", "tch_suscripciones", ["banco_nombre"])
    op.create_index("ix_tch_suscripciones_origen", "tch_suscripciones", ["origen"])
    op.create_index("ix_tch_suscripciones_centro_costo", "tch_suscripciones", ["centro_costo"])

    op.create_table(
        "tch_transacciones",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("numero_ficha", sa.Integer(), nullable=False),
        sa.Column("numero_mandato", sa.Integer(), nullable=True),
        sa.Column("periodo", sa.String(10), nullable=True),
        sa.Column("numero_cuota", sa.String(20), nullable=True),
        sa.Column("total_cuotas", sa.String(20), nullable=True),
        sa.Column("monto", sa.String(20), nullable=True),
        sa.Column("fecha_cargo", sa.String(20), nullable=True),
        sa.Column("tipo_transaccion", sa.String(50), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("entidad_recaudadora", sa.String(100), nullable=True),
        sa.Column("codigo_respuesta", sa.String(50), nullable=True),
        sa.Column("razon_rechazo", sa.String(500), nullable=True),
        sa.Column("archivo_origen", sa.String(255), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tch_transacciones_numero_ficha", "tch_transacciones", ["numero_ficha"])
    op.create_index("ix_tch_transacciones_periodo", "tch_transacciones", ["periodo"])
    op.create_index("ix_tch_transacciones_estado", "tch_transacciones", ["estado"])
    op.create_index("ix_tch_transacciones_archivo_origen", "tch_transacciones", ["archivo_origen"])
    op.create_index("ix_tch_transacciones_entidad_recaudadora", "tch_transacciones", ["entidad_recaudadora"])
    op.create_index("ix_tch_transacciones_fecha_cargo", "tch_transacciones", ["fecha_cargo"])


def downgrade() -> None:
    op.drop_table("tch_transacciones")
    op.drop_table("tch_suscripciones")
    op.drop_table("tch_clientes")
    op.drop_table("tch_centros_costo")
    op.drop_table("tch_origenes")
    op.drop_table("tch_tipos_mandato")
    op.drop_table("tch_bancos")
