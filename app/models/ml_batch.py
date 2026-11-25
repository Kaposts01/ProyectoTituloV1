"""ML-10 synthetic shadow batches, independent from sync/write run semantics."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

SCOPE = "source IN ('virtualpos1','virtualpos2','toku','payku','tch')"


class MlCoreReceipt(Base):
    __tablename__ = "ml_core_receipts"
    __table_args__ = (UniqueConstraint("id", "source", name="uq_ml_core_receipt_scope"),
                      CheckConstraint(SCOPE, name="ck_ml_core_receipt_source"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    core_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MlBatch(Base):
    __tablename__ = "ml_batches"
    __table_args__ = (
        UniqueConstraint("id", "source", name="uq_ml_batch_scope"),
        ForeignKeyConstraint(["receipt_id", "source"], ["ml_core_receipts.id", "ml_core_receipts.source"], ondelete="RESTRICT"),
        CheckConstraint(SCOPE, name="ck_ml_batch_source"),
        CheckConstraint("state IN ('queued','running','completed','completed_with_errors')", name="ck_ml_batch_state"),
        CheckConstraint("total >= 0 AND total <= 1000 AND max_age_seconds BETWEEN 1 AND 86400 AND max_attempts BETWEEN 1 AND 5", name="ck_ml_batch_limits"),
        CheckConstraint("purpose = 'synthetic'", name="ck_ml_batch_purpose"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    receipt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bundle_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    max_age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MlBatchResult(Base):
    __tablename__ = "ml_batch_results"
    __table_args__ = (UniqueConstraint("id", "source", name="uq_ml_batch_result_scope"),
                      CheckConstraint(SCOPE, name="ck_ml_batch_result_source"),
                      CheckConstraint("purpose = 'synthetic'", name="ck_ml_batch_result_purpose"))
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MlBatchItem(Base):
    __tablename__ = "ml_batch_items"
    __table_args__ = (
        ForeignKeyConstraint(["batch_id", "source"], ["ml_batches.id", "ml_batches.source"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["result_id", "source"], ["ml_batch_results.id", "ml_batch_results.source"], ondelete="RESTRICT"),
        UniqueConstraint("batch_id", "input_sha256", name="uq_ml_batch_item_input"),
        CheckConstraint("state IN ('queued','running','succeeded','failed')", name="ck_ml_batch_item_state"),
        CheckConstraint("ordinal >= 0 AND attempts BETWEEN 0 AND 5", name="ck_ml_batch_item_attempts"),
        CheckConstraint("resource_type IN ('charge','payment','transaction')", name="ck_ml_batch_item_resource"),
        CheckConstraint("(state = 'running') = (lease_token IS NOT NULL AND lease_until IS NOT NULL)", name="ck_ml_batch_item_lease"),
        CheckConstraint("(state = 'succeeded') = (result_id IS NOT NULL)", name="ck_ml_batch_item_result"),
        Index("ix_ml_batch_item_pending", "batch_id", "state", "ordinal"),
    )
    batch_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_id: Mapped[str | None] = mapped_column(String(64))


class MlBatchEvent(Base):
    __tablename__ = "ml_batch_events"
    __table_args__ = (
        ForeignKeyConstraint(["batch_id", "ordinal"], ["ml_batch_items.batch_id", "ml_batch_items.ordinal"], ondelete="RESTRICT"),
        CheckConstraint("action IN ('claimed','succeeded','retry','failed','lease_exhausted')", name="ck_ml_batch_event_action"),
        CheckConstraint("error_code IS NULL OR error_code IN ('snapshot_changed','invalid_snapshot','calculation_failed','lease_expired')", name="ck_ml_batch_event_error"),
        CheckConstraint("attempt BETWEEN 1 AND 5", name="ck_ml_batch_event_attempt"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
