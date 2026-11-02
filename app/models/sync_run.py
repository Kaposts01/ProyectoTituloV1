import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func, or_
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# Los jobs de facturacion registran su corrida en `sync_runs` con `source` = id del job, SIEMPRE con este prefijo.
# Los KPI y listados de sincronizacion de CANALES excluyen por prefijo (no por lista blanca de canales): un canal nuevo
# aparece solo, y un job de facturacion nuevo queda excluido mientras respete el prefijo (lo exige un test sobre
# BILLING_JOB_IDS).
BILLING_JOB_PREFIX = "billing_"
# Los jobs de bajas de suscripcion (expiracion y barredor) usan su propio prefijo, tambien excluido de los KPI de canales.
CANCELLATION_JOB_PREFIX = "cancellation_"


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    # SYNC-D-17: estadisticas por recurso ({recurso: {mode, seconds, pages, records, inserted, updated, unchanged, ...}})
    # y la corrida global (`etl_runs.id`) a la que pertenece. Solo nombres, conteos y duraciones: nada personal.
    resource_stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    etl_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)

    @classmethod
    def is_channel_source(cls):
        """Condicion SQL: fila de sincronizacion de un canal (no de un job de facturacion ni de bajas)."""
        return ~or_(
            cls.source.startswith(BILLING_JOB_PREFIX, autoescape=True),
            cls.source.startswith(CANCELLATION_JOB_PREFIX, autoescape=True),
        )
