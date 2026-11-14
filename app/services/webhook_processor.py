"""Procesador asincrono de la cola `webhook_events` (RT-05 / RT-07).

Toma eventos `pending` (con `FOR UPDATE SKIP LOCKED`, de modo que dos workers nunca toman el mismo evento), decide por
reglas de evento que suscripcion afecta y la relee del proveedor con `refresh_subscription` (MGT-06: solo GET, fail-closed,
idempotente). Esa relectura actualiza canal + consolidacion de ESA suscripcion y alimenta `status_change_events` con un
`run_id` propio. El contenido del webhook NUNCA se aplica: solo sirve para saber que recurso mirar.

Ciclo de vida: `pending` -> `processing` (reclamado, `attempts` + 1) -> `done` | `ignored` | de vuelta a `pending` con
backoff exponencial (`next_attempt_at`) | `failed` tras `webhook_max_attempts` (5) intentos. `last_error_code` es siempre un
codigo fijo, nunca texto del proveedor. Un `processing` abandonado (proceso caido) vuelve a `pending` pasado el plazo.

Reglas (RT-07):
  Toku         subscription.created|updated|deleted|cancelled -> refresh de la suscripcion
               invoice.paid|voided|updated|created, transaction.success|failed|status_update -> suscripcion del recurso
               payment_method.* -> suscripciones del cliente dueno del medio de pago
               `subscription.deleted` = baja: si el proveedor ya no devuelve la suscripcion (404) se marca `deleted`
               transaction.bulk_* y demas -> ignored (los cubre la conciliacion)
  VirtualPOS   payment (uuid) -> suscripcion del pago/cobro local; subscription (callback) -> esa suscripcion; payout -> ignored
  Payku        subscription -> esa suscripcion; payment|transaction|nullification -> suscripcion de la transaccion; payout -> ignored
Varios eventos de la misma suscripcion en un lote se resuelven con UN solo refresh.
SYNC-O-15: cuando un evento queda `failed` (agoto intentos), sus suscripciones se encolan en `refresh_queue`
(`reason='webhook_failed'`) y la reconciliacion dirigida las relee primero en su siguiente pasada.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.crm import Subscription
from app.models.payku_channel import PaykuTransaction
from app.models.toku_channel import (
    TokuInvoice,
    TokuPaymentMethod,
    TokuSubscription,
    TokuTransaction,
)
from app.models.vp import VpCharge, VpPayment, VpSubscription
from app.models.webhook_event import WebhookEvent
from app.services.refresh_queue import enqueue_refresh
from app.services.status_events import emit_status_events, event_context
from app.services.subscription_refresh import RefreshError, refresh_subscription

logger = logging.getLogger(__name__)

# Codigos fijos de resultado/error (nunca texto libre del proveedor).
CODE_NO_RESOURCE = "NO_RESOURCE"
CODE_UNKNOWN_EVENT = "UNKNOWN_EVENT"
CODE_BULK_EVENT = "BULK_EVENT"
CODE_IGNORED_KIND = "IGNORED_KIND"
CODE_UNEXPECTED = "UNEXPECTED"
CODE_STALE = "STALE_PROCESSING"

_TOKU_SUBSCRIPTION_EVENTS = frozenset({
    "subscription.created", "subscription.updated", "subscription.deleted", "subscription.cancelled"})
_TOKU_INVOICE_EVENTS = frozenset({"invoice.paid", "invoice.voided", "invoice.updated", "invoice.created"})
_TOKU_TRANSACTION_EVENTS = frozenset({"transaction.success", "transaction.failed", "transaction.status_update"})
_VP_EVENTS = frozenset({"payment", "subscription", "charge_paid", "charge_reject", "card_change"})
_MAX_CUSTOMER_SUBSCRIPTIONS = 10
_MAX_BACKOFF_SECONDS = 3600.0

RefreshFn = Callable[..., Awaitable[Any]]


@dataclass
class ProcessSummary:
    claimed: int = 0
    done: int = 0
    ignored: int = 0
    retried: int = 0
    failed: int = 0
    refreshes: int = 0
    codes: dict[str, int] = field(default_factory=dict)

    def count_code(self, code: str) -> None:
        self.codes[code] = self.codes.get(code, 0) + 1


@dataclass(frozen=True)
class EventSnapshot:
    """Copia desacoplada de la sesion de lo necesario para decidir (el evento ya esta `processing` en la BD)."""

    id: uuid.UUID
    source: str
    event_type: str
    resource_type: str | None
    resource_external_id: str | None
    subscription_external_id: str | None
    attempts: int
    payload: dict[str, Any]


@dataclass
class Decision:
    targets: list[tuple[str, str]] = field(default_factory=list)  # (source del refresh, id de suscripcion)
    ignore_code: str | None = None  # si no es None, el evento queda `ignored` con este codigo
    deleted_hint: bool = False  # Toku subscription.deleted


def backoff_seconds(attempts: int) -> float:
    """Espera antes del siguiente intento: base * 2**(intentos-1), con tope de 1 hora."""
    return min(settings.webhook_backoff_base_seconds * (2 ** max(attempts - 1, 0)), _MAX_BACKOFF_SECONDS)


# ----------------------------- cola -----------------------------


def select_due_events(db: Session, limit: int, now: datetime):
    """Consulta de eventos vencidos con `FOR UPDATE SKIP LOCKED` (las filas bloqueadas por otro worker se saltan)."""
    return (
        select(WebhookEvent)
        .where(WebhookEvent.status == "pending", WebhookEvent.next_attempt_at <= now)
        .order_by(WebhookEvent.received_at, WebhookEvent.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )


def recover_stale(db: Session, now: datetime) -> int:
    """`processing` abandonado (worker caido) -> `pending`, o `failed` si ya agoto los intentos. No hace commit."""
    cutoff = now - timedelta(minutes=settings.webhook_processing_stale_minutes)
    stale = WebhookEvent.status == "processing", WebhookEvent.locked_at < cutoff
    failed = db.execute(
        update(WebhookEvent)
        .where(*stale, WebhookEvent.attempts >= settings.webhook_max_attempts)
        .values(status="failed", last_error_code=CODE_STALE, processed_at=now, locked_at=None)
    ).rowcount or 0
    back = db.execute(
        update(WebhookEvent)
        .where(*stale, WebhookEvent.attempts < settings.webhook_max_attempts)
        .values(status="pending", locked_at=None, next_attempt_at=now)
    ).rowcount or 0
    return failed + back


def claim_events(db: Session, limit: int, now: datetime | None = None) -> list[EventSnapshot]:
    """Reclama hasta `limit` eventos: `pending` -> `processing`, `attempts` + 1. Commit al final (libera los locks)."""
    now = now or datetime.now(UTC)
    recover_stale(db, now)
    rows = list(db.scalars(select_due_events(db, limit, now)))
    snaps = []
    for row in rows:
        row.status = "processing"
        row.locked_at = now
        row.attempts += 1
        snaps.append(EventSnapshot(
            id=row.id, source=row.source, event_type=row.event_type, resource_type=row.resource_type,
            resource_external_id=row.resource_external_id, subscription_external_id=row.subscription_external_id,
            attempts=row.attempts, payload=dict(row.payload_masked or {}),
        ))
    db.commit()
    return snaps


def _finish(db: Session, ids: list[uuid.UUID], status: str, code: str | None, now: datetime) -> None:
    db.execute(
        update(WebhookEvent)
        .where(WebhookEvent.id.in_(ids))
        .values(status=status, last_error_code=code, processed_at=now, locked_at=None)
    )
    db.commit()


def _retry_or_fail(db: Session, events: list[EventSnapshot], code: str, now: datetime, summary: ProcessSummary) -> None:
    for ev in events:
        if ev.attempts >= settings.webhook_max_attempts:
            _finish(db, [ev.id], "failed", code, now)
            summary.failed += 1
        else:
            db.execute(
                update(WebhookEvent)
                .where(WebhookEvent.id == ev.id)
                .values(status="pending", last_error_code=code, locked_at=None,
                        next_attempt_at=now + timedelta(seconds=backoff_seconds(ev.attempts)))
            )
            db.commit()
            summary.retried += 1
        summary.count_code(code)


REQUEUEABLE_STATUSES = ("failed", "ignored")


def requeue_events(db: Session, ids: list[uuid.UUID] | None = None, *, source: str | None = None,
                   now: datetime | None = None) -> int:
    """Reproceso manual (RT-14): `failed`/`ignored` -> `pending` con `attempts` a 0 y vencimiento inmediato.

    Con `ids` reencola esos eventos; sin `ids`, todos los `failed` (opcionalmente de un `source`). Los `ignored` solo se
    reencolan por id (fueron descartados a proposito). No toca `pending`/`processing`/`done`. Seguro: el procesador
    siempre relee al proveedor, asi que reprocesar un evento no aplica datos viejos. Hace commit; devuelve cuantos.
    """
    now = now or datetime.now(UTC)
    stmt = update(WebhookEvent)
    if ids is not None:
        if not ids:
            return 0
        stmt = stmt.where(WebhookEvent.id.in_(ids), WebhookEvent.status.in_(REQUEUEABLE_STATUSES))
    else:
        stmt = stmt.where(WebhookEvent.status == "failed")
        if source:
            stmt = stmt.where(WebhookEvent.source == source)
    n = db.execute(stmt.values(status="pending", attempts=0, next_attempt_at=now, locked_at=None,
                               last_error_code=None, processed_at=None)).rowcount or 0
    db.commit()
    return n


# ----------------------------- reglas por evento -----------------------------


def _nested(payload: dict[str, Any], head: str, *keys: str) -> str | None:
    obj = payload.get(head)
    if not isinstance(obj, dict):
        return None
    for key in keys:
        value = obj.get(key)
        if isinstance(value, dict):
            value = value.get("id")
        if isinstance(value, str | int) and str(value):
            return str(value)
    return None


def _toku_subscriptions_of_customer(db: Session, customer_id: str | None) -> list[str]:
    if not customer_id:
        return []
    return list(db.scalars(
        select(TokuSubscription.external_id).where(TokuSubscription.customer_id == customer_id)
        .order_by(TokuSubscription.external_id).limit(_MAX_CUSTOMER_SUBSCRIPTIONS)))


def _decide_toku(db: Session, ev: EventSnapshot) -> Decision:
    et = ev.event_type
    if et.startswith("transaction.bulk_") or et.startswith("invoice.bulk_"):
        return Decision(ignore_code=CODE_BULK_EVENT)
    head = et.split(".", 1)[0]
    res = ev.resource_external_id
    sub = ev.subscription_external_id

    if et in _TOKU_SUBSCRIPTION_EVENTS:
        sub = sub or res
        return Decision(targets=[("toku", sub)], deleted_hint=et == "subscription.deleted") if sub else Decision(
            ignore_code=CODE_NO_RESOURCE)

    if et in _TOKU_INVOICE_EVENTS:
        sub = sub or (db.scalar(select(TokuInvoice.subscription_id).where(TokuInvoice.external_id == res)) if res else None)
        return Decision(targets=[("toku", sub)]) if sub else Decision(ignore_code=CODE_NO_RESOURCE)

    if et in _TOKU_TRANSACTION_EVENTS:
        if not sub:
            invoice_id = _nested(ev.payload, head, "invoice_id", "invoice")
            if invoice_id:
                sub = db.scalar(select(TokuInvoice.subscription_id).where(TokuInvoice.external_id == invoice_id))
        if sub:
            return Decision(targets=[("toku", sub)])
        pm_id = _nested(ev.payload, head, "payment_method_id", "payment_method") or (
            db.scalar(select(TokuTransaction.payment_method_id).where(TokuTransaction.external_id == res)) if res else None)
        customer = _nested(ev.payload, head, "customer_id", "customer") or (
            db.scalar(select(TokuPaymentMethod.customer_id).where(TokuPaymentMethod.external_id == pm_id)) if pm_id else None)
        subs = _toku_subscriptions_of_customer(db, customer)
        return Decision(targets=[("toku", s) for s in subs]) if subs else Decision(ignore_code=CODE_NO_RESOURCE)

    if head == "payment_method":
        customer = _nested(ev.payload, head, "customer_id", "customer") or (
            db.scalar(select(TokuPaymentMethod.customer_id).where(TokuPaymentMethod.external_id == res)) if res else None)
        subs = _toku_subscriptions_of_customer(db, customer)
        return Decision(targets=[("toku", s) for s in subs]) if subs else Decision(ignore_code=CODE_NO_RESOURCE)

    return Decision(ignore_code=CODE_UNKNOWN_EVENT)


def _decide_virtualpos(db: Session, ev: EventSnapshot) -> Decision:
    res = ev.resource_external_id
    if ev.event_type == "payout":
        return Decision(ignore_code=CODE_IGNORED_KIND)
    if ev.event_type not in _VP_EVENTS:
        return Decision(ignore_code=CODE_UNKNOWN_EVENT)
    if not res and not ev.subscription_external_id:
        return Decision(ignore_code=CODE_NO_RESOURCE)
    found: set[tuple[str, str]] = set()
    if ev.event_type in ("subscription", "card_change"):
        sub = ev.subscription_external_id or res
        for platform in db.scalars(select(VpSubscription.platform).where(VpSubscription.external_id == sub)):
            found.add((platform, sub))
    elif ev.event_type in ("charge_paid", "charge_reject"):
        # Eventos PAT sin firma: el id del cargo y la suscripcion solo sirven para elegir que releer por API, y
        # solo si ya existen localmente (cargo o suscripcion sincronizados).
        sub = ev.subscription_external_id
        if sub:
            for platform in db.scalars(select(VpSubscription.platform).where(VpSubscription.external_id == sub)):
                found.add((platform, sub))
        if res:
            for platform, charge_sub in db.execute(
                    select(VpCharge.platform, VpCharge.subscription_external_id).where(VpCharge.external_id == res)):
                if charge_sub:
                    found.add((platform, charge_sub))
    else:  # payment: por uuid del pago, o del cobro si el uuid coincide con uno
        for platform, charge_id in db.execute(
                select(VpPayment.platform, VpPayment.charge_external_id).where(VpPayment.external_id == res)):
            if charge_id:
                sub = db.scalar(select(VpCharge.subscription_external_id).where(
                    VpCharge.platform == platform, VpCharge.external_id == charge_id))
                if sub:
                    found.add((platform, sub))
        for platform, sub in db.execute(
                select(VpCharge.platform, VpCharge.subscription_external_id).where(VpCharge.external_id == res)):
            if sub:
                found.add((platform, sub))
    if not found:
        return Decision(ignore_code=CODE_NO_RESOURCE)
    return Decision(targets=sorted(found))


def _decide_payku(db: Session, ev: EventSnapshot) -> Decision:
    kind, res, sub = ev.event_type, ev.resource_external_id, ev.subscription_external_id
    if kind == "payout":
        return Decision(ignore_code=CODE_IGNORED_KIND)
    if kind not in ("subscription", "payment", "transaction", "nullification"):
        return Decision(ignore_code=CODE_UNKNOWN_EVENT)
    if kind == "subscription":
        sub = sub or res
    elif not sub and res:
        sub = db.scalar(select(PaykuTransaction.subscription_id).where(PaykuTransaction.external_id == res))
    return Decision(targets=[("payku", sub)]) if sub else Decision(ignore_code=CODE_NO_RESOURCE)


def decide(db: Session, ev: EventSnapshot) -> Decision:
    """Reglas por canal/evento. Funcion pura sobre el evento y la base local (sin red)."""
    if ev.source == "toku":
        return _decide_toku(db, ev)
    if ev.source == "virtualpos":
        return _decide_virtualpos(db, ev)
    if ev.source == "payku":
        return _decide_payku(db, ev)
    return Decision(ignore_code=CODE_UNKNOWN_EVENT)


# ----------------------------- baja de Toku (subscription.deleted) -----------------------------


def _is_not_found(exc: BaseException) -> bool:
    cause = exc.__cause__ or exc
    return getattr(getattr(cause, "response", None), "status_code", None) == 404


def mark_toku_subscription_deleted(db: Session, external_id: str, run_id: uuid.UUID) -> bool:
    """Baja confirmada: el proveedor ya no devuelve la suscripcion (404). Marca `deleted` y deja el evento de cambio.

    Idempotente: si ya estaba `deleted` no emite nada. Devuelve True si cambio algo.
    """
    changed = False
    sub = db.scalar(select(Subscription).where(Subscription.source == "toku", Subscription.external_id == external_id))
    if sub is not None and (sub.status or "").lower() != "deleted":
        with event_context(run_id=run_id, baseline=False):
            emit_status_events(db, Subscription, [{
                "source": "toku", "external_id": external_id, "status": "deleted", "amount": sub.amount}])
        sub.status = "deleted"
        changed = True
    tk = db.scalar(select(TokuSubscription).where(TokuSubscription.external_id == external_id))
    if tk is not None and (tk.status or "").lower() != "deleted":
        tk.status = "deleted"
        changed = True
    db.commit()
    return changed


# ----------------------------- procesamiento -----------------------------


def _enqueue_failed_targets(db: Session, targets: list[tuple[str, str]]) -> None:
    """SYNC-O-15: el evento agoto sus intentos; sus suscripciones quedan en `refresh_queue` para la reconciliacion.

    Idempotente (una sola orden viva por suscripcion). Nunca lanza: la cola es un extra sobre el dead-letter.
    """
    if not targets:
        return
    try:
        for source, sub_id in targets:
            enqueue_refresh(db, source, sub_id, "webhook_failed")
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("webhook_processor: no se encolo la relectura del evento fallido (%s)", type(exc).__name__)


def _invalidate_dashboard_cache() -> None:
    try:
        from app.api.v1.routes.staging import invalidate_dashboard_cache

        invalidate_dashboard_cache()
    except Exception:  # noqa: BLE001 - la cache es un extra; nunca debe tumbar el procesamiento
        logger.warning("webhook_processor: no se pudo invalidar la cache del dashboard")


async def process_pending(
    db: Session,
    *,
    limit: int | None = None,
    refresh: RefreshFn | None = None,
    now: datetime | None = None,
) -> ProcessSummary:
    """Reclama y procesa un lote de eventos. `refresh` es inyectable (tests); por defecto `refresh_subscription`."""
    refresh_fn = refresh or refresh_subscription
    summary = ProcessSummary()
    events = claim_events(db, limit or settings.webhook_processor_batch_size, now)
    summary.claimed = len(events)
    if not events:
        return summary

    by_target: dict[tuple[str, str], list[EventSnapshot]] = {}
    deleted_hint: dict[tuple[str, str], bool] = {}
    for ev in events:
        try:
            decision = decide(db, ev)
        except Exception as exc:  # noqa: BLE001 - un evento raro no debe bloquear el lote
            logger.warning("webhook_processor: no se pudo decidir un evento (%s)", type(exc).__name__)
            db.rollback()
            _retry_or_fail(db, [ev], CODE_UNEXPECTED, datetime.now(UTC), summary)
            continue
        if decision.ignore_code:
            _finish(db, [ev.id], "ignored", decision.ignore_code, datetime.now(UTC))
            summary.ignored += 1
            summary.count_code(decision.ignore_code)
            continue
        for target in decision.targets:
            by_target.setdefault(target, []).append(ev)
            deleted_hint[target] = deleted_hint.get(target, False) or decision.deleted_hint

    # Un evento con varios objetivos (p. ej. medio de pago con 2 suscripciones) queda `done` si TODOS salen bien.
    outcome: dict[uuid.UUID, str | None] = {}
    for (source, sub_id), evs in by_target.items():
        run_id = uuid.uuid4()
        code: str | None = None
        try:
            await refresh_fn(db, source, sub_id, run_id=run_id)
            summary.refreshes += 1
        except RefreshError as exc:
            code = exc.code
            if deleted_hint.get((source, sub_id)) and source == "toku" and _is_not_found(exc):
                try:
                    mark_toku_subscription_deleted(db, sub_id, run_id)
                    code = None
                except Exception as mark_exc:  # noqa: BLE001
                    db.rollback()
                    logger.warning("webhook_processor: baja Toku no aplicada (%s)", type(mark_exc).__name__)
                    code = CODE_UNEXPECTED
        except Exception as exc:  # noqa: BLE001 - el codigo es fijo; el texto del proveedor no se guarda
            db.rollback()
            logger.warning("webhook_processor: fallo inesperado en %s (%s)", source, type(exc).__name__)
            code = CODE_UNEXPECTED
        for ev in evs:
            outcome[ev.id] = outcome.get(ev.id) or code  # el primer fallo manda; None si todos salieron bien

    by_id = {e.id: e for e in events}
    targets_of: dict[uuid.UUID, list[tuple[str, str]]] = {}
    for target, evs in by_target.items():
        for ev in evs:
            targets_of.setdefault(ev.id, []).append(target)
    for ev_id, code in outcome.items():
        if code is None:
            _finish(db, [ev_id], "done", None, datetime.now(UTC))
            summary.done += 1
        else:
            _retry_or_fail(db, [by_id[ev_id]], code, datetime.now(UTC), summary)
            if by_id[ev_id].attempts >= settings.webhook_max_attempts:
                _enqueue_failed_targets(db, targets_of.get(ev_id, []))

    if summary.done:
        _invalidate_dashboard_cache()
    return summary
