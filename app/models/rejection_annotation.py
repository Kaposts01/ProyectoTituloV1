"""Immutable contextual vocabulary and append-only human decisions, independent of Core facts."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.ml.annotation_contract import CONTEXT_COLUMNS


class RejectionReasonLabel(Base):
    __tablename__ = "rejection_reason_labels"
    __table_args__ = (
        UniqueConstraint(*CONTEXT_COLUMNS, name="uq_rejection_label_context"),
        CheckConstraint("source IN ('virtualpos1','virtualpos2','toku','payku','tch')", name="ck_label_source"),
        CheckConstraint("resource_type IN ('charge','payment','transaction','subscription_state')", name="ck_label_resource"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(24), nullable=False)
    processor: Mapped[str] = mapped_column(String(40), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    processor_code: Mapped[str] = mapped_column(String(3), nullable=False)
    normalized_text: Mapped[str] = mapped_column(String(200), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(40), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    privacy_reviewed_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RejectionReasonLabelRevision(Base):
    __tablename__ = "rejection_reason_label_revisions"
    __table_args__ = (
        UniqueConstraint("label_id", "revision", name="uq_rejection_label_revision"),
        CheckConstraint("revision > 0", name="ck_label_revision_positive"),
        CheckConstraint("decision IN ('draft','approved','rejected','abstained','withdrawn')", name="ck_label_decision"),
        CheckConstraint("category IS NULL OR category IN ('FUNDS','LIMIT','TECH','EXPIRED','BLOCKED','INVALID','FRAUD','ISSUER')", name="ck_label_category"),
        CheckConstraint("severity IN ('temporary','permanent','unknown')", name="ck_label_severity"),
        CheckConstraint("decision <> 'approved' OR category IS NOT NULL", name="ck_label_approved_category"),
        CheckConstraint("decision IN ('draft','approved') OR (category IS NULL AND severity = 'unknown')", name="ck_label_no_false_label"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    label_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("rejection_reason_labels.id", ondelete="RESTRICT"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    category: Mapped[str | None] = mapped_column(String(16), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    rationale: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
