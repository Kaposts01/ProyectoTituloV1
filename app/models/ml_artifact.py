"""ML-08 registry metadata. No model bytes or predictions in Core entities."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class MlArtifact(Base):
    __tablename__ = "ml_artifacts"
    __table_args__ = (
        UniqueConstraint("id", "task", "source", name="uq_ml_artifact_scope"),
        CheckConstraint("task IN ('p1','p2')", name="ck_ml_artifact_task"),
        CheckConstraint("source IN ('virtualpos1','virtualpos2','toku','payku','tch')", name="ck_ml_artifact_source"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task: Mapped[str] = mapped_column(String(2), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    manifest_relative: Mapped[str] = mapped_column(String(255), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    descriptor: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MlArtifactRelease(Base):
    __tablename__ = "ml_artifact_releases"
    __table_args__ = (
        ForeignKeyConstraint(["active_artifact_id", "task", "source"], ["ml_artifacts.id", "ml_artifacts.task", "ml_artifacts.source"], name="fk_ml_release_scope", ondelete="RESTRICT"),
        CheckConstraint("revision >= 0", name="ck_ml_release_revision"),
        CheckConstraint("task IN ('p1','p2')", name="ck_ml_release_task"),
        CheckConstraint("source IN ('virtualpos1','virtualpos2','toku','payku','tch')", name="ck_ml_release_source"),
    )
    task: Mapped[str] = mapped_column(String(2), primary_key=True)
    source: Mapped[str] = mapped_column(String(16), primary_key=True)
    active_artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class MlArtifactEvent(Base):
    __tablename__ = "ml_artifact_events"
    __table_args__ = (
        UniqueConstraint("task", "source", "revision", name="uq_ml_artifact_event_revision"),
        ForeignKeyConstraint(["task", "source"], ["ml_artifact_releases.task", "ml_artifact_releases.source"], name="fk_ml_event_release", ondelete="RESTRICT"),
        ForeignKeyConstraint(["artifact_id", "task", "source"], ["ml_artifacts.id", "ml_artifacts.task", "ml_artifacts.source"], name="fk_ml_event_artifact_scope", ondelete="RESTRICT"),
        ForeignKeyConstraint(["active_after_id", "task", "source"], ["ml_artifacts.id", "ml_artifacts.task", "ml_artifacts.source"], name="fk_ml_event_active_scope", ondelete="RESTRICT"),
        CheckConstraint("revision > 0", name="ck_ml_event_revision"),
        CheckConstraint("action IN ('registered','approved','promoted','rolled_back','disabled')", name="ck_ml_event_action"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task: Mapped[str] = mapped_column(String(2), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    artifact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active_after_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
