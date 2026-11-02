"""SYNC-O-08: marcas de agua y cursores de lectura por (fuente, recurso, modo).

Una fila con `window_start` NULL es la marca de agua de un modo (p. ej. `full` o `window`): `last_success_at` es el
instante en que EMPEZO la ultima lectura exitosa de ese recurso, asi que todo lo que cambio despues cae en la
siguiente ventana. Las filas con `window_start` son ventanas de una carga historica (SYNC-O-13, todavia sin uso).
La clave unica trata NULL como igual (`NULLS NOT DISTINCT`, PostgreSQL 15+): hay una sola marca por modo.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class SyncCursor(Base):
    __tablename__ = "sync_cursors"
    __table_args__ = (
        UniqueConstraint(
            "source", "resource", "mode", "window_start", name="uq_sync_cursors_key", postgresql_nulls_not_distinct=True
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    resource: Mapped[str] = mapped_column(String(40), nullable=False)
    mode: Mapped[str] = mapped_column(String(12), nullable=False)
    window_start: Mapped[date | None] = mapped_column(Date)
    window_end: Mapped[date | None] = mapped_column(Date)
    cursor: Mapped[str | None] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="pending")
    records_seen: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    requests_made: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_by: Mapped[str | None] = mapped_column(String(60))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
