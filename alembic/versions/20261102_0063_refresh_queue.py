"""SYNC-O-15: tabla `refresh_queue` (orden de relectura por suscripcion).

Una fila por orden de refrescar una suscripcion (`source`, `subscription_external_id`) con `reason`
(`webhook_failed`, `manual`, `post_write`), `state` (`pending`, `running`, `done`, `failed`), intentos, `not_before`
(backoff) y codigo fijo de error. Indice unico parcial `(source, subscription_external_id) WHERE state IN
('pending','running')`: una sola orden viva por suscripcion (encolar dos veces no duplica). Sin datos personales.

Solo crea una tabla nueva (sin tocar datos existentes). Reversible: el downgrade la borra. La aplica el usuario.

Revision ID: 20261102_0063
Revises: 20261102_0062
Create Date: 2026-11-02 15:30:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261102_0063"
down_revision = "20261102_0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refresh_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("subscription_external_id", sa.String(255), nullable=False),
        sa.Column("reason", sa.String(20), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_error_code", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("state IN ('pending', 'running', 'done', 'failed')", name="ck_refresh_queue_state"),
        sa.CheckConstraint("reason IN ('webhook_failed', 'manual', 'post_write')", name="ck_refresh_queue_reason"),
    )
    op.create_index(
        "uq_refresh_queue_live_target", "refresh_queue", ["source", "subscription_external_id"], unique=True,
        postgresql_where=sa.text("state IN ('pending', 'running')"),
    )
    op.create_index("ix_refresh_queue_state_not_before", "refresh_queue", ["state", "not_before"])


def downgrade() -> None:
    op.drop_index("ix_refresh_queue_state_not_before", table_name="refresh_queue")
    op.drop_index("uq_refresh_queue_live_target", table_name="refresh_queue")
    op.drop_table("refresh_queue")
