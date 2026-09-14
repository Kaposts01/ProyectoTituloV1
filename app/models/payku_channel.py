import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
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
    amount: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
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
    amount: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
