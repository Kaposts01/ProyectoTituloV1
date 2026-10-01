import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CanonicalRecord(Base):
    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_records.id"), nullable=True, unique=True
    )
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Client(CanonicalRecord):
    __tablename__ = "clients"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_client_source_external_id"),)

    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    phone_number: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str | None] = mapped_column(String(50), index=True)
    social_id: Mapped[str | None] = mapped_column(String(50), index=True)
    gender_id: Mapped[str | None] = mapped_column(String(50))
    birth_date: Mapped[str | None] = mapped_column(String(50))
    provider_created_at: Mapped[str | None] = mapped_column(String(50))
    private_note: Mapped[str | None] = mapped_column(String(2000))
    cards: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)


class Plan(CanonicalRecord):
    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_plan_source_external_id"),)

    name: Mapped[str | None] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(String(2000))
    amount: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str | None] = mapped_column(String(10))
    plan_type: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[str | None] = mapped_column(String(10), index=True)
    status: Mapped[str | None] = mapped_column(String(50), index=True)


class Subscription(CanonicalRecord):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_subscription_source_external_id"),)

    client_external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    client_social_id: Mapped[str | None] = mapped_column(String(50), index=True)
    plan_external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    service_id: Mapped[str | None] = mapped_column(String(255), index=True)
    status: Mapped[str | None] = mapped_column(String(50), index=True)
    automatic_renewal: Mapped[str | None] = mapped_column(String(10))
    suscription_date: Mapped[str | None] = mapped_column(String(50))
    canceled_at: Mapped[str | None] = mapped_column(String(50))
    amount: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str | None] = mapped_column(String(10))


class Charge(CanonicalRecord):
    __tablename__ = "charges"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_charge_source_external_id"),)

    subscription_external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    client_external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    amount: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str | None] = mapped_column(String(50), index=True)
    charge_date: Mapped[str | None] = mapped_column(String(50))


class Payment(CanonicalRecord):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_payment_source_external_id"),)

    charge_external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    client_external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    amount: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str | None] = mapped_column(String(50), index=True)
    payment_date: Mapped[str | None] = mapped_column(String(50))


class PaymentMethod(CanonicalRecord):
    __tablename__ = "payment_methods"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_payment_method_source_external_id"),)

    client_external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    status: Mapped[str | None] = mapped_column(String(50), index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)
