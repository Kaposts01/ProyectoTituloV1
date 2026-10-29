"""Historial append-only de cambios de estado/monto y catalogo de glosas de rechazo (SYNC-D-01).

Los eventos NO guardan datos personales: solo ids externos, estados, montos y marcas de tiempo.
La inmutabilidad (sin UPDATE/DELETE) la impone un trigger de base (migracion 20261029_0042).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

ENTITY_TYPES = ("charge", "subscription", "payment", "client")
EVENT_KINDS = ("created", "status_changed", "amount_changed", "reason_changed", "removed")


class StatusChangeEvent(Base):
    __tablename__ = "status_change_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_status_change_events_dedupe_key"),
        CheckConstraint("entity_type IN ('charge', 'subscription', 'payment', 'client')", name="ck_sce_entity_type"),
        CheckConstraint(
            "event_kind IN ('created', 'status_changed', 'amount_changed', 'reason_changed', 'removed')",
            name="ck_sce_event_kind",
        ),
        Index("ix_sce_detected_at", "detected_at"),
        Index("ix_sce_entity_source_external", "entity_type", "source", "external_id"),
        Index("ix_sce_kind_detected_at", "event_kind", "detected_at"),
        Index("ix_sce_detected_not_baseline", "detected_at", postgresql_where=text("is_baseline = false")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    subscription_external_id: Mapped[str | None] = mapped_column(String(255))
    event_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    field: Mapped[str] = mapped_column(String(30), nullable=False)
    from_value: Mapped[str | None] = mapped_column(Text)
    to_value: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    provider_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    is_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)


class RejectionReasonCatalog(Base):
    __tablename__ = "rejection_reason_catalog"
    __table_args__ = (UniqueConstraint("source", "code", "reason", name="uq_rrc_source_code_reason"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False, server_default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
