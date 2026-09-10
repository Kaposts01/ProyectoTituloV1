import re
from collections import Counter, defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.source_record import SourceRecord
from app.models.sync_run import SyncRun

router = APIRouter()
SOURCES = ("virtualpos", "toku", "payku")
PaginationOffset = Annotated[int, Query(ge=0)]
PaginationLimit = Annotated[int, Query(ge=1, le=100)]
ACTIVITY_FIELDS = {
    "virtualpos": ("payment", ("order", "authorized_at"), ("order", "amount"), ("order", "status")),
    "toku": ("invoice", ("due_date",), ("amount",), ("status",)),
    "payku": ("transaction", ("created_at",), ("amount",), ("status",)),
}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _serialize(record: SourceRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "source": record.source,
        "resource_type": record.resource_type,
        "external_id": record.external_id,
        "payload": record.payload,
        "sync_context": record.sync_context,
        "first_seen_at": record.first_seen_at,
        "last_seen_at": record.last_seen_at,
    }


def _payload_value(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _amount(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _month(value: Any) -> tuple[int, int] | None:
    match = re.match(r"(\d{4})-(\d{2})", str(value or ""))
    if not match:
        return None
    year, month = (int(part) for part in match.groups())
    return (year, month) if 1 <= month <= 12 else None


def _staging_filter(source: str, resource_type: str, filter_field: str, query: str):
    payload = SourceRecord.payload
    fields = {
        "virtualpos": {
            "client": {
                "uuid": func.coalesce(payload["uuid"].astext, SourceRecord.external_id),
                "social_id": payload["social_id"].astext,
                "name": func.concat_ws(" ", payload["first_name"].astext, payload["last_name"].astext),
                "email": payload["email"].astext,
                "phone_number": payload["phone_number"].astext,
                "status": payload["status"].astext,
            },
            "plan": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "name": payload["name"].astext,
                "amount": payload["amount"].astext,
                "automatic_renewal": payload["automatic_renewal"].astext,
                "is_active": payload["is_active"].astext,
                "show_in_terminal": payload["show_in_terminal"].astext,
            },
            "subscription": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "status": payload["status"].astext,
                "social_id": payload["client"]["social_id"].astext,
                "amount": payload["amount"].astext,
                "suscription_date": payload["suscription_date"].astext,
                "canceled_at": payload["canceled_at"].astext,
            },
            "charge": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "status": payload["status"].astext,
                "social_id": payload["client"]["social_id"].astext,
                "amount": payload["amount"].astext,
                "charge_date": payload["charge_date"].astext,
            },
            "payment": {
                "uuid": func.coalesce(payload["order"]["uuid"].astext, SourceRecord.external_id),
                "status": payload["order"]["status"].astext,
                "social_id": payload["client"]["social_id"].astext,
                "amount": payload["order"]["amount"].astext,
                "authorized_at": payload["order"]["authorized_at"].astext,
            },
        },
        "toku": {
            "customer": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "government_id": payload["government_id"].astext,
                "name": payload["name"].astext,
                "mail": func.coalesce(payload["mail"].astext, payload["email"].astext),
                "phone_number": payload["phone_number"].astext,
            },
            "subscription": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "customer": func.coalesce(payload["customer"]["id"].astext, payload["customer"].astext),
                "amount": payload["amount"].astext,
                "status": payload["status"].astext,
                "anchor": payload["anchor"].astext,
                "end_date": payload["end_date"].astext,
            },
            "payment_method": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "status": payload["status"].astext,
                "created_at": payload["created_at"].astext,
                "bank_name": payload["bank_name"].astext,
                "card_type": payload["card_type"].astext,
                "customer_id": payload["customer_id"].astext,
                "external_id": SourceRecord.external_id,
                "subscription_ids": payload["subscription_ids"].astext,
            },
            "invoice": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "customer": func.coalesce(payload["customer"]["id"].astext, payload["customer"].astext),
                "subscription": func.coalesce(payload["subscription"]["id"].astext, payload["subscription"].astext),
                "amount": payload["amount"].astext,
                "is_paid": payload["is_paid"].astext,
                "status": payload["status"].astext,
                "due_date": payload["due_date"].astext,
            },
            "transaction": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "customer_id": payload["customer_id"].astext,
                "subscription_id": payload["subscription_id"].astext,
                "amount": payload["amount"].astext,
                "transaction_date": payload["transaction_date"].astext,
            },
        },
        "payku": {
            "client": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "rut": payload["rut"].astext,
                "name": func.coalesce(func.concat_ws(" ", payload["first_name"].astext, payload["last_name"].astext), payload["name"].astext),
                "email": payload["email"].astext,
                "phone": payload["phone"].astext,
            },
            "plan": {"id": func.coalesce(payload["id"].astext, SourceRecord.external_id), "status": payload["status"].astext, "name": payload["name"].astext},
            "subscription": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "status": payload["status"].astext,
                "rut": payload["client"]["rut"].astext,
                "start": payload["start"].astext,
                "end": payload["end"].astext,
            },
            "transaction": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "status": payload["status"].astext,
                "subscriptions": payload["subscriptions"].astext,
                "amount": payload["amount"].astext,
                "created_at": payload["created_at"].astext,
            },
        },
    }
    field = fields.get(source, {}).get(resource_type, {}).get(filter_field)
    if field is None:
        raise HTTPException(status_code=422, detail="Invalid staging filter field")
    normalized_query = query.strip().lower()
    if filter_field in {"automatic_renewal", "is_active", "show_in_terminal", "is_paid"}:
        if normalized_query in {"activo", "activa", "true", "t", "1", "si", "sí"}:
            return cast(field, String).ilike("%true%") | cast(field, String).ilike("%t%")
        if normalized_query in {"inactivo", "inactiva", "false", "f", "0", "no"}:
            return cast(field, String).ilike("%false%") | cast(field, String).ilike("%f%")
    return cast(field, String).ilike(f"%{query.strip()}%")


def _record_order(source: str, resource_type: str):
    if source == "virtualpos" and resource_type == "charge":
        return (SourceRecord.payload["charge_date"].astext.desc().nullslast(), SourceRecord.last_seen_at.desc())
    if source == "virtualpos" and resource_type == "payment":
        return (SourceRecord.payload["order"]["authorized_at"].astext.desc().nullslast(), SourceRecord.last_seen_at.desc())
    return (SourceRecord.last_seen_at.desc(),)


@router.get("/records", tags=["Staging"])
def list_records(
    source: str,
    db: Session = Depends(get_db),  # noqa: B008
    resource_type: str | None = None,
    filter_field: str | None = None,
    query: str | None = None,
    offset: PaginationOffset = 0,
    limit: PaginationLimit = 50,
) -> dict[str, Any]:
    statement = select(SourceRecord).where(SourceRecord.source == source)
    count_statement = select(func.count()).select_from(SourceRecord).where(SourceRecord.source == source)
    if resource_type:
        statement = statement.where(SourceRecord.resource_type == resource_type)
        count_statement = count_statement.where(SourceRecord.resource_type == resource_type)
    if filter_field and query and resource_type:
        filter_expression = _staging_filter(source, resource_type, filter_field, query)
        statement = statement.where(filter_expression)
        count_statement = count_statement.where(filter_expression)
    records = db.scalars(statement.order_by(*_record_order(source, resource_type or "")).offset(offset).limit(limit)).all()
    return {
        "items": [_serialize(record) for record in records],
        "total": db.scalar(count_statement) or 0,
        "offset": offset,
        "limit": limit,
    }


@router.get("/virtualpos/clients/{external_id}", tags=["Staging"])
def virtualpos_client_detail(
    external_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    offset: PaginationOffset = 0,
    limit: PaginationLimit = 50,
) -> dict[str, Any]:
    client = db.scalar(
        select(SourceRecord).where(
            SourceRecord.source == "virtualpos",
            SourceRecord.resource_type == "client",
            SourceRecord.external_id == external_id,
        )
    )
    if client is None:
        raise HTTPException(status_code=404, detail="VirtualPOS client not found")

    social_id = client.payload.get("social_id")
    if social_id is None:
        return {"client": _serialize(client), "subscriptions": [], "subscription_total": 0}

    filters = (
        SourceRecord.source == "virtualpos",
        SourceRecord.resource_type == "subscription",
        SourceRecord.payload["client"]["social_id"].astext == str(social_id),
    )
    subscriptions = db.scalars(
        select(SourceRecord).where(*filters).order_by(SourceRecord.last_seen_at.desc()).offset(offset).limit(limit)
    ).all()
    total = db.scalar(select(func.count()).select_from(SourceRecord).where(*filters)) or 0
    return {
        "client": _serialize(client),
        "subscriptions": [_serialize(subscription) for subscription in subscriptions],
        "subscription_total": total,
    }


@router.get("/virtualpos/plans/{external_id}", tags=["Staging"])
def virtualpos_plan_detail(
    external_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    offset: PaginationOffset = 0,
    limit: PaginationLimit = 50,
) -> dict[str, Any]:
    plan = db.scalar(
        select(SourceRecord).where(
            SourceRecord.source == "virtualpos",
            SourceRecord.resource_type == "plan",
            SourceRecord.external_id == external_id,
        )
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="VirtualPOS plan not found")

    plan_id = str(plan.payload.get("id", plan.external_id))
    filters = (
        SourceRecord.source == "virtualpos",
        SourceRecord.resource_type == "subscription",
        or_(
            SourceRecord.payload["plan_id"].astext == plan_id,
            SourceRecord.payload["plan_id"].astext == plan.external_id,
        ),
    )
    subscriptions = db.scalars(
        select(SourceRecord).where(*filters).order_by(SourceRecord.last_seen_at.desc()).offset(offset).limit(limit)
    ).all()
    total = db.scalar(select(func.count()).select_from(SourceRecord).where(*filters)) or 0
    return {
        "plan": _serialize(plan),
        "subscriptions": [_serialize(subscription) for subscription in subscriptions],
        "subscription_total": total,
    }


@router.get("/virtualpos/subscriptions/{external_id}", tags=["Staging"])
def virtualpos_subscription_detail(
    external_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    offset: PaginationOffset = 0,
    limit: PaginationLimit = 50,
) -> dict[str, Any]:
    subscription = db.scalar(
        select(SourceRecord).where(
            SourceRecord.source == "virtualpos",
            SourceRecord.resource_type == "subscription",
            SourceRecord.external_id == external_id,
        )
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="VirtualPOS subscription not found")

    filters = (
        SourceRecord.source == "virtualpos",
        SourceRecord.resource_type == "charge",
        SourceRecord.sync_context["subscription_external_id"].astext == subscription.external_id,
    )
    charges = db.scalars(
        select(SourceRecord)
        .where(*filters)
        .order_by(SourceRecord.payload["charge_date"].astext.desc().nullslast(), SourceRecord.last_seen_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    total = db.scalar(select(func.count()).select_from(SourceRecord).where(*filters)) or 0
    return {
        "subscription": _serialize(subscription),
        "payment_method": subscription.payload.get("payment_method"),
        "charges": [_serialize(charge) for charge in charges],
        "charge_total": total,
    }


@router.get("/virtualpos/charges/{external_id}", tags=["Staging"])
def virtualpos_charge_detail(
    external_id: str,
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    charge = db.scalar(
        select(SourceRecord).where(
            SourceRecord.source == "virtualpos",
            SourceRecord.resource_type == "charge",
            SourceRecord.external_id == external_id,
        )
    )
    if charge is None:
        raise HTTPException(status_code=404, detail="VirtualPOS charge not found")
    return {"charge": _serialize(charge)}


@router.get("/virtualpos/payments/{external_id}", tags=["Staging"])
def virtualpos_payment_detail(
    external_id: str,
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    payment = db.scalar(
        select(SourceRecord).where(
            SourceRecord.source == "virtualpos",
            SourceRecord.resource_type == "payment",
            SourceRecord.external_id == external_id,
        )
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="VirtualPOS payment not found")
    return {"payment": _serialize(payment)}


def _record_value(record: SourceRecord) -> str:
    return str(record.payload.get("id", record.external_id))


def _relationship_id(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("id")
    return str(value) if value is not None else None


def _matching_records(records: list[SourceRecord], resource_type: str, predicate: Any) -> list[dict[str, Any]]:
    return [_serialize(record) for record in records if record.resource_type == resource_type and predicate(record)]


def _related(label: str, resource_type: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"label": label, "resource_type": resource_type, "items": items}


def _toku_related(record: SourceRecord, records: list[SourceRecord]) -> list[dict[str, Any]]:
    record_id = _record_value(record)
    if record.resource_type == "customer":
        return [
            _related("Subscripciones", "subscription", _matching_records(records, "subscription", lambda item: _relationship_id(item.payload.get("customer")) == record_id)),
            _related("Métodos de pago", "payment_method", _matching_records(records, "payment_method", lambda item: _relationship_id(item.payload.get("customer_id")) == record_id)),
            _related("Deudas", "invoice", _matching_records(records, "invoice", lambda item: _relationship_id(item.payload.get("customer")) == record_id)),
            _related("Transacciones", "transaction", _matching_records(records, "transaction", lambda item: _relationship_id(item.payload.get("customer_id")) == record_id)),
        ]
    if record.resource_type == "subscription":
        return [
            _related("Cliente", "customer", _matching_records(records, "customer", lambda item: _record_value(item) == _relationship_id(record.payload.get("customer")))),
            _related("Métodos de pago", "payment_method", _matching_records(records, "payment_method", lambda item: record_id in item.payload.get("subscription_ids", []) if isinstance(item.payload.get("subscription_ids"), list) else False)),
            _related("Deudas", "invoice", _matching_records(records, "invoice", lambda item: _relationship_id(item.payload.get("subscription")) == record_id)),
            _related("Transacciones", "transaction", _matching_records(records, "transaction", lambda item: _relationship_id(item.payload.get("subscription_id")) == record_id)),
        ]
    if record.resource_type == "payment_method":
        subscription_ids = record.payload.get("subscription_ids", [])
        return [
            _related("Cliente", "customer", _matching_records(records, "customer", lambda item: _record_value(item) == _relationship_id(record.payload.get("customer_id")))),
            _related("Subscripciones", "subscription", _matching_records(records, "subscription", lambda item: _record_value(item) in subscription_ids if isinstance(subscription_ids, list) else False)),
        ]
    if record.resource_type == "invoice":
        return [
            _related("Cliente", "customer", _matching_records(records, "customer", lambda item: _record_value(item) == _relationship_id(record.payload.get("customer")))),
            _related("Subscripción", "subscription", _matching_records(records, "subscription", lambda item: _record_value(item) == _relationship_id(record.payload.get("subscription")))),
        ]
    if record.resource_type == "transaction":
        return [
            _related("Cliente", "customer", _matching_records(records, "customer", lambda item: _record_value(item) == _relationship_id(record.payload.get("customer_id")))),
            _related("Subscripción", "subscription", _matching_records(records, "subscription", lambda item: _record_value(item) == _relationship_id(record.payload.get("subscription_id")))),
        ]
    return []


def _payku_related(record: SourceRecord, records: list[SourceRecord]) -> list[dict[str, Any]]:
    record_id = _record_value(record)
    if record.resource_type == "client":
        return [_related("Suscripciones", "subscription", _matching_records(records, "subscription", lambda item: _relationship_id(item.payload.get("client")) == record_id))]
    if record.resource_type == "plan":
        return [_related("Suscripciones", "subscription", _matching_records(records, "subscription", lambda item: _relationship_id(item.payload.get("plan")) == record_id))]
    if record.resource_type == "subscription":
        return [
            _related("Cliente", "client", _matching_records(records, "client", lambda item: _record_value(item) == _relationship_id(record.payload.get("client")))),
            _related("Plan", "plan", _matching_records(records, "plan", lambda item: _record_value(item) == _relationship_id(record.payload.get("plan")))),
        ]
    return []


@router.get("/{source}/{resource_type}/{external_id}", tags=["Staging"])
def provider_record_detail(
    source: str,
    resource_type: str,
    external_id: str,
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    allowed_resources = {
        "toku": {"customer", "subscription", "payment_method", "invoice", "transaction"},
        "payku": {"client", "plan", "subscription", "transaction"},
    }
    if resource_type not in allowed_resources.get(source, set()):
        raise HTTPException(status_code=404, detail="Unknown staging resource")
    records = db.scalars(select(SourceRecord).where(SourceRecord.source == source)).all()
    record = next((item for item in records if item.resource_type == resource_type and item.external_id == external_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail="Staging record not found")
    related = _toku_related(record, records) if source == "toku" else _payku_related(record, records)
    return {"record": _serialize(record), "related": related}


@router.get("/summary", tags=["Staging"])
def staging_summary(db: Session = Depends(get_db)) -> dict[str, list[dict[str, Any]]]:  # noqa: B008
    sources = []
    for source in SOURCES:
        resource_counts = dict(
            db.execute(
                select(SourceRecord.resource_type, func.count())
                .where(SourceRecord.source == source)
                .group_by(SourceRecord.resource_type)
            ).all()
        )
        latest_run = db.scalars(
            select(SyncRun).where(SyncRun.source == source).order_by(SyncRun.started_at.desc()).limit(1)
        ).first()
        sources.append(
            {
                "source": source,
                "records": sum(resource_counts.values()),
                "resources": resource_counts,
                "last_sync": (
                    {
                        "id": str(latest_run.id),
                        "status": latest_run.status,
                        "started_at": latest_run.started_at,
                        "finished_at": latest_run.finished_at,
                        "records_processed": latest_run.records_processed,
                    }
                    if latest_run
                    else None
                ),
            }
        )
    return {"sources": sources}


@router.get("/dashboard/{source}", tags=["Staging"])
def channel_dashboard(source: str, db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    if source not in SOURCES:
        raise HTTPException(status_code=404, detail="Unknown staging source")

    records = db.scalars(select(SourceRecord).where(SourceRecord.source == source)).all()
    resource_counts = Counter(record.resource_type for record in records)
    resource_amounts: dict[str, float] = defaultdict(float)
    status_counts: Counter[tuple[str, str]] = Counter()
    activity_by_month: dict[tuple[int, int], dict[str, float]] = defaultdict(lambda: {"count": 0, "amount": 0})
    activity_resource, date_path, amount_path, _ = ACTIVITY_FIELDS[source]

    for record in records:
        amount_value = _payload_value(record.payload, ("amount",))
        if amount_value is None:
            amount_value = _payload_value(record.payload, ("order", "amount"))
        if amount_value is not None:
            resource_amounts[record.resource_type] += _amount(amount_value)
        status = _payload_value(record.payload, ("status",))
        if status is None:
            status = _payload_value(record.payload, ("order", "status"))
        if status is not None:
            status_counts[(record.resource_type, str(status))] += 1
        if record.resource_type != activity_resource:
            continue
        month = _month(_payload_value(record.payload, date_path))
        if month is None:
            continue
        activity = activity_by_month[month]
        activity["count"] += 1
        activity["amount"] += _amount(_payload_value(record.payload, amount_path))

    latest_run = db.scalars(
        select(SyncRun).where(SyncRun.source == source).order_by(SyncRun.started_at.desc()).limit(1)
    ).first()
    activity = [
        {"year": year, "month": month, "count": int(values["count"]), "amount": values["amount"]}
        for (year, month), values in sorted(activity_by_month.items())
    ]
    return {
        "source": source,
        "records": len(records),
        "resources": dict(resource_counts),
        "resource_amounts": {resource: round(total, 2) for resource, total in resource_amounts.items()},
        "statuses": [
            {"resource": resource, "status": status, "count": count}
            for (resource, status), count in sorted(status_counts.items())
        ],
        "activity_resource": activity_resource,
        "activity": activity,
        "years": sorted({entry["year"] for entry in activity}, reverse=True),
        "last_sync": (
            {
                "status": latest_run.status,
                "started_at": latest_run.started_at,
                "finished_at": latest_run.finished_at,
                "records_processed": latest_run.records_processed,
            }
            if latest_run
            else None
        ),
    }
