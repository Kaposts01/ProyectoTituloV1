"""Tareas manuales de suscripcion (MGT-11/13/14), Toku en la bandeja de cambios de cobro (MGT-12) y sus permisos.

1. Tablas NUEVAS `subscription_manual_tasks` y `subscription_manual_task_events` (eventos inmutables con la funcion
   `billing_audit_immutable()` de la migracion 0038). Una sola tarea abierta (`pending`/`confirmed`) por
   (tipo, canal, suscripcion). Sin datos personales ni de tarjeta.
2. `billing_change_requests.platform` admite tambien `toku` (CHECK `ck_bcr_platform`): el cambio de monto de Toku
   reutiliza la bandeja y los aprobadores de la Opcion A (d106). El resto de tablas de la Opcion A (cobros gestionados,
   marcas de calendario, tareas de renovacion) siguen solo para VirtualPOS.
3. Permisos `subscriptions.manual_tasks.view` (admin, jefatura, soporte, ejecutivo, coordinador) y
   `subscriptions.manual_tasks.confirm` (admin, jefatura). Si un rol no existe, no falla ni lo crea.

Reversible: el downgrade borra las tablas nuevas y los permisos, y restaura el CHECK de plataforma. Si ya hay
solicitudes de Toku en la bandeja, el downgrade se NIEGA (no borra datos de negocio): hay que resolverlas antes.
La aplica el usuario (ningun agente corre Alembic contra `crm`); respaldar antes.

Revision ID: 20261102_0066
Revises: 20261102_0061
Create Date: 2026-11-02 18:00:00
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "20261102_0066"
down_revision = "20261102_0061"
branch_labels = None
depends_on = None

TASKS = "subscription_manual_tasks"
EVENTS = "subscription_manual_task_events"
TASK_TYPES = "('payment_method_retained', 'tch_bank_mandate', 'payku_amount_change')"
CHANNELS = "('virtualpos1', 'virtualpos2', 'toku', 'payku', 'tch')"
STATUSES = "('pending', 'confirmed', 'verified', 'dismissed')"
EVENT_TYPES = "('created', 'assigned', 'confirmed', 'verified', 'dismissed', 'exported')"

VIEW = "subscriptions.manual_tasks.view"
CONFIRM = "subscriptions.manual_tasks.confirm"
PERMISSIONS = {
    VIEW: "Ver tareas manuales de suscripciones (medios de pago, mandatos TCH, montos de Payku)",
    CONFIRM: "Confirmar, asignar y descartar tareas manuales de suscripciones",
}
ROLE_GRANTS = {
    "admin": (VIEW, CONFIRM),
    "jefatura": (VIEW, CONFIRM),
    "soporte": (VIEW,),
    "ejecutivo": (VIEW,),
    "coordinador": (VIEW,),
}


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _user_fk(name: str) -> sa.Column:
    return sa.Column(name, UUID(as_uuid=True), sa.ForeignKey("users.id"))


def upgrade() -> None:
    op.create_table(
        TASKS,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("task_type", sa.String(40), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("subscription_external_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        # Referencia blanda (sin FK): la 0051 sigue siendo reversible por si sola.
        sa.Column("cancellation_request_id", UUID(as_uuid=True)),
        sa.Column("target_amount", sa.Numeric(14, 2)),
        sa.Column("previous_amount", sa.Numeric(14, 2)),
        _user_fk("created_by_user_id"),
        _user_fk("assigned_to_user_id"),
        _user_fk("confirmed_by_user_id"),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("confirmation_comment", sa.Text()),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("verification_source", sa.String(40)),
        _user_fk("dismissed_by_user_id"),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        sa.Column("dismiss_comment", sa.Text()),
        sa.Column("detail", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint(f"task_type IN {TASK_TYPES}", name="ck_smt_task_type"),
        sa.CheckConstraint(f"channel IN {CHANNELS}", name="ck_smt_channel"),
        sa.CheckConstraint(f"status IN {STATUSES}", name="ck_smt_status"),
        sa.CheckConstraint(
            "status <> 'confirmed' OR (confirmed_by_user_id IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="ck_smt_confirmed_has_actor",
        ),
        sa.CheckConstraint("status <> 'verified' OR verified_at IS NOT NULL", name="ck_smt_verified_has_date"),
        sa.CheckConstraint(
            "status <> 'dismissed' OR length(btrim(coalesce(dismiss_comment, ''))) > 0",
            name="ck_smt_dismiss_needs_comment",
        ),
        sa.CheckConstraint(
            "task_type <> 'payku_amount_change' OR (channel = 'payku' AND target_amount IS NOT NULL "
            "AND target_amount > 0)",
            name="ck_smt_payku_amount",
        ),
        sa.CheckConstraint("task_type <> 'tch_bank_mandate' OR channel = 'tch'", name="ck_smt_tch_channel"),
        sa.CheckConstraint("jsonb_typeof(detail) = 'object'", name="ck_smt_detail_object"),
    )
    op.create_index(
        "uq_smt_one_open_per_subscription", TASKS, ["task_type", "channel", "subscription_external_id"],
        unique=True, postgresql_where=sa.text("status IN ('pending', 'confirmed')"),
    )
    op.create_index("ix_smt_status_type", TASKS, ["status", "task_type"])
    op.create_index("ix_smt_cancellation_request", TASKS, ["cancellation_request_id"])

    op.create_table(
        EVENTS,
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey(f"{TASKS}.id"), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        _user_fk("actor_user_id"),
        sa.Column("detail", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        _ts("created_at"),
        sa.CheckConstraint(f"event_type IN {EVENT_TYPES}", name="ck_smte_event_type"),
    )
    op.create_index("ix_smte_task_created", EVENTS, ["task_id", "created_at"])
    op.execute(
        f"CREATE TRIGGER trg_{EVENTS}_immutable BEFORE UPDATE OR DELETE ON {EVENTS} "
        "FOR EACH ROW EXECUTE FUNCTION billing_audit_immutable()"
    )

    op.drop_constraint("ck_bcr_platform", "billing_change_requests", type_="check")
    op.create_check_constraint(
        "ck_bcr_platform", "billing_change_requests", "platform IN ('virtualpos1', 'virtualpos2', 'toku')")

    bind = op.get_bind()
    for code, description in PERMISSIONS.items():
        bind.execute(
            sa.text("INSERT INTO permissions (id, code, description) VALUES (:id, :code, :description) "
                    "ON CONFLICT (code) DO NOTHING"),
            {"id": uuid.uuid4(), "code": code, "description": description},
        )
    for role, codes in ROLE_GRANTS.items():
        for code in codes:
            bind.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT roles.id, permissions.id FROM roles CROSS JOIN permissions "
                    "WHERE roles.name = :role AND permissions.code = :code ON CONFLICT DO NOTHING"
                ),
                {"role": role, "code": code},
            )


def downgrade() -> None:
    bind = op.get_bind()
    toku_rows = bind.execute(sa.text("SELECT count(*) FROM billing_change_requests WHERE platform = 'toku'")).scalar()
    if toku_rows:
        raise RuntimeError(
            "Hay solicitudes de cambio de cobro de Toku: resuélvalas o respáldelas antes de bajar la migración 0066.")
    op.drop_constraint("ck_bcr_platform", "billing_change_requests", type_="check")
    op.create_check_constraint(
        "ck_bcr_platform", "billing_change_requests", "platform IN ('virtualpos1', 'virtualpos2')")

    for code in PERMISSIONS:
        bind.execute(sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code = :code)"),
            {"code": code})
        bind.execute(sa.text("DELETE FROM permissions WHERE code = :code"), {"code": code})

    op.execute(f"DROP TRIGGER IF EXISTS trg_{EVENTS}_immutable ON {EVENTS}")
    op.drop_table(EVENTS)
    op.drop_table(TASKS)
