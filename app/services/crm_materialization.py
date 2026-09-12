from collections.abc import Iterable
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.crm import Charge, Client, Payment, PaymentMethod, Plan, Subscription
from app.models.source_record import SourceRecord


def _text(record: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if value is not None:
            return str(value)
    return None


def _nested_text(record: dict[str, Any], key: str, *nested_keys: str) -> str | None:
    nested = record.get(key)
    if not isinstance(nested, dict):
        return None
    return _text(nested, *nested_keys)


def _card_summaries(payload: dict[str, Any]) -> list[dict[str, str | None]]:
    cards = payload.get("cards")
    if not isinstance(cards, list):
        return []
    summaries = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        details = card.get("card") if isinstance(card.get("card"), dict) else {}
        summaries.append(
            {
                "reference_id": _text(card, "card_reference_id"),
                "status": _text(card, "status"),
                "created_at": _text(card, "created_at"),
                "brand": _text(details, "brand"),
                "card_type": _text(details, "card_type"),
                "issuer": _text(details, "issuer"),
                "issuer_code": _text(details, "issuer_code"),
                "last4": _text(details, "last4"),
                "nacional": _text(details, "nacional"),
            }
        )
    return summaries


def _values(record: SourceRecord) -> dict[str, Any]:
    payload = record.payload
    sync_context = record.sync_context or {}
    return {
        "first_name": _text(payload, "first_name", "name"),
        "last_name": _text(payload, "last_name"),
        "name": _text(payload, "name"),
        "description": _text(payload, "description"),
        "email": _text(payload, "email"),
        "phone_number": _text(payload, "phone_number", "phone"),
        "social_id": _text(payload, "social_id"),
        "gender_id": _text(payload, "gender_id"),
        "birth_date": _text(payload, "birth_date"),
        "provider_created_at": _text(payload, "created"),
        "cards": _card_summaries(payload),
        "client_external_id": _text(payload, "client_id", "client_uuid") or _nested_text(payload, "customer", "id", "external_id"),
        "client_social_id": _nested_text(payload, "client", "social_id") or _text(payload, "social_id"),
        "plan_external_id": _text(payload, "plan_id"),
        "service_id": _text(payload, "service_id"),
        "automatic_renewal": _text(payload, "automatic_renewal"),
        "suscription_date": _text(payload, "suscription_date"),
        "canceled_at": _text(payload, "canceled_at"),
        "plan_type": _text(payload, "type"),
        "is_active": _text(payload, "is_active"),
        "subscription_external_id": _text(
            sync_context, "subscription_external_id"
        ) or _text(payload, "suscription_id", "subscription_id"),
        "charge_external_id": _text(payload, "charge_id", "charge_uuid"),
        "amount": _text(payload, "amount") or _nested_text(payload, "order", "amount"),
        "currency": _text(payload, "currency") or _nested_text(payload, "order", "currency"),
        "status": _text(payload, "status") or _nested_text(payload, "order", "status"),
        "charge_date": _text(payload, "charge_date"),
        "payment_date": _text(payload, "payment_date") or _nested_text(payload, "order", "authorized_at", "created_at"),
    }


def _upsert(db: Session, model: type[Charge | Client | Payment | PaymentMethod | Plan | Subscription], record: SourceRecord) -> None:
    values = _values(record)
    allowed = {column.name for column in model.__table__.columns}
    row = {
        "source": record.source,
        "external_id": record.external_id,
        "source_record_id": record.id,
        **{key: value for key, value in values.items() if key in allowed},
    }
    statement = insert(model).values(**row)
    statement = statement.on_conflict_do_update(
        constraint={
            Client: "uq_client_source_external_id",
            Plan: "uq_plan_source_external_id",
            Subscription: "uq_subscription_source_external_id",
            Charge: "uq_charge_source_external_id",
            Payment: "uq_payment_source_external_id",
        }[model],
        set_={key: statement.excluded[key] for key in row if key not in {"source", "external_id"}},
    )
    db.execute(statement)


def materialize_records(db: Session, records: Iterable[SourceRecord]) -> int:
    models = {
        "client": Client,
        "plan": Plan,
        "subscription": Subscription,
        "charge": Charge,
        "payment": Payment,
        "payment_method": PaymentMethod,
    }
    processed = 0
    for record in records:
        model = models.get(record.resource_type)
        if model is None:
            continue
        _upsert(db, model, record)
        processed += 1
    return processed
