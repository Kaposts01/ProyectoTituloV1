"""status_change_events (append-only) y rejection_reason_catalog (SYNC-D-01).

Solo crea tablas nuevas: no toca datos existentes. Los eventos no guardan datos personales.

Revision ID: 20261029_0042
Revises: 20261028_0041
Create Date: 2026-10-29 10:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20261029_0042"
down_revision = "20261028_0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "status_change_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("subscription_external_id", sa.String(255)),
        sa.Column("event_kind", sa.String(20), nullable=False),
        sa.Column("field", sa.String(30), nullable=False),
        sa.Column("from_value", sa.Text()),
        sa.Column("to_value", sa.Text()),
        sa.Column("amount", sa.Numeric(18, 2)),
        sa.Column("provider_event_at", sa.DateTime(timezone=True)),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True)),
        sa.Column("is_baseline", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.UniqueConstraint("dedupe_key", name="uq_status_change_events_dedupe_key"),
        sa.CheckConstraint("entity_type IN ('charge', 'subscription', 'payment', 'client')", name="ck_sce_entity_type"),
        sa.CheckConstraint(
            "event_kind IN ('created', 'status_changed', 'amount_changed', 'reason_changed', 'removed')",
            name="ck_sce_event_kind",
        ),
    )
    op.create_index("ix_sce_detected_at", "status_change_events", ["detected_at"])
    op.create_index("ix_sce_entity_source_external", "status_change_events", ["entity_type", "source", "external_id"])
    op.create_index("ix_sce_kind_detected_at", "status_change_events", ["event_kind", "detected_at"])
    op.create_index(
        "ix_sce_detected_not_baseline",
        "status_change_events",
        ["detected_at"],
        postgresql_where=sa.text("is_baseline = false"),
    )

    # Append-only: mismo patron que billing_change_request_events (funcion propia para no acoplar migraciones).
    op.execute(
        """
        CREATE FUNCTION status_events_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% es una tabla de eventos inmutable', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_status_change_events_immutable BEFORE UPDATE OR DELETE ON status_change_events "
        "FOR EACH ROW EXECUTE FUNCTION status_events_immutable()"
    )

    op.create_table(
        "rejection_reason_catalog",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("code", sa.String(100), nullable=False, server_default=""),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("source", "code", "reason", name="uq_rrc_source_code_reason"),
    )


def downgrade() -> None:
    op.drop_table("rejection_reason_catalog")
    op.execute("DROP TRIGGER IF EXISTS trg_status_change_events_immutable ON status_change_events")
    op.drop_table("status_change_events")
    op.execute("DROP FUNCTION IF EXISTS status_events_immutable()")
