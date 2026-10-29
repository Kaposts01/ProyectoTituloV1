"""Reportes descargados de Toku (carga manual): tablas `tk_report_*` y senales de suscripcion.

Sin datos personales: no hay nombre, mail, telefono, RUT, tarjeta, token ni payload crudo. El `ID Producto`
de los reportes contiene el RUT del socio, por eso solo se guarda `product_key_hash` (HMAC-SHA256 en hex,
calculado por el parser con un pepper) junto con el `sub_` resuelto.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

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
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

REPORT_TYPES = ("productos", "intentos", "medios_pago", "deudas", "inscripciones", "clientes", "pagos")
FILE_STATUSES = ("running", "completed", "failed")
CODE_SEVERITIES = ("SU", "TE", "PE", "UE")
SEVERITIES = (*CODE_SEVERITIES, "UNKNOWN")
LIFECYCLE_STATUSES = ("active", "deleted", "unknown")
RECOVERABLE_REASONS = ("streak", "blocked_card", "expired_card")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


def _file_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("tk_report_files.id"), nullable=False)


class TkReportFile(Base):
    __tablename__ = "tk_report_files"
    __table_args__ = (
        UniqueConstraint("report_type", "file_sha256", name="uq_tk_report_files_type_sha"),
        CheckConstraint(_in("report_type", REPORT_TYPES), name="ck_tkr_files_report_type"),
        CheckConstraint(_in("status", FILE_STATUSES), name="ck_tkr_files_status"),
        CheckConstraint("file_sha256 ~ '^[0-9a-f]{64}$'", name="ck_tkr_files_sha256"),
        CheckConstraint(
            "rows_total >= 0 AND rows_new >= 0 AND rows_updated >= 0 AND rows_skipped >= 0",
            name="ck_tkr_files_rows",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    report_type: Mapped[str] = mapped_column(String(30), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)  # solo nombre, sin ruta
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_start: Mapped[date | None] = mapped_column(Date)
    window_end: Mapped[date | None] = mapped_column(Date)
    rows_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rows_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rows_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rows_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", server_default="running")
    error_label: Mapped[str | None] = mapped_column(String(100))  # etiqueta tecnica, sin PII
    etl_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("etl_runs.id"))
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class TkReportResponseCode(Base):
    __tablename__ = "tk_report_response_codes"
    __table_args__ = (
        UniqueConstraint("code", name="uq_tk_report_response_codes_code"),
        CheckConstraint("code ~ '^[0-9]{4}$'", name="ck_tkr_codes_code"),
        CheckConstraint(_in("severity", CODE_SEVERITIES), name="ck_tkr_codes_severity"),
    )

    id: Mapped[uuid.UUID] = _pk()
    code: Mapped[str] = mapped_column(String(4), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tk_report_files.id"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class TkReportProduct(Base):
    __tablename__ = "tk_report_products"
    __table_args__ = (
        UniqueConstraint("subscription_external_id", name="uq_tk_report_products_subscription"),
        CheckConstraint("due_day IS NULL OR due_day BETWEEN 1 AND 31", name="ck_tkr_products_due_day"),
        Index("ix_tk_report_products_product_key_hash", "product_key_hash"),
        Index("ix_tk_report_products_customer", "customer_external_id"),
        Index("ix_tk_report_products_payment_method", "payment_method_external_id"),
    )

    id: Mapped[uuid.UUID] = _pk()
    subscription_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    product_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payment_method_external_id: Mapped[str | None] = mapped_column(String(255))
    payment_method_status: Mapped[str | None] = mapped_column(String(100))
    payment_processor: Mapped[str | None] = mapped_column(String(100))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    due_day: Mapped[int | None] = mapped_column(SmallInteger)
    is_recurring: Mapped[bool | None] = mapped_column(Boolean)
    created_at_source: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at_source: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_file_id: Mapped[uuid.UUID] = _file_fk()
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class TkReportPaymentMethod(Base):
    """`product_key_hash = ''` significa "medio de pago sin producto asociado" (NOT NULL para que el UNIQUE funcione)."""

    __tablename__ = "tk_report_payment_methods"
    __table_args__ = (
        UniqueConstraint(
            "payment_method_external_id", "product_key_hash", name="uq_tk_report_payment_methods_pm_product"
        ),
        Index("ix_tk_report_payment_methods_pm", "payment_method_external_id"),
        Index("ix_tk_report_payment_methods_product_key_hash", "product_key_hash"),
    )

    id: Mapped[uuid.UUID] = _pk()
    payment_method_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    product_key_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    status: Mapped[str | None] = mapped_column(String(100))
    card_type: Mapped[str | None] = mapped_column(String(50))
    card_brand: Mapped[str | None] = mapped_column(String(50))
    issuer_bank: Mapped[str | None] = mapped_column(String(100))
    processor: Mapped[str | None] = mapped_column(String(100))
    last_response_code: Mapped[str | None] = mapped_column(String(10))
    last_response_message: Mapped[str | None] = mapped_column(Text)
    deleted_at_source: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at_source: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_file_id: Mapped[uuid.UUID] = _file_fk()
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class TkReportAttempt(Base):
    __tablename__ = "tk_report_attempts"
    __table_args__ = (
        UniqueConstraint("attempt_external_id", name="uq_tk_report_attempts_attempt"),
        CheckConstraint("severity IS NULL OR " + _in("severity", SEVERITIES), name="ck_tkr_attempts_severity"),
        Index("ix_tk_report_attempts_debt", "debt_external_id"),
        Index("ix_tk_report_attempts_customer", "customer_external_id"),
        Index("ix_tk_report_attempts_subscription", "subscription_external_id"),
        Index("ix_tk_report_attempts_product_key_hash", "product_key_hash"),
        Index("ix_tk_report_attempts_sub_attempted", "subscription_external_id", "attempted_at"),
    )

    id: Mapped[uuid.UUID] = _pk()
    attempt_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    debt_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    subscription_external_id: Mapped[str | None] = mapped_column(String(255))
    product_key_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    due_date: Mapped[date | None] = mapped_column(Date)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str | None] = mapped_column(String(50))
    response_code: Mapped[str | None] = mapped_column(String(4))
    severity: Mapped[str | None] = mapped_column(String(10))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    processor: Mapped[str | None] = mapped_column(String(100))
    has_mandate: Mapped[bool | None] = mapped_column(Boolean)
    deleted_at_source: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_file_id: Mapped[uuid.UUID] = _file_fk()
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class TkReportDebt(Base):
    __tablename__ = "tk_report_debts"
    __table_args__ = (
        UniqueConstraint("debt_external_id", name="uq_tk_report_debts_debt"),
        Index("ix_tk_report_debts_subscription", "subscription_external_id"),
        Index("ix_tk_report_debts_product_key_hash", "product_key_hash"),
    )

    id: Mapped[uuid.UUID] = _pk()
    debt_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    subscription_external_id: Mapped[str | None] = mapped_column(String(255))
    product_key_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    customer_external_id: Mapped[str | None] = mapped_column(String(255))
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    paid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    voided: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str | None] = mapped_column(String(50))
    deleted_at_source: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_file_id: Mapped[uuid.UUID] = _file_fk()
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class TkReportInscription(Base):
    __tablename__ = "tk_report_inscriptions"
    __table_args__ = (
        UniqueConstraint("inscription_external_id", name="uq_tk_report_inscriptions_inscription"),
        CheckConstraint("severity IS NULL OR " + _in("severity", SEVERITIES), name="ck_tkr_inscriptions_severity"),
        Index("ix_tk_report_inscriptions_subscription", "subscription_external_id"),
    )

    id: Mapped[uuid.UUID] = _pk()
    inscription_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payment_method_external_id: Mapped[str | None] = mapped_column(String(255))
    subscription_external_id: Mapped[str | None] = mapped_column(String(255))
    transaction_status: Mapped[str | None] = mapped_column(String(100))
    response_code_full: Mapped[str | None] = mapped_column(String(30))
    severity: Mapped[str | None] = mapped_column(String(10))
    payment_method_status: Mapped[str | None] = mapped_column(String(100))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_status: Mapped[str | None] = mapped_column(String(100))
    deleted_at_source: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_file_id: Mapped[uuid.UUID] = _file_fk()
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class CoreSubscriptionSignal(Base):
    __tablename__ = "core_subscription_signals"
    __table_args__ = (
        UniqueConstraint("subscription_id", name="uq_core_subscription_signals_subscription"),
        UniqueConstraint("source", "external_id", name="uq_core_subscription_signals_source_external"),
        CheckConstraint(_in("lifecycle_status", LIFECYCLE_STATUSES), name="ck_tkr_signals_lifecycle"),
        CheckConstraint(
            "last_response_severity IS NULL OR " + _in("last_response_severity", SEVERITIES),
            name="ck_tkr_signals_severity",
        ),
        CheckConstraint(
            "recoverable_reason IS NULL OR " + _in("recoverable_reason", RECOVERABLE_REASONS),
            name="ck_tkr_signals_reason",
        ),
        CheckConstraint(
            "consecutive_failed_debts >= 0 AND consecutive_failed_attempts >= 0", name="ck_tkr_signals_counters"
        ),
        Index("ix_core_subscription_signals_is_recoverable", "is_recoverable"),
        Index("ix_core_subscription_signals_recoverable_reason", "recoverable_reason"),
    )

    id: Mapped[uuid.UUID] = _pk()
    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core_subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="toku", server_default="toku")
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(20), nullable=False)
    payment_method_status: Mapped[str | None] = mapped_column(String(100))
    is_chargeable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_effectively_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    consecutive_failed_debts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    consecutive_failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_response_code: Mapped[str | None] = mapped_column(String(10))
    last_response_severity: Mapped[str | None] = mapped_column(String(10))
    recoverable_reason: Mapped[str | None] = mapped_column(String(20))
    is_recoverable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    report_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
