"""Synthetic prospectively registered protocol and immutable, ordered observations."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class MlProspectiveStudy(Base):
    __tablename__ = "ml_prospective_studies"
    __table_args__ = (
        CheckConstraint("source IN ('virtualpos1','virtualpos2','toku','payku','tch')", name="ck_ml_study_source"),
        CheckConstraint("purpose='synthetic'", name="ck_ml_study_purpose"),
        CheckConstraint("resource_type IN ('charge','payment','transaction')", name="ck_ml_study_resource"),
        CheckConstraint("revision BETWEEN 0 AND 2000 AND ((revision=0)=(head_event_id IS NULL))", name="ck_ml_study_revision"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(24), nullable=False)
    protocol: Mapped[dict] = mapped_column(JSONB, nullable=False)
    protocol_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    head_event_id: Mapped[str | None] = mapped_column(String(64))


class MlProspectiveEvent(Base):
    __tablename__ = "ml_prospective_events"
    __table_args__ = (
        UniqueConstraint("study_id", "revision", name="uq_ml_prospective_revision"),
        UniqueConstraint("study_id", "request_id", name="uq_ml_prospective_request"),
        CheckConstraint("revision BETWEEN 1 AND 2000", name="ck_ml_prospective_revision"),
        CheckConstraint("kind IN ('enrolled','exposed','decision','outcome')", name="ck_ml_prospective_kind"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    study_id: Mapped[str] = mapped_column(String(64), ForeignKey("ml_prospective_studies.id", ondelete="RESTRICT"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    record: Mapped[dict] = mapped_column(JSONB, nullable=False)
