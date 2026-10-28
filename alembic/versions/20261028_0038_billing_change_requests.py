"""Billing change requests, approvals policy, managed charges and renewal tasks (VirtualPOS option A, phase 2).

Revision ID: 20261028_0038
Revises: 20261028_0037
Create Date: 2026-10-28 12:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "20261028_0038"
down_revision = "20261028_0037"
branch_labels = None
depends_on = None

PLATFORMS = "('virtualpos1', 'virtualpos2')"
REQUEST_TYPES = "('change_amount', 'change_date', 'renew_calendar', 'one_off_charge')"
REQUEST_STATUSES = (
    "('pendiente', 'aprobada', 'aplicando', 'ejecutada', 'rechazada', 'expirada', 'retirada', "
    "'fallida', 'requiere_conciliacion', 'no_ejecutable')"
)
EVENT_TYPES = (
    "('creada', 'aprobada', 'autoaprobada', 'rechazada', 'retirada', 'expirada', 'aplicando', 'aplicada', "
    "'fallida', 'requiere_conciliacion', 'no_ejecutable', 'reintentada')"
)
MONTH_RE = r"'^[0-9]{4}-(0[1-9]|1[0-2])$'"


def _id() -> sa.Column:
    return sa.Column("id", UUID(as_uuid=True), primary_key=True)


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "billing_change_requests",
        _id(),
        sa.Column("request_type", sa.String(30), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("subscription_external_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pendiente"),
        sa.Column("requested_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("new_amount", sa.Numeric(14, 2)),
        sa.Column("previous_amount", sa.Numeric(14, 2)),
        sa.Column("new_charge_day", sa.SmallInteger()),
        sa.Column("previous_charge_day", sa.SmallInteger()),
        sa.Column("new_charge_date", sa.Date()),
        sa.Column("horizon_months", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("horizon_start_month", sa.String(7)),
        sa.Column("plan_preview", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("rules_snapshot", JSONB, nullable=False),
        sa.Column("approvals_required", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("approvals_count", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("requester_comment", sa.Text()),
        sa.Column("approved_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("self_approved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_comment", sa.Text()),
        sa.Column("write_run_id", UUID(as_uuid=True), sa.ForeignKey("write_runs.id")),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.String(2000)),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(f"request_type IN {REQUEST_TYPES}", name="ck_bcr_request_type"),
        sa.CheckConstraint(f"status IN {REQUEST_STATUSES}", name="ck_bcr_status"),
        sa.CheckConstraint(f"platform IN {PLATFORMS}", name="ck_bcr_platform"),
        sa.CheckConstraint("horizon_months BETWEEN 1 AND 60", name="ck_bcr_horizon"),
        sa.CheckConstraint("new_amount IS NULL OR new_amount > 0", name="ck_bcr_new_amount_positive"),
        sa.CheckConstraint("new_charge_day IS NULL OR new_charge_day BETWEEN 1 AND 31", name="ck_bcr_new_charge_day"),
        sa.CheckConstraint("approvals_required >= 1 AND approvals_count >= 0", name="ck_bcr_approvals"),
        sa.CheckConstraint("request_type <> 'change_amount' OR new_amount IS NOT NULL", name="ck_bcr_amount_required"),
        sa.CheckConstraint("request_type <> 'change_date' OR new_charge_day IS NOT NULL", name="ck_bcr_day_required"),
        sa.CheckConstraint(
            "request_type <> 'one_off_charge' OR (new_amount IS NOT NULL AND new_charge_date IS NOT NULL)",
            name="ck_bcr_one_off_required",
        ),
        sa.CheckConstraint(
            "status <> 'rechazada' OR length(btrim(coalesce(decision_comment, ''))) > 0",
            name="ck_bcr_reject_needs_comment",
        ),
    )
    op.create_index(
        "uq_bcr_one_open_per_subscription",
        "billing_change_requests",
        ["platform", "subscription_external_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pendiente', 'aprobada', 'aplicando', 'requiere_conciliacion')"),
    )
    op.create_index("ix_bcr_subscription", "billing_change_requests", ["platform", "subscription_external_id"])
    op.create_index("ix_bcr_status_expires", "billing_change_requests", ["status", "expires_at"])
    op.create_index("ix_bcr_requested_by", "billing_change_requests", ["requested_by_user_id"])

    op.create_table(
        "billing_change_request_events",
        _id(),
        sa.Column("request_id", UUID(as_uuid=True), sa.ForeignKey("billing_change_requests.id"), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("actor_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("detail", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        _ts("created_at"),
        sa.CheckConstraint(f"event_type IN {EVENT_TYPES}", name="ck_bcre_event_type"),
    )
    op.create_index("ix_bcre_request_created", "billing_change_request_events", ["request_id", "created_at"])

    op.create_table(
        "billing_policy",
        _id(),
        sa.Column("singleton", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("approver_roles", JSONB, nullable=False, server_default=sa.text("""'["admin"]'::jsonb""")),
        sa.Column("approver_user_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("self_approval_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("dual_approval_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("dual_threshold_subscriptions", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("dual_threshold_variation_pct", sa.Numeric(6, 2), nullable=False, server_default="50"),
        sa.Column("renewal_threshold_days", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("request_expiry_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("horizon_months", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("window_days", sa.Integer(), nullable=False, server_default="31"),
        sa.Column("updated_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("singleton", name="billing_policy_singleton_key"),
        sa.CheckConstraint("singleton IS TRUE", name="ck_bp_singleton"),
        sa.CheckConstraint("jsonb_typeof(approver_roles) = 'array'", name="ck_bp_roles_array"),
        sa.CheckConstraint("jsonb_typeof(approver_user_ids) = 'array'", name="ck_bp_users_array"),
        sa.CheckConstraint("dual_threshold_subscriptions >= 1", name="ck_bp_dual_subs"),
        sa.CheckConstraint("dual_threshold_variation_pct >= 0", name="ck_bp_dual_pct"),
        sa.CheckConstraint("renewal_threshold_days >= 1", name="ck_bp_renewal_days"),
        sa.CheckConstraint("request_expiry_days >= 1", name="ck_bp_expiry_days"),
        sa.CheckConstraint("horizon_months BETWEEN 1 AND 60", name="ck_bp_horizon"),
        sa.CheckConstraint("window_days >= 1", name="ck_bp_window_days"),
    )

    op.create_table(
        "billing_policy_audit",
        _id(),
        sa.Column("policy_id", UUID(as_uuid=True), sa.ForeignKey("billing_policy.id"), nullable=False),
        sa.Column("changed_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id")),
        _ts("changed_at"),
        sa.Column("before_values", JSONB),
        sa.Column("after_values", JSONB, nullable=False),
        sa.Column("reason", sa.Text()),
    )
    op.create_index("ix_bpa_changed_at", "billing_policy_audit", ["changed_at"])

    # Auditoria inmutable: se bloquea UPDATE/DELETE por fila en las tablas de historial.
    op.execute(
        """
        CREATE FUNCTION billing_audit_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% es una tabla de auditoria inmutable', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("billing_change_request_events", "billing_policy_audit"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION billing_audit_immutable()"
        )

    op.create_table(
        "vp_managed_charges",
        _id(),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("charge_id", sa.String(255), nullable=False),
        sa.Column("subscription_external_id", sa.String(255), nullable=False),
        sa.Column("internal_code", sa.String(255), nullable=False),
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("charge_date", sa.Date()),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("request_id", UUID(as_uuid=True), sa.ForeignKey("billing_change_requests.id")),
        sa.Column("write_run_id", UUID(as_uuid=True), sa.ForeignKey("write_runs.id")),
        sa.Column("status", sa.String(30), nullable=False, server_default="creado"),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("platform", "charge_id", name="uq_vp_managed_charge"),
        sa.CheckConstraint(f"platform IN {PLATFORMS}", name="ck_vmc_platform"),
        sa.CheckConstraint(
            "status IN ('creado', 'cancelado', 'compensado', 'requiere_conciliacion')", name="ck_vmc_status"
        ),
        sa.CheckConstraint(f"month ~ {MONTH_RE}", name="ck_vmc_month"),
        sa.CheckConstraint("amount > 0", name="ck_vmc_amount_positive"),
    )
    op.create_index("ix_vmc_subscription_month", "vp_managed_charges", ["platform", "subscription_external_id", "month"])
    op.create_index("ix_vmc_internal_code", "vp_managed_charges", ["platform", "internal_code"])
    op.create_index("ix_vmc_request", "vp_managed_charges", ["request_id"])
    op.create_index("ix_vmc_write_run", "vp_managed_charges", ["write_run_id"])

    op.create_table(
        "vp_calendar_marks",
        _id(),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("subscription_external_id", sa.String(255), nullable=False),
        sa.Column("last_scheduled_month", sa.String(7), nullable=False),
        sa.Column("last_scheduled_date", sa.Date(), nullable=False),
        sa.Column("scheduled_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("charge_day", sa.SmallInteger(), nullable=False),
        sa.Column("origin_request_id", UUID(as_uuid=True), sa.ForeignKey("billing_change_requests.id")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("platform", "subscription_external_id", name="uq_vp_calendar_mark"),
        sa.CheckConstraint(f"platform IN {PLATFORMS}", name="ck_vcm_platform"),
        sa.CheckConstraint(f"last_scheduled_month ~ {MONTH_RE}", name="ck_vcm_month"),
        sa.CheckConstraint("charge_day BETWEEN 1 AND 31", name="ck_vcm_charge_day"),
        sa.CheckConstraint("scheduled_amount > 0", name="ck_vcm_amount_positive"),
    )
    op.create_index("ix_vcm_active_last_date", "vp_calendar_marks", ["is_active", "last_scheduled_date"])
    op.create_index("ix_vcm_origin_request", "vp_calendar_marks", ["origin_request_id"])

    op.create_table(
        "billing_renewal_tasks",
        _id(),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("subscription_external_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="abierta"),
        sa.Column("priority", sa.String(10), nullable=False, server_default="normal"),
        sa.Column("last_scheduled_date", sa.Date(), nullable=False),
        sa.Column("scheduled_amount", sa.Numeric(14, 2)),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("days_remaining", sa.Integer()),
        sa.Column("data_stale", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("request_id", UUID(as_uuid=True), sa.ForeignKey("billing_change_requests.id")),
        sa.Column("close_reason", sa.String(500)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(f"platform IN {PLATFORMS}", name="ck_brt_platform"),
        sa.CheckConstraint("status IN ('abierta', 'vencida', 'cerrada', 'no_aplica')", name="ck_brt_status"),
        sa.CheckConstraint("priority IN ('normal', 'alta')", name="ck_brt_priority"),
    )
    op.create_index(
        "uq_brt_one_open_per_subscription",
        "billing_renewal_tasks",
        ["platform", "subscription_external_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('abierta', 'vencida')"),
    )
    op.create_index("ix_brt_status_due", "billing_renewal_tasks", ["status", "due_date"])
    op.create_index("ix_brt_request", "billing_renewal_tasks", ["request_id"])

    # write_runs: columnas nullable, sin backfill; no afecta a las filas ni a los escritores existentes.
    op.add_column("write_runs", sa.Column("requested_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id")))
    op.add_column(
        "write_runs", sa.Column("request_id", UUID(as_uuid=True), sa.ForeignKey("billing_change_requests.id"))
    )
    op.create_index("ix_write_runs_request_id", "write_runs", ["request_id"])

    # Fila vigente por defecto (idempotente).
    op.execute(
        "INSERT INTO billing_policy (id, singleton) VALUES (gen_random_uuid(), true) "
        "ON CONFLICT (singleton) DO NOTHING"
    )


def downgrade() -> None:
    op.drop_index("ix_write_runs_request_id", table_name="write_runs")
    op.drop_column("write_runs", "request_id")
    op.drop_column("write_runs", "requested_by_user_id")
    op.drop_table("billing_renewal_tasks")
    op.drop_table("vp_calendar_marks")
    op.drop_table("vp_managed_charges")
    for table in ("billing_policy_audit", "billing_change_request_events"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
    op.drop_table("billing_policy_audit")
    op.drop_table("billing_policy")
    op.drop_table("billing_change_request_events")
    op.execute("DROP FUNCTION IF EXISTS billing_audit_immutable()")
    op.drop_table("billing_change_requests")
