"""ETL de consolidación: lee de tablas canal (vp_*, toku_*, payku_*, tch_*)
y upserta en las tablas centralizadas (clients, subscriptions, charges, payments, plans).

Este módulo reemplaza crm_materialization.py para la consolidación principal.
crm_materialization.py queda desactivado (presente pero sin llamadores en el flujo
de sync ni en la API) mientras se completa la transición.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    String,
    and_,
    cast,
    delete,
    exists,
    func,
    literal,
    or_,
    select,
    tuple_,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.crm import Charge, Client, Payment, PaymentMethod, Plan, Subscription
from app.models.payku_channel import (
    PaykuClient,
    PaykuPlan,
    PaykuSubscription,
    PaykuTransaction,
)
from app.models.source_record import SourceRecord
from app.models.tch import TchClient, TchSubscription, TchTransaction
from app.models.toku_channel import (
    TokuCustomer,
    TokuInvoice,
    TokuPaymentMethod,
    TokuSubscription,
    TokuTransaction,
)
from app.models.vp import VpCharge, VpClient, VpPayment, VpPlan, VpSubscription
from app.services import sync_cursors, toku_client_status
from app.services.channel_store import _VP_PLATFORMS
from app.services.core_materialization import materialize_core_clients
from app.services.core_tch_etl import _resolve_currency as _resolve_tch_currency
from app.services.core_tch_etl import legacy_key_filter
from app.services.status_events import (
    REASON_CODE_KEY,
    REASON_TEXT_KEY,
    emit_status_events,
    event_context,
    pop_reason_hints,
)
from app.services.tch_rut import identity_rut
from app.services.toku_rejection_projection import (
    load_report_attempt_codes,
    toku_transaction_rejection,
)
from app.services.toku_report_lifecycle import chile_date_iso, report_product_dates
from app.services.upsert_guard import distinct_where
from app.services.vp_current_amount import load_current_amount
from app.services.vp_typed_fields import as_legacy_text

logger = logging.getLogger(__name__)

_CHUNK = 2000

# (source, subscription_external_id): acota una consolidacion a UNA suscripcion y sus cobros/pagos (MGT-06).
Scope = tuple[str, str]


def _relationship_id(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("id") or value.get("external_id")
    return str(value) if value is not None else None


def _toku_payment_subscription_id(payload: dict) -> str | None:
    intents = payload.get("payment_intents")
    if not isinstance(intents, list):
        return None
    for intent in intents:
        if isinstance(intent, dict) and (subscription_id := _relationship_id(intent.get("id_subscription"))):
            return subscription_id
    return None


def _log_null_relations(resource: str, rows: list[dict], fields: tuple[str, ...]) -> None:
    """SYNC-GAP-04: loguea cuantas filas quedaron con relaciones NULL (solo conteos, sin PII)."""
    if not rows:
        return
    counts = {f: sum(1 for r in rows if r.get(f) is None) for f in fields}
    if any(counts.values()):
        logger.warning(
            "relaciones NULL %s: %s de %d filas",
            resource,
            ", ".join(f"{f}={n}" for f, n in counts.items()),
            len(rows),
        )


# ── Trazabilidad: source_record_id ────────────────────────────────────────────

def _source_record_ids(
    db: Session, source: str, resource_type: str, external_ids: Iterable[str | None]
) -> dict[str, uuid.UUID]:
    """Devuelve {external_id: source_records.id} para (source, resource_type).

    Los external_id sin coincidencia simplemente no aparecen en el resultado.
    """
    ids = sorted({e for e in external_ids if e})
    result: dict[str, uuid.UUID] = {}
    for i in range(0, len(ids), _CHUNK):
        chunk = ids[i : i + _CHUNK]
        stmt = select(SourceRecord.external_id, SourceRecord.id).where(
            SourceRecord.source == source,
            SourceRecord.resource_type == resource_type,
            SourceRecord.external_id.in_(chunk),
        )
        for external_id, record_id in db.execute(stmt):
            result[external_id] = record_id
    return result


def _link_source_records(db: Session, rows: list[dict], resource_type: str) -> list[dict]:
    """Asigna ``source_record_id`` a cada fila (NULL si no hay coincidencia)."""
    by_source: dict[str, list[dict]] = {}
    for row in rows:
        row["source_record_id"] = None
        by_source.setdefault(row["source"], []).append(row)
    linked = 0
    for source, group in by_source.items():
        mapping = _source_record_ids(db, source, resource_type, (r["external_id"] for r in group))
        for row in group:
            record_id = mapping.get(row["external_id"])
            if record_id is not None:
                row["source_record_id"] = record_id
                linked += 1
    if rows:
        logger.info("source_record_id %s: %d vinculados de %d", resource_type, linked, len(rows))
    return rows


def _drop_conflicting_source_record_ids(db: Session, model: type, chunk: list[dict]) -> None:
    """source_record_id es UNIQUE: anula el vínculo que ya pertenece a otra fila."""
    wanted = {r["source_record_id"] for r in chunk if r.get("source_record_id") is not None}
    if not wanted:
        return
    owners = {
        record_id: (source, external_id)
        for record_id, source, external_id in db.execute(
            select(model.source_record_id, model.source, model.external_id).where(
                model.source_record_id.in_(wanted)
            )
        )
    }
    seen: set[uuid.UUID] = set()
    for row in chunk:
        record_id = row.get("source_record_id")
        if record_id is None:
            continue
        owner = owners.get(record_id)
        if record_id in seen or (owner is not None and owner != (row["source"], row["external_id"])):
            logger.warning("source_record_id duplicado en %s; se deja NULL", model.__tablename__)
            row["source_record_id"] = None
        else:
            seen.add(record_id)


# ── Upsert genérico en tabla centralizada ─────────────────────────────────────

def _upsert_centralized(
    db: Session,
    model: type,
    constraint: str,
    rows: list[dict],
    *,
    commit: bool = True,
) -> int:
    """Upsert por trozos con eventos de cambio y guarda IS DISTINCT FROM.

    `commit=False` deja el commit al llamador: necesario si el llamador sigue usando la sesion dentro del SAVEPOINT de
    `_consolidate` (un commit intermedio cierra ese contexto y la siguiente consulta falla).
    """
    if not rows:
        return 0
    # Asegurar que todas las filas tienen id
    for row in rows:
        row.setdefault("id", uuid.uuid4())

    processed = 0
    for i in range(0, len(rows), _CHUNK):
        chunk = rows[i : i + _CHUNK]
        reason_hints = pop_reason_hints(chunk)
        emit_status_events(db, model, chunk, reason_hints)  # SYNC-D-02: nunca lanza; antes del upsert
        _drop_conflicting_source_record_ids(db, model, chunk)
        stmt = insert(model).values(chunk)
        updatable = {
            k: stmt.excluded[k]
            for k in chunk[0]
            if k not in ("id", "source", "external_id", "created_at")
        }
        if "source_record_id" in updatable:
            # Una segunda pasada sin coincidencia no debe borrar un vínculo existente.
            updatable["source_record_id"] = func.coalesce(
                stmt.excluded.source_record_id, model.__table__.c.source_record_id
            )
        # SYNC-O-07: solo reescribe la fila si alguna columna cambia de valor (IS DISTINCT FROM); una consolidacion
        # repetida sin cambios escribe 0 filas. Los eventos ya se calcularon arriba contra los valores previos.
        stmt = stmt.on_conflict_do_update(
            constraint=constraint, set_=updatable, where=distinct_where(model.__table__, updatable)
        )
        # RETURNING solo devuelve las filas insertadas o realmente actualizadas (las omitidas por la guarda no): es el
        # conteo fiable de escrituras (el `rowcount` del driver no lo es para INSERT ... ON CONFLICT multi-fila).
        result = db.execute(stmt.returning(model.__table__.c.id))
        _count_written(len(result.all()))
        processed += len(chunk)
    if commit:
        db.commit()
    return processed


# SYNC-O-07: filas realmente escritas (insertadas o cambiadas) por las llamadas a `_upsert_centralized` del bloque.
_WRITTEN: ContextVar[list[int] | None] = ContextVar("consolidation_written", default=None)


def _count_written(rowcount: int | None) -> None:
    counter = _WRITTEN.get()
    if counter is not None and rowcount is not None and rowcount >= 0:
        counter[0] += rowcount


@contextmanager
def _written_counter() -> Iterator[list[int]]:
    counter = [0]
    token = _WRITTEN.set(counter)
    try:
        yield counter
    finally:
        _WRITTEN.reset(token)


# SYNC-O-07: lectura diferencial. Con un instante fijado, los consolidadores que lo soportan leen solo las filas del
# canal cambiadas desde entonces (`updated_at`, que `upsert_channel` solo mueve si la fila cambio). None = todo.
_SINCE: ContextVar[datetime | None] = ContextVar("consolidation_since", default=None)


def _changed_since(model: type) -> tuple:
    """Criterio `model.updated_at >= desde` si la consolidacion es diferencial; () si se lee completo."""
    since = _SINCE.get()
    return (model.updated_at >= since,) if since is not None else ()


# ── Helpers de conversión ─────────────────────────────────────────────────────

def _s(val: Any) -> str | None:
    return str(val) if val is not None else None


def _vp_records(db: Session, model: type, *criteria: Any) -> list:
    """Filas VirtualPOS con platform conocido; las demás se omiten y se registran."""
    valid = []
    skipped = 0
    for vp in db.scalars(select(model).where(*criteria)).all():
        if vp.platform in _VP_PLATFORMS:
            valid.append(vp)
        else:
            skipped += 1
    if skipped:
        logger.warning(
            "VirtualPOS %s: %d filas omitidas por platform desconocido", model.__tablename__, skipped
        )
    return valid


# ── VirtualPOS → Canónicas ────────────────────────────────────────────────────

def _consolidate_vp_clients(db: Session) -> int:
    rows = []
    for vp in _vp_records(db, VpClient, *_changed_since(VpClient)):
        rows.append({
            "source": vp.platform,
            "external_id": vp.external_id,
            "first_name": vp.first_name,
            "last_name": vp.last_name,
            "email": vp.email,
            "phone_number": vp.phone_number,
            "status": vp.status,
            "social_id": vp.social_id,
            "gender_id": vp.gender_id,
            "birth_date": vp.birth_date,
            "provider_created_at": vp.provider_created_at,
            "private_note": vp.private_note,
            "cards": vp.cards or [],
            "raw_payload": vp.raw_payload,
        })
    return _upsert_centralized(db, Client, "uq_client_source_external_id", _link_source_records(db, rows, "client"))


def _consolidate_vp_plans(db: Session) -> int:
    # VP-PAR-13: `vp_*` ya tiene montos y fechas tipados; las tablas `crm` siguen en texto y reciben el texto canonico
    # (`as_legacy_text`), el mismo que guardaban antes de la migracion 0061.
    rows = []
    for vp in _vp_records(db, VpPlan, *_changed_since(VpPlan)):
        rows.append({
            "source": vp.platform,
            "external_id": vp.external_id,
            "name": vp.name,
            "description": vp.description,
            "amount": as_legacy_text(vp.amount),
            "currency": vp.currency,
            "plan_type": vp.plan_type,
            "is_active": vp.is_active,
            "status": vp.status,
            "raw_payload": vp.raw_payload,
        })
    return _upsert_centralized(db, Plan, "uq_plan_source_external_id", _link_source_records(db, rows, "plan"))


def _consolidate_vp_subscriptions(db: Session, scope: Scope | None = None) -> int:
    # El monto de una suscripcion VP es el ultimo monto cobrado (plan fijo no editable);
    # sin cargos vigentes cae al monto de la suscripcion/plan. Una consulta agregada.
    # `scope` = (platform, subscription_external_id): refresco de UNA suscripcion (MGT-06).
    current_amounts = load_current_amount(
        db, family="vp",
        sources=[scope[0]] if scope else None, subscription_ids=[scope[1]] if scope else None,
    )
    criteria = (VpSubscription.platform == scope[0], VpSubscription.external_id == scope[1]) if scope else ()
    since = _SINCE.get()
    if not scope and since is not None:
        # Diferencial: la suscripcion cambio o cambio alguno de sus cobros (el monto vigente sale de los cobros).
        criteria = (or_(
            VpSubscription.updated_at >= since,
            tuple_(VpSubscription.platform, VpSubscription.external_id).in_(
                select(VpCharge.platform, VpCharge.subscription_external_id).where(VpCharge.updated_at >= since)
            ),
        ),)
    rows = []
    for vp in _vp_records(db, VpSubscription, *criteria):
        current_amount = current_amounts.get((vp.platform, vp.external_id))
        rows.append({
            "source": vp.platform,
            "external_id": vp.external_id,
            "client_external_id": vp.client_external_id,
            "client_social_id": vp.client_social_id,
            "plan_external_id": vp.plan_external_id,
            "service_id": vp.service_id,
            "status": vp.status,
            "automatic_renewal": vp.automatic_renewal,
            "suscription_date": as_legacy_text(vp.suscription_date),
            "canceled_at": as_legacy_text(vp.canceled_at),
            "amount": format(current_amount.normalize(), "f") if current_amount is not None else as_legacy_text(vp.amount),
            "currency": vp.currency,
            "raw_payload": vp.raw_payload,
        })
    return _upsert_centralized(db, Subscription, "uq_subscription_source_external_id", _link_source_records(db, rows, "subscription"))


def _consolidate_vp_charges(db: Session, scope: Scope | None = None) -> int:
    criteria = (VpCharge.platform == scope[0], VpCharge.subscription_external_id == scope[1]) if scope else _changed_since(VpCharge)
    rows = []
    for vp in _vp_records(db, VpCharge, *criteria):
        rows.append({
            "source": vp.platform,
            "external_id": vp.external_id,
            "subscription_external_id": vp.subscription_external_id,
            "client_external_id": vp.client_external_id,
            "amount": as_legacy_text(vp.amount),
            "currency": vp.currency,
            "status": vp.status,
            "charge_date": as_legacy_text(vp.charge_date),
            "raw_payload": vp.raw_payload,
        })
    return _upsert_centralized(db, Charge, "uq_charge_source_external_id", _link_source_records(db, rows, "charge"))


def _consolidate_vp_payments(db: Session) -> int:
    rows = []
    for vp in _vp_records(db, VpPayment, *_changed_since(VpPayment)):
        rows.append({
            "source": vp.platform,
            "external_id": vp.external_id,
            "charge_external_id": vp.charge_external_id,
            "client_external_id": vp.client_external_id,
            "amount": as_legacy_text(vp.amount),
            "currency": vp.currency,
            "status": vp.status,
            "payment_date": as_legacy_text(vp.payment_date),
            "raw_payload": vp.raw_payload,
        })
    return _upsert_centralized(db, Payment, "uq_payment_source_external_id", _link_source_records(db, rows, "payment"))


# ── Toku → Canónicas ──────────────────────────────────────────────────────────

def _consolidate_toku_clients(db: Session) -> int:
    rows = []
    for t in db.scalars(select(TokuCustomer).where(*_changed_since(TokuCustomer))).all():
        rows.append({
            "source": "toku",
            "external_id": t.external_id,
            "first_name": t.name,
            "last_name": None,
            "email": t.email,
            "phone_number": t.phone_number,
            "status": t.status,
            "social_id": t.government_id,
            "gender_id": None,
            "birth_date": None,
            "provider_created_at": None,
            "private_note": None,
            "cards": [],
            "raw_payload": t.raw_payload,
        })
    # d126 (TK-PAR-07): manda la API; si deja el estado vacio, lo completa el reporte de Clientes.
    statuses = toku_client_status.report_statuses(
        db, [row["external_id"] for row in rows if toku_client_status.is_blank(row["status"])]
    )
    rows = [toku_client_status.fill_blank_status(row, statuses) for row in rows]
    return _upsert_centralized(db, Client, "uq_client_source_external_id", _link_source_records(db, rows, "customer"))


def _consolidate_toku_subscriptions(db: Session, scope: Scope | None = None) -> int:
    criteria = (TokuSubscription.external_id == scope[1],) if scope else ()
    rows = []
    # TK-PAR-05: alta y baja reales desde el reporte de Productos. La API solo trae el proximo cobro (`anchor`) y no
    # lista las eliminadas. d141 (opcion a): sin fila de reporte el alta queda NULL (el `anchor` es el proximo cobro,
    # no el alta, y contaba como alta futura); la suscripcion queda fuera de las altas (`altas_sin_fecha`).
    report_dates = report_product_dates(db)
    for t in db.scalars(select(TokuSubscription).where(*criteria)).all():
        payload = t.raw_payload or {}
        report = report_dates.get(t.external_id)
        rows.append({
            "source": "toku",
            "external_id": t.external_id,
            "client_external_id": t.customer_id or _relationship_id(payload.get("customer")),
            "client_social_id": None,
            "plan_external_id": None,
            "service_id": None,
            "status": t.status,
            "automatic_renewal": None,
            "suscription_date": chile_date_iso(report.created_at) if report else None,
            "canceled_at": t.end_date or (chile_date_iso(report.deleted_at) if report else None),
            "amount": t.amount,
            "currency": t.currency_code,
            "raw_payload": t.raw_payload,
        })
    _log_null_relations('toku.subscription', rows, ('client_external_id',))
    return _upsert_centralized(db, Subscription, "uq_subscription_source_external_id", _link_source_records(db, rows, "subscription"))


def _consolidate_toku_invoices(db: Session, scope: Scope | None = None) -> int:
    criteria = (TokuInvoice.subscription_id == scope[1],) if scope else _changed_since(TokuInvoice)
    rows = []
    for t in db.scalars(select(TokuInvoice).where(*criteria)).all():
        payload = t.raw_payload or {}
        rows.append({
            "source": "toku",
            "external_id": t.external_id,
            "subscription_external_id": t.subscription_id or _relationship_id(payload.get("subscription")),
            "client_external_id": _relationship_id(payload.get("customer")),
            "amount": t.amount,
            "currency": t.currency,
            "status": t.status,
            "charge_date": t.due_date,
            "raw_payload": t.raw_payload,
        })
    _log_null_relations('toku.invoice', rows, ('subscription_external_id', 'client_external_id'))
    return _upsert_centralized(db, Charge, "uq_charge_source_external_id", _link_source_records(db, rows, "invoice"))


def _consolidate_toku_transactions(db: Session) -> int:
    rows = []
    report_codes = load_report_attempt_codes(db)  # TK-PAR-03: código del reporte de Intentos si la API no lo trae
    for t in db.scalars(select(TokuTransaction)).all():
        payload = t.raw_payload or {}
        rejection_code, rejection_reason, rejected_at = toku_transaction_rejection(
            payload, t.status, report_codes, external_id=t.external_id, created_at_api=t.created_at_api
        )
        rows.append({
            "source": "toku",
            "external_id": t.external_id,
            "charge_external_id": _toku_payment_subscription_id(payload),
            "client_external_id": _relationship_id(payload.get("customer")),
            "amount": t.amount,
            "currency": t.currency,
            "status": t.status,
            "payment_date": t.created_at_api,
            "rejection_code": rejection_code,
            "rejection_reason": rejection_reason,
            "rejected_at": rejected_at,
            "raw_payload": t.raw_payload,
        })
    _log_null_relations('toku.transaction', rows, ('charge_external_id', 'client_external_id'))
    return _upsert_centralized(db, Payment, "uq_payment_source_external_id", _link_source_records(db, rows, "transaction"))


def _consolidate_toku_payment_methods(db: Session) -> int:
    rows = []
    for t in db.scalars(select(TokuPaymentMethod).where(*_changed_since(TokuPaymentMethod))).all():
        rows.append({
            "source": "toku",
            "external_id": t.external_id,
            "client_external_id": t.customer_id,
            "status": t.status,
            "raw_payload": t.raw_payload,
        })
    return _upsert_centralized(db, PaymentMethod, "uq_payment_method_source_external_id", _link_source_records(db, rows, "payment_method"))


# ── Payku → Canónicas ─────────────────────────────────────────────────────────

def _consolidate_payku_clients(db: Session) -> int:
    rows = []
    for p in db.scalars(select(PaykuClient).where(*_changed_since(PaykuClient))).all():
        rows.append({
            "source": "payku",
            "external_id": p.external_id,
            "first_name": p.name,
            "last_name": None,
            "email": p.email,
            "phone_number": p.phone,
            "status": p.status,
            "social_id": p.rut,
            "gender_id": None,
            "birth_date": None,
            "provider_created_at": None,
            "private_note": None,
            "cards": [],
            "raw_payload": p.raw_payload,
        })
    return _upsert_centralized(db, Client, "uq_client_source_external_id", _link_source_records(db, rows, "client"))


def _consolidate_payku_plans(db: Session) -> int:
    rows = []
    for p in db.scalars(select(PaykuPlan).where(*_changed_since(PaykuPlan))).all():
        rows.append({
            "source": "payku",
            "external_id": p.external_id,
            "name": p.name,
            "description": None,
            "amount": p.amount,
            "currency": p.currency,
            "plan_type": None,
            "is_active": None,
            "status": p.status,
            "raw_payload": p.raw_payload,
        })
    return _upsert_centralized(db, Plan, "uq_plan_source_external_id", _link_source_records(db, rows, "plan"))


def _payku_last_transition_date(payload: dict, final_status: str) -> str | None:
    """Return the change_date of the most recent log entry with the given final_status."""
    logs = payload.get("logs") if isinstance(payload, dict) else None
    entries = logs.get("status", []) if isinstance(logs, dict) else []
    dates = [
        e["change_date"]
        for e in entries
        if isinstance(e, dict) and str(e.get("final_status", "")).lower() == final_status and e.get("change_date")
    ]
    return max(dates) if dates else None


def _consolidate_payku_subscriptions(db: Session, scope: Scope | None = None) -> int:
    latest_successful_amounts: dict[str, tuple[str, str | None]] = {}
    tx_criteria = (PaykuTransaction.subscription_id == scope[1],) if scope else ()
    for transaction in db.scalars(
        select(PaykuTransaction).where(
            PaykuTransaction.subscription_id.isnot(None),
            func.lower(PaykuTransaction.status) == "success",
            *tx_criteria,
        )
    ):
        current = latest_successful_amounts.get(transaction.subscription_id)
        timestamp = transaction.created_at_api or ""
        if current is None or timestamp > current[0]:
            latest_successful_amounts[transaction.subscription_id] = (timestamp, transaction.amount)

    sub_criteria = (PaykuSubscription.external_id == scope[1],) if scope else ()
    since = _SINCE.get()
    if not scope and since is not None:
        # Diferencial: la suscripcion cambio o cambio alguna de sus transacciones (monto de respaldo).
        sub_criteria = (or_(
            PaykuSubscription.updated_at >= since,
            PaykuSubscription.external_id.in_(
                select(PaykuTransaction.subscription_id).where(PaykuTransaction.updated_at >= since)
            ),
        ),)
    rows = []
    for p in db.scalars(select(PaykuSubscription).where(*sub_criteria)).all():
        payload = p.raw_payload or {}
        client = payload.get("client") if isinstance(payload.get("client"), dict) else {}
        if not p.amount:
            p.amount = latest_successful_amounts.get(p.external_id, ("", None))[1]
        status = (p.status or "").lower()
        if status in {"active", "register", "suspended_awaits_change_plan"}:
            canceled_at = None
        else:
            # Prefer the status-log transition date; fall back to payload.end when absent.
            canceled_at = _payku_last_transition_date(payload, status) or payload.get("end")
        rows.append({
            "source": "payku",
            "external_id": p.external_id,
            "client_external_id": p.client_id,
            "client_social_id": client.get("rut"),
            "plan_external_id": p.plan_id,
            "service_id": None,
            "status": p.status,
            "automatic_renewal": None,
            "suscription_date": payload.get("start"),
            "canceled_at": canceled_at,
            "amount": p.amount,
            "currency": p.currency,
            "raw_payload": p.raw_payload,
        })
    _log_null_relations('payku.subscription', rows, ('client_external_id', 'plan_external_id'))
    return _upsert_centralized(db, Subscription, "uq_subscription_source_external_id", _link_source_records(db, rows, "subscription"))


def _consolidate_payku_transactions(db: Session, scope: Scope | None = None) -> int:
    criteria = (PaykuTransaction.subscription_id == scope[1],) if scope else _changed_since(PaykuTransaction)
    rows = []
    for p in db.scalars(select(PaykuTransaction).where(*criteria)).all():
        rows.append({
            "source": "payku",
            "external_id": p.external_id,
            "charge_external_id": p.subscription_id,
            "client_external_id": None,
            "amount": p.amount,
            "currency": p.currency,
            "status": p.status,
            "payment_date": p.created_at_api,
            "raw_payload": p.raw_payload,
        })
    _log_null_relations('payku.transaction', rows, ('charge_external_id',))
    return _upsert_centralized(db, Payment, "uq_payment_source_external_id", _link_source_records(db, rows, "transaction"))


# ── TCH → Canónicas ───────────────────────────────────────────────────────────

def _consolidate_tch_clients(db: Session) -> int:
    rows = []
    for t in db.scalars(select(TchClient)).all():
        rows.append({
            "source": "tch",
            "external_id": t.rut,
            "first_name": t.name,
            "last_name": t.last_name,
            "email": None,
            "phone_number": None,
            "status": "active",
            "social_id": identity_rut(t.rut),  # TCH-PAR-14: solo un RUT valido es senal de identidad
            "gender_id": None,
            "birth_date": t.birth_date,
            "provider_created_at": None,
            "private_note": None,
            "cards": [],
            "raw_payload": t.raw_payload,
        })
    return _upsert_centralized(db, Client, "uq_client_source_external_id", _link_source_records(db, rows, "client"))


def _consolidate_tch_subscriptions(db: Session) -> int:
    rows = []
    for t in db.scalars(select(TchSubscription)).all():
        rows.append({
            "source": "tch",
            "external_id": _s(t.file_number),
            "client_external_id": t.client_rut,  # TCH-PAR-12: llave del cliente en el canal (external_id de clients)
            "client_social_id": identity_rut(t.client_rut),
            "plan_external_id": None,
            "service_id": None,
            "status": t.status,
            "automatic_renewal": None,
            "suscription_date": t.activation_date,
            "canceled_at": t.deletion_date,
            "amount": t.amount,
            "currency": _resolve_tch_currency(t),
            "raw_payload": t.raw_payload,
        })
    return _upsert_centralized(db, Subscription, "uq_subscription_source_external_id", _link_source_records(db, rows, "subscription"))


def _tch_changed_transactions(after_id: uuid.UUID | None) -> Any:
    """TCH-PAR-13: cuotas de `tch_transacciones` cuya fila de `charges` falta o difiere de lo que se consolidaria.

    La comparacion se hace en SQL (un LEFT JOIN contra `charges` por la clave de la cuota): a Python solo llegan las
    cuotas nuevas o cambiadas, en lotes por id (paginacion por clave, no por OFFSET). Las columnas comparadas son
    exactamente las que arma `_consolidate_tch_transactions`, asi que el resultado es el mismo que releer todo.
    """
    external_id = func.coalesce(TchTransaction.dedupe_key, cast(TchTransaction.id, String))
    has_source_record = exists(
        select(SourceRecord.id).where(
            SourceRecord.source == "tch",
            SourceRecord.resource_type == "transaction",
            SourceRecord.external_id == external_id,
        )
    )
    changed = or_(
        Charge.id.is_(None),
        Charge.subscription_external_id.is_distinct_from(cast(TchTransaction.file_number, String)),
        Charge.client_external_id.is_distinct_from(TchSubscription.client_rut),
        Charge.amount.is_distinct_from(TchTransaction.amount),
        Charge.currency.is_distinct_from(literal(_TCH_CURRENCY)),
        Charge.status.is_distinct_from(TchTransaction.status),
        Charge.charge_date.is_distinct_from(TchTransaction.charge_date),
        Charge.raw_payload.is_distinct_from(TchTransaction.raw_payload),
        and_(Charge.source_record_id.is_(None), has_source_record),
    )
    stmt = (
        select(
            TchTransaction.id, TchTransaction.dedupe_key, TchTransaction.file_number, TchTransaction.amount,
            TchTransaction.status, TchTransaction.charge_date, TchTransaction.raw_payload,
            TchTransaction.response_code, TchTransaction.rejection_reason, TchSubscription.client_rut,
        )
        .outerjoin(TchSubscription, TchSubscription.file_number == TchTransaction.file_number)
        .outerjoin(Charge, and_(Charge.source == "tch", Charge.external_id == external_id))
        .where(changed)
        .order_by(TchTransaction.id)
        .limit(_CHUNK)
    )
    return stmt.where(TchTransaction.id > after_id) if after_id is not None else stmt


_TCH_CURRENCY = "CLP"


def _consolidate_tch_transactions(db: Session) -> int:
    """tch_transacciones → charges, solo las cuotas nuevas o cambiadas (TCH-PAR-13; ~1,47 M filas en total).

    Devuelve las cuotas leidas (nuevas o cambiadas): una segunda consolidacion sin cargas nuevas lee y escribe 0.
    """
    # D13: la clave de la cuota es ficha|periodo|cuota; los cobros con la clave antigua que ya no estan en
    # tch_transacciones quedarian duplicados tras la recarga completa.
    pruned = db.execute(delete(Charge).where(legacy_key_filter(Charge, Charge.external_id))).rowcount or 0
    if pruned:
        logger.info("TCH: %d cobros con clave antigua eliminados de charges", pruned)
    total = 0
    last_id: uuid.UUID | None = None
    while True:
        batch = db.execute(_tch_changed_transactions(last_id)).all()
        if not batch:
            break
        rows = []
        for t in batch:  # filas de columnas (no entidades ORM): no se acumulan en el mapa de identidad
            rows.append({
                "source": "tch",
                "external_id": t.dedupe_key or _s(t.id),
                "subscription_external_id": _s(t.file_number),
                # TCH-PAR-12: llave del cliente de la ficha (antes NULL en el 100 % de los cobros TCH).
                "client_external_id": t.client_rut,
                "amount": t.amount,
                "currency": _TCH_CURRENCY,
                "status": t.status,
                "charge_date": t.charge_date,
                "raw_payload": t.raw_payload,
                REASON_CODE_KEY: t.response_code,  # glosa para el catalogo (SYNC-D-02); no es columna
                REASON_TEXT_KEY: t.rejection_reason,
            })
        last_id = batch[-1].id
        # Sin commit entre lotes: un commit intermedio cierra el SAVEPOINT de `_consolidate` y el lote siguiente fallaba
        # ("closed transaction inside context manager") en cuanto habia mas de un lote. Un solo commit al final.
        total += _upsert_centralized(
            db, Charge, "uq_charge_source_external_id", _link_source_records(db, rows, "transaction"), commit=False
        )
        if len(batch) < _CHUNK:
            break
    db.commit()
    if total:
        logger.info("TCH: %d cuotas nuevas o cambiadas consolidadas", total)
    return total


# ── Punto de entrada principal ─────────────────────────────────────────────────

_SOURCE_FNS = {
    "virtualpos": [
        _consolidate_vp_clients,
        _consolidate_vp_plans,
        _consolidate_vp_subscriptions,
        _consolidate_vp_charges,
        _consolidate_vp_payments,
    ],
    "toku": [
        _consolidate_toku_clients,
        _consolidate_toku_subscriptions,
        _consolidate_toku_invoices,
        _consolidate_toku_transactions,
        _consolidate_toku_payment_methods,
    ],
    "payku": [
        _consolidate_payku_clients,
        _consolidate_payku_plans,
        _consolidate_payku_subscriptions,
        _consolidate_payku_transactions,
    ],
    "tch": [
        _consolidate_tch_clients,
        _consolidate_tch_subscriptions,
        _consolidate_tch_transactions,
    ],
}


class ConsolidationError(Exception):
    """Una o mas funciones de consolidacion fallaron (las demas se ejecutaron)."""

    def __init__(self, failures: list[str]) -> None:
        self.failures = failures
        super().__init__("Consolidacion fallida: " + ", ".join(failures))


def consolidate_to_centralized(
    db: Session,
    sources: list[str] | None = None,
    raise_on_error: bool = False,
    failures: list[str] | None = None,
    timings: list[dict[str, Any]] | None = None,
    run_id: uuid.UUID | None = None,
    baseline: bool | None = None,
    differential: bool | None = None,
) -> int:
    """Lee de tablas canal y upserta en tablas centralizadas.

    Cada funcion corre en su propio SAVEPOINT: un error de BD revierte solo esa
    funcion y la sesion sigue usable para las demas.

    Args:
        sources: lista de fuentes a consolidar, ej. ['virtualpos', 'toku'].
                 None = todas las fuentes.
        raise_on_error: si es True, al final lanza ConsolidationError con los
                 nombres fallidos (``source.fn``). Por defecto solo se loguea.
        failures: lista opcional que se llena con los nombres fallidos, para
                 callers que mantienen el comportamiento no-raise.
        timings: lista opcional que se llena con ``{source, fn, seconds, records}`` por funcion (SYNC-O-01).
        run_id: id de la corrida (``etl_runs.id``) que firma los eventos de cambio (SYNC-D-02); sin id se usa un
                 token propio de esta llamada.
        baseline: True marca los eventos de esta corrida como linea base (SYNC-D-03: no cuentan como novedad).
                 None = ``settings.status_events_baseline``.
        differential: True lee solo lo cambiado desde la ultima consolidacion exitosa de cada funcion (SYNC-O-07);
                 None = ``settings.consolidation_differential_enabled``. Una linea base (``baseline=True``) siempre
                 lee completo. Con o sin lectura diferencial, una fila sin cambios nunca se reescribe.
    Returns:
        Total de registros procesados. Cada item de ``timings`` lleva ademas ``written`` (filas escritas de verdad).
    """
    is_baseline = settings.status_events_baseline if baseline is None else baseline
    use_differential = settings.consolidation_differential_enabled if differential is None else differential
    with event_context(run_id=run_id, baseline=baseline):
        return _consolidate(db, sources, raise_on_error, failures, timings, use_differential and not is_baseline)


_SCOPED_FNS: dict[str, list[Any]] = {
    "virtualpos": [_consolidate_vp_subscriptions, _consolidate_vp_charges],
    "toku": [_consolidate_toku_subscriptions, _consolidate_toku_invoices],
    "payku": [_consolidate_payku_subscriptions, _consolidate_payku_transactions],
}


def consolidate_subscription(
    db: Session,
    source: str,
    external_id: str,
    *,
    run_id: uuid.UUID | None = None,
    baseline: bool = False,
) -> int:
    """Consolida SOLO una suscripcion (y sus cobros/pagos) desde las tablas canal a las centralizadas (MGT-06).

    Reutiliza los mismos constructores de filas y el mismo upsert (con el enganche de eventos de estado) que la
    consolidacion completa, acotados por `scope`. `source` es la fuente centralizada: `virtualpos1`/`virtualpos2`,
    `toku` o `payku`. No toca otras suscripciones ni el nucleo de clientes. `baseline=False`: los cambios de estado
    de esta operacion son novedad real. Un fallo se propaga como `ConsolidationError`.
    """
    family = "virtualpos" if source in _VP_PLATFORMS else source
    fns = _SCOPED_FNS.get(family)
    if fns is None:
        raise ValueError(f"Fuente sin consolidacion por suscripcion: {source!r}")
    failures: list[str] = []
    total = 0
    with event_context(run_id=run_id, baseline=baseline):
        for fn in fns:
            try:
                with db.begin_nested():
                    total += fn(db, scope=(source, external_id))
            except Exception:
                logger.exception("Error consolidando %s.%s (suscripcion acotada)", family, fn.__name__)
                failures.append(f"{family}.{fn.__name__.removeprefix('_consolidate_')}")
    if failures:
        raise ConsolidationError(failures)
    return total


# SYNC-O-07: consolidadores cuya fila canonica depende solo de filas de canal con `updated_at` fiable (o que filtran
# tambien por sus dependencias). Los demas leen completo siempre: Toku suscripciones y transacciones dependen de los
# reportes importados (fechas de alta/baja, codigos de rechazo) y TCH usa su propia deteccion de cambios (TCH-PAR-13).
_DIFFERENTIAL_FNS = frozenset({
    _consolidate_vp_clients, _consolidate_vp_plans, _consolidate_vp_subscriptions, _consolidate_vp_charges,
    _consolidate_vp_payments,
    _consolidate_toku_clients, _consolidate_toku_invoices, _consolidate_toku_payment_methods,
    _consolidate_payku_clients, _consolidate_payku_plans, _consolidate_payku_subscriptions,
    _consolidate_payku_transactions,
})
# Marca de agua en `sync_cursors`: source fijo (no aparece en la salud por canal), recurso = "<familia>.<funcion>".
CURSOR_SOURCE = "consolidation"
CURSOR_MODE = "consolidate"


def _cursor_resource(source: str, fn: Any) -> str:
    return f"{source}.{fn.__name__.removeprefix('_consolidate_')}"


def _differential_since(db: Session, source: str, fn: Any) -> datetime | None:
    """Desde cuando leer: ultima consolidacion exitosa de la funcion menos el solape; None = lectura completa."""
    last = sync_cursors.last_success(db, CURSOR_SOURCE, _cursor_resource(source, fn), CURSOR_MODE)
    if last is None:
        return None
    return last - timedelta(minutes=max(0.0, float(settings.consolidation_differential_overlap_minutes)))


def _consolidate(
    db: Session,
    sources: list[str] | None,
    raise_on_error: bool,
    failures: list[str] | None,
    timings: list[dict[str, Any]] | None,
    differential: bool = False,
) -> int:
    targets = sources or list(_SOURCE_FNS.keys())
    total = 0
    failed: list[str] = failures if failures is not None else []
    for source in targets:
        fns = _SOURCE_FNS.get(source, [])
        for fn in fns:
            started = time.perf_counter()
            tracked = differential and fn in _DIFFERENTIAL_FNS
            # now() de la BD (inicio de la transaccion): nunca posterior a una escritura que esta lectura no vea.
            started_db = db.scalar(select(func.now())) if tracked else None
            since = _differential_since(db, source, fn) if tracked else None
            since_token = _SINCE.set(since)
            try:
                with _written_counter() as written, db.begin_nested():
                    count = fn(db)
                if tracked and started_db is not None:
                    sync_cursors.record_success(
                        db, CURSOR_SOURCE, _cursor_resource(source, fn), CURSOR_MODE,
                        started_at=started_db, records_seen=count,
                    )
                    db.commit()
                logger.info(
                    "Consolidado %s.%s: %d registros leidos, %d escritos%s", source, fn.__name__, count, written[0],
                    " (diferencial)" if since is not None else "",
                )
                total += count
                if timings is not None:
                    timings.append({
                        "source": source,
                        "fn": fn.__name__.removeprefix("_consolidate_"),
                        "seconds": round(time.perf_counter() - started, 3),
                        "records": count,
                        "written": written[0],
                    })
            except Exception:
                logger.exception("Error consolidando %s.%s", source, fn.__name__)
                failed.append(f"{source}.{fn.__name__.removeprefix('_consolidate_')}")
            finally:
                _SINCE.reset(since_token)
    started = time.perf_counter()
    try:
        with db.begin_nested():
            core_clients = materialize_core_clients(db, targets)
            total += core_clients
        if timings is not None:
            timings.append({
                "source": "core", "fn": "materialize_core_clients",
                "seconds": round(time.perf_counter() - started, 3), "records": core_clients,
                "written": core_clients,  # solo crea identidades nuevas: lo creado es lo escrito
            })
    except Exception:
        logger.exception("Error en materialize_core_clients")
        failed.append("materialize_core_clients")
    if raise_on_error and failed:
        raise ConsolidationError(failed)
    return total
