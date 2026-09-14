import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TokuCustomer(Base):
    __tablename__ = "tk_customers"
    __table_args__ = (UniqueConstraint("external_id", name="uq_tk_customer_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    government_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TokuSubscription(Base):
    __tablename__ = "tk_subscriptions"
    __table_args__ = (UniqueConstraint("external_id", name="uq_tk_subscription_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    amount: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    anchor: Mapped[str | None] = mapped_column(String(50), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TokuInvoice(Base):
    __tablename__ = "tk_invoices"
    __table_args__ = (UniqueConstraint("external_id", name="uq_tk_invoice_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    amount: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    due_date: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TokuTransaction(Base):
    __tablename__ = "tk_transactions"
    __table_args__ = (UniqueConstraint("external_id", name="uq_tk_transaction_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    amount: Mapped[str | None] = mapped_column(String(50), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    payment_method_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at_api: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TokuPaymentMethod(Base):
    __tablename__ = "tk_payment_methods"
    __table_args__ = (UniqueConstraint("external_id", name="uq_tk_payment_method_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
