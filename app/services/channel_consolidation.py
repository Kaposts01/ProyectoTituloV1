"""ETL de consolidación: lee de tablas canal (vp_*, toku_*, payku_*, tch_*)
y upserta en las tablas centralizadas (clients, subscriptions, charges, payments, plans).

Este módulo reemplaza crm_materialization.py para la consolidación principal.
crm_materialization.py queda desactivado (presente pero sin llamadores en el flujo
de sync ni en la API) mientras se completa la transición.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.crm import Charge, Client, Payment, PaymentMethod, Plan, Subscription
from app.models.payku_channel import (
    PaykuClient,
    PaykuPlan,
    PaykuSubscription,
    PaykuTransaction,
)
from app.models.source_record import SourceRecord
from app.models.tch import TchCliente, TchSuscripcion, TchTransaccion
from app.models.toku_channel import (
    TokuCustomer,
    TokuInvoice,
    TokuPaymentMethod,
    TokuSubscription,
    TokuTransaction,
)
from app.models.vp import VpCharge, VpClient, VpPayment, VpPlan, VpSubscription
from app.services.channel_store import _VP_PLATFORMS
from app.services.core_materialization import materialize_core_clients

logger = logging.getLogger(__name__)

_CHUNK = 2000


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
) -> int:
    if not rows:
        return 0
    # Asegurar que todas las filas tienen id
    for row in rows:
        row.setdefault("id", uuid.uuid4())

    processed = 0
    for i in range(0, len(rows), _CHUNK):
        chunk = rows[i : i + _CHUNK]
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
        stmt = stmt.on_conflict_do_update(constraint=constraint, set_=updatable)
        db.execute(stmt)
        processed += len(chunk)
    db.commit()
    return processed


# ── Helpers de conversión ─────────────────────────────────────────────────────

def _s(val: Any) -> str | None:
    return str(val) if val is not None else None


def _vp_records(db: Session, model: type) -> list:
    """Filas VirtualPOS con platform conocido; las demás se omiten y se registran."""
    valid = []
    skipped = 0
    for vp in db.scalars(select(model)).all():
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
    for vp in _vp_records(db, VpClient):
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
    rows = []
    for vp in _vp_records(db, VpPlan):
        rows.append({
            "source": vp.platform,
            "external_id": vp.external_id,
            "name": vp.name,
            "description": vp.description,
            "amount": vp.amount,
            "currency": vp.currency,
            "plan_type": vp.plan_type,
            "is_active": vp.is_active,
            "status": vp.status,
            "raw_payload": vp.raw_payload,
        })
    return _upsert_centralized(db, Plan, "uq_plan_source_external_id", _link_source_records(db, rows, "plan"))


def _consolidate_vp_subscriptions(db: Session) -> int:
    rows = []
    for vp in _vp_records(db, VpSubscription):
        rows.append({
            "source": vp.platform,
            "external_id": vp.external_id,
            "client_external_id": vp.client_external_id,
            "client_social_id": vp.client_social_id,
            "plan_external_id": vp.plan_external_id,
            "service_id": vp.service_id,
            "status": vp.status,
            "automatic_renewal": vp.automatic_renewal,
            "suscription_date": vp.suscription_date,
            "canceled_at": vp.canceled_at,
            "amount": vp.amount,
            "currency": vp.currency,
            "raw_payload": vp.raw_payload,
        })
    return _upsert_centralized(db, Subscription, "uq_subscription_source_external_id", _link_source_records(db, rows, "subscription"))


def _consolidate_vp_charges(db: Session) -> int:
    rows = []
    for vp in _vp_records(db, VpCharge):
        rows.append({
            "source": vp.platform,
            "external_id": vp.external_id,
            "subscription_external_id": vp.subscription_external_id,
            "client_external_id": vp.client_external_id,
            "amount": vp.amount,
            "currency": vp.currency,
            "status": vp.status,
            "charge_date": vp.charge_date,
            "raw_payload": vp.raw_payload,
        })
    return _upsert_centralized(db, Charge, "uq_charge_source_external_id", _link_source_records(db, rows, "charge"))


def _consolidate_vp_payments(db: Session) -> int:
    rows = []
    for vp in _vp_records(db, VpPayment):
        rows.append({
            "source": vp.platform,
            "external_id": vp.external_id,
            "charge_external_id": vp.charge_external_id,
            "client_external_id": vp.client_external_id,
            "amount": vp.amount,
            "currency": vp.currency,
            "status": vp.status,
            "payment_date": vp.payment_date,
            "raw_payload": vp.raw_payload,
        })
    return _upsert_centralized(db, Payment, "uq_payment_source_external_id", _link_source_records(db, rows, "payment"))


# ── Toku → Canónicas ──────────────────────────────────────────────────────────

def _consolidate_toku_clients(db: Session) -> int:
    rows = []
    for t in db.scalars(select(TokuCustomer)).all():
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
    return _upsert_centralized(db, Client, "uq_client_source_external_id", _link_source_records(db, rows, "customer"))


def _consolidate_toku_subscriptions(db: Session) -> int:
    rows = []
    for t in db.scalars(select(TokuSubscription)).all():
        payload = t.raw_payload or {}
        rows.append({
            "source": "toku",
            "external_id": t.external_id,
            "client_external_id": t.customer_id or _relationship_id(payload.get("customer")),
            "client_social_id": None,
            "plan_external_id": None,
            "service_id": None,
            "status": t.status,
            "automatic_renewal": None,
            "suscription_date": t.anchor,
            "canceled_at": t.end_date,
            "amount": t.amount,
            "currency": t.currency_code,
            "raw_payload": t.raw_payload,
        })
    _log_null_relations('toku.subscription', rows, ('client_external_id',))
    return _upsert_centralized(db, Subscription, "uq_subscription_source_external_id", _link_source_records(db, rows, "subscription"))


def _consolidate_toku_invoices(db: Session) -> int:
    rows = []
    for t in db.scalars(select(TokuInvoice)).all():
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
    for t in db.scalars(select(TokuTransaction)).all():
        payload = t.raw_payload or {}
        rows.append({
            "source": "toku",
            "external_id": t.external_id,
            "charge_external_id": _toku_payment_subscription_id(payload),
            "client_external_id": _relationship_id(payload.get("customer")),
            "amount": t.amount,
            "currency": t.currency,
            "status": t.status,
            "payment_date": t.created_at_api,
            "raw_payload": t.raw_payload,
        })
    _log_null_relations('toku.transaction', rows, ('charge_external_id', 'client_external_id'))
    return _upsert_centralized(db, Payment, "uq_payment_source_external_id", _link_source_records(db, rows, "transaction"))


def _consolidate_toku_payment_methods(db: Session) -> int:
    rows = []
    for t in db.scalars(select(TokuPaymentMethod)).all():
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
    for p in db.scalars(select(PaykuClient)).all():
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
    for p in db.scalars(select(PaykuPlan)).all():
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


def _consolidate_payku_subscriptions(db: Session) -> int:
    latest_successful_amounts: dict[str, tuple[str, str | None]] = {}
    for transaction in db.scalars(
        select(PaykuTransaction).where(
            PaykuTransaction.subscription_id.isnot(None),
            func.lower(PaykuTransaction.status) == "success",
        )
    ):
        current = latest_successful_amounts.get(transaction.subscription_id)
        timestamp = transaction.created_at_api or ""
        if current is None or timestamp > current[0]:
            latest_successful_amounts[transaction.subscription_id] = (timestamp, transaction.amount)

    rows = []
    for p in db.scalars(select(PaykuSubscription)).all():
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


def _consolidate_payku_transactions(db: Session) -> int:
    rows = []
    for p in db.scalars(select(PaykuTransaction)).all():
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
    for t in db.scalars(select(TchCliente)).all():
        rows.append({
            "source": "tch",
            "external_id": t.rut,
            "first_name": t.nombre,
            "last_name": t.apellido,
            "email": None,
            "phone_number": None,
            "status": "active",
            "social_id": t.rut,
            "gender_id": None,
            "birth_date": t.fecha_nacimiento,
            "provider_created_at": None,
            "private_note": None,
            "cards": [],
            "raw_payload": t.raw_payload,
        })
    return _upsert_centralized(db, Client, "uq_client_source_external_id", _link_source_records(db, rows, "client"))


def _consolidate_tch_subscriptions(db: Session) -> int:
    rows = []
    for t in db.scalars(select(TchSuscripcion)).all():
        rows.append({
            "source": "tch",
            "external_id": _s(t.numero_ficha),
            "client_external_id": None,
            "client_social_id": t.cliente_rut,
            "plan_external_id": None,
            "service_id": None,
            "status": t.estado,
            "automatic_renewal": None,
            "suscription_date": t.fecha_activacion,
            "canceled_at": t.fecha_eliminacion,
            "amount": t.monto,
            "currency": "CLP",
            "raw_payload": t.raw_payload,
        })
    return _upsert_centralized(db, Subscription, "uq_subscription_source_external_id", _link_source_records(db, rows, "subscription"))


def _consolidate_tch_transactions(db: Session) -> int:
    """tch_transacciones → charges (procesadas en chunks por volumen ~150k)."""
    total = 0
    offset = 0
    while True:
        batch = db.scalars(
            select(TchTransaccion).order_by(TchTransaccion.id).offset(offset).limit(_CHUNK)
        ).all()
        if not batch:
            break
        rows = []
        for t in batch:
            rows.append({
                "source": "tch",
                "external_id": t.dedupe_key or _s(t.id),
                "subscription_external_id": _s(t.numero_ficha),
                "client_external_id": None,
                "amount": t.monto,
                "currency": "CLP",
                "status": t.estado,
                "charge_date": t.fecha_cargo,
                "raw_payload": t.raw_payload,
            })
        total += _upsert_centralized(db, Charge, "uq_charge_source_external_id", _link_source_records(db, rows, "transaction"))
        offset += _CHUNK
        if len(batch) < _CHUNK:
            break
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
    Returns:
        Total de registros procesados.
    """
    targets = sources or list(_SOURCE_FNS.keys())
    total = 0
    failed: list[str] = failures if failures is not None else []
    for source in targets:
        fns = _SOURCE_FNS.get(source, [])
        for fn in fns:
            try:
                with db.begin_nested():
                    count = fn(db)
                logger.info("Consolidado %s.%s: %d registros", source, fn.__name__, count)
                total += count
            except Exception:
                logger.exception("Error consolidando %s.%s", source, fn.__name__)
                failed.append(f"{source}.{fn.__name__.removeprefix('_consolidate_')}")
    try:
        with db.begin_nested():
            total += materialize_core_clients(db, targets)
    except Exception:
        logger.exception("Error en materialize_core_clients")
        failed.append("materialize_core_clients")
    if raise_on_error and failed:
        raise ConsolidationError(failed)
    return total
