"""Upsert helpers para escribir en las tablas tipadas por canal (vp_*, toku_*, payku_*).

Cada proveedor tiene sus propios extractores que mapean el payload de la API
a los campos de la tabla de canal correspondiente.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.payku_channel import (
    PaykuClient,
    PaykuPlan,
    PaykuSubscription,
    PaykuTransaction,
)
from app.models.toku_channel import (
    TokuCustomer,
    TokuInvoice,
    TokuPaymentMethod,
    TokuSubscription,
    TokuTransaction,
)
from app.models.vp import VpCharge, VpClient, VpPayment, VpPlan, VpSubscription
from app.services.payload_sanitization import sanitize_payload

# ── Utilidades ────────────────────────────────────────────────────────────────

def _get(d: dict, *keys: str, default: Any = None) -> Any:
    """Primer valor no-None de una lista de claves (soporta notación 'a.b')."""
    for key in keys:
        val: Any = d
        for part in key.split("."):
            val = val.get(part) if isinstance(val, dict) else None
        if val is not None:
            return val
    return default


def _str(d: dict, *keys: str) -> str | None:
    val = _get(d, *keys)
    return str(val) if val is not None else None


def _relationship_id(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("id") or value.get("external_id")
    return str(value) if value is not None else None


def _card_summaries(cards: Any) -> list[dict] | None:
    if not isinstance(cards, list):
        return None
    result = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        inner = card.get("card") or {}
        result.append({
            "reference_id": card.get("card_reference_id"),
            "status": card.get("status"),
            "created_at": card.get("created_at"),
            "brand": inner.get("brand"),
            "card_type": inner.get("card_type"),
            "issuer": inner.get("issuer"),
            "issuer_code": inner.get("issuer_code"),
            "last4": inner.get("last4"),
            "nacional": inner.get("nacional"),
            "expiration_month": inner.get("expiration_month") or inner.get("expiry_month"),
            "expiration_year": inner.get("expiration_year") or inner.get("expiry_year"),
        })
    return result or None


def upsert_channel(
    db: Session,
    model: type,
    records: Iterable[dict],
    extract: Callable[[dict], dict],
) -> int:
    """Inserta o actualiza un lote saneado de registros de un canal."""
    identity_fields = ("platform", "external_id") if model in {VpClient, VpPlan, VpSubscription, VpCharge, VpPayment} else ("external_id",)
    rows = []
    for record in records:
        sanitized = sanitize_payload(record)
        values = extract(sanitized)
        if not values.get("external_id"):
            continue
        values.setdefault("id", uuid.uuid4())
        sanitized.pop("__external_id", None)
        values["raw_payload"] = sanitized
        rows.append(values)
    if not rows:
        return 0
    # Deduplicar por identity_fields para evitar CardinalityViolation en ON CONFLICT DO UPDATE
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for row in rows:
        key = tuple(row.get(f) for f in identity_fields)
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    rows = deduped
    stmt = insert(model).values(rows)
    updatable = {key: stmt.excluded[key] for key in rows[0] if key not in (*identity_fields, "id", "created_at")}
    stmt = stmt.on_conflict_do_update(index_elements=list(identity_fields), set_=updatable)
    db.execute(stmt)
    db.commit()
    return len(rows)


# ── Extractores VirtualPOS ────────────────────────────────────────────────────

def extract_vp_client(p: dict) -> dict:
    return {
        "external_id": _str(p, "__external_id", "id", "uuid"),
        "first_name": _str(p, "first_name", "name"),
        "last_name": _str(p, "last_name"),
        "email": _str(p, "email"),
        "phone_number": _str(p, "phone_number", "phone"),
        "status": _str(p, "status"),
        "social_id": _str(p, "social_id"),
        "gender_id": _str(p, "gender_id"),
        "birth_date": _str(p, "birth_date"),
        "provider_created_at": _str(p, "created", "created_at"),
        "private_note": _str(p, "private_note"),
        "cards": _card_summaries(p.get("cards")),
    }


def extract_vp_plan(p: dict) -> dict:
    return {
        "external_id": _str(p, "__external_id", "id", "uuid"),
        "name": _str(p, "name"),
        "description": _str(p, "description"),
        "amount": _str(p, "amount"),
        "currency": _str(p, "currency"),
        "plan_type": _str(p, "type"),
        "is_active": _str(p, "is_active"),
        "status": _str(p, "status"),
    }


def extract_vp_subscription(p: dict) -> dict:
    order = p.get("order") or {}
    return {
        "external_id": _str(p, "__external_id", "id", "uuid"),
        "client_external_id": _str(p, "client_uuid", "client_id", "client.uuid"),
        "client_social_id": _str(p, "client.social_id", "social_id"),
        "plan_external_id": _str(p, "plan_id"),
        "service_id": _str(p, "service_id"),
        "status": _str(p, "status") or _str(order, "status"),
        "automatic_renewal": _str(p, "automatic_renewal", "renewal"),
        "suscription_date": _str(p, "suscription_date"),
        "canceled_at": _str(p, "canceled_at"),
        "amount": _str(p, "amount") or _str(order, "amount"),
        "currency": _str(p, "currency") or _str(order, "currency"),
    }


def extract_vp_charge(p: dict, subscription_external_id: str | None = None) -> dict:
    order = p.get("order") or {}
    return {
        "external_id": _str(p, "__external_id", "id", "uuid", "order.uuid"),
        "subscription_external_id": _str(p, "suscription_id", "subscription_id") or subscription_external_id,
        "client_external_id": _str(p, "client_uuid", "client_id"),
        "amount": _str(p, "amount") or _str(order, "amount"),
        "currency": _str(p, "currency") or _str(order, "currency"),
        "status": _str(p, "status") or _str(order, "status"),
        "charge_date": _str(p, "charge_date") or _str(order, "created_at"),
    }


def extract_vp_payment(p: dict) -> dict:
    order = p.get("order") or {}
    return {
        "external_id": _str(p, "__external_id", "id", "uuid", "order.uuid"),
        "charge_external_id": _str(p, "charge_id", "charge_uuid"),
        "client_external_id": _str(p, "client_uuid", "client_id"),
        "amount": _str(p, "amount") or _str(order, "amount"),
        "currency": _str(p, "currency") or _str(order, "currency"),
        "status": _str(p, "status") or _str(order, "status"),
        "payment_date": _str(p, "payment_date") or _str(order, "authorized_at") or _str(order, "created_at"),
    }


# ── Extractores Toku ──────────────────────────────────────────────────────────

def extract_toku_customer(p: dict) -> dict:
    return {
        "external_id": _str(p, "__external_id", "id", "external_id"),
        "name": _str(p, "name"),
        "email": _str(p, "mail", "email"),
        "phone_number": _str(p, "phone_number", "phone"),
        "government_id": _str(p, "government_id"),
        "status": _str(p, "status"),
    }


def extract_toku_subscription(p: dict) -> dict:
    recurring = p.get("recurring") or {}
    customer = p.get("customer") or {}
    return {
        "external_id": _str(p, "__external_id", "id"),
        "customer_id": _relationship_id(customer) or _str(p, "customer_id"),
        "status": _str(p, "status") or _str(recurring, "status"),
        "amount": _str(p, "amount") or _str(recurring, "amount"),
        "currency_code": _str(p, "currency_code") or _str(recurring, "currency"),
        "anchor": _str(p, "anchor") or _str(recurring, "anchor"),
        "end_date": _str(p, "end_date") or _str(recurring, "end_date"),
    }


def extract_toku_invoice(p: dict) -> dict:
    sub = p.get("subscription") or {}
    return {
        "external_id": _str(p, "__external_id", "id"),
        "subscription_id": _str(p, "subscription_id") or _relationship_id(sub),
        "status": _str(p, "status"),
        "amount": _str(p, "amount"),
        "currency": _str(p, "currency"),
        "due_date": _str(p, "due_date", "created_at"),
    }


def extract_toku_transaction(p: dict) -> dict:
    transaction = p.get("transaction") or p
    pm = transaction.get("payment_method") or p.get("payment_method") or {}
    return {
        "external_id": _str(p, "__external_id") or _str(transaction, "id"),
        "status": _str(transaction, "status"),
        "amount": _str(transaction, "amount"),
        "currency": _str(transaction, "currency"),
        "payment_method_id": _str(transaction, "payment_method_id") or _str(pm, "id"),
        "created_at_api": _str(transaction, "created_at", "transaction_date"),
    }


def extract_toku_payment_method(p: dict) -> dict:
    method = p.get("payment_method") or p
    customer = p.get("customer") or {}
    return {
        "external_id": _str(p, "__external_id") or _str(method, "id", "external_id"),
        "customer_id": _str(p, "customer_id") or _relationship_id(customer),
        "status": _str(method, "status") or _str(p, "status"),
    }


# ── Extractores Payku ─────────────────────────────────────────────────────────

def extract_payku_client(p: dict) -> dict:
    return {
        "external_id": _str(p, "__external_id", "id"),
        "name": _str(p, "name"),
        "email": _str(p, "email"),
        "phone": _str(p, "phone"),
        "rut": _str(p, "rut"),
        "status": _str(p, "status"),
    }


def extract_payku_plan(p: dict) -> dict:
    return {
        "external_id": _str(p, "__external_id", "id"),
        "name": _str(p, "name"),
        "amount": _str(p, "amount"),
        "currency": _str(p, "currency"),
        "status": _str(p, "status"),
    }


def extract_payku_subscription(p: dict) -> dict:
    client = p.get("client") or {}
    plan = p.get("plain") or p.get("plan") or {}
    successful_transactions = [
        transaction
        for transaction in p.get("transactions", [])
        if isinstance(transaction, dict)
        and str(transaction.get("status", "")).lower() == "success"
        and transaction.get("amount") is not None
    ]
    latest_successful_amount = None
    if successful_transactions:
        latest_successful_amount = max(
            successful_transactions,
            key=lambda transaction: str(transaction.get("created_at") or ""),
        ).get("amount")
    amount = _str(p, "amount") or _str(plan, "amount")
    if amount is None and latest_successful_amount is not None:
        amount = str(latest_successful_amount)
    return {
        "external_id": _str(p, "__external_id", "id"),
        "client_id": _str(p, "client_id") or _str(client, "id"),
        "plan_id": _str(p, "plan_id") or _str(plan, "id"),
        "status": _str(p, "status"),
        "amount": amount,
        "currency": _str(p, "currency") or _str(plan, "currency"),
    }


def extract_payku_transaction(p: dict) -> dict:
    sub = p.get("subscription") or p.get("subscriptions") or {}
    return {
        "external_id": _str(p, "__external_id", "id"),
        "subscription_id": _str(p, "subscription_id") or _str(sub, "id"),
        "amount": _str(p, "amount"),
        "currency": _str(p, "currency"),
        "status": _str(p, "status"),
        "created_at_api": _str(p, "created_at"),
    }


# ── Funciones de sincronización por canal ─────────────────────────────────────

def store_vp_resources(db: Session, resource_type: str, records: list[dict], *, platform: str, **kwargs: Any) -> int:
    """Escribe registros VirtualPOS en su tabla canal correspondiente."""
    _map = {
        "client": (VpClient, extract_vp_client),
        "plan": (VpPlan, extract_vp_plan),
        "subscription": (VpSubscription, extract_vp_subscription),
        "payment": (VpPayment, extract_vp_payment),
    }
    if resource_type == "charge":
        subscription_id = kwargs.get("subscription_external_id")
        return upsert_channel(db, VpCharge, records, lambda r: {"platform": platform, **extract_vp_charge(r, subscription_id)})
    if resource_type not in _map:
        return 0
    model, extractor = _map[resource_type]
    return upsert_channel(db, model, records, lambda r: {"platform": platform, **extractor(r)})


def store_toku_resources(db: Session, resource_type: str, records: list[dict]) -> int:
    """Escribe registros Toku en su tabla canal correspondiente."""
    _map = {
        "customer": (TokuCustomer, extract_toku_customer),
        "subscription": (TokuSubscription, extract_toku_subscription),
        "invoice": (TokuInvoice, extract_toku_invoice),
        "transaction": (TokuTransaction, extract_toku_transaction),
        "payment_method": (TokuPaymentMethod, extract_toku_payment_method),
    }
    if resource_type not in _map:
        return 0
    model, extractor = _map[resource_type]
    return upsert_channel(db, model, records, extractor)


def store_payku_resources(db: Session, resource_type: str, records: list[dict]) -> int:
    """Escribe registros Payku en su tabla canal correspondiente."""
    _map = {
        "client": (PaykuClient, extract_payku_client),
        "plan": (PaykuPlan, extract_payku_plan),
        "subscription": (PaykuSubscription, extract_payku_subscription),
        "transaction": (PaykuTransaction, extract_payku_transaction),
    }
    if resource_type not in _map:
        return 0
    model, extractor = _map[resource_type]
    return upsert_channel(db, model, records, extractor)
