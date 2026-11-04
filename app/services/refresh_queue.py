"""Cola `refresh_queue` (SYNC-O-15): ordenes de relectura por suscripcion que consume la reconciliacion dirigida.

Solape con lo ya hecho (revisado antes de implementar):
* RT-04/RT-05: `webhook_events` YA es la cola de hecho para los webhooks (dedupe por notificacion, reclamo con
  `FOR UPDATE SKIP LOCKED`, backoff, dead-letter `failed`, reproceso manual RT-14, relectura por API y no por payload,
  un solo refresh por suscripcion dentro de un lote). No se duplica nada de eso.
* RT-06: la reconciliacion dirigida YA relee por ventana de riesgo con tope, pausa y respeto del lock.
Lo que faltaba y cierra este modulo: cuando un evento de webhook agota sus intentos, la suscripcion afectada quedaba
sin relectura automatica hasta la sync diaria (el plan de RT-06 pedia incluir los «webhook con error»). Ahora el
procesador encola esa suscripcion (`reason='webhook_failed'`) y cada pasada de la reconciliacion la refresca PRIMERO.

Idempotencia: una sola orden viva por suscripcion (indice unico parcial, `ON CONFLICT DO NOTHING`); refrescar es
idempotente (`refresh_subscription` solo lee y reescribe lo mismo); una orden `done` no vuelve a procesarse.
Ciclo: `pending` -> `running` (reclamada; `not_before` pasa a ser el vencimiento del reclamo) -> `done` | de vuelta a
`pending` con backoff | `failed` al llegar a `REFRESH_QUEUE_MAX_ATTEMPTS`. Un `running` vencido (proceso caido) vuelve a
`pending`. Codigos de error fijos, nunca texto del proveedor.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.refresh_queue import REFRESH_QUEUE_REASONS, RefreshQueueItem

CLAIM_LEASE = timedelta(minutes=30)
_BACKOFF_BASE = timedelta(minutes=30)
_BACKOFF_MAX = timedelta(hours=6)
_LIVE = text("state IN ('pending', 'running')")


@dataclass(frozen=True)
class QueueItem:
    id: uuid.UUID
    source: str
    subscription_external_id: str
    attempts: int


def enqueue_refresh(db: Session, source: str, subscription_external_id: str, reason: str,
                    now: datetime | None = None) -> bool:
    """Encola una relectura. Si ya hay una orden viva para esa suscripcion no hace nada. No hace commit.

    Devuelve True si inserto una orden nueva.
    """
    if reason not in REFRESH_QUEUE_REASONS:
        raise ValueError(f"reason desconocida: {reason!r}")
    stmt = (
        insert(RefreshQueueItem)
        .values(id=uuid.uuid4(), source=source, subscription_external_id=subscription_external_id, reason=reason,
                state="pending", attempts=0, not_before=now or datetime.now(UTC))
        .on_conflict_do_nothing(index_elements=["source", "subscription_external_id"], index_where=_LIVE)
        .returning(RefreshQueueItem.id)
    )
    return db.execute(stmt).first() is not None


def recover_stale(db: Session, now: datetime) -> int:
    """`running` con el reclamo vencido (proceso caido) -> `pending`. No hace commit."""
    return db.execute(
        update(RefreshQueueItem)
        .where(RefreshQueueItem.state == "running", RefreshQueueItem.not_before <= now)
        .values(state="pending", not_before=now)
    ).rowcount or 0


def claim_due(db: Session, limit: int, now: datetime | None = None) -> list[QueueItem]:
    """Reclama hasta `limit` ordenes vencidas (`FOR UPDATE SKIP LOCKED`): `running`, `attempts` + 1. Hace commit."""
    now = now or datetime.now(UTC)
    if limit <= 0:
        return []
    recover_stale(db, now)
    rows = list(db.scalars(
        select(RefreshQueueItem)
        .where(RefreshQueueItem.state == "pending", RefreshQueueItem.not_before <= now)
        .order_by(RefreshQueueItem.created_at, RefreshQueueItem.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ))
    items = []
    for row in rows:
        row.state = "running"
        row.attempts += 1
        row.not_before = now + CLAIM_LEASE
        items.append(QueueItem(row.id, row.source, row.subscription_external_id, row.attempts))
    db.commit()
    return items


def release(db: Session, items: list[QueueItem], now: datetime | None = None) -> None:
    """Devuelve a `pending` ordenes reclamadas que no se alcanzaron a procesar (pasada cortada), sin gastar intento."""
    if not items:
        return
    now = now or datetime.now(UTC)
    for item in items:
        db.execute(update(RefreshQueueItem).where(RefreshQueueItem.id == item.id, RefreshQueueItem.state == "running")
                   .values(state="pending", not_before=now, attempts=max(item.attempts - 1, 0)))
    db.commit()


def backoff(attempts: int) -> timedelta:
    return min(_BACKOFF_BASE * (2 ** max(attempts - 1, 0)), _BACKOFF_MAX)


def finish(db: Session, item: QueueItem, error_code: str | None, now: datetime | None = None) -> str:
    """Cierra una orden reclamada: `done`, de vuelta a `pending` con backoff o `failed`. Hace commit; devuelve el estado."""
    now = now or datetime.now(UTC)
    if error_code is None:
        values = {"state": "done", "last_error_code": None, "finished_at": now}
    elif item.attempts >= settings.refresh_queue_max_attempts:
        values = {"state": "failed", "last_error_code": error_code[:40], "finished_at": now}
    else:
        values = {"state": "pending", "last_error_code": error_code[:40], "not_before": now + backoff(item.attempts)}
    db.execute(update(RefreshQueueItem).where(RefreshQueueItem.id == item.id).values(**values))
    db.commit()
    return values["state"]
