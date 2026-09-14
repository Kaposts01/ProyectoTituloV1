"""Store TCH customer contacts and subscription peso equivalents.

Revision ID: 20260912_0019
Revises: 20260912_0018
Create Date: 2026-09-12 22:45:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20260912_0019"
down_revision = "20260912_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tch_clientes", sa.Column("telefono", sa.String(length=100), nullable=True))
    op.add_column("tch_clientes", sa.Column("email", sa.String(length=320), nullable=True))
    op.add_column("tch_clientes", sa.Column("direccion", sa.String(length=500), nullable=True))
    op.add_column("tch_clientes", sa.Column("comuna", sa.String(length=150), nullable=True))
    op.add_column("tch_clientes", sa.Column("ciudad", sa.String(length=150), nullable=True))
    op.add_column("tch_suscripciones", sa.Column("equivalente_pesos", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("tch_suscripciones", "equivalente_pesos")
    op.drop_column("tch_clientes", "ciudad")
    op.drop_column("tch_clientes", "comuna")
    op.drop_column("tch_clientes", "direccion")
    op.drop_column("tch_clientes", "email")
    op.drop_column("tch_clientes", "telefono")
