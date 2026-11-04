"""Tareas manuales de suscripcion con estados y confirmacion auditada (MGT-11, MGT-13, MGT-14).

Una tarea manual registra una accion que el CRM NO hace por API y que una persona ejecuta fuera del sistema:
- `payment_method_retained` (MGT-11, d105): al dar de baja, el medio de pago de VirtualPOS/Toku/Payku SE CONSERVA. La
  tarea deja la traza (y permite revertir la decision: quien la confirma deja constancia de lo revisado).
- `tch_bank_mandate` (MGT-13, d107): la revocacion del mandato TCH la ejecuta un ejecutivo (no Tesoreria) a mano.
  Paso de CONFIRMACION: el ejecutivo confirma que lo hizo (usuario y fecha). El Excel de TCH la verifica y la cierra.
- `payku_amount_change` (MGT-14, d108): Payku no tiene API para cambiar el monto; el ejecutivo lo cambia en el portal
  y confirma. La sincronizacion de Payku detecta el monto nuevo y cierra la tarea (`verified`).

Estados (ingles): `pending -> confirmed -> verified`; `pending -> verified` (la fuente externa lo detecta antes de la
confirmacion); `pending|confirmed -> dismissed` (descartada, comentario obligatorio). Abiertas: `pending`, `confirmed`.
Eventos inmutables por trigger (`billing_audit_immutable()`, migracion 0038). Sin datos personales ni de tarjeta.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

TASK_TYPES = ("payment_method_retained", "tch_bank_mandate", "payku_amount_change")
CHANNELS = ("virtualpos1", "virtualpos2", "toku", "payku", "tch")
STATUSES = ("pending", "confirmed", "verified", "dismissed")
OPEN_STATUSES = ("pending", "confirmed")
EVENT_TYPES = ("created", "assigned", "confirmed", "verified", "dismissed", "exported")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class SubscriptionManualTask(Base):
    __tablename__ = "subscription_manual_tasks"
    __table_args__ = (
        CheckConstraint(_in("task_type", TASK_TYPES), name="ck_smt_task_type"),
        CheckConstraint(_in("channel", CHANNELS), name="ck_smt_channel"),
        CheckConstraint(_in("status", STATUSES), name="ck_smt_status"),
        CheckConstraint(
            "status <> 'confirmed' OR (confirmed_by_user_id IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="ck_smt_confirmed_has_actor",
        ),
        CheckConstraint("status <> 'verified' OR verified_at IS NOT NULL", name="ck_smt_verified_has_date"),
        CheckConstraint(
            "status <> 'dismissed' OR length(btrim(coalesce(dismiss_comment, ''))) > 0",
            name="ck_smt_dismiss_needs_comment",
        ),
        CheckConstraint(
            "task_type <> 'payku_amount_change' OR (channel = 'payku' AND target_amount IS NOT NULL "
            "AND target_amount > 0)",
            name="ck_smt_payku_amount",
        ),
        CheckConstraint("task_type <> 'tch_bank_mandate' OR channel = 'tch'", name="ck_smt_tch_channel"),
        CheckConstraint("jsonb_typeof(detail) = 'object'", name="ck_smt_detail_object"),
        Index(
            "uq_smt_one_open_per_subscription",
            "task_type",
            "channel",
            "subscription_external_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'confirmed')"),
        ),
        Index("ix_smt_status_type", "status", "task_type"),
        Index("ix_smt_cancellation_request", "cancellation_request_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    subscription_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    # Referencia blanda (sin FK) a `subscription_cancellation_requests.id`: asi la 0051 sigue siendo reversible sola.
    cancellation_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    target_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # solo payku_amount_change
    previous_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_comment: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_source: Mapped[str | None] = mapped_column(String(40))  # payku_sync | tch_report
    dismissed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismiss_comment: Mapped[str | None] = mapped_column(Text)
    # Solo codigos fijos y conteos (p. ej. {"code": "TOKU_PAYMENT_METHOD_RETAINED"}): nunca PAN ni datos de tarjeta.
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SubscriptionManualTaskEvent(Base):
    """Auditoria inmutable (el trigger `billing_audit_immutable` impide UPDATE/DELETE)."""

    __tablename__ = "subscription_manual_task_events"
    __table_args__ = (
        CheckConstraint(_in("event_type", EVENT_TYPES), name="ck_smte_event_type"),
        Index("ix_smte_task_created", "task_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_manual_tasks.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))  # NULL = sistema
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
