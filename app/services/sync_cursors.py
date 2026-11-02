"""SYNC-O-08: marcas de agua por (fuente, recurso, modo) en `sync_cursors`.

Modos usados hoy:
  * ``full``:   lectura completa del recurso (la de siempre).
  * ``window``: lectura por ventana de fecha (SYNC-O-02/05, detras de `SYNC_WINDOWED_READS_ENABLED`).
`last_success_at` es el instante en que EMPEZO la lectura exitosa del recurso. La marca se escribe en la misma
transaccion que la corrida: si la corrida falla y se revierte, la marca no avanza.

Si la tabla todavia no existe (codigo desplegado antes de aplicar la migracion 20261102_0053), escribir o leer una
marca nunca rompe la sincronizacion: se hace dentro de un SAVEPOINT y se registra un aviso.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.sync_cursor import SyncCursor

logger = logging.getLogger(__name__)

MODE_FULL = "full"
MODE_WINDOW = "window"


def record_success(
    db: Session,
    source: str,
    resource: str,
    mode: str,
    *,
    started_at: datetime,
    records_seen: int = 0,
    requests_made: int = 0,
) -> None:
    """Avanza la marca de agua de (fuente, recurso, modo). No hace commit y nunca lanza."""
    now = datetime.now(UTC)
    statement = insert(SyncCursor).values(
        source=source,
        resource=resource,
        mode=mode,
        status="done",
        records_seen=records_seen,
        requests_made=requests_made,
        last_success_at=started_at,
        last_error=None,
        updated_at=now,
    )
    statement = statement.on_conflict_do_update(
        constraint="uq_sync_cursors_key",
        set_={
            "status": "done",
            "records_seen": statement.excluded.records_seen,
            "requests_made": statement.excluded.requests_made,
            "last_success_at": statement.excluded.last_success_at,
            "last_error": None,
            "updated_at": now,
        },
    )
    try:
        with db.begin_nested():
            db.execute(statement)
    except SQLAlchemyError as exc:
        logger.warning("No se pudo registrar la marca de %s/%s/%s (%s).", source, resource, mode, type(exc).__name__)


def get(db: Session, source: str, resource: str, mode: str) -> SyncCursor | None:
    """Marca de agua del modo (fila con `window_start` NULL) o None."""
    try:
        with db.begin_nested():
            return db.scalar(
                select(SyncCursor).where(
                    SyncCursor.source == source,
                    SyncCursor.resource == resource,
                    SyncCursor.mode == mode,
                    SyncCursor.window_start.is_(None),
                )
            )
    except SQLAlchemyError as exc:
        logger.warning("No se pudo leer la marca de %s/%s/%s (%s).", source, resource, mode, type(exc).__name__)
        return None


def last_success(db: Session, source: str, resource: str, mode: str | None = None) -> datetime | None:
    """Ultimo exito de (fuente, recurso) en el modo pedido, o en cualquier modo si `mode` es None."""
    query = select(func.max(SyncCursor.last_success_at)).where(
        SyncCursor.source == source, SyncCursor.resource == resource, SyncCursor.window_start.is_(None)
    )
    if mode is not None:
        query = query.where(SyncCursor.mode == mode)
    try:
        with db.begin_nested():
            value = db.scalar(query)
    except SQLAlchemyError as exc:
        logger.warning("No se pudo leer la marca de %s/%s (%s).", source, resource, type(exc).__name__)
        return None
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


def resources_health(db: Session, sources: tuple[str, ...]) -> list[dict[str, object]]:
    """`last_success_at` por (fuente, recurso, modo) de las marcas de agua; [] si no hay tabla o no hay marcas."""
    if not sources:
        return []
    try:
        with db.begin_nested():
            rows = db.execute(
                select(SyncCursor.source, SyncCursor.resource, SyncCursor.mode, SyncCursor.last_success_at)
                .where(SyncCursor.source.in_(sources), SyncCursor.window_start.is_(None))
                .order_by(SyncCursor.source, SyncCursor.resource, SyncCursor.mode)
            ).all()
    except SQLAlchemyError as exc:
        logger.warning("No se pudieron leer las marcas de sincronizacion (%s).", type(exc).__name__)
        return []
    return [
        {
            "source": row.source,
            "resource": row.resource,
            "mode": row.mode,
            "last_success_at": row.last_success_at.isoformat() if row.last_success_at else None,
        }
        for row in rows
    ]
