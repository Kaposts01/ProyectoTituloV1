"""SYNC-O-10: escritura en lotes de `source_records` (antes, una sentencia INSERT por registro).

Un lote es un solo `INSERT ... VALUES (...), (...) ON CONFLICT (source, resource_type, external_id) DO UPDATE ...
WHERE <payload distinto>` con `RETURNING (xmax = 0)`, que distingue filas nuevas de actualizadas. La guarda es la
misma de antes: una fila solo se reescribe si el payload (o el `sync_context`, cuando se gestiona) cambio, asi que
repetir la escritura es idempotente (la segunda vez no cuenta nada).

PostgreSQL no admite que un mismo INSERT ... ON CONFLICT toque dos veces la misma fila: dentro de un lote, si un
`external_id` se repite, gana la ULTIMA aparicion (igual que la escritura fila a fila, donde la ultima pisaba).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, literal_column, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.source_record import SourceRecord

BATCH_SIZE = 500


@dataclass
class StoreResult:
    seen: int = 0
    inserted: int = 0
    updated: int = 0

    @property
    def processed(self) -> int:
        """Filas escritas (nuevas + cambiadas): lo que antes contaba `records_processed`."""
        return self.inserted + self.updated

    @property
    def unchanged(self) -> int:
        return max(0, self.seen - self.processed)

    def add(self, other: StoreResult) -> None:
        self.seen += other.seen
        self.inserted += other.inserted
        self.updated += other.updated


def upsert_source_records(
    db: Session,
    source: str,
    resource_type: str,
    records: Sequence[dict[str, Any]],
    *,
    external_id_fn: Callable[[dict[str, Any]], str],
    contexts: Sequence[dict[str, Any] | None] | None = None,
    batch_size: int = BATCH_SIZE,
) -> StoreResult:
    """Escribe `records` (ya saneados) en lotes. Con `contexts` (uno por registro) tambien gestiona `sync_context`."""
    result = StoreResult(seen=len(records))
    if not records:
        return result
    if contexts is not None and len(contexts) != len(records):
        raise ValueError("contexts debe tener un elemento por registro")
    track_context = contexts is not None
    rows: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        external_id = external_id_fn(record)
        row: dict[str, Any] = {
            "id": uuid.uuid4(),
            "source": source,
            "resource_type": resource_type,
            "external_id": external_id,
            "payload": record,
        }
        if track_context:
            row["sync_context"] = contexts[index]  # type: ignore[index]
        rows.pop(external_id, None)  # la ultima aparicion gana y conserva el orden de llegada
        rows[external_id] = row
    pending = list(rows.values())
    inserted_flag = literal_column("(xmax = 0)", Boolean)
    for start in range(0, len(pending), batch_size):
        chunk = pending[start : start + batch_size]
        statement = insert(SourceRecord).values(chunk)
        set_: dict[str, Any] = {"payload": statement.excluded.payload, "last_seen_at": datetime.now(UTC)}
        where = SourceRecord.payload.is_distinct_from(statement.excluded.payload)
        if track_context:
            set_["sync_context"] = statement.excluded.sync_context
            where = or_(where, SourceRecord.sync_context.is_distinct_from(statement.excluded.sync_context))
        statement = statement.on_conflict_do_update(constraint="uq_source_record", set_=set_, where=where)
        for (was_inserted,) in db.execute(statement.returning(inserted_flag)).all():
            if was_inserted:
                result.inserted += 1
            else:
                result.updated += 1
    return result
