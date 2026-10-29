"""Historial de cambios de estado/monto (SYNC-D-02/03): diff previo al upsert de la consolidacion.

Enganche en `channel_consolidation._upsert_centralized` (decision D7: en el codigo, no en un trigger):
por trozo se leen los valores previos (una SELECT indexada por `(source, external_id)`), se comparan en
Python y se insertan los eventos con `ON CONFLICT (dedupe_key) DO NOTHING` dentro de un SAVEPOINT propio.
Si la tabla de eventos falla, se registra un aviso y la consolidacion sigue igual.

Los eventos NO guardan datos personales: solo ids externos, estados, montos y marcas de tiempo.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.crm import Charge, Payment, Subscription
from app.models.status_change import RejectionReasonCatalog, StatusChangeEvent

logger = logging.getLogger(__name__)

_EVENT_CHUNK = 2000
_MAX_VALUE_LEN = 500
# Claves transitorias que un consolidador puede poner en una fila de `charges` (no son columnas).
REASON_CODE_KEY = "_rejection_code"
REASON_TEXT_KEY = "_rejection_reason"

# modelo -> (entity_type, campos vigilados). Clients/Plans/PaymentMethods quedan fuera (volumen sin valor).
TRACKED: dict[type, tuple[str, tuple[str, ...]]] = {
    Charge: ("charge", ("status", "amount")),
    Subscription: ("subscription", ("status", "amount")),
    Payment: ("payment", ("status",)),
}


@dataclass
class EventContext:
    """Corrida que genera los eventos. `token` reemplaza a `run_id` cuando no hay corrida registrada."""

    run_id: uuid.UUID | None = None
    baseline: bool = False
    enabled: bool = True
    token: str = field(default_factory=lambda: uuid.uuid4().hex)
    emitted: int = 0

    @property
    def run_key(self) -> str:
        return str(self.run_id) if self.run_id is not None else f"token:{self.token}"


_CTX: ContextVar[EventContext | None] = ContextVar("status_events_ctx", default=None)


@contextmanager
def event_context(
    run_id: uuid.UUID | None = None, baseline: bool | None = None, enabled: bool | None = None
) -> Iterator[EventContext]:
    """Fija la corrida para los upserts del bloque. `baseline`/`enabled` None = valor de configuracion."""
    ctx = EventContext(
        run_id=run_id,
        baseline=settings.status_events_baseline if baseline is None else baseline,
        enabled=settings.status_events_enabled if enabled is None else enabled,
    )
    token = _CTX.set(ctx)
    try:
        yield ctx
    finally:
        _CTX.reset(token)


def _norm_text(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _amount_changed(old: Any, new: Any) -> bool:
    old_d, new_d = _to_decimal(old), _to_decimal(new)
    if old_d is not None and new_d is not None:
        return old_d != new_d
    return _norm_text(old) != _norm_text(new)


def _amount_for_event(value: Any) -> Decimal | None:
    parsed = _to_decimal(value)
    if parsed is None or abs(parsed) >= Decimal(10) ** 16:
        return None
    return parsed.quantize(Decimal("0.01"))


def _clip(value: str | None) -> str | None:
    return None if value is None else value[:_MAX_VALUE_LEN]


def _dedupe_key(entity: str, source: str, external_id: str, kind: str, fld: str, old: str | None, new: str | None,
                run_key: str) -> str:
    raw = "|".join([entity, source, external_id, kind, fld, old or "", new or "", run_key])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def pop_reason_hints(chunk: list[dict]) -> dict[tuple[str, str], tuple[str, str]]:
    """Quita las claves transitorias de glosa de las filas y devuelve {(source, external_id): (codigo, glosa)}."""
    hints: dict[tuple[str, str], tuple[str, str]] = {}
    for row in chunk:
        if REASON_CODE_KEY in row or REASON_TEXT_KEY in row:
            code = _norm_text(row.pop(REASON_CODE_KEY, None)) or ""
            reason = _norm_text(row.pop(REASON_TEXT_KEY, None)) or ""
            if code or reason:
                hints[(row["source"], row["external_id"])] = (code[:100], reason)
    return hints


def _previous_values(db: Session, model: type, chunk: list[dict], fields: tuple[str, ...]) -> dict[tuple[str, str], dict]:
    by_source: dict[str, list[str]] = {}
    for row in chunk:
        by_source.setdefault(row["source"], []).append(row["external_id"])
    columns = [getattr(model, f) for f in fields]
    previous: dict[tuple[str, str], dict] = {}
    for source, ids in by_source.items():
        stmt = select(model.external_id, *columns).where(model.source == source, model.external_id.in_(ids))
        for external_id, *values in db.execute(stmt):
            previous[(source, external_id)] = dict(zip(fields, values, strict=True))
    return previous


def build_events(
    model: type, chunk: list[dict], previous: dict[tuple[str, str], dict], ctx: EventContext, now: datetime
) -> tuple[list[dict], set[tuple[str, str]]]:
    """Diff puro (sin BD). Devuelve (eventos, claves (source, external_id) que son nuevas o cambiaron de estado)."""
    entity, fields = TRACKED[model]
    events: list[dict] = []
    reason_candidates: set[tuple[str, str]] = set()

    def add(row: dict, kind: str, fld: str, old: str | None, new: str | None) -> None:
        sub_id = row["external_id"] if entity == "subscription" else row.get("subscription_external_id")
        events.append({
            "id": uuid.uuid4(),
            "entity_type": entity,
            "source": row["source"],
            "external_id": row["external_id"],
            "subscription_external_id": sub_id,
            "event_kind": kind,
            "field": fld,
            "from_value": _clip(old),
            "to_value": _clip(new),
            "amount": _amount_for_event(row.get("amount")) if "amount" in fields else None,
            "detected_at": now,
            "run_id": ctx.run_id,
            "is_baseline": ctx.baseline,
            "dedupe_key": _dedupe_key(entity, row["source"], row["external_id"], kind, fld, old, new, ctx.run_key),
        })

    for row in chunk:
        key = (row["source"], row["external_id"])
        prev = previous.get(key)
        if prev is None:
            add(row, "created", "record", None, _norm_text(row.get("status")))
            reason_candidates.add(key)
            continue
        if "status" in fields and _norm_text(prev["status"]) != _norm_text(row.get("status")):
            add(row, "status_changed", "status", _norm_text(prev["status"]), _norm_text(row.get("status")))
            reason_candidates.add(key)
        if "amount" in fields and _amount_changed(prev["amount"], row.get("amount")):
            add(row, "amount_changed", "amount", _norm_text(prev["amount"]), _norm_text(row.get("amount")))
    return events, reason_candidates


def _record_reasons(
    db: Session, model: type, chunk: list[dict], hints: dict[tuple[str, str], tuple[str, str]],
    candidates: set[tuple[str, str]], ctx: EventContext, now: datetime,
) -> list[dict]:
    """Alimenta el catalogo con las glosas de cobros nuevos o recien cambiados; devuelve eventos `reason_changed`."""
    entity, _ = TRACKED[model]
    counts: dict[tuple[str, str, str], list] = {}
    for row in chunk:
        key = (row["source"], row["external_id"])
        if key not in candidates or key not in hints:
            continue
        code, reason = hints[key]
        item = counts.setdefault((row["source"], code, reason), [0, row])
        item[0] += 1
    events: list[dict] = []
    for (source, code, reason), (n, sample) in counts.items():
        stmt = (
            insert(RejectionReasonCatalog)
            .values(id=uuid.uuid4(), source=source, code=code, reason=reason, first_seen_at=now, last_seen_at=now,
                    occurrences=n)
            .on_conflict_do_update(
                constraint="uq_rrc_source_code_reason",
                set_={"last_seen_at": now, "occurrences": RejectionReasonCatalog.occurrences + n},
            )
            .returning(RejectionReasonCatalog.__table__.c.first_seen_at == now)
        )
        # first_seen_at == now solo si la fila es nueva (ahora unico por corrida de este trozo).
        if db.execute(stmt).scalar_one():
            events.append({
                "id": uuid.uuid4(),
                "entity_type": entity,
                "source": source,
                "external_id": sample["external_id"],
                "subscription_external_id": sample.get("subscription_external_id"),
                "event_kind": "reason_changed",
                "field": "rejection_reason",
                "from_value": None,
                "to_value": _clip(reason or code),
                "amount": _amount_for_event(sample.get("amount")),
                "detected_at": now,
                "run_id": ctx.run_id,
                "is_baseline": ctx.baseline,
                "dedupe_key": _dedupe_key(entity, source, "catalog", "reason_changed", "rejection_reason",
                                          code, reason, "catalog"),
            })
    return events


def emit_status_events(
    db: Session, model: type, chunk: list[dict], hints: dict[tuple[str, str], tuple[str, str]] | None = None
) -> int:
    """Calcula e inserta los eventos del trozo ANTES del upsert. Nunca lanza: un fallo solo se registra."""
    if model not in TRACKED or not chunk:
        return 0
    ctx = _CTX.get()
    if ctx is None:
        ctx = EventContext(baseline=settings.status_events_baseline, enabled=settings.status_events_enabled)
    if not ctx.enabled:
        return 0
    try:
        with db.begin_nested():
            now = datetime.now(UTC)
            _, fields = TRACKED[model]
            previous = _previous_values(db, model, chunk, fields)
            events, candidates = build_events(model, chunk, previous, ctx, now)
            if hints:
                events.extend(_record_reasons(db, model, chunk, hints, candidates, ctx, now))
            inserted = 0
            for i in range(0, len(events), _EVENT_CHUNK):
                part = events[i : i + _EVENT_CHUNK]
                result = db.execute(
                    insert(StatusChangeEvent)
                    .values(part)
                    .on_conflict_do_nothing(index_elements=["dedupe_key"])
                    .returning(StatusChangeEvent.id)
                )
                inserted += len(result.all())
        ctx.emitted += inserted
        return inserted
    except Exception as exc:  # noqa: BLE001 - el historial nunca debe tumbar la consolidacion
        logger.warning("status_events: no se registraron eventos de %s (%s); la consolidacion continua",
                       model.__tablename__, type(exc).__name__)
        return 0
