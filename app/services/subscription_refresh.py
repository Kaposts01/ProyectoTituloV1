"""Refresco puntual de UNA suscripcion desde el proveedor (MGT-06).

`refresh_subscription(db, source, external_id)` relee por GET la suscripcion y sus cobros/pagos, actualiza las tablas
del canal (`vp_*`, `toku_*`, `payku_*`), `source_records` y la consolidacion centralizada SOLO de ese registro
(reutiliza los upserts de `channel_store` y `channel_consolidation`, con el enganche de eventos de estado de
`status_events` firmado con un `run_id` propio de la operacion). Es la pieza que usaran las bajas, los webhooks y la
conciliacion.

Garantias:
  * Solo lecturas al proveedor (GET). Ninguna escritura remota.
  * Fail-closed: si cualquier lectura falla o llega con forma inesperada, NO se escribe nada local y se lanza
    `RefreshError` con un codigo fijo (nunca texto libre del proveedor).
  * Idempotente: repetirlo con el mismo estado remoto no cambia nada ni genera eventos nuevos.
  * No toca otras suscripciones ni el nucleo de clientes.

Pagos: VirtualPOS no expone pagos por suscripcion (el listado es global) y Toku tampoco; en esos canales solo se
refrescan suscripcion y cobros/invoices. En Payku las transacciones vienen embebidas en la suscripcion y se refrescan.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.payku.client import PaykuClient, is_failed_response
from app.integrations.toku.client import TokuClient
from app.integrations.virtualpos.client import VirtualPOSClient
from app.models.crm import Subscription
from app.models.payku_channel import PaykuSubscription
from app.models.toku_channel import TokuSubscription
from app.models.vp import VpSubscription
from app.services.billing_plan import is_pending_status, norm_state
from app.services.channel_consolidation import (
    ConsolidationError,
    consolidate_subscription,
)
from app.services.channel_store import (
    _VP_PLATFORMS,
    store_payku_resources,
    store_toku_resources,
    store_vp_resources,
)
from app.services.payload_sanitization import sanitize_payload
from app.services.read_only_provider_sync import store_records
from app.services.virtualpos_sync import _store_records as store_vp_source_records

log = logging.getLogger(__name__)

PROCESSING_STATES = frozenset({"procesando", "processing"})
TOKU_PENDING_STATES = frozenset({"unpaid", "partially_paid"})
PAYKU_PENDING_STATES = frozenset({"pending", "retry"})


class RefreshError(Exception):
    """El refresco no se completo. `code` es fijo (UNSUPPORTED_SOURCE, PROVIDER_READ_FAILED, EMPTY_SUBSCRIPTION,
    LOCAL_WRITE_FAILED, CONSOLIDATION_FAILED); no lleva texto libre del proveedor."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class RefreshResult:
    source: str
    external_id: str
    status_before: str | None
    status_after: str | None
    changed: bool
    pending_charges: int
    pending_charge_ids: list[str]
    processing_charges: int
    processing_charge_ids: list[str]
    charges_seen: int
    run_id: uuid.UUID
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["run_id"] = str(self.run_id)
        return out


@dataclass
class _Snapshot:
    """Lo leido del proveedor, ya saneado y clasificado (nada local se toca hasta tenerlo completo)."""

    subscription: dict[str, Any]
    charges: list[dict[str, Any]]
    pending_ids: list[str]
    processing_ids: list[str]
    notes: list[str] = field(default_factory=list)


def _unwrap(response: Any, keys: tuple[str, ...]) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    for key in keys:
        value = response.get(key)
        if isinstance(value, dict):
            return value
    return response


def _current_status(db: Session, source: str, external_id: str) -> str | None:
    status = db.scalar(
        select(Subscription.status)
        .where(Subscription.source == source, Subscription.external_id == external_id)
        .execution_options(populate_existing=True)
    )
    if status is not None:
        return status
    if source in _VP_PLATFORMS:
        return db.scalar(select(VpSubscription.status).where(
            VpSubscription.platform == source, VpSubscription.external_id == external_id))
    if source == "toku":
        return db.scalar(select(TokuSubscription.status).where(TokuSubscription.external_id == external_id))
    return db.scalar(select(PaykuSubscription.status).where(PaykuSubscription.external_id == external_id))


# ----------------------------- lectura por canal -----------------------------


async def _read_virtualpos(source: str, external_id: str) -> _Snapshot:
    from app.services.write_virtualpos import (  # import local: write_virtualpos usa este modulo en la baja
        _subscription_payload,
        fetch_all_charge_pages,
    )

    async with VirtualPOSClient(platform=source) as provider:
        payload = _subscription_payload(await provider.get_subscription(external_id))
        if not payload:
            raise RefreshError("EMPTY_SUBSCRIPTION")
        raw_charges = await fetch_all_charge_pages(provider, external_id)
    subscription = sanitize_payload(payload)
    subscription["id"] = subscription.get("id") or external_id
    currency = subscription.get("currency")
    charges = [
        sanitize_payload({**c, "currency": c.get("currency") or currency, "suscription_id": external_id})
        for c in raw_charges
        if c.get("id")
    ]
    pending = [str(c["id"]) for c in charges if is_pending_status(c.get("status"))]
    processing = [str(c["id"]) for c in charges if norm_state(c.get("status")) in PROCESSING_STATES]
    return _Snapshot(subscription, charges, pending, processing)


async def _read_toku(external_id: str) -> _Snapshot:
    async with TokuClient() as provider:
        payload = _unwrap(await provider.get_subscription(external_id), ("subscription", "data"))
        if not payload:
            raise RefreshError("EMPTY_SUBSCRIPTION")
        response = await provider.list_subscription_invoices(external_id)
    raw = response.get("invoices") if isinstance(response, dict) else None
    if not isinstance(raw, list) or any(not isinstance(i, dict) for i in raw):
        raise RefreshError("PROVIDER_READ_FAILED")
    subscription = sanitize_payload(payload)
    subscription["id"] = subscription.get("id") or external_id
    invoices = [
        sanitize_payload({**i, "subscription_id": i.get("subscription_id") or external_id}) for i in raw if i.get("id")
    ]
    pending, processing = [], []
    for inv in invoices:
        general = norm_state(inv.get("general_status") or inv.get("status"))
        if general not in TOKU_PENDING_STATES:
            continue
        (processing if inv.get("in_progress") else pending).append(str(inv["id"]))
    return _Snapshot(subscription, invoices, pending, processing)


async def _read_payku(external_id: str) -> _Snapshot:
    async with PaykuClient() as provider:
        response = await provider.get_subscription(external_id)
    # d188: el cliente ya lanza PaykuApiError ante `status: "failed"`; esta guarda evita guardar el dict de error como
    # suscripcion si llegara por otra via (p. ej. un cliente sustituto). Solo el nivel superior: dentro de `data`, el
    # `status` es el de la suscripcion.
    if is_failed_response(response):
        raise RefreshError("PROVIDER_READ_FAILED")
    payload = _unwrap(response, ("data", "subscription"))
    if not payload:
        raise RefreshError("EMPTY_SUBSCRIPTION")
    subscription = sanitize_payload(payload)
    subscription["id"] = subscription.get("id") or external_id
    embedded = subscription.get("transactions")
    txs = [
        sanitize_payload({**t, "__subscription_id": external_id})
        for t in (embedded if isinstance(embedded, list) else [])
        if isinstance(t, dict) and (t.get("id") or t.get("transaction"))
    ]
    pending = [str(t.get("id") or t.get("transaction")) for t in txs if norm_state(t.get("status")) in PAYKU_PENDING_STATES]
    return _Snapshot(subscription, txs, pending, [])


# ----------------------------- escritura local -----------------------------


def _write_virtualpos(db: Session, source: str, external_id: str, snap: _Snapshot) -> None:
    skipped: list[str] = []
    store_vp_source_records(db, source, "subscription", [snap.subscription])
    store_vp_resources(db, "subscription", [snap.subscription], platform=source, skipped_subscriptions=skipped)
    if skipped:
        snap.notes.append("duplicate_active_subscription_skipped")
    store_vp_source_records(db, source, "charge", snap.charges, sync_context={"subscription_external_id": external_id})
    store_vp_resources(db, "charge", snap.charges, platform=source, subscription_external_id=external_id)


def _write_toku(db: Session, external_id: str, snap: _Snapshot) -> None:
    store_records(db, "toku", "subscription", [snap.subscription])
    store_toku_resources(db, "subscription", [snap.subscription])
    store_records(db, "toku", "invoice", snap.charges)
    store_toku_resources(db, "invoice", snap.charges)


def _write_payku(db: Session, external_id: str, snap: _Snapshot) -> None:
    store_records(db, "payku", "subscription", [snap.subscription])
    store_payku_resources(db, "subscription", [snap.subscription])
    store_records(db, "payku", "transaction", snap.charges)
    store_payku_resources(db, "transaction", snap.charges)


# ----------------------------- API publica -----------------------------


async def refresh_subscription(
    db: Session,
    source: str,
    external_id: str,
    *,
    run_id: uuid.UUID | None = None,
) -> RefreshResult:
    """Relee UNA suscripcion del proveedor y actualiza canal + consolidacion de ese registro. Ver docstring del modulo.

    `source`: `virtualpos1` | `virtualpos2` | `toku` | `payku`. `run_id` firma los eventos de estado que genere la
    operacion (por defecto uno nuevo). Devuelve estado antes/despues y los cobros pendientes/procesando del proveedor.
    """
    run_id = run_id or uuid.uuid4()
    is_vp = source in _VP_PLATFORMS
    if not (is_vp or source in ("toku", "payku")):
        raise RefreshError("UNSUPPORTED_SOURCE")

    status_before = _current_status(db, source, external_id)

    try:  # 1) todas las lecturas primero: si algo falla, no se escribe nada
        if is_vp:
            snap = await _read_virtualpos(source, external_id)
        elif source == "toku":
            snap = await _read_toku(external_id)
        else:
            snap = await _read_payku(external_id)
    except RefreshError:
        raise
    except Exception as exc:
        log.warning("refresh_subscription %s/%s: lectura fallida (%s)", source, external_id, type(exc).__name__)
        raise RefreshError("PROVIDER_READ_FAILED") from exc

    try:  # 2) canal + source_records
        if is_vp:
            _write_virtualpos(db, source, external_id, snap)
        elif source == "toku":
            _write_toku(db, external_id, snap)
        else:
            _write_payku(db, external_id, snap)
    except Exception as exc:
        db.rollback()
        log.warning("refresh_subscription %s/%s: escritura local fallida (%s)", source, external_id, type(exc).__name__)
        raise RefreshError("LOCAL_WRITE_FAILED") from exc

    try:  # 3) consolidacion acotada a ESTA suscripcion (con eventos de estado)
        consolidate_subscription(db, source, external_id, run_id=run_id, baseline=False)
        db.commit()
    except ConsolidationError as exc:
        db.rollback()
        raise RefreshError("CONSOLIDATION_FAILED") from exc

    status_after = _current_status(db, source, external_id)
    return RefreshResult(
        source=source,
        external_id=external_id,
        status_before=status_before,
        status_after=status_after,
        changed=status_before != status_after,
        pending_charges=len(snap.pending_ids),
        pending_charge_ids=snap.pending_ids,
        processing_charges=len(snap.processing_ids),
        processing_charge_ids=snap.processing_ids,
        charges_seen=len(snap.charges),
        run_id=run_id,
        notes=snap.notes,
    )
