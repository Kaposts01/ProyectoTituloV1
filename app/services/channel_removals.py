"""Bajas por desaparicion (SYNC-D-13): suscripciones que el proveedor dejo de devolver en una sync COMPLETA.

`channel_store.upsert_channel` pone `last_seen_at` en cada fila de `vp_subscriptions`, `tk_subscriptions` y
`p_subscriptions` que llega del proveedor. Al final de una sync COMPLETA y exitosa del canal (todas las paginas de
suscripciones leidas sin ventana ni corte), `detect_removals` toma las filas vivas (`removed_at IS NULL`) que no se
vieron desde el inicio de esa lectura y:

* con la bandera `SYNC_REMOVAL_DETECTION_ENABLED` apagada (por defecto) no hace nada;
* con una lectura parcial (ventana, pagina tope, sync fallida) no hace nada: nunca se marca una baja por ventana;
* si las desaparecidas superan `SYNC_REMOVAL_MAX_RATIO` de las conocidas o `SYNC_REMOVAL_MAX_COUNT`, ABORTA sin
  marcar nada (casi seguro es un error del proveedor: pagina vacia, filtro roto) y deja una marca de alerta en
  `source_records` (`source='removal_guard'`, sin datos personales: solo canal y conteos) que lee el chequeo de
  alertas (`removal_aborted:<canal>`). La marca se borra en la siguiente corrida que no aborta;
* si no, en un SAVEPOINT pone `removed_at` en la tabla de canal y emite un evento `removed` por fila en
  `status_change_events`. Es idempotente: una fila ya marcada no vuelve a contar ni a emitir.

Que NO hace (decision de negocio pendiente): no cambia `status` del canal ni de `subscriptions` (la baja queda como
marca y evento; quien decide si una desaparicion es una baja real es una persona). Si la fila reaparece en una sync
posterior, el upsert limpia `removed_at` (sin evento de "reaparicion").
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.payku_channel import PaykuSubscription
from app.models.source_record import SourceRecord
from app.models.toku_channel import TokuSubscription
from app.models.vp import VpSubscription
from app.services.status_events import emit_removed_events

logger = logging.getLogger(__name__)

GUARD_SOURCE = "removal_guard"
GUARD_RESOURCE = "abort"

STATUS_DISABLED = "disabled"
STATUS_PARTIAL = "partial"
STATUS_NOTHING = "nothing"
STATUS_ABORTED = "aborted"
STATUS_APPLIED = "applied"
STATUS_ERROR = "error"
STATUS_UNSUPPORTED = "unsupported"

# source de la sync -> modelo de canal. VirtualPOS filtra por `platform` (las dos cuentas comparten tabla).
_MODELS: dict[str, type] = {
    "virtualpos1": VpSubscription,
    "virtualpos2": VpSubscription,
    "toku": TokuSubscription,
    "payku": PaykuSubscription,
}
_LABELS = {"virtualpos1": "VirtualPOS 1", "virtualpos2": "VirtualPOS 2", "toku": "Toku", "payku": "Payku"}


@dataclass
class RemovalOutcome:
    source: str
    status: str
    known: int = 0
    missing: int = 0
    marked: int = 0
    events: int = 0


def _scope(model: type, source: str) -> list[Any]:
    return [model.platform == source] if model is VpSubscription else []


def _exceeds_threshold(missing: int, known: int) -> bool:
    if missing > max(int(settings.sync_removal_max_count), 0):
        return True
    return known > 0 and missing / known > max(float(settings.sync_removal_max_ratio), 0.0)


def _clear_guard(db: Session, source: str) -> None:
    db.execute(delete(SourceRecord).where(
        SourceRecord.source == GUARD_SOURCE, SourceRecord.resource_type == GUARD_RESOURCE,
        SourceRecord.external_id == source))


def _save_guard(db: Session, source: str, known: int, missing: int, now: datetime) -> None:
    payload = {"known": known, "missing": missing, "max_ratio": float(settings.sync_removal_max_ratio),
               "max_count": int(settings.sync_removal_max_count), "at": now.isoformat()}
    stmt = insert(SourceRecord).values(source=GUARD_SOURCE, resource_type=GUARD_RESOURCE, external_id=source,
                                       payload=payload)
    db.execute(stmt.on_conflict_do_update(constraint="uq_source_record", set_={"payload": stmt.excluded.payload}))


def detect_removals(
    db: Session,
    source: str,
    *,
    seen_since: datetime,
    complete: bool,
    run_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> RemovalOutcome:
    """Marca las suscripciones de `source` no vistas desde `seen_since` (inicio de la lectura de suscripciones).

    `complete` debe ser True solo si TODAS las paginas de suscripciones se leyeron sin filtro de fecha y la corrida
    termino bien. No hace commit (lo hace quien llama, junto con el cierre de la corrida); escribe en un SAVEPOINT y
    nunca lanza: un fallo deja la corrida como estaba y solo se registra en el log.
    """
    if not settings.sync_removal_detection_enabled:
        return RemovalOutcome(source, STATUS_DISABLED)
    model = _MODELS.get(source)
    if model is None:
        return RemovalOutcome(source, STATUS_UNSUPPORTED)
    if not complete:
        logger.info("channel_removals: %s sin sync completa de suscripciones; no se evaluan bajas", source)
        return RemovalOutcome(source, STATUS_PARTIAL)
    now = now or datetime.now(UTC)
    alive = [*_scope(model, source), model.removed_at.is_(None)]
    try:
        with db.begin_nested():
            known = int(db.scalar(select(func.count()).select_from(model).where(*alive)) or 0)
            not_seen = or_(model.last_seen_at.is_(None), model.last_seen_at < seen_since)
            missing_rows = [(str(ext), status) for ext, status in db.execute(
                select(model.external_id, model.status).where(*alive, not_seen).order_by(model.external_id))]
            outcome = RemovalOutcome(source, STATUS_NOTHING, known=known, missing=len(missing_rows))
            if not missing_rows:
                _clear_guard(db, source)
                return outcome
            if _exceeds_threshold(len(missing_rows), known):
                _save_guard(db, source, known, len(missing_rows), now)
                outcome.status = STATUS_ABORTED
                logger.warning(
                    "channel_removals: %s abortado, %d de %d suscripciones desaparecidas superan el umbral "
                    "(max %.2f %% o %d); no se marca ninguna baja", source, len(missing_rows), known,
                    float(settings.sync_removal_max_ratio) * 100, int(settings.sync_removal_max_count))
                return outcome
            ids = [ext for ext, _ in missing_rows]
            outcome.marked = db.execute(
                update(model).where(*alive, not_seen, model.external_id.in_(ids)).values(removed_at=now)
            ).rowcount or 0
            outcome.events = emit_removed_events(db, source, missing_rows, run_id=run_id)
            _clear_guard(db, source)
            outcome.status = STATUS_APPLIED
    except Exception as exc:  # noqa: BLE001 - la deteccion de bajas nunca debe tumbar la sincronizacion
        logger.warning("channel_removals: no se evaluaron bajas de %s (%s)", source, type(exc).__name__)
        return RemovalOutcome(source, STATUS_ERROR)
    logger.info("channel_removals: %s marcadas=%d eventos=%d (de %d conocidas)", source, outcome.marked,
                outcome.events, outcome.known)
    return outcome


def removal_abort_conditions(db: Session, now: datetime) -> list:
    """Condiciones de alerta `removal_aborted:<canal>` (una por marca vigente). Solo lectura; solo conteos."""
    from app.services.alerts import SYNC_LINK, Condition

    rows = db.execute(select(SourceRecord.external_id, SourceRecord.payload).where(
        SourceRecord.source == GUARD_SOURCE, SourceRecord.resource_type == GUARD_RESOURCE
    ).order_by(SourceRecord.external_id)).all()
    found = []
    for source, payload in rows:
        data = dict(payload or {})
        label = _LABELS.get(source, source)
        found.append(Condition(
            key=f"removal_aborted:{source}", channel=label, title=f"bajas por desaparición abortadas en {label}",
            text=(f"La sync completa de {label} no devolvió {int(data.get('missing') or 0)} de "
                  f"{int(data.get('known') or 0)} suscripciones conocidas; supera el umbral y no se marcó ninguna baja."),
            details=("Probable error del proveedor (página vacía o filtro roto). Revisar antes de la próxima corrida.",),
            link=SYNC_LINK))
    return found


def describe_removal_abort(source: str) -> tuple[str, str]:
    label = _LABELS.get(source, source)
    return label, f"bajas por desaparición abortadas en {label}"
