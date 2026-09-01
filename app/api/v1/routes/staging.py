import re
from collections import Counter, defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
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


@router.get("/records", tags=["Staging"])
def list_records(
    source: str,
    db: Session = Depends(get_db),  # noqa: B008
    resource_type: str | None = None,
    offset: PaginationOffset = 0,
    limit: PaginationLimit = 50,
) -> dict[str, Any]:
    statement = select(SourceRecord).where(SourceRecord.source == source)
    count_statement = select(func.count()).select_from(SourceRecord).where(SourceRecord.source == source)
    if resource_type:
        statement = statement.where(SourceRecord.resource_type == resource_type)
        count_statement = count_statement.where(SourceRecord.resource_type == resource_type)
    records = db.scalars(statement.order_by(SourceRecord.last_seen_at.desc()).offset(offset).limit(limit)).all()
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
        select(SourceRecord).where(*filters).order_by(SourceRecord.last_seen_at.desc()).offset(offset).limit(limit)
    ).all()
    total = db.scalar(select(func.count()).select_from(SourceRecord).where(*filters)) or 0
    return {
        "subscription": _serialize(subscription),
        "payment_method": subscription.payload.get("payment_method"),
        "charges": [_serialize(charge) for charge in charges],
        "charge_total": total,
    }


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
    status_counts: Counter[tuple[str, str]] = Counter()
    activity_by_month: dict[tuple[int, int], dict[str, float]] = defaultdict(lambda: {"count": 0, "amount": 0})
    activity_resource, date_path, amount_path, _ = ACTIVITY_FIELDS[source]

    for record in records:
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
