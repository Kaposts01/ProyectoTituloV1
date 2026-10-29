"""Solicitudes de baja de suscripcion multicanal y sus eventos inmutables (MGT-07).

Tablas NUEVAS (`subscription_cancellation_requests`, `subscription_cancellation_request_events`); no toca la Opcion A ni
sus estados en espanol. Reutiliza la funcion de base `billing_audit_immutable()` creada por la migracion 0038 para
bloquear UPDATE/DELETE de los eventos. Una sola solicitud abierta por (canal, suscripcion): indice unico parcial.
La baja de Payku exige `options.confirm_irreversible = true` (CHECK). Sin datos personales. La aplica el usuario
(ningun agente corre Alembic); respaldar antes.

Revision ID: 20261029_0051
Revises: 20261029_0050
Create Date: 2026-10-29 20:30:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "20261029_0051"
down_revision = "20261029_0050"
branch_labels = None
depends_on = None

CHANNELS = "('virtualpos1', 'virtualpos2', 'toku', 'payku', 'tch')"
STATUSES = (
    "('pending', 'approved', 'applying', 'pending_external', 'completed', 'failed', 'requires_reconciliation', "
    "'rejected', 'withdrawn', 'expired', 'not_executable')"
)
REASON_CODES = (
    "('member_request', 'payment_failure', 'duplicate_subscription', 'deceased', 'fraud_suspected', "
    "'organization_decision', 'other')"
)
EVENT_TYPES = (
    "('created', 'approved', 'self_approved', 'rejected', 'withdrawn', 'expired', 'applying', 'step_completed', "
    "'step_failed', 'step_manual', 'completed', 'failed', 'requires_reconciliation', 'not_executable', 'reopened', "
    "'pending_external', 'closed_by_report')"
)
EVENTS_TABLE = "subscription_cancellation_request_events"


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "subscription_cancellation_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("subscription_external_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("reason_code", sa.String(40), nullable=False),
        sa.Column("reason_comment", sa.Text(), nullable=False),
        sa.Column("requested_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("self_approved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("approvals_required", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("approvals_count", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_comment", sa.Text()),
        sa.Column("options", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("cascade_preview", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("steps", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("requires_reconciliation", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rules_snapshot", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("write_run_id", UUID(as_uuid=True), sa.ForeignKey("write_runs.id")),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.String(200)),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(f"channel IN {CHANNELS}", name="ck_scr_channel"),
        sa.CheckConstraint(f"status IN {STATUSES}", name="ck_scr_status"),
        sa.CheckConstraint(f"reason_code IN {REASON_CODES}", name="ck_scr_reason_code"),
        sa.CheckConstraint("length(btrim(reason_comment)) > 0", name="ck_scr_reason_comment"),
        sa.CheckConstraint("approvals_required >= 1 AND approvals_count >= 0", name="ck_scr_approvals"),
        sa.CheckConstraint(
            "status <> 'rejected' OR length(btrim(coalesce(decision_comment, ''))) > 0",
            name="ck_scr_reject_needs_comment",
        ),
        sa.CheckConstraint("jsonb_typeof(options) = 'object'", name="ck_scr_options_object"),
        sa.CheckConstraint("jsonb_typeof(steps) = 'array'", name="ck_scr_steps_array"),
        sa.CheckConstraint(
            "channel <> 'payku' OR coalesce(options ->> 'confirm_irreversible', '') = 'true'",
            name="ck_scr_payku_confirmation",
        ),
    )
    op.create_index(
        "uq_scr_one_open_per_subscription",
        "subscription_cancellation_requests",
        ["channel", "subscription_external_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending', 'approved', 'applying', 'requires_reconciliation', 'pending_external')"
        ),
    )
    op.create_index(
        "ix_scr_subscription", "subscription_cancellation_requests", ["channel", "subscription_external_id"]
    )
    op.create_index("ix_scr_status_expires", "subscription_cancellation_requests", ["status", "expires_at"])
    op.create_index("ix_scr_requested_by", "subscription_cancellation_requests", ["requested_by_user_id"])

    op.create_table(
        EVENTS_TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "request_id",
            UUID(as_uuid=True),
            sa.ForeignKey("subscription_cancellation_requests.id"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("actor_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("detail", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        _ts("created_at"),
        sa.CheckConstraint(f"event_type IN {EVENT_TYPES}", name="ck_scre_event_type"),
    )
    op.create_index("ix_scre_request_created", EVENTS_TABLE, ["request_id", "created_at"])
    # Auditoria inmutable: misma funcion de base que la Opcion A (migracion 0038).
    op.execute(
        f"CREATE TRIGGER trg_{EVENTS_TABLE}_immutable BEFORE UPDATE OR DELETE ON {EVENTS_TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION billing_audit_immutable()"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_{EVENTS_TABLE}_immutable ON {EVENTS_TABLE}")
    op.drop_table(EVENTS_TABLE)
    op.drop_table("subscription_cancellation_requests")
