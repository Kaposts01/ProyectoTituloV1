"""ETL desde BDlocales hacia las tablas canónicas del CRM.

Lee de los 3 PostgreSQL locales (virtualPOS_Local, Payku_Local, Toku_Local)
y upserta en las tablas clients, plans, subscriptions, charges, payments
del CRM. No pasa por staging; source_record_id queda en NULL.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg
import psycopg.rows
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.crm import Charge, Client, Payment, PaymentMethod, Plan, Subscription
from app.models.etl_run import EtlRun

_CONSTRAINTS: dict[type, str] = {
    Client: "uq_client_source_external_id",
    Plan: "uq_plan_source_external_id",
    Subscription: "uq_subscription_source_external_id",
    Charge: "uq_charge_source_external_id",
    Payment: "uq_payment_source_external_id",
    PaymentMethod: "uq_payment_method_source_external_id",
}


# ─── Utilidades de extracción ─────────────────────────────────────────────────

def _t(v: Any) -> str | None:
    return str(v) if v is not None else None


def _get(obj: dict, *keys: str) -> str | None:
    for k in keys:
        v = obj.get(k)
        if v is not None:
            return _t(v)
    return None


def _nested(obj: dict, key: str, *nested_keys: str) -> str | None:
    inner = obj.get(key)
    if not isinstance(inner, dict):
        return None
    return _get(inner, *nested_keys)


def _card_summaries(payload: dict) -> list[dict]:
    cards = payload.get("cards")
    if not isinstance(cards, list):
        return []
    summaries = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        details = card.get("card") if isinstance(card.get("card"), dict) else {}
        summaries.append({
            "reference_id": _get(card, "card_reference_id"),
            "status": _get(card, "status"),
            "created_at": _get(card, "created_at"),
            "brand": _get(details, "brand"),
            "card_type": _get(details, "card_type"),
            "issuer": _get(details, "issuer"),
            "issuer_code": _get(details, "issuer_code"),
            "last4": _get(details, "last4"),
            "nacional": _get(details, "nacional"),
        })
    return summaries


# ─── Lectura de BDlocales ─────────────────────────────────────────────────────

def _fetch(dsn: str, query: str) -> list[dict]:
    """Ejecuta una query en una BDlocal y retorna lista de dicts."""
    conn_dsn = dsn.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(conn_dsn, row_factory=psycopg.rows.dict_row) as conn, conn.cursor() as cur:
        cur.execute(query)
        return cur.fetchall()


# ─── Upsert canónico ──────────────────────────────────────────────────────────

def _upsert(
    db: Session,
    model: type[Client | Plan | Subscription | Charge | Payment | PaymentMethod],
    data: dict[str, Any],
    source: str,
    external_id: str | None,
) -> bool:
    if not external_id:
        return False
    allowed = {c.name for c in model.__table__.columns}
    values: dict[str, Any] = {
        "source": source,
        "external_id": external_id,
        "source_record_id": None,
        **{k: v for k, v in data.items() if k in allowed},
    }
    stmt = insert(model).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint=_CONSTRAINTS[model],
        set_={k: stmt.excluded[k] for k in values if k not in ("source", "external_id")},
    )
    db.execute(stmt)
    return True


# ─── VirtualPOS ───────────────────────────────────────────────────────────────

def _etl_vpos_clientes(db: Session, dsn: str) -> int:
    rows = _fetch(dsn, "SELECT platform, raw_payload FROM cliente")
    count = 0
    for row in rows:
        payload = row["raw_payload"]
        source = (row.get("platform") or "virtualpos").lower()
        external_id = _get(payload, "client_uuid", "uuid", "id")
        data = {
            "first_name": _get(payload, "first_name"),
            "last_name": _get(payload, "last_name"),
            "email": _get(payload, "email"),
            "phone_number": _get(payload, "phone_number"),
            "social_id": _get(payload, "social_id"),
            "gender_id": _get(payload, "gender_id"),
            "birth_date": _get(payload, "birth_date"),
            "provider_created_at": _get(payload, "created"),
            "status": _get(payload, "status"),
            "cards": _card_summaries(payload),
            "raw_payload": payload,
        }
        if _upsert(db, Client, data, source, external_id):
            count += 1
    db.flush()
    return count


def _etl_vpos_planes(db: Session, dsn: str) -> int:
    rows = _fetch(dsn, "SELECT platform, raw_payload FROM plan")
    count = 0
    for row in rows:
        payload = row["raw_payload"]
        source = (row.get("platform") or "virtualpos").lower()
        external_id = _get(payload, "plan_id", "id")
        is_active = _get(payload, "is_active")
        data = {
            "name": _get(payload, "name"),
            "description": _get(payload, "description"),
            "amount": _get(payload, "amount"),
            "currency": _get(payload, "currency"),
            "plan_type": _get(payload, "type"),
            "is_active": is_active,
            "status": "active" if is_active in ("1", "true", "True") else "inactive",
            "raw_payload": payload,
        }
        if _upsert(db, Plan, data, source, external_id):
            count += 1
    db.flush()
    return count


def _etl_vpos_subscripciones(db: Session, dsn: str) -> int:
    rows = _fetch(dsn, "SELECT platform, raw_payload FROM subscripcion")
    count = 0
    for row in rows:
        payload = row["raw_payload"]
        source = (row.get("platform") or "virtualpos").lower()
        external_id = _get(payload, "suscription_id", "subscription_id", "id")
        # client_uuid puede estar directo o anidado en el objeto "client"
        client_obj = payload.get("client")
        client_id = _get(payload, "client_uuid") or (
            _get(client_obj, "uuid") if isinstance(client_obj, dict) else None
        )
        data = {
            "client_external_id": client_id,
            "client_social_id": _get(client_obj, "social_id") if isinstance(client_obj, dict) else None,
            "plan_external_id": _get(payload, "plan_id"),
            "service_id": _get(payload, "service_id"),
            "status": _get(payload, "status"),
            "automatic_renewal": _get(payload, "automatic_renewal"),
            "suscription_date": _get(payload, "suscription_date"),
            "canceled_at": _get(payload, "canceled_at"),
            "amount": _get(payload, "amount"),
            "currency": _get(payload, "currency"),
            "raw_payload": payload,
        }
        if _upsert(db, Subscription, data, source, external_id):
            count += 1
    db.flush()
    return count


def _etl_vpos_cargos(db: Session, dsn: str) -> int:
    # suscription_id es columna dinámica materializada por BDlocales junto al raw_payload
    try:
        rows = _fetch(dsn, "SELECT platform, raw_payload, suscription_id FROM cargos")
        has_col = True
    except psycopg.Error:
        rows = _fetch(dsn, "SELECT platform, raw_payload FROM cargos")
        has_col = False

    count = 0
    for row in rows:
        payload = row["raw_payload"]
        source = (row.get("platform") or "virtualpos").lower()
        external_id = _get(payload, "charge_id", "id")
        sub_id = (row.get("suscription_id") if has_col else None) or _get(
            payload, "suscription_id", "subscription_id"
        )
        data = {
            "subscription_external_id": _t(sub_id) if sub_id else None,
            "amount": _get(payload, "amount"),
            "currency": _get(payload, "currency"),
            "status": _get(payload, "status"),
            "charge_date": _get(payload, "charge_date"),
            "raw_payload": payload,
        }
        if _upsert(db, Charge, data, source, external_id):
            count += 1
    db.flush()
    return count


def _etl_vpos_transacciones(db: Session, dsn: str) -> int:
    rows = _fetch(dsn, "SELECT platform, raw_payload FROM transacciones")
    count = 0
    for row in rows:
        payload = row["raw_payload"]
        source = (row.get("platform") or "virtualpos").lower()
        external_id = (
            _nested(payload, "order", "uuid")
            or _get(payload, "payment_uuid", "id")
        )
        data = {
            "amount": _nested(payload, "order", "amount") or _get(payload, "amount"),
            "currency": _nested(payload, "order", "currency") or _get(payload, "currency"),
            "status": _nested(payload, "order", "status") or _get(payload, "status"),
            "payment_date": (
                _nested(payload, "order", "authorized_at", "created_at")
                or _get(payload, "payment_date")
            ),
            "raw_payload": payload,
        }
        if _upsert(db, Payment, data, source, external_id):
            count += 1
    db.flush()
    return count


# ─── Toku ─────────────────────────────────────────────────────────────────────

def _etl_toku_clientes(db: Session, dsn: str) -> int:
    rows = _fetch(dsn, "SELECT raw_payload FROM customer")
    count = 0
    for row in rows:
        payload = row["raw_payload"]
        external_id = _get(payload, "id")
        data = {
            "first_name": _get(payload, "name"),
            "email": _get(payload, "mail"),
            "phone_number": _get(payload, "phone_number"),
            "social_id": _get(payload, "government_id"),
            "status": "active",
            "cards": [],
            "raw_payload": payload,
        }
        if _upsert(db, Client, data, "toku", external_id):
            count += 1
    db.flush()
    return count


def _etl_toku_planes(db: Session, dsn: str) -> int:
    """Deriva Plans de Toku desde los product_ids únicos en subscription."""
    rows = _fetch(
        dsn,
        "SELECT DISTINCT raw_payload->>'product_id' AS product_id"
        " FROM subscription"
        " WHERE raw_payload->>'product_id' IS NOT NULL",
    )
    count = 0
    for row in rows:
        product_id = row.get("product_id")
        if not product_id:
            continue
        data = {
            "name": f"Toku producto {product_id}",
            "status": "active",
            "is_active": "true",
            "raw_payload": {"product_id": product_id},
        }
        if _upsert(db, Plan, data, "toku", product_id):
            count += 1
    db.flush()
    return count


def _etl_toku_subscripciones(db: Session, dsn: str) -> int:
    rows = _fetch(dsn, "SELECT raw_payload FROM subscription")
    count = 0
    for row in rows:
        payload = row["raw_payload"]
        external_id = _get(payload, "id")
        customer = payload.get("customer")
        recurring = payload.get("recurring") if isinstance(payload.get("recurring"), dict) else {}
        customer_id = (
            _get(customer, "id") if isinstance(customer, dict) else _get(payload, "customer")
        )
        data = {
            "client_external_id": customer_id,
            "plan_external_id": _get(payload, "product_id"),
            "status": _get(payload, "status") or _get(recurring, "status"),
            "suscription_date": _get(payload, "anchor") or _get(recurring, "anchor"),
            "canceled_at": _get(payload, "end_date") or _get(recurring, "end_date"),
            "amount": _get(payload, "amount") or _get(recurring, "amount"),
            "currency": _get(payload, "currency_code") or _get(recurring, "currency"),
            "raw_payload": payload,
        }
        if _upsert(db, Subscription, data, "toku", external_id):
            count += 1
    db.flush()
    return count


def _etl_toku_cargos(db: Session, dsn: str) -> int:
    rows = _fetch(dsn, "SELECT raw_payload FROM invoices")
    count = 0
    for row in rows:
        payload = row["raw_payload"]
        external_id = _get(payload, "id")
        subscription = payload.get("subscription")
        sub_id = (
            _get(subscription, "id") if isinstance(subscription, dict) else _get(payload, "subscription")
        )
        data = {
            "subscription_external_id": sub_id,
            "client_external_id": _relationship_id(payload.get("customer")),
            "amount": _get(payload, "amount"),
            "currency": _get(payload, "currency_code"),
            "status": _get(payload, "status"),
            "charge_date": _get(payload, "due_date"),
            "raw_payload": payload,
        }
        if _upsert(db, Charge, data, "toku", external_id):
            count += 1
    db.flush()
    return count


def _etl_toku_pagos(db: Session, dsn: str) -> int:
    rows = _fetch(dsn, "SELECT raw_payload FROM payment")
    count = 0
    for row in rows:
        payload = row["raw_payload"]
        # El payload de Toku payment tiene estructura anidada: {transaction: {id, amount, ...}}
        txn = payload.get("transaction") if isinstance(payload.get("transaction"), dict) else {}
        external_id = _get(txn, "id") or _get(payload, "id")
        data = {
            "client_external_id": _relationship_id(payload.get("customer")),
            "amount": _get(txn, "amount") or _get(payload, "amount"),
            "currency": _get(txn, "currency") or _get(payload, "currency"),
            "status": _get(txn, "status") or _get(payload, "status"),
            "payment_date": _get(txn, "transaction_date") or _get(payload, "transaction_date"),
            "raw_payload": payload,
        }
        if _upsert(db, Payment, data, "toku", external_id):
            count += 1
    db.flush()
    return count


def _relationship_id(value: Any) -> str | None:
    if isinstance(value, dict):
        return _get(value, "id", "external_id")
    return _t(value)


def _etl_toku_metodos_pago(db: Session, dsn: str) -> int:
    rows = _fetch(dsn, "SELECT raw_payload FROM payment_method")
    count = 0
    for row in rows:
        payload = row["raw_payload"]
        method = payload.get("payment_method") if isinstance(payload.get("payment_method"), dict) else {}
        external_id = _get(method, "id", "external_id") or _get(payload, "id", "external_id")
        data = {
            "client_external_id": _relationship_id(payload.get("customer")),
            "status": _get(method, "status") or _get(payload, "status"),
            "raw_payload": payload,
        }
        if _upsert(db, PaymentMethod, data, "toku", external_id):
            count += 1
    db.flush()
    return count


def materialize_toku(db: Session) -> int:
    """Refresh canonical Toku records from the local database only."""
    dsn = settings.toku_db_url
    return (
        _etl_toku_clientes(db, dsn)
        + _etl_toku_planes(db, dsn)
        + _etl_toku_subscripciones(db, dsn)
        + _etl_toku_cargos(db, dsn)
        + _etl_toku_metodos_pago(db, dsn)
        + _etl_toku_pagos(db, dsn)
    )


# ─── Payku ────────────────────────────────────────────────────────────────────

def _etl_payku_clientes(db: Session, dsn: str) -> int:
    rows = _fetch(dsn, "SELECT raw_payload FROM cliente")
    count = 0
    for row in rows:
        payload = row["raw_payload"]
        external_id = _get(payload, "id")
        data = {
            "first_name": _get(payload, "first_name"),
            "last_name": _get(payload, "last_name"),
            "email": _get(payload, "email"),
            "phone_number": _get(payload, "phone"),
            "social_id": _get(payload, "rut"),
            "status": _get(payload, "status"),
            "cards": [],
            "raw_payload": payload,
        }
        if _upsert(db, Client, data, "payku", external_id):
            count += 1
    db.flush()
    return count


def _etl_payku_planes(db: Session, dsn: str) -> int:
    rows = _fetch(dsn, "SELECT raw_payload FROM plan")
    count = 0
    for row in rows:
        payload = row["raw_payload"]
        external_id = _get(payload, "id")
        status = _get(payload, "status")
        data = {
            "name": _get(payload, "name"),
            "amount": _get(payload, "amount"),
            "status": status,
            "is_active": "true" if status == "active" else "false",
            "raw_payload": payload,
        }
        if _upsert(db, Plan, data, "payku", external_id):
            count += 1
    db.flush()
    return count


def _etl_payku_subscripciones(db: Session, dsn: str) -> int:
    rows = _fetch(dsn, "SELECT raw_payload FROM subscripcion")
    count = 0
    for row in rows:
        payload = row["raw_payload"]
        external_id = _get(payload, "id")
        client = payload.get("client")
        # Payku usa el campo "plain" (no "plan") para el plan de la suscripción
        plan = payload.get("plain") or payload.get("plan")
        data = {
            "client_external_id": (
                _get(client, "id") if isinstance(client, dict) else _get(payload, "client_id")
            ),
            "client_social_id": _get(client, "rut") if isinstance(client, dict) else None,
            "plan_external_id": (
                _get(plan, "id") if isinstance(plan, dict) else _get(payload, "plan_id")
            ),
            "status": _get(payload, "status"),
            "suscription_date": _get(payload, "start"),
            "canceled_at": _get(payload, "end"),
            "currency": _get(plan, "currency") if isinstance(plan, dict) else None,
            "raw_payload": payload,
        }
        if _upsert(db, Subscription, data, "payku", external_id):
            count += 1
    db.flush()
    return count


def materialize_payku(db: Session) -> int:
    """Refresh canonical Payku records from the local database only."""
    dsn = settings.payku_db_url
    return (
        _etl_payku_clientes(db, dsn)
        + _etl_payku_planes(db, dsn)
        + _etl_payku_subscripciones(db, dsn)
        + _etl_payku_transacciones(db, dsn)
    )


def _etl_payku_transacciones(db: Session, dsn: str) -> int:
    rows = _fetch(dsn, "SELECT raw_payload FROM transaccion")
    count = 0
    for row in rows:
        payload = row["raw_payload"]
        external_id = _get(payload, "id")
        data = {
            "amount": _get(payload, "amount"),
            "status": _get(payload, "status"),
            "payment_date": _get(payload, "created_at"),
            "raw_payload": payload,
        }
        if _upsert(db, Payment, data, "payku", external_id):
            count += 1
    db.flush()
    return count


# ─── Runner ───────────────────────────────────────────────────────────────────

def run_etl_background(run_id: uuid.UUID) -> None:
    """Punto de entrada para BackgroundTask: gestiona su propia sesión."""
    db = SessionLocal()
    try:
        _execute_etl(db, run_id)
    finally:
        db.close()


def _execute_etl(db: Session, run_id: uuid.UUID) -> None:
    etl_run = db.get(EtlRun, run_id)
    if not etl_run:
        return

    vpos_dsn = settings.virtualpos_db_url
    toku_dsn = settings.toku_db_url
    payku_dsn = settings.payku_db_url

    total = 0
    try:
        # Orden: clientes → planes → suscripciones → cargos → pagos
        total += _etl_vpos_clientes(db, vpos_dsn)
        total += _etl_toku_clientes(db, toku_dsn)
        total += _etl_payku_clientes(db, payku_dsn)

        total += _etl_vpos_planes(db, vpos_dsn)
        total += _etl_toku_planes(db, toku_dsn)
        total += _etl_payku_planes(db, payku_dsn)

        total += _etl_vpos_subscripciones(db, vpos_dsn)
        total += _etl_toku_subscripciones(db, toku_dsn)
        total += _etl_payku_subscripciones(db, payku_dsn)

        total += _etl_vpos_cargos(db, vpos_dsn)
        total += _etl_toku_cargos(db, toku_dsn)
        total += _etl_toku_metodos_pago(db, toku_dsn)

        total += _etl_vpos_transacciones(db, vpos_dsn)
        total += _etl_toku_pagos(db, toku_dsn)
        total += _etl_payku_transacciones(db, payku_dsn)

        etl_run.status = "completed"
        etl_run.records_upserted = total
        etl_run.channels_processed = ["virtualpos1", "virtualpos2", "toku", "payku"]
        etl_run.finished_at = datetime.now(tz=timezone.utc)
        db.commit()

    except Exception as exc:
        db.rollback()
        etl_run = db.get(EtlRun, run_id)
        if etl_run:
            etl_run.status = "failed"
            etl_run.error_message = str(exc)[:2000]
            etl_run.finished_at = datetime.now(tz=timezone.utc)
            db.commit()
        raise
