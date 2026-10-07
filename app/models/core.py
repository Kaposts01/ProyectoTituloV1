import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CoreClient(Base):
    __tablename__ = "core_clients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (UniqueConstraint("source", "resource_type", "external_id", name="uq_external_identity"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core_clients.id"), index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    link_reason: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CoreSubscription(Base):
    __tablename__ = "core_subscriptions"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_core_subscription_source_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core_clients.id"), index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str | None] = mapped_column(String(50), index=True)
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CoreCharge(Base):
    __tablename__ = "core_charges"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_core_charge_source_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("core_subscriptions.id"), index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    period_reference: Mapped[str | None] = mapped_column(String(50))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    latest_rejection_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core_payments.id", use_alter=True, name="fk_core_charges_latest_rejection_payment")
    )
    latest_rejection_code: Mapped[str | None] = mapped_column(String(100))
    latest_rejection_reason: Mapped[str | None] = mapped_column(Text)
    latest_rejection_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CorePayment(Base):
    __tablename__ = "core_payments"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_core_payment_source_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core_subscriptions.id"), index=True)
    charge_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core_charges.id"), index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_status: Mapped[str | None] = mapped_column(String(100), index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    amount: Mapped[float | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    rejection_code: Mapped[str | None] = mapped_column(String(100))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    rejection_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CoreClientAttribute(Base):
    __tablename__ = "core_client_attributes"
    __table_args__ = (UniqueConstraint("source", "attribute_type", "attribute_value", name="uq_core_client_attribute"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("core_clients.id"), index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    attribute_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    attribute_value: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceRecordObservation(Base):
    __tablename__ = "source_record_observations"
    __table_args__ = (UniqueConstraint("source_record_id", "payload_hash", name="uq_source_observation_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("source_records.id"), nullable=False, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_sanitized: Mapped[dict] = mapped_column(JSONB, nullable=False)
    provider_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataCatalogMapping(Base):
    __tablename__ = "data_catalog_mappings"
    __table_args__ = (UniqueConstraint("source", "source_resource", "source_field", "core_entity", "core_field", name="uq_catalog_mapping"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_resource: Mapped[str] = mapped_column(String(100), nullable=False)
    source_field: Mapped[str] = mapped_column(String(150), nullable=False)
    staging_table: Mapped[str | None] = mapped_column(String(100))
    core_entity: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    core_field: Mapped[str] = mapped_column(String(150), nullable=False)
    transformation: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(30), nullable=False, default="proposed")
    limitation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QaScenario(Base):
    __tablename__ = "qa_scenarios"
    __table_args__ = (UniqueConstraint("code", name="uq_qa_scenario_code"), Index("ix_qa_scenarios_source", "source"))

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    expected_result: Mapped[str] = mapped_column(Text, nullable=False)
    coverage_status: Mapped[str] = mapped_column(String(30), nullable=False, default="planned")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
