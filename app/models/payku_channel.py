import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class PaykuClient(Base):
    __tablename__ = "p_clients"
    __table_args__ = (UniqueConstraint("external_id", name="uq_p_client_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rut: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PaykuPlan(Base):
    __tablename__ = "p_plans"
    __table_args__ = (UniqueConstraint("external_id", name="uq_p_plan_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    code: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    total_suscription: Mapped[int | None] = mapped_column(nullable=True)
    total_suscription_active: Mapped[int | None] = mapped_column(nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PaykuSubscription(Base):
    __tablename__ = "p_subscriptions"
    __table_args__ = (UniqueConstraint("external_id", name="uq_p_subscription_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    plan_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # Estado en la taxonomia comun (PK-PAR-07, `payku_status`); `status` conserva el valor crudo de Payku.
    status_normalized: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    last_status_current_payment: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    start_date: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    end_date: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    amount: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # SYNC-D-13: ultima vez que una lectura del proveedor trajo la fila (lo pone `channel_store.upsert_channel`) y marca de
    # baja por desaparicion (la pone `channel_removals` tras una sync completa; se limpia si la fila reaparece).
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # PK-PAR-11 (migracion 0065): proxima fecha de cobro; solo la trae el reporte de suscripciones de Payku.
    next_charge_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PaykuTransaction(Base):
    __tablename__ = "p_transactions"
    __table_args__ = (UniqueConstraint("external_id", name="uq_p_transaction_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    amount: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    created_at_api: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # PK-06 (p_transactions ampliada): estado comun de cobro y datos del cobro que antes solo vivian en raw_payload.
    # `verification_key` y `authorization_code` no se guardan (el saneador los trata como credenciales de pago).
    status_normalized: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    order_ref: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PK-PAR-11 (migracion 0065): campos financieros sin equivalente en el API de suscripciones. Comision, neto y medio
    # de pago los completa el importador de reportes (`payku_report_import`); el numero de cuota sale de «Cobro: # n».
    commission: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    installment_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PaykuCycle(Base):
    """Ciclo de cobro de una suscripcion Payku (PK-06): un elemento de `paid[]` de `GET /api/sususcriptionv3`.

    Payku no tiene un recurso «cargo»: el ciclo (`payment_cycle_day`) con sus intentos (`try_number`) es lo mas
    parecido y se materializa en `core_charges` (source=payku). Clave propia `<suscripcion>:<payment_cycle_day>`
    (Payku no da id de ciclo); si llegan varios intentos del mismo ciclo se conserva el de mayor `try_number`.
    `transaction_ids` guarda los ids de `paid[].transactions[]` (estructura no documentada, Q-05) para enlazar
    `core_payments.charge_id`. Sin sandbox (DEC-10) el modelo se valida solo con fixtures sinteticas.
    """

    __tablename__ = "p_cycles"
    __table_args__ = (UniqueConstraint("external_id", name="uq_p_cycle_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subscription_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    cycle_day: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    payment_day: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    status_normalized: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    amount_paid: Mapped[str | None] = mapped_column(String(50), nullable=True)
    try_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paid_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transaction_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
