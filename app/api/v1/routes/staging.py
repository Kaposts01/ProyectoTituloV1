import re
from collections import Counter, defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
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
