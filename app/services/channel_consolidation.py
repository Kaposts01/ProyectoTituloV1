"""ETL de consolidación: lee de tablas canal (vp_*, toku_*, payku_*, tch_*)
y upserta en las tablas canónicas (clients, subscriptions, charges, payments, plans).

Este módulo reemplaza crm_materialization.py para la consolidación principal.
crm_materialization.py sigue usándose temporalmente en virtualpos_sync para
el flujo legacy mientras se completa la transición.
"""

from __future__ import annotations

import logging
import uuid
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
from app.models.tch import TchCliente, TchSuscripcion, TchTransaccion
from app.models.toku_channel import (
    TokuCustomer,
    TokuInvoice,
    TokuPaymentMethod,
    TokuSubscription,
    TokuTransaction,
)
from app.models.vp import VpCharge, VpClient, VpPayment, VpPlan, VpSubscription

logger = logging.getLogger(__name__)

_CHUNK = 2000


# ── Upsert genérico en tabla canónica ─────────────────────────────────────────

def _upsert_canonical(
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
        stmt = insert(model).values(chunk)
        updatable = {
            k: stmt.excluded[k]
            for k in chunk[0]
            if k not in ("id", "source", "external_id", "created_at")
        }
        stmt = stmt.on_conflict_do_update(constraint=constraint, set_=updatable)
        db.execute(stmt)
        processed += len(chunk)
    db.commit()
    return processed


# ── Helpers de conversión ─────────────────────────────────────────────────────

def _s(val: Any) -> str | None:
    return str(val) if val is not None else None


# ── VirtualPOS → Canónicas ────────────────────────────────────────────────────

def _consolidate_vp_clients(db: Session) -> int:
    rows = []
    for vp in db.scalars(select(VpClient)).all():
        rows.append({
            "source": vp.platform,
            "external_id": vp.external_id,
            "source_record_id": None,
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
    return _upsert_canonical(db, Client, "uq_client_source_external_id", rows)


def _consolidate_vp_plans(db: Session) -> int:
    rows = []
    for vp in db.scalars(select(VpPlan)).all():
        rows.append({
            "source": vp.platform,
            "external_id": vp.external_id,
            "source_record_id": None,
            "name": vp.name,
            "description": vp.description,
            "amount": vp.amount,
            "currency": vp.currency,
            "plan_type": vp.plan_type,
            "is_active": vp.is_active,
            "status": vp.status,
            "raw_payload": vp.raw_payload,
        })
    return _upsert_canonical(db, Plan, "uq_plan_source_external_id", rows)


def _consolidate_vp_subscriptions(db: Session) -> int:
    rows = []
    for vp in db.scalars(select(VpSubscription)).all():
        rows.append({
            "source": vp.platform,
            "external_id": vp.external_id,
            "source_record_id": None,
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
    return _upsert_canonical(db, Subscription, "uq_subscription_source_external_id", rows)


def _consolidate_vp_charges(db: Session) -> int:
    rows = []
    for vp in db.scalars(select(VpCharge)).all():
        rows.append({
            "source": vp.platform,
            "external_id": vp.external_id,
            "source_record_id": None,
            "subscription_external_id": vp.subscription_external_id,
            "client_external_id": vp.client_external_id,
            "amount": vp.amount,
            "currency": vp.currency,
            "status": vp.status,
            "charge_date": vp.charge_date,
            "raw_payload": vp.raw_payload,
        })
    return _upsert_canonical(db, Charge, "uq_charge_source_external_id", rows)


def _consolidate_vp_payments(db: Session) -> int:
    rows = []
    for vp in db.scalars(select(VpPayment)).all():
        rows.append({
            "source": vp.platform,
            "external_id": vp.external_id,
            "source_record_id": None,
            "charge_external_id": vp.charge_external_id,
            "client_external_id": vp.client_external_id,
            "amount": vp.amount,
            "currency": vp.currency,
            "status": vp.status,
            "payment_date": vp.payment_date,
            "raw_payload": vp.raw_payload,
        })
    return _upsert_canonical(db, Payment, "uq_payment_source_external_id", rows)


# ── Toku → Canónicas ──────────────────────────────────────────────────────────

def _consolidate_toku_clients(db: Session) -> int:
    rows = []
    for t in db.scalars(select(TokuCustomer)).all():
        rows.append({
            "source": "toku",
            "external_id": t.external_id,
            "source_record_id": None,
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
    return _upsert_canonical(db, Client, "uq_client_source_external_id", rows)


def _consolidate_toku_subscriptions(db: Session) -> int:
    rows = []
    for t in db.scalars(select(TokuSubscription)).all():
        rows.append({
            "source": "toku",
            "external_id": t.external_id,
            "source_record_id": None,
            "client_external_id": t.customer_id,
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
    return _upsert_canonical(db, Subscription, "uq_subscription_source_external_id", rows)


def _consolidate_toku_invoices(db: Session) -> int:
    rows = []
    for t in db.scalars(select(TokuInvoice)).all():
        rows.append({
            "source": "toku",
            "external_id": t.external_id,
            "source_record_id": None,
            "subscription_external_id": t.subscription_id,
            "client_external_id": None,
            "amount": t.amount,
            "currency": t.currency,
            "status": t.status,
            "charge_date": t.due_date,
            "raw_payload": t.raw_payload,
        })
    return _upsert_canonical(db, Charge, "uq_charge_source_external_id", rows)


def _consolidate_toku_transactions(db: Session) -> int:
    rows = []
    for t in db.scalars(select(TokuTransaction)).all():
        rows.append({
            "source": "toku",
            "external_id": t.external_id,
            "source_record_id": None,
            "charge_external_id": None,
            "client_external_id": None,
            "amount": t.amount,
            "currency": t.currency,
            "status": t.status,
            "payment_date": t.created_at_api,
            "raw_payload": t.raw_payload,
        })
    return _upsert_canonical(db, Payment, "uq_payment_source_external_id", rows)


def _consolidate_toku_payment_methods(db: Session) -> int:
    rows = []
    for t in db.scalars(select(TokuPaymentMethod)).all():
        rows.append({
            "source": "toku",
            "external_id": t.external_id,
            "source_record_id": None,
            "client_external_id": t.customer_id,
            "status": t.status,
            "raw_payload": t.raw_payload,
        })
    return _upsert_canonical(db, PaymentMethod, "uq_payment_method_source_external_id", rows)


# ── Payku → Canónicas ─────────────────────────────────────────────────────────

def _consolidate_payku_clients(db: Session) -> int:
    rows = []
    for p in db.scalars(select(PaykuClient)).all():
        rows.append({
            "source": "payku",
            "external_id": p.external_id,
            "source_record_id": None,
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
    return _upsert_canonical(db, Client, "uq_client_source_external_id", rows)


def _consolidate_payku_plans(db: Session) -> int:
    rows = []
    for p in db.scalars(select(PaykuPlan)).all():
        rows.append({
            "source": "payku",
            "external_id": p.external_id,
            "source_record_id": None,
            "name": p.name,
            "description": None,
            "amount": p.amount,
            "currency": p.currency,
            "plan_type": None,
            "is_active": None,
            "status": p.status,
            "raw_payload": p.raw_payload,
        })
    return _upsert_canonical(db, Plan, "uq_plan_source_external_id", rows)


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
        rows.append({
            "source": "payku",
            "external_id": p.external_id,
            "source_record_id": None,
            "client_external_id": p.client_id,
            "client_social_id": client.get("rut"),
            "plan_external_id": p.plan_id,
            "service_id": None,
            "status": p.status,
            "automatic_renewal": None,
            "suscription_date": payload.get("start"),
            "canceled_at": payload.get("end"),
            "amount": p.amount,
            "currency": p.currency,
            "raw_payload": p.raw_payload,
        })
    return _upsert_canonical(db, Subscription, "uq_subscription_source_external_id", rows)


def _consolidate_payku_transactions(db: Session) -> int:
    rows = []
    for p in db.scalars(select(PaykuTransaction)).all():
        rows.append({
            "source": "payku",
            "external_id": p.external_id,
            "source_record_id": None,
            "charge_external_id": p.subscription_id,
            "client_external_id": None,
            "amount": p.amount,
            "currency": p.currency,
            "status": p.status,
            "payment_date": p.created_at_api,
            "raw_payload": p.raw_payload,
        })
    return _upsert_canonical(db, Payment, "uq_payment_source_external_id", rows)


# ── TCH → Canónicas ───────────────────────────────────────────────────────────

def _consolidate_tch_clients(db: Session) -> int:
    rows = []
    for t in db.scalars(select(TchCliente)).all():
        rows.append({
            "source": "tch",
            "external_id": t.rut,
            "source_record_id": None,
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
    return _upsert_canonical(db, Client, "uq_client_source_external_id", rows)


def _consolidate_tch_subscriptions(db: Session) -> int:
    rows = []
    for t in db.scalars(select(TchSuscripcion)).all():
        rows.append({
            "source": "tch",
            "external_id": _s(t.numero_ficha),
            "source_record_id": None,
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
    return _upsert_canonical(db, Subscription, "uq_subscription_source_external_id", rows)


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
                "source_record_id": None,
                "subscription_external_id": _s(t.numero_ficha),
                "client_external_id": None,
                "amount": t.monto,
                "currency": "CLP",
                "status": t.estado,
                "charge_date": t.fecha_cargo,
                "raw_payload": t.raw_payload,
            })
        total += _upsert_canonical(db, Charge, "uq_charge_source_external_id", rows)
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


def consolidate_to_canonical(db: Session, sources: list[str] | None = None) -> int:
    """Lee de tablas canal y upserta en tablas canónicas.

    Args:
        sources: lista de fuentes a consolidar, ej. ['virtualpos', 'toku'].
                 None = todas las fuentes.
    Returns:
        Total de registros procesados.
    """
    targets = sources or list(_SOURCE_FNS.keys())
    total = 0
    for source in targets:
        fns = _SOURCE_FNS.get(source, [])
        for fn in fns:
            try:
                count = fn(db)
                logger.info("Consolidado %s.%s: %d registros", source, fn.__name__, count)
                total += count
            except Exception:
                logger.exception("Error consolidando %s.%s", source, fn.__name__)
    return total
