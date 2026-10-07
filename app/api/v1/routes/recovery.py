from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from httpx import HTTPStatusError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.config import settings
from app.core.security import require_csrf, require_permissions
from app.integrations.virtualpos.client import VirtualPOSClient
from app.models.crm import Charge, Client, Payment, Subscription
from app.models.write_run import WriteRun
from app.services.charge_recovery import PAID_STATUSES, needs_card_change
from app.services.read_only_provider_sync import safe_error_message
from app.services.write_virtualpos import (
    ChargeNotFoundError,
    WriteDisabledError,
    retry_charge,
)

router = APIRouter()
_SOURCES = ("virtualpos1", "virtualpos2")
_REJECTED = {"rechazado", "rejected", "failed", "failure", "declined", "error"}
_ACTIVE_STATUSES = {"activa", "activo", "active", "vigente"}


def _secondary_status(status: str, last_paid: str | None) -> str:
    if str(status).lower() not in _ACTIVE_STATUSES:
        return "inactiva"
    if not last_paid:
        return "nunca_cobrado"
    try:
        paid_date = date.fromisoformat(str(last_paid)[:10])
        if paid_date <= date.today() - timedelta(days=182):
            return "incobrable"
        return "cobrable"
    except (ValueError, TypeError):
        return "nunca_cobrado"


def _date(value: str | None, name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{name} must use YYYY-MM-DD") from exc


def _in_range(value: str | None, start: date | None, end: date | None) -> bool:
    try:
        current = date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return False
    return (start is None or current >= start) and (end is None or current <= end)


def _reason(charge: Charge) -> tuple[str | None, str | None]:
    payload = charge.raw_payload or {}
    rejected = payload.get("rejected_object") if isinstance(payload.get("rejected_object"), dict) else {}
    return (
        str(rejected.get("code")) if rejected.get("code") is not None else None,
        str(rejected.get("message") or payload.get("razon_rechazo") or payload.get("reason") or payload.get("rejection_reason") or "") or None,
    )


def _clients(db: Session) -> dict[tuple[str, str], Client]:
    return {(row.source, row.external_id): row for row in db.scalars(select(Client).where(Client.source.in_(_SOURCES)))}


def _name(client: Client | None) -> str | None:
    if client is None:
        return None
    return " ".join(value for value in (client.first_name, client.last_name) if value) or None


def _card_expiration(client: Client | None) -> str | None:
    """Return a non-sensitive month/year when VirtualPOS supplied it."""
    if client is None:
        return None
    cards = client.cards
    if not cards and isinstance(client.raw_payload, dict):
        cards = client.raw_payload.get("cards")
    if not isinstance(cards, list):
        return None
    for item in cards:
        details = item.get("card") if isinstance(item, dict) and isinstance(item.get("card"), dict) else item
        if not isinstance(details, dict):
            continue
        month = details.get("expiration_month") or details.get("expiry_month")
        year = details.get("expiration_year") or details.get("expiry_year")
        if month is not None and year is not None:
            return f"{int(month):02d}/{year}"
    return None


def _page(rows: list[dict], offset: int, limit: int) -> dict:
    return {"items": rows[offset:offset + limit], "total": len(rows), "offset": offset, "limit": limit}


def _cancelled_rows(db: Session, start: date | None, end: date | None) -> list[dict]:
    subscriptions = [
        sub for sub in db.scalars(select(Subscription).where(Subscription.source.in_(_SOURCES)))
        if _in_range(sub.canceled_at, start, end)
    ]
    clients = _clients(db)
    charges = db.scalars(select(Charge).where(Charge.source.in_(_SOURCES))).all()
    charge_subscriptions = {(charge.source, charge.external_id): charge.subscription_external_id for charge in charges}
    paid_by_subscription: dict[tuple[str, str], float] = {}
    for payment in db.scalars(select(Payment).where(Payment.source.in_(_SOURCES))).all():
        if str(payment.status or "").lower() not in PAID_STATUSES:
            continue
        subscription_id = charge_subscriptions.get((payment.source, payment.charge_external_id or ""))
        if subscription_id is None:
            continue
        try:
            amount = float(payment.amount or 0)
        except (TypeError, ValueError):
            continue
        key = (payment.source, subscription_id)
        paid_by_subscription[key] = paid_by_subscription.get(key, 0) + amount
    rows = []
    for sub in subscriptions:
        client = clients.get((sub.source, sub.client_external_id or ""))
        days = None
        try:
            days = (date.fromisoformat(str(sub.canceled_at)[:10]) - date.fromisoformat(str(sub.suscription_date)[:10])).days
        except (TypeError, ValueError):
            pass
        rows.append({
            "source": sub.source, "subscription_id": sub.external_id, "external_id": sub.external_id,
            "rut": client.social_id if client else sub.client_social_id,
            "client_name": _name(client), "started_at": sub.suscription_date, "cancelled_at": sub.canceled_at,
            "antiquity_days": days, "amount": paid_by_subscription.get((sub.source, sub.external_id), 0),
            "currency": sub.currency, "email": client.email if client else None, "phone": client.phone_number if client else None,
        })
    return sorted(rows, key=lambda row: str(row["cancelled_at"]), reverse=True)


def _rejected_rows(db: Session, start: date | None, end: date | None, bucket: str) -> list[dict]:
    clients = _clients(db)
    rows = []
    for charge in db.scalars(select(Charge).where(Charge.source.in_(_SOURCES))).all():
        if str(charge.status or "").lower() not in _REJECTED or not _in_range(charge.charge_date, start, end):
            continue
        code, reason = _reason(charge)
        is_card = needs_card_change(code, reason)
        if (bucket == "card") != is_card:
            continue
        client = clients.get((charge.source, charge.client_external_id or ""))
        rows.append({
            "source": charge.source, "external_id": charge.external_id, "subscription_id": charge.subscription_external_id,
            "client_name": _name(client), "charge_date": charge.charge_date, "amount": charge.amount,
            "currency": charge.currency, "rejection_code": code, "rejection_reason": reason,
            "card_expiration": _card_expiration(client),
        })
    return sorted(rows, key=lambda row: str(row["charge_date"]), reverse=True)


@router.get("/cancelled", dependencies=[Depends(require_permissions("virtualpos.recovery.view"))], tags=["Recovery"])
def cancelled_subscriptions(db: Annotated[Session, Depends(get_db)], date_from: str | None = None, date_to: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)) -> dict:
    return _page(_cancelled_rows(db, _date(date_from, "date_from"), _date(date_to, "date_to")), offset, limit)


def _group_rows(db: Session, group: str, start: date | None, end: date | None) -> list[dict]:
    """Return subscriptions filtered by secondary_status group with last_paid enrichment."""
    subscriptions = db.scalars(select(Subscription).where(Subscription.source.in_(_SOURCES))).all()

    # Build client lookups: primary by external_id, fallback by social_id (RUT).
    # VirtualPOS subscriptions have client_external_id=NULL but client_social_id (RUT) populated,
    # so the RUT-based fallback is required to resolve names and emails.
    all_clients = db.scalars(select(Client).where(Client.source.in_(_SOURCES))).all()
    clients_by_id: dict[tuple[str, str], Client] = {(c.source, c.external_id): c for c in all_clients}
    clients_by_rut: dict[tuple[str, str], Client] = {}
    for c in all_clients:
        if c.social_id:
            key = (c.source, c.social_id)
            if key not in clients_by_rut:
                clients_by_rut[key] = c

    # Build last_paid_date, ever_paid, and has_charges per (source, subscription_external_id)
    # using Charge directly — it has subscription_external_id as a first-class field,
    # which avoids the fragile Payment→charge_external_id→Charge→subscription chain.
    charges = db.scalars(select(Charge).where(Charge.source.in_(_SOURCES))).all()
    last_paid_map: dict[tuple[str, str], str] = {}
    ever_paid: set[tuple[str, str]] = set()    # at least one accepted charge
    has_charges: set[tuple[str, str]] = set()  # at least one charge attempt of any status

    for charge in charges:
        if not charge.subscription_external_id:
            continue
        key = (charge.source, charge.subscription_external_id)
        has_charges.add(key)
        if str(charge.status or "").strip().lower() in PAID_STATUSES:
            ever_paid.add(key)
            cdate = str(charge.charge_date or "")
            if not last_paid_map.get(key) or cdate > last_paid_map[key]:
                last_paid_map[key] = cdate

    # First pass: collect candidates matching the group and date filter
    candidates: list[Subscription] = []
    for sub in subscriptions:
        last_paid = last_paid_map.get((sub.source, sub.external_id))
        ss = _secondary_status(sub.status or "", last_paid)

        if ss != group:
            continue

        if group == "inactiva":
            # Exclude subs fallidas: never had any charge attempt registered
            if (sub.source, sub.external_id) not in has_charges:
                continue
            if not _in_range(sub.canceled_at, start, end):
                continue
        else:
            # For incobrable / nunca_cobrado, date filter on suscription_date is optional
            if (start or end) and not _in_range(sub.suscription_date, start, end):
                continue

        candidates.append(sub)

    # For incobrable / nunca_cobrado: deduplicate to one row per client.
    # Key priority: client_external_id > client_social_id (RUT) > subscription external_id.
    # VirtualPOS has client_external_id=NULL, so RUT is the effective dedup key.
    if group != "inactiva":
        candidates.sort(key=lambda s: str(s.suscription_date or ""), reverse=True)
        seen_clients: set[tuple[str, str]] = set()
        deduped: list[Subscription] = []
        for sub in candidates:
            client_key = (sub.source, sub.client_external_id or sub.client_social_id or sub.external_id)
            if client_key not in seen_clients:
                seen_clients.add(client_key)
                deduped.append(sub)
        candidates = deduped

    rows = []
    for sub in candidates:
        last_paid = last_paid_map.get((sub.source, sub.external_id))
        # Dual client lookup: external_id first, then RUT fallback
        client: Client | None = clients_by_id.get((sub.source, sub.client_external_id or "")) if sub.client_external_id else None
        if client is None and sub.client_social_id:
            client = clients_by_rut.get((sub.source, sub.client_social_id))
        antiquity_days = None
        try:
            ref_end = date.fromisoformat(str(sub.canceled_at)[:10]) if group == "inactiva" else date.today()
            antiquity_days = (ref_end - date.fromisoformat(str(sub.suscription_date)[:10])).days
        except (TypeError, ValueError):
            pass

        rows.append({
            "source": sub.source,
            "subscription_id": sub.external_id,
            "external_id": sub.external_id,
            "secondary_status": group,
            "rut": client.social_id if client else sub.client_social_id,
            "client_name": _name(client),
            "started_at": sub.suscription_date,
            "cancelled_at": sub.canceled_at,
            "last_paid_date": last_paid,
            "antiquity_days": antiquity_days,
            "amount": sub.amount,
            "currency": sub.currency,
            "email": client.email if client else None,
            "phone": client.phone_number if client else None,
        })

    sort_key = "cancelled_at" if group == "inactiva" else "started_at"
    return sorted(rows, key=lambda r: str(r.get(sort_key) or ""), reverse=True)


@router.get("/group", dependencies=[Depends(require_permissions("virtualpos.recovery.view"))], tags=["Recovery"])
def group_subscriptions(
    db: Annotated[Session, Depends(get_db)],
    group: Literal["inactiva", "incobrable", "nunca_cobrado"] = "inactiva",
    date_from: str | None = None,
    date_to: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    return _page(_group_rows(db, group, _date(date_from, "date_from"), _date(date_to, "date_to")), offset, limit)


@router.get("/group/export", dependencies=[Depends(require_permissions("virtualpos.recovery.export"))], tags=["Recovery"])
def export_group_subscriptions(
    db: Annotated[Session, Depends(get_db)],
    group: Literal["inactiva", "incobrable", "nunca_cobrado"] = "inactiva",
    date_from: str | None = None,
    date_to: str | None = None,
) -> Response:
    group_labels = {"inactiva": "Fecha cancelación", "incobrable": "Último cobro", "nunca_cobrado": "Fecha inicio"}
    date_col = group_labels.get(group, "Fecha")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["ID_SUB", "RUT", "Nombre completo", "Fecha inicio", date_col, "Estado secundario", "Último cobro", "Antigüedad (días)", "Monto mensual", "Email", "Teléfono"])
    for row in _group_rows(db, group, _date(date_from, "date_from"), _date(date_to, "date_to")):
        date_val = row["cancelled_at"] if group == "inactiva" else row["last_paid_date"] if group == "incobrable" else row["started_at"]
        writer.writerow([
            row["subscription_id"], row["rut"], row["client_name"], row["started_at"],
            date_val, row["secondary_status"], row["last_paid_date"], row["antiquity_days"],
            row["amount"], row["email"], row["phone"],
        ])
    filename = f"socios-{group}.csv"
    return Response(output.getvalue().encode("utf-8-sig"), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})


@router.get("/cancelled/export", dependencies=[Depends(require_permissions("virtualpos.recovery.export"))], tags=["Recovery"])
def export_cancelled_subscriptions(db: Annotated[Session, Depends(get_db)], date_from: str | None = None, date_to: str | None = None) -> Response:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["ID_SUB", "RUT", "Nombre completo", "Fecha de inicio", "Fecha de cancelacion", "Antiguedad (dias)", "Monto total recaudado", "Email", "Telefono"])
    for row in _cancelled_rows(db, _date(date_from, "date_from"), _date(date_to, "date_to")):
        writer.writerow([row["subscription_id"], row["rut"], row["client_name"], row["started_at"], row["cancelled_at"], row["antiquity_days"], row["amount"], row["email"], row["phone"]])
    return Response(output.getvalue().encode("utf-8-sig"), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=socios-cancelados.csv"})


@router.get("/rejected", dependencies=[Depends(require_permissions("virtualpos.recovery.view"))], tags=["Recovery"])
def rejected_charges(db: Annotated[Session, Depends(get_db)], bucket: Literal["retry", "card"] = "retry", date_from: str | None = None, date_to: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)) -> dict:
    return _page(_rejected_rows(db, _date(date_from, "date_from"), _date(date_to, "date_to"), bucket), offset, limit)


@router.get("/card-expirations", dependencies=[Depends(require_permissions("virtualpos.recovery.view"))], tags=["Recovery"])
def expired_card_charges(db: Annotated[Session, Depends(get_db)], offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)) -> dict:
    return _page(_rejected_rows(db, None, None, "card"), offset, limit)


class RetryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["virtualpos1", "virtualpos2"]
    external_id: str = Field(min_length=1, max_length=255)


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[RetryItem] = Field(min_length=1, max_length=200)


@router.post("/retries", dependencies=[Depends(require_permissions("virtualpos.charges.retry")), Depends(require_csrf)], tags=["Recovery"])
async def request_retries(body: RetryRequest, db: Annotated[Session, Depends(get_db)]) -> dict:
    results = []
    for item in body.items:
        try:
            charge = await retry_charge(db, item.external_id, item.source)
            results.append({"source": item.source, "external_id": item.external_id, "success": True, "status": charge.status})
        except (ChargeNotFoundError, WriteDisabledError) as exc:
            results.append({"source": item.source, "external_id": item.external_id, "success": False, "error": type(exc).__name__})
        except HTTPStatusError as exc:
            results.append({"source": item.source, "external_id": item.external_id, "success": False, "error": f"HTTP {exc.response.status_code}"})
    return {"results": results, "succeeded": sum(result["success"] for result in results)}


@router.post("/card-change-links/{subscription_id}", dependencies=[Depends(require_permissions("virtualpos.cards.change")), Depends(require_csrf)], tags=["Recovery"])
async def create_card_change_link(subscription_id: str, db: Annotated[Session, Depends(get_db)], source: Literal["virtualpos1", "virtualpos2"] = "virtualpos1") -> dict:
    if not settings.virtualpos_writes_enabled:
        raise HTTPException(status_code=403, detail="VirtualPOS writes are disabled")
    subscription = db.scalar(select(Subscription).where(Subscription.source == source, Subscription.external_id == subscription_id))
    if subscription is None:
        raise HTTPException(status_code=404, detail="Suscripción no encontrada")
    run = WriteRun(source=source, resource_type="subscription", external_id=subscription_id, operation="create_card_change_link", status="pending", request_payload={"subscription_id": subscription_id})
    db.add(run)
    db.commit()
    try:
        async with VirtualPOSClient(platform=source) as provider:
            response = await provider.create_card_change_link(subscription_id)
    except Exception as exc:
        run.status = "failed"
        run.error_message = safe_error_message(exc, (settings.virtualpos_api_key, settings.virtualpos_secret_key, settings.virtualpos2_api_key, settings.virtualpos2_secret_key))
        run.finished_at = datetime.now().astimezone()
        db.commit()
        raise
    url = response.get("url") or response.get("link") or response.get("card_change_url") if isinstance(response, dict) else None
    expires_at = response.get("expires_at") or response.get("expiration") if isinstance(response, dict) else None
    run.status = "completed"
    run.response_payload = {"expires_at": expires_at, "link_generated": bool(url)}
    run.finished_at = datetime.now().astimezone()
    db.commit()
    return {"url": url, "expires_at": expires_at}
