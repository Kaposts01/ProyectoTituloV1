"""REP-02: registro de reportes programados por correo (migracion 20261120_0085).

Una fila por (`report_kind`, `period_key`): garantiza que cada periodo se envie una sola vez aunque el programador corra
dos veces o el backend se reinicie. Solo guarda la cantidad de destinatarios (nunca las direcciones) y el NOMBRE de la
clase de la excepcion, nunca el mensaje.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

REPORT_KINDS = ("weekly", "monthly")
REPORT_DISPATCH_STATES = ("sending", "sent", "failed")


class ReportDispatch(Base):
    __tablename__ = "report_dispatches"
    __table_args__ = (
        UniqueConstraint("report_kind", "period_key", name="uq_report_dispatches_kind_period"),
        CheckConstraint("status IN ('sending', 'sent', 'failed')", name="ck_report_dispatches_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    period_key: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="sending", server_default="sending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    recipients_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_class: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
