"""Cola unificada de webhooks (RT-04): una fila por notificacion recibida de Toku, VirtualPOS o Payku.

El receptor solo valida y encola; el procesador (`app/services/webhook_processor.py`) toma las filas `pending`,
relee el recurso afectado por API y deja `done`, `failed` o `ignored`. NUNCA se confia en el contenido del webhook:
`payload_masked` es solo contexto (ids y estados), sin datos personales (se enmascara antes de insertar).
`last_error_code` es un codigo fijo (no texto del proveedor).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

WEBHOOK_EVENT_STATUSES = ("pending", "processing", "done", "failed", "ignored")


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_webhook_events_dedupe_key"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'done', 'failed', 'ignored')", name="ck_webhook_events_status"
        ),
        Index("ix_webhook_events_status_next_attempt", "status", "next_attempt_at"),
        Index("ix_webhook_events_source_resource", "source", "resource_external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(30), nullable=False)  # toku | virtualpos | payku
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subscription_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_masked: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
