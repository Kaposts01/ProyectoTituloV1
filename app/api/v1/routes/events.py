"""SSE de cambios de estado hacia el navegador (RT-11, decision D9: SSE con polling de respaldo).

`GET /api/v1/events/stream` emite, como Server-Sent Events, las filas nuevas de `status_change_events` (sin baseline).
La tabla es la fuente: el stream funciona con varios workers y sobrevive a reinicios, porque cada conexion relee la
tabla cada `EVENTS_STREAM_POLL_SECONDS`. Dentro del mismo proceso, `event_bus.notify_status_changes()` (lo llama
`status_events` al insertar) adelanta la relectura.

- Autenticacion: la cookie JWT de la sesion (el router v1 exige `get_current_user`) y el permiso `dashboard.view`, el
  mismo de `/changes/daily`. `EventSource` envia la cookie sola (mismo origen, `withCredentials`).
- Reanudacion: cada evento lleva `id: <microsegundos>.<uuid>`. Al reconectar, el navegador manda `Last-Event-ID` (o el
  cliente pasa `?last_event_id=`) y se reenvia desde ahi, con un margen de `GRACE` para transacciones que confirman
  tarde; el cliente descarta ids repetidos. Si el cursor es invalido o mas viejo que `MAX_REPLAY`, se emite `reset` y el
  cliente debe recargar sus datos.
- La conexion se cierra sola tras `EVENTS_STREAM_MAX_SECONDS` (el navegador reconecta y la sesion se revalida).
- Sin datos personales: entidad, canal, id externo del proveedor, tipo de cambio, campo, valores de estado/monto y
  fecha. Las glosas de rechazo (texto libre) no viajan: el cliente las lee de la API con su permiso.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import require_permissions
from app.db.session import SessionLocal
from app.models.status_change import StatusChangeEvent
from app.scheduler import event_bus

router = APIRouter(tags=["Events"])

GRACE = timedelta(minutes=2)  # margen para filas detectadas antes pero confirmadas despues
MAX_REPLAY = timedelta(hours=24)
BATCH_LIMIT = 200  # filas por relectura; si hay mas, la siguiente relectura continua
HEARTBEAT_SECONDS = 15.0
RETRY_MS = 5000
_SEEN_LIMIT = 5000
_TEXT_FIELDS = frozenset({"status", "amount", "record"})


@contextmanager
def _open_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def make_cursor(detected_at: datetime, event_id: uuid.UUID) -> str:
    micros = int(_aware(detected_at).timestamp() * 1_000_000)
    return f"{micros}.{event_id}"


def parse_cursor(value: str | None) -> tuple[datetime, uuid.UUID | None] | None:
    """`<microsegundos>.<uuid>` -> (fecha, id). None si falta o no es valido."""
    if not value:
        return None
    micros, _, raw_id = value.strip().partition(".")
    try:
        moment = datetime.fromtimestamp(int(micros) / 1_000_000, tz=UTC)
        return moment, uuid.UUID(raw_id) if raw_id else None
    except (ValueError, OverflowError, OSError):
        return None


def public_change(ev: StatusChangeEvent) -> dict[str, Any]:
    """Forma publica de un evento: sin datos personales ni texto libre del proveedor."""
    show_values = ev.field in _TEXT_FIELDS
    return {
        "entity": ev.entity_type,
        "source": ev.source,
        "external_id": ev.external_id,
        "subscription_external_id": ev.subscription_external_id,
        "kind": ev.event_kind,
        "field": ev.field,
        "from": ev.from_value if show_values else None,
        "to": ev.to_value if show_values else None,
        "at": _aware(ev.detected_at).isoformat(),
    }


def changes_since(db: Session, since: datetime, limit: int = BATCH_LIMIT) -> list[StatusChangeEvent]:
    """Eventos (sin baseline) detectados desde `since` (inclusive), en orden de deteccion."""
    stmt = (
        select(StatusChangeEvent)
        .where(StatusChangeEvent.is_baseline.is_(False), StatusChangeEvent.detected_at >= since)
        .order_by(StatusChangeEvent.detected_at, StatusChangeEvent.id)
        .limit(limit)
    )
    return list(db.scalars(stmt))


def format_sse(event: str, data: dict[str, Any], event_id: str | None = None) -> str:
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}")
    return "\n".join(lines) + "\n\n"


class ChangeCursor:
    """Marca de agua + ids ya enviados (para no repetir dentro del margen `GRACE`)."""

    def __init__(self, high_water: datetime, skip: uuid.UUID | None = None) -> None:
        self.high_water = high_water
        self.seen: dict[uuid.UUID, datetime] = {}
        if skip is not None:
            self.seen[skip] = high_water

    def water_mark(self) -> str:
        """Cursor sin id: reanudar desde la marca de agua (con el margen `GRACE`)."""
        return f"{int(self.high_water.timestamp() * 1_000_000)}."

    def poll(self, db: Session) -> list[StatusChangeEvent]:
        rows = changes_since(db, self.high_water - GRACE)
        fresh = [r for r in rows if r.id not in self.seen]
        for r in fresh:
            at = _aware(r.detected_at)
            self.seen[r.id] = at
            if at > self.high_water:
                self.high_water = at
        if len(rows) >= BATCH_LIMIT and not fresh and rows:
            # Ventana llena de ids ya vistos: avanza para no quedar atascado en ella.
            self.high_water = max(self.high_water, _aware(rows[-1].detected_at) + GRACE)
        if len(self.seen) > _SEEN_LIMIT:
            cutoff = self.high_water - GRACE
            self.seen = {k: v for k, v in self.seen.items() if v >= cutoff}
        return fresh


def _poll_once(cursor: ChangeCursor) -> list[tuple[str, dict[str, Any]]]:
    """Una relectura en su propia sesion corta (no se retiene una conexion durante todo el stream)."""
    with _open_session() as db:
        return [(make_cursor(r.detected_at, r.id), public_change(r)) for r in cursor.poll(db)]


def _start(cursor_value: str | None, now: datetime) -> tuple[ChangeCursor, bool]:
    """(cursor, reset). Sin cursor: desde ahora. Cursor invalido o demasiado viejo: desde ahora y `reset`."""
    if not cursor_value:
        return ChangeCursor(now), False
    parsed = parse_cursor(cursor_value)
    if parsed is None or parsed[0] < now - MAX_REPLAY or parsed[0] > now + GRACE:
        return ChangeCursor(now), True
    return ChangeCursor(parsed[0], parsed[1]), False


@router.get("/stream", dependencies=[Depends(require_permissions("dashboard.view"))])
async def stream_changes(
    request: Request,
    last_event_id_header: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    last_event_id: Annotated[str | None, Query(max_length=80, description="Cursor de reanudacion")] = None,
) -> StreamingResponse:
    """SSE de cambios de estado/monto. Eventos: `ready`, `change`, `reset` y comentarios de latido."""
    cursor, reset = _start(last_event_id_header or last_event_id, datetime.now(UTC))
    poll_every = max(float(settings.events_stream_poll_seconds), 0.2)
    max_seconds = max(float(settings.events_stream_max_seconds), 0.0)

    async def generator():
        started = time.monotonic()
        yield f"retry: {RETRY_MS}\n\n"
        if reset:
            yield format_sse("reset", {"reason": "cursor_expired"})
        yield format_sse("ready", {"poll_seconds": poll_every}, cursor.water_mark())
        last_poll = -1e9
        last_beat = time.monotonic()
        seq = event_bus.status_change_seq()
        while True:
            now_mono = time.monotonic()
            if now_mono - started >= max_seconds:
                return
            if await request.is_disconnected():
                return
            current_seq = event_bus.status_change_seq()
            if current_seq != seq or now_mono - last_poll >= poll_every:
                seq = current_seq
                last_poll = now_mono
                batch = await asyncio.to_thread(_poll_once, cursor)
                for event_id, data in batch:
                    yield format_sse("change", data, event_id)
                if batch:
                    last_beat = time.monotonic()
            if time.monotonic() - last_beat >= HEARTBEAT_SECONDS:
                yield ": ping\n\n"
                last_beat = time.monotonic()
            await asyncio.sleep(min(0.5, poll_every, max(max_seconds - (time.monotonic() - started), 0.01)))

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "X-Content-Type-Options": "nosniff"},
    )
