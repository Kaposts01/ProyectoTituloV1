"""Cola de refrescos dirigidos por suscripcion (SYNC-O-15).

Complementa a `webhook_events` (RT-04/05), que ya es la cola de hecho para los avisos de webhook: alli se deduplica por
notificacion, se reclama con `FOR UPDATE SKIP LOCKED`, se reintenta con backoff y se deja `failed` al agotar intentos.
Esta tabla cubre lo que faltaba: una orden de relectura por SUSCRIPCION, independiente de la notificacion que la origino
(`reason`: `webhook_failed` = un evento agoto sus intentos; `manual`/`post_write` quedan disponibles para otros llamadores),
que la reconciliacion dirigida (RT-06) consume primero. Una sola orden viva por suscripcion: indice unico parcial sobre
`(source, subscription_external_id)` mientras esta `pending` o `running`. Sin datos personales: solo ids y codigos fijos.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

REFRESH_QUEUE_STATES = ("pending", "running", "done", "failed")
REFRESH_QUEUE_REASONS = ("webhook_failed", "manual", "post_write")


class RefreshQueueItem(Base):
    __tablename__ = "refresh_queue"
    __table_args__ = (
        CheckConstraint("state IN ('pending', 'running', 'done', 'failed')", name="ck_refresh_queue_state"),
        CheckConstraint("reason IN ('webhook_failed', 'manual', 'post_write')", name="ck_refresh_queue_reason"),
        Index(
            "uq_refresh_queue_live_target", "source", "subscription_external_id", unique=True,
            postgresql_where=text("state IN ('pending', 'running')"),
        ),
        Index("ix_refresh_queue_state_not_before", "state", "not_before"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(30), nullable=False)  # virtualpos1 | virtualpos2 | toku | payku
    subscription_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
