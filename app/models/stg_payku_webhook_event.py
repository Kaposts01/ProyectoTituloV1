import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class StgPaykuWebhookEvent(Base):
    __tablename__ = "stg_payku_webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    payku_resource_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    raw_body: Mapped[str] = mapped_column(Text, nullable=False)
    headers: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    process_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
