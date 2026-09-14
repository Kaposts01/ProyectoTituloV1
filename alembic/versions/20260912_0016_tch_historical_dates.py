"""Support TCH end dates and historical charge idempotency.

Revision ID: 20260912_0016
Revises: 20260912_0015
Create Date: 2026-09-12 21:10:00
"""

import sqlalchemy as sa

from alembic import op

revision = "20260912_0016"
down_revision = "20260912_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tch_suscripciones", sa.Column("fecha_rechazo", sa.String(length=20), nullable=True))
    op.add_column("tch_transacciones", sa.Column("dedupe_key", sa.String(length=255), nullable=True))
    op.create_unique_constraint("uq_tch_transaccion_dedupe_key", "tch_transacciones", ["dedupe_key"])


def downgrade() -> None:
    op.drop_constraint("uq_tch_transaccion_dedupe_key", "tch_transacciones", type_="unique")
    op.drop_column("tch_transacciones", "dedupe_key")
    op.drop_column("tch_suscripciones", "fecha_rechazo")
