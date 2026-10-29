"""Marca de "ultimo ETL Core exitoso" por canal (SYNC-O-16), sin tablas nuevas.

Guarda una fila en ``source_records`` (``source='core_etl'``, ``resource_type='mark'``, ``external_id=<canal>``) con
el instante y los conteos del ultimo ETL Core terminado sin error. La usan `sync_all_channels`, los endpoints
manuales `/etl/core/*` y `/sync-runs/health` (para marcar ``degraded`` si el ETL Core queda mas de 24 h detras
del ultimo sync exitoso). El payload solo lleva conteos enteros: nada personal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.source_record import SourceRecord

SOURCE = "core_etl"
RESOURCE_TYPE = "mark"


def record(db: Session, channel: str, result: dict[str, Any] | None, finished_at: datetime | None = None) -> None:
    """Registra un ETL Core exitoso del canal. Idempotente por canal. No hace commit."""
    finished = finished_at or datetime.now(UTC)
    counts = {k: v for k, v in (result or {}).items() if isinstance(v, int) and not isinstance(v, bool)}
    statement = insert(SourceRecord).values(
        source=SOURCE,
        resource_type=RESOURCE_TYPE,
        external_id=channel,
        payload={"finished_at": finished.isoformat(), "result": counts},
    )
    db.execute(statement.on_conflict_do_update(constraint="uq_source_record", set_={"payload": statement.excluded.payload}))
    db.flush()


def last_finished_at(db: Session, channel: str) -> datetime | None:
    payload = db.scalar(
        select(SourceRecord.payload).where(
            SourceRecord.source == SOURCE,
            SourceRecord.resource_type == RESOURCE_TYPE,
            SourceRecord.external_id == channel,
        )
    )
    if not payload or not payload.get("finished_at"):
        return None
    try:
        value = datetime.fromisoformat(payload["finished_at"])
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)
