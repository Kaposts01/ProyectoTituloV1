"""Reportes PAT descargados del portal de VirtualPOS (VP-PAR-02 / RJ-04): tablas `vp_report_*`.

Diseno (ver `docs/data/vp-reports.md`): tablas PROPIAS, sin tocar `vp_charges`/`vp_payments`/`vp_subscriptions`
(el sync las reescribe en cada corrida; estas tablas no se pisan con el sync y no se pisan entre si).

Sin datos personales: nombre, apellido, correo, RUT, telefono, nacimiento, genero y direccion del cliente
NUNCA se leen ni se guardan. Tampoco hay `raw_payload` ni contenido de archivo.

* `card_last4`: ultimos 4 digitos del PAN (dato enmascarado que el proyecto ya guarda en
  `vp_subscriptions.raw_payload`); un CHECK impide guardar mas de 4 digitos (nunca un PAN completo ni CVV).
* `seller_code_hash`: el `Codigo de vendedor` del portal tiene forma de RUT (identificador de una persona); solo se
  guarda como HMAC-SHA256 (pepper `VP_REPORT_HASH_PEPPER`), nunca en claro.
* `platform` (virtualpos1/virtualpos2): los PAT no la traen; se deduce de las tablas `vp_*` (ver el importador).
  `platform_status` = resolved | ambiguous | unresolved; solo `resolved` tiene `platform`.

Migracion `20261029_0045`.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
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

REPORT_TYPES = ("transacciones", "suscriptores")
FILE_STATUSES = ("running", "completed", "failed")
PLATFORM_STATUSES = ("resolved", "ambiguous", "unresolved")
PLATFORMS = ("virtualpos1", "virtualpos2")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


_PLATFORM_CONSISTENT = "(platform_status = 'resolved') = (platform IS NOT NULL)"
_LAST4 = "card_last4 IS NULL OR card_last4 ~ '^[0-9]{4}$'"
_SELLER = "seller_code_hash IS NULL OR seller_code_hash ~ '^[0-9a-f]{64}$'"


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class VpReportFile(Base):
    __tablename__ = "vp_report_files"
    __table_args__ = (
        UniqueConstraint("file_sha256", name="uq_vp_report_files_sha256"),
        CheckConstraint(_in("report_type", REPORT_TYPES), name="ck_vpr_files_report_type"),
        CheckConstraint(_in("status", FILE_STATUSES), name="ck_vpr_files_status"),
        CheckConstraint("file_sha256 ~ '^[0-9a-f]{64}$'", name="ck_vpr_files_sha256"),
        CheckConstraint(
            "rows_total >= 0 AND rows_new >= 0 AND rows_updated >= 0 AND rows_skipped >= 0", name="ck_vpr_files_rows"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    report_type: Mapped[str] = mapped_column(String(20), nullable=False)
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
    error_label: Mapped[str | None] = mapped_column(String(100))
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    loaded_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


def _file_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("vp_report_files.id"), nullable=False)


class VpReportPayment(Base):
    """Un cobro del reporte `TransaccionesPAT` (clave: `Id cargo`)."""

    __tablename__ = "vp_report_payments"
    __table_args__ = (
        UniqueConstraint("charge_external_id", name="uq_vp_report_payments_charge"),
        CheckConstraint(_in("platform_status", PLATFORM_STATUSES), name="ck_vpr_pay_platform_status"),
        CheckConstraint(_PLATFORM_CONSISTENT, name="ck_vpr_pay_platform_consistent"),
        CheckConstraint(_LAST4, name="ck_vpr_pay_last4"),
        CheckConstraint(_SELLER, name="ck_vpr_pay_seller_hash"),
        Index("ix_vp_report_payments_payment", "payment_external_id"),
        Index("ix_vp_report_payments_subscription", "subscription_external_id"),
        Index("ix_vp_report_payments_platform_status", "platform_status"),
        Index("ix_vp_report_payments_scheduled", "scheduled_date"),
    )

    id: Mapped[uuid.UUID] = _pk()
    charge_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payment_external_id: Mapped[str | None] = mapped_column(String(255))  # `UUID transaccion`
    subscription_external_id: Mapped[str | None] = mapped_column(String(255))
    platform: Mapped[str | None] = mapped_column(String(50))
    platform_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unresolved", server_default="unresolved"
    )
    charge_status: Mapped[str | None] = mapped_column(String(50))
    scheduled_date: Mapped[date | None] = mapped_column(Date)
    charge_number: Mapped[int | None] = mapped_column(SmallInteger)
    charges_total: Mapped[int | None] = mapped_column(SmallInteger)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(10))
    response_code: Mapped[str | None] = mapped_column(String(100))  # solo en cobros rechazados ('' = sin codigo)
    response_text: Mapped[str | None] = mapped_column(Text)  # glosa del proveedor, solo en rechazados
    payment_medium: Mapped[str | None] = mapped_column(String(30))  # Debito / Credito / Prepago
    card_last4: Mapped[str | None] = mapped_column(String(4))
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    payout_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    payout_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pos_alias: Mapped[str | None] = mapped_column(String(255))
    seller_code_hash: Mapped[str | None] = mapped_column(String(64))
    subscription_origin: Mapped[str | None] = mapped_column(String(50))
    charge_origin: Mapped[str | None] = mapped_column(String(100))
    source_generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_file_id: Mapped[uuid.UUID] = _file_fk()
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class VpReportSubscription(Base):
    """Una suscripcion del reporte `SuscriptoresPAT` (clave: `Id de suscripcion`)."""

    __tablename__ = "vp_report_subscriptions"
    __table_args__ = (
        UniqueConstraint("subscription_external_id", name="uq_vp_report_subscriptions_subscription"),
        CheckConstraint(_in("platform_status", PLATFORM_STATUSES), name="ck_vpr_sub_platform_status"),
        CheckConstraint(_PLATFORM_CONSISTENT, name="ck_vpr_sub_platform_consistent"),
        CheckConstraint(_LAST4, name="ck_vpr_sub_last4"),
        CheckConstraint(_SELLER, name="ck_vpr_sub_seller_hash"),
        Index("ix_vp_report_subscriptions_platform_status", "platform_status"),
        Index("ix_vp_report_subscriptions_status", "status"),
    )

    id: Mapped[uuid.UUID] = _pk()
    subscription_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(50))
    platform_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unresolved", server_default="unresolved"
    )
    status: Mapped[str | None] = mapped_column(String(50))
    subscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    plan_external_id: Mapped[str | None] = mapped_column(String(255))
    charges_total: Mapped[int | None] = mapped_column(SmallInteger)
    charges_authorized: Mapped[int | None] = mapped_column(Integer)
    charges_rejected: Mapped[int | None] = mapped_column(Integer)
    charges_pending: Mapped[int | None] = mapped_column(Integer)
    charges_processing: Mapped[int | None] = mapped_column(Integer)
    charges_canceled: Mapped[int | None] = mapped_column(Integer)
    channel_origin: Mapped[str | None] = mapped_column(String(50))
    pos_alias: Mapped[str | None] = mapped_column(String(255))
    seller_code_hash: Mapped[str | None] = mapped_column(String(64))
    card_type: Mapped[str | None] = mapped_column(String(20))
    card_brand: Mapped[str | None] = mapped_column(String(50))
    card_last4: Mapped[str | None] = mapped_column(String(4))
    rejection_reason: Mapped[str | None] = mapped_column(Text)  # «Motivo de rechazo» de la suscripcion fallida
    source_generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_file_id: Mapped[uuid.UUID] = _file_fk()
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
