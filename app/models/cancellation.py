"""Solicitudes de baja de suscripcion multicanal (MGT-07): VirtualPOS, Toku, Payku y TCH.

Modelo propio (tabla nueva) en vez de extender `billing_change_requests`: ver docs/designs/baja-cascada.md §3.
La Opcion A (cambios de cobro de VirtualPOS) queda intacta, con sus estados en espanol (D38 pendiente). Esta
maquina de estados esta en INGLES. Reutiliza de la Opcion A: el advisory lock por suscripcion
(`billing_apply.subscription_lock`), la politica (`billing_policy`: autoaprobacion, doble aprobacion, expiracion) y el
patron de eventos inmutables por trigger (`billing_audit_immutable()`, creado por la migracion 0038).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

CHANNELS = ("virtualpos1", "virtualpos2", "toku", "payku", "tch")
STATUSES = (
    "pending",
    "approved",
    "applying",
    "pending_external",  # TCH: «en tramite»; se cierra con el siguiente Excel que traiga la ficha eliminada
    "completed",
    "failed",
    "requires_reconciliation",
    "rejected",
    "withdrawn",
    "expired",
    "not_executable",
)
OPEN_STATUSES = ("pending", "approved", "applying", "requires_reconciliation", "pending_external")
REASON_CODES = (
    "member_request",
    "payment_failure",
    "duplicate_subscription",
    "deceased",
    "fraud_suspected",
    "organization_decision",
    "other",
)
EVENT_TYPES = (
    "created",
    "approved",
    "self_approved",
    "rejected",
    "withdrawn",
    "expired",
    "applying",
    "step_completed",
    "step_failed",
    "step_manual",
    "completed",
    "failed",
    "requires_reconciliation",
    "not_executable",
    "reopened",
    "pending_external",
    "closed_by_report",
)
STEP_STATUSES = ("pending", "done", "failed", "skipped", "manual")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SubscriptionCancellationRequest(Base):
    __tablename__ = "subscription_cancellation_requests"
    __table_args__ = (
        CheckConstraint(_in("channel", CHANNELS), name="ck_scr_channel"),
        CheckConstraint(_in("status", STATUSES), name="ck_scr_status"),
        CheckConstraint(_in("reason_code", REASON_CODES), name="ck_scr_reason_code"),
        CheckConstraint("length(btrim(reason_comment)) > 0", name="ck_scr_reason_comment"),
        CheckConstraint("approvals_required >= 1 AND approvals_count >= 0", name="ck_scr_approvals"),
        CheckConstraint(
            "status <> 'rejected' OR length(btrim(coalesce(decision_comment, ''))) > 0",
            name="ck_scr_reject_needs_comment",
        ),
        CheckConstraint("jsonb_typeof(options) = 'object'", name="ck_scr_options_object"),
        CheckConstraint("jsonb_typeof(steps) = 'array'", name="ck_scr_steps_array"),
        CheckConstraint(
            "channel <> 'payku' OR coalesce(options ->> 'confirm_irreversible', '') = 'true'",
            name="ck_scr_payku_confirmation",  # la baja de Payku es irreversible: exige confirmacion explicita
        ),
        Index(
            "uq_scr_one_open_per_subscription",
            "channel",
            "subscription_external_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending', 'approved', 'applying', 'requires_reconciliation', 'pending_external')"
            ),
        ),
        Index("ix_scr_subscription", "channel", "subscription_external_id"),
        Index("ix_scr_status_expires", "status", "expires_at"),
        Index("ix_scr_requested_by", "requested_by_user_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    subscription_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", server_default="pending")
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    reason_comment: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    self_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    approvals_required: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")
    approvals_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[str | None] = mapped_column(Text)
    # Opciones de la cascada: cancel_pending_charges, toku_stop_mode (paused|end_date), toku_end_date, confirm_irreversible
    options: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Vista previa al crear: suscripcion, cobros pendientes y medio de pago (que se cancelara / queda manual).
    cascade_preview: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Resultado por paso: [{step, status: pending|done|failed|skipped|manual, ...codigos fijos}]
    steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    requires_reconciliation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    rules_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    write_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("write_runs.id"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(String(200))  # solo etiqueta fija, nunca texto libre
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SubscriptionCancellationRequestEvent(Base):
    """Auditoria inmutable (el trigger `billing_audit_immutable` impide UPDATE/DELETE)."""

    __tablename__ = "subscription_cancellation_request_events"
    __table_args__ = (
        CheckConstraint(_in("event_type", EVENT_TYPES), name="ck_scre_event_type"),
        Index("ix_scre_request_created", "request_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_cancellation_requests.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))  # NULL = sistema
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = _created_at()
