import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.crm import CanonicalRecord, Charge, Client, Payment, Plan, Subscription

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _serialize(record: CanonicalRecord, include_cards: bool = True) -> dict[str, Any]:
    return {
        column.name: str(value) if column.name in {"id", "source_record_id"} else value
        for column in record.__table__.columns
        if include_cards or column.name != "cards"
        if (value := getattr(record, column.name)) is not None
    }


def _list(
    db: Session,
    model: type[CanonicalRecord],
    source: str | None,
    status: str | None,
    offset: int,
    limit: int,
) -> list[dict[str, Any]]:
    statement = select(model).order_by(model.updated_at.desc()).offset(offset).limit(limit)
    if source:
        statement = statement.where(model.source == source)
    if status:
        statement = statement.where(model.status == status)
    return [_serialize(record, include_cards=False) for record in db.scalars(statement)]


def _detail(db: Session, model: type[CanonicalRecord], record_id: uuid.UUID) -> dict[str, Any]:
    record = db.get(model, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return _serialize(record)


PaginationOffset = Annotated[int, Query(ge=0)]
PaginationLimit = Annotated[int, Query(ge=1, le=100)]


@router.get("/counts", tags=["CRM"])
def get_counts(
    source: str | None = None,
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, int]:
    """Conteo de registros canónicos por entidad, opcionalmente filtrado por source."""
    models = {
        "clients": Client,
        "plans": Plan,
        "subscriptions": Subscription,
        "charges": Charge,
        "payments": Payment,
    }
    result: dict[str, int] = {}
    for name, model in models.items():
        stmt = select(func.count()).select_from(model)
        if source:
            stmt = stmt.where(model.source == source)
        result[name] = db.scalar(stmt) or 0
    return result


@router.get("/clients", tags=["Cliente"])
def list_clients(
    db: Session = Depends(get_db),  # noqa: B008
    source: str | None = None,
    status: str | None = None,
    offset: PaginationOffset = 0,
    limit: PaginationLimit = 50,
) -> list[dict[str, Any]]:
    return _list(db, Client, source, status, offset, limit)


@router.get("/clients/{record_id}", tags=["Cliente"])
def get_client(record_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    return _detail(db, Client, record_id)


@router.get("/plans", tags=["Plan"])
def list_plans(
    db: Session = Depends(get_db),  # noqa: B008
    source: str | None = None,
    status: str | None = None,
    offset: PaginationOffset = 0,
    limit: PaginationLimit = 50,
) -> list[dict[str, Any]]:
    return _list(db, Plan, source, status, offset, limit)


@router.get("/plans/{record_id}", tags=["Plan"])
def get_plan(record_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    return _detail(db, Plan, record_id)


@router.get("/subscriptions", tags=["Suscription"])
def list_subscriptions(
    db: Session = Depends(get_db),  # noqa: B008
    source: str | None = None,
    status: str | None = None,
    offset: PaginationOffset = 0,
    limit: PaginationLimit = 50,
) -> list[dict[str, Any]]:
    return _list(db, Subscription, source, status, offset, limit)


@router.get("/subscriptions/{record_id}", tags=["Suscription"])
def get_subscription(record_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    return _detail(db, Subscription, record_id)


@router.get("/subscriptions/{record_id}/detail", tags=["Suscription"])
def get_subscription_detail(
    record_id: uuid.UUID,
    db: Session = Depends(get_db),  # noqa: B008
    offset: PaginationOffset = 0,
    limit: PaginationLimit = 50,
) -> dict[str, Any]:
    subscription = db.get(Subscription, record_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Record not found")
    plan = None
    if subscription.plan_external_id:
        plan = db.scalar(
            select(Plan).where(
                Plan.source == subscription.source,
                Plan.external_id == subscription.plan_external_id,
            )
        )
    charge_filter = (
        Charge.source == subscription.source,
        Charge.subscription_external_id == subscription.external_id,
    )
    charges = db.scalars(select(Charge).where(*charge_filter).order_by(Charge.updated_at.desc()).offset(offset).limit(limit)).all()
    charge_total = db.scalar(select(func.count()).select_from(Charge).where(*charge_filter))
    return {
        "subscription": _serialize(subscription),
        "plan": _serialize(plan) if plan else None,
        "charges": [_serialize(charge) for charge in charges],
        "charge_total": charge_total,
    }


@router.get("/charges", tags=["Charge"])
def list_charges(
    db: Session = Depends(get_db),  # noqa: B008
    source: str | None = None,
    status: str | None = None,
    offset: PaginationOffset = 0,
    limit: PaginationLimit = 50,
) -> list[dict[str, Any]]:
    return _list(db, Charge, source, status, offset, limit)


@router.get("/charges/{record_id}", tags=["Charge"])
def get_charge(record_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    return _detail(db, Charge, record_id)


@router.get("/payments", tags=["Payment"])
def list_payments(
    db: Session = Depends(get_db),  # noqa: B008
    source: str | None = None,
    status: str | None = None,
    offset: PaginationOffset = 0,
    limit: PaginationLimit = 50,
) -> list[dict[str, Any]]:
    return _list(db, Payment, source, status, offset, limit)


@router.get("/payments/{record_id}", tags=["Payment"])
def get_payment(record_id: uuid.UUID, db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    return _detail(db, Payment, record_id)
