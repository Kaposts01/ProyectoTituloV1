"""EXP-06 (d114 opcion b): exportaciones CSV en segundo plano (migracion 20261102_0065).

Una fila por job: quien lo pidio, entidad y canal, estado (`queued`, `running`, `completed`, `failed`, `expired`), si el
archivo lleva datos personales (`export.pii`), filas estimadas y escritas, ruta del archivo en el servidor y caducidad.
`filters` guarda SOLO la version auditable de los filtros (`ExportFilters.audit()`: el texto de busqueda de un campo que
puede ser dato personal se reduce a su largo). Los filtros completos viven en memoria del proceso que corre el job.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

EXPORT_JOB_STATES = ("queued", "running", "completed", "failed", "expired")


class ExportJob(Base):
    __tablename__ = "export_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'expired')", name="ck_export_jobs_status"
        ),
        Index("ix_export_jobs_user_created", "requested_by_user_id", "created_at"),
        Index("ix_export_jobs_status_expires", "status", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    entity: Mapped[str] = mapped_column(String(20), nullable=False)
    channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", server_default="queued")
    include_pii: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    filters: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rows_estimated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rows_written: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
