import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ChargeRecovery(Base):
    """One provider-accepted retry request and its later financial outcome."""

    __tablename__ = "charge_recoveries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    charge_external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subscription_external_id: Mapped[str | None] = mapped_column(String(255), index=True)
    write_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("write_runs.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True, default="en_seguimiento")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    observed_charge_status: Mapped[str | None] = mapped_column(String(50))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
