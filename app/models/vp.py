import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class VpClient(Base):
    __tablename__ = "vp_clients"
    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_vp_client_platform_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    social_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    gender_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    birth_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_created_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    private_note: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    cards: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class VpPlan(Base):
    __tablename__ = "vp_plans"
    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_vp_plan_platform_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    amount: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    plan_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class VpSubscription(Base):
    __tablename__ = "vp_subscriptions"
    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_vp_subscription_platform_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    client_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    client_social_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    plan_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    service_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    automatic_renewal: Mapped[str | None] = mapped_column(String(10), nullable=True)
    suscription_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    canceled_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    amount: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class VpCharge(Base):
    __tablename__ = "vp_charges"
    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_vp_charge_platform_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    subscription_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    client_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    amount: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    charge_date: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class VpPayment(Base):
    __tablename__ = "vp_payments"
    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_vp_payment_platform_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    charge_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    client_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    amount: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    payment_date: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
