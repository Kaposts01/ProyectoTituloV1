"""webhook_events: cola unificada de webhooks de Toku, VirtualPOS y Payku (RT-04).

Solo CREA una tabla nueva con sus indices: no toca ni reescribe datos existentes (seguro de aplicar sobre `crm`).
`payload_masked` guarda solo ids y estados (los datos personales se enmascaran antes de insertar); `last_error_code`
es un codigo fijo. La idempotencia vive en `dedupe_key` UNIQUE.

NO se agrega UNIQUE a `stg_vpos_webhook_events` ni `stg_payku_webhook_events`: esas tablas no tienen id de evento
(VirtualPOS y Payku no lo envian) y pueden tener filas duplicadas previas; el receptor deja de escribirlas y la
idempotencia pasa a `webhook_events.dedupe_key`. Las tablas stg_* quedan como historico sin cambios.

La aplica el usuario (ningun agente corre Alembic).

Revision ID: 20261029_0049
Revises: 20261029_0048
Create Date: 2026-10-29 21:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "20261029_0049"
down_revision = "20261029_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("provider_event_id", sa.String(255)),
        sa.Column("resource_type", sa.String(50)),
        sa.Column("resource_external_id", sa.String(255)),
        sa.Column("subscription_external_id", sa.String(255)),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(40)),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("payload_masked", JSONB(), nullable=False),
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.UniqueConstraint("dedupe_key", name="uq_webhook_events_dedupe_key"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'done', 'failed', 'ignored')", name="ck_webhook_events_status"
        ),
    )
    op.create_index("ix_webhook_events_status_next_attempt", "webhook_events", ["status", "next_attempt_at"])
    op.create_index("ix_webhook_events_source_resource", "webhook_events", ["source", "resource_external_id"])


def downgrade() -> None:
    op.drop_index("ix_webhook_events_source_resource", table_name="webhook_events")
    op.drop_index("ix_webhook_events_status_next_attempt", table_name="webhook_events")
    op.drop_table("webhook_events")
