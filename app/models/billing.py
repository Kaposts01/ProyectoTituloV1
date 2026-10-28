"""Facturacion gestionada VirtualPOS (opcion A): solicitudes de cambio, aprobaciones y registro propio.

Diseno: docs/designs/facturacion-gestionada-escenarios.md (decisiones 2026-10-28, seccion 5 y hallazgos).
Esta fase solo define el esquema. Las reglas de servicio (nunca quedar sin aprobador, lock por suscripcion,
transicion atomica de estados, autoaprobacion/doble aprobacion) se implementan en las fases 3 y 4.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

PLATFORMS = ("virtualpos1", "virtualpos2")
REQUEST_TYPES = ("change_amount", "change_date", "renew_calendar", "one_off_charge")
REQUEST_STATUSES = (
    "pendiente",
    "aprobada",
    "aplicando",
    "ejecutada",
    "rechazada",
    "expirada",
    "retirada",
    "fallida",
    "requiere_conciliacion",
    "no_ejecutable",
)
EVENT_TYPES = (
    "creada",
    "aprobada",
    "autoaprobada",
    "rechazada",
    "retirada",
    "expirada",
    "aplicando",
    "aplicada",
    "fallida",
    "requiere_conciliacion",
    "no_ejecutable",
    "reintentada",
)
MANAGED_CHARGE_STATUSES = ("creado", "cancelado", "compensado", "requiere_conciliacion")
TASK_STATUSES = ("abierta", "vencida", "cerrada", "no_aplica")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class BillingChangeRequest(Base):
    __tablename__ = "billing_change_requests"
    __table_args__ = (
        CheckConstraint(_in("request_type", REQUEST_TYPES), name="ck_bcr_request_type"),
        CheckConstraint(_in("status", REQUEST_STATUSES), name="ck_bcr_status"),
        CheckConstraint(_in("platform", PLATFORMS), name="ck_bcr_platform"),
        CheckConstraint("horizon_months BETWEEN 1 AND 60", name="ck_bcr_horizon"),
        CheckConstraint("new_amount IS NULL OR new_amount > 0", name="ck_bcr_new_amount_positive"),
        CheckConstraint("new_charge_day IS NULL OR new_charge_day BETWEEN 1 AND 31", name="ck_bcr_new_charge_day"),
        CheckConstraint("approvals_required >= 1 AND approvals_count >= 0", name="ck_bcr_approvals"),
        CheckConstraint(
            "request_type <> 'change_amount' OR new_amount IS NOT NULL", name="ck_bcr_amount_required"
        ),
        CheckConstraint(
            "request_type <> 'change_date' OR new_charge_day IS NOT NULL", name="ck_bcr_day_required"
        ),
        CheckConstraint(
            "request_type <> 'one_off_charge' OR (new_amount IS NOT NULL AND new_charge_date IS NOT NULL)",
            name="ck_bcr_one_off_required",
        ),
        CheckConstraint(
            "status <> 'rechazada' OR length(btrim(coalesce(decision_comment, ''))) > 0",
            name="ck_bcr_reject_needs_comment",
        ),
        Index(
            "uq_bcr_one_open_per_subscription",
            "platform",
            "subscription_external_id",
            unique=True,
            postgresql_where=text("status IN ('pendiente', 'aprobada', 'aplicando', 'requiere_conciliacion')"),
        ),
        Index("ix_bcr_subscription", "platform", "subscription_external_id"),
        Index("ix_bcr_status_expires", "status", "expires_at"),
        Index("ix_bcr_requested_by", "requested_by_user_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    request_type: Mapped[str] = mapped_column(String(30), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    subscription_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pendiente", server_default="pendiente")
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    new_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    previous_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    new_charge_day: Mapped[int | None] = mapped_column(SmallInteger)
    previous_charge_day: Mapped[int | None] = mapped_column(SmallInteger)
    new_charge_date: Mapped[date | None] = mapped_column(Date)  # solo one_off_charge
    horizon_months: Mapped[int] = mapped_column(Integer, nullable=False, default=12, server_default="12")
    horizon_start_month: Mapped[str | None] = mapped_column(String(7))  # YYYY-MM (renovacion: mes siguiente al ultimo)
    plan_preview: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    rules_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # AP-27
    approvals_required: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, server_default="1")
    approvals_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    requester_comment: Mapped[str | None] = mapped_column(Text)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    self_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[str | None] = mapped_column(Text)
    write_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("write_runs.id"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class BillingChangeRequestEvent(Base):
    """Auditoria inmutable (trigger de BD impide UPDATE/DELETE)."""

    __tablename__ = "billing_change_request_events"
    __table_args__ = (
        CheckConstraint(_in("event_type", EVENT_TYPES), name="ck_bcre_event_type"),
        Index("ix_bcre_request_created", "request_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_change_requests.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))  # NULL = sistema
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = _created_at()


class BillingPolicy(Base):
    """Politica vigente (fila unica: `singleton` es TRUE y UNIQUE).

    Regla de servicio pendiente (fase 3/4): no permitir guardar sin aprobador (sin roles ni usuarios) ni
    desactivar la autoaprobacion si no queda otro aprobador activo (AP-23, AP-24).
    """

    __tablename__ = "billing_policy"
    __table_args__ = (
        CheckConstraint("singleton IS TRUE", name="ck_bp_singleton"),
        CheckConstraint("jsonb_typeof(approver_roles) = 'array'", name="ck_bp_roles_array"),
        CheckConstraint("jsonb_typeof(approver_user_ids) = 'array'", name="ck_bp_users_array"),
        CheckConstraint("dual_threshold_subscriptions >= 1", name="ck_bp_dual_subs"),
        CheckConstraint("dual_threshold_variation_pct >= 0", name="ck_bp_dual_pct"),
        CheckConstraint("renewal_threshold_days >= 1", name="ck_bp_renewal_days"),
        CheckConstraint("request_expiry_days >= 1", name="ck_bp_expiry_days"),
        CheckConstraint("horizon_months BETWEEN 1 AND 60", name="ck_bp_horizon"),
        CheckConstraint("window_days >= 1", name="ck_bp_window_days"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    singleton: Mapped[bool] = mapped_column(
        Boolean, nullable=False, unique=True, default=True, server_default=text("true")
    )
    approver_roles: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=lambda: ["admin"], server_default=text("""'["admin"]'::jsonb""")
    )
    approver_user_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    self_approval_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    dual_approval_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    dual_threshold_subscriptions: Mapped[int] = mapped_column(Integer, nullable=False, default=20, server_default="20")
    dual_threshold_variation_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 2), nullable=False, default=Decimal("50"), server_default="50"
    )
    renewal_threshold_days: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
    request_expiry_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7, server_default="7")
    horizon_months: Mapped[int] = mapped_column(Integer, nullable=False, default=12, server_default="12")
    window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=31, server_default="31")
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class BillingPolicyAudit(Base):
    """Historial inmutable de cambios de politica (trigger de BD impide UPDATE/DELETE)."""

    __tablename__ = "billing_policy_audit"
    __table_args__ = (Index("ix_bpa_changed_at", "changed_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    policy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("billing_policy.id"), nullable=False)
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    before_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_values: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)


class VpManagedCharge(Base):
    """Registro propio de charge_id creados por el CRM (el listado de suscripciones no trae internal_code)."""

    __tablename__ = "vp_managed_charges"
    __table_args__ = (
        UniqueConstraint("platform", "charge_id", name="uq_vp_managed_charge"),
        CheckConstraint(_in("platform", PLATFORMS), name="ck_vmc_platform"),
        CheckConstraint(_in("status", MANAGED_CHARGE_STATUSES), name="ck_vmc_status"),
        CheckConstraint(r"month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="ck_vmc_month"),
        CheckConstraint("amount > 0", name="ck_vmc_amount_positive"),
        Index("ix_vmc_subscription_month", "platform", "subscription_external_id", "month"),
        Index("ix_vmc_internal_code", "platform", "internal_code"),
        Index("ix_vmc_request", "request_id"),
        Index("ix_vmc_write_run", "write_run_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    charge_id: Mapped[str] = mapped_column(String(255), nullable=False)
    subscription_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    internal_code: Mapped[str] = mapped_column(String(255), nullable=False)
    month: Mapped[str] = mapped_column(String(7), nullable=False)
    charge_date: Mapped[date | None] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("billing_change_requests.id"))
    write_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("write_runs.id"))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="creado", server_default="creado")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class VpCalendarMark(Base):
    """Suscripcion con calendario modificado (entrada del chequeo de renovacion)."""

    __tablename__ = "vp_calendar_marks"
    __table_args__ = (
        UniqueConstraint("platform", "subscription_external_id", name="uq_vp_calendar_mark"),
        CheckConstraint(_in("platform", PLATFORMS), name="ck_vcm_platform"),
        CheckConstraint(r"last_scheduled_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="ck_vcm_month"),
        CheckConstraint("charge_day BETWEEN 1 AND 31", name="ck_vcm_charge_day"),
        CheckConstraint("scheduled_amount > 0", name="ck_vcm_amount_positive"),
        Index("ix_vcm_active_last_date", "is_active", "last_scheduled_date"),
        Index("ix_vcm_origin_request", "origin_request_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    subscription_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    last_scheduled_month: Mapped[str] = mapped_column(String(7), nullable=False)
    last_scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    charge_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    origin_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing_change_requests.id")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class BillingRenewalTask(Base):
    """Tarea 'renovar calendario' generada por el chequeo diario de solo lectura."""

    __tablename__ = "billing_renewal_tasks"
    __table_args__ = (
        CheckConstraint(_in("platform", PLATFORMS), name="ck_brt_platform"),
        CheckConstraint(_in("status", TASK_STATUSES), name="ck_brt_status"),
        CheckConstraint("priority IN ('normal', 'alta')", name="ck_brt_priority"),
        Index(
            "uq_brt_one_open_per_subscription",
            "platform",
            "subscription_external_id",
            unique=True,
            postgresql_where=text("status IN ('abierta', 'vencida')"),
        ),
        Index("ix_brt_status_due", "status", "due_date"),
        Index("ix_brt_request", "request_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    subscription_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="abierta", server_default="abierta")
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="normal", server_default="normal")
    last_scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    days_remaining: Mapped[int | None] = mapped_column(Integer)
    data_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("billing_change_requests.id"))
    close_reason: Mapped[str | None] = mapped_column(String(500))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()
