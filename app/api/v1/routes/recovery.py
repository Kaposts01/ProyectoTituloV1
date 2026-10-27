from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from httpx import HTTPStatusError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.config import settings
from app.core.security import require_csrf, require_permissions
from app.integrations.virtualpos.client import VirtualPOSAPIError, VirtualPOSClient
from app.models.auth import User
from app.models.charge_recovery import ChargeRecovery
from app.models.core import CoreCharge
from app.models.crm import Charge, Client, Payment, Subscription
from app.models.write_run import WriteRun
from app.services.charge_recovery import PAID_STATUSES, needs_card_change
from app.services.rbac import permission_codes
from app.services.read_only_provider_sync import safe_error_message
from app.services.vp_current_amount import load_monto_vigente
from app.services.vp_rejection_codes import format_rejection_reason
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
        if paid_date <= datetime.now(tz=timezone.utc).date() - timedelta(days=182):
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


@dataclass(frozen=True)
class RecoveryFilters:
    account: str | None = None
    rejection_code: str | None = None
    min_amount: float | None = None
    max_amount: float | None = None
    secondary_status: str | None = None
    rejected_from: date | None = None
    rejected_to: date | None = None

    def as_audit(self) -> dict[str, str | float]:
        return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in self.__dict__.items() if v is not None}


def recovery_filters(
    account: Literal["virtualpos1", "virtualpos2"] | None = None,
    rejection_code: str | None = Query(None, max_length=100),
    min_amount: float | None = Query(None, ge=0),
    max_amount: float | None = Query(None, ge=0),
    secondary_status: Literal["inactiva", "incobrable", "nunca_cobrado", "cobrable"] | None = None,
    rejected_from: str | None = None,
    rejected_to: str | None = None,
) -> RecoveryFilters:
    return RecoveryFilters(
        account, (rejection_code or "").strip() or None, min_amount, max_amount, secondary_status,
        _date(rejected_from, "rejected_from"), _date(rejected_to, "rejected_to"),
    )


Filters = Annotated[RecoveryFilters, Depends(recovery_filters)]


def _apply_filters(rows: list[dict], filters: RecoveryFilters | None) -> list[dict]:
    """Global row filter; always runs before sorting and pagination."""
    if filters is None:
        return rows
    out = []
    for row in rows:
        if filters.account and row.get("account") != filters.account:
            continue
        if filters.rejection_code and row.get("rejection_code") != filters.rejection_code:
            continue
        amount = row.get("monto")
        if filters.min_amount is not None and (amount is None or amount < filters.min_amount):
            continue
        if filters.max_amount is not None and (amount is None or amount > filters.max_amount):
            continue
        if filters.secondary_status and row.get("secondary_status") != filters.secondary_status:
            continue
        if (filters.rejected_from or filters.rejected_to) and not _in_range(row.get("rejection_at"), filters.rejected_from, filters.rejected_to):
            continue
        out.append(row)
    return out


def _num(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _reason(charge: Charge, core: CoreCharge | None = None) -> tuple[str | None, str | None]:
    """Rejection (code, raw reason): CoreCharge.latest_rejection_* first, raw_payload as fallback."""
    payload = charge.raw_payload or {}
    rejected = payload.get("rejected_object") if isinstance(payload.get("rejected_object"), dict) else {}
    raw_code = rejected.get("code") if rejected.get("code") is not None else rejected.get("error_code")
    raw_reason = rejected.get("message") or payload.get("razon_rechazo") or payload.get("reason") or payload.get("rejection_reason") or ""
    core_code = core.latest_rejection_code if core is not None else None
    core_reason = core.latest_rejection_reason if core is not None else None
    code = core_code or (str(raw_code) if raw_code is not None else None)
    return code, (core_reason or str(raw_reason) or None)


def _core_rejections(db: Session) -> dict[tuple[str, str], CoreCharge]:
    query = select(CoreCharge).where(
        CoreCharge.source.in_(_SOURCES),
        CoreCharge.latest_rejection_code.is_not(None) | CoreCharge.latest_rejection_reason.is_not(None) | CoreCharge.latest_rejection_at.is_not(None),
    )
    return {(c.source, c.external_id): c for c in db.scalars(query)}


def _charge_stats(charges: list[Charge]) -> dict[tuple[str, str], dict]:
    """Per subscription: attempts, last paid date/amount and last rejected charge."""
    stats: dict[tuple[str, str], dict] = {}
    for charge in charges:
        if not charge.subscription_external_id:
            continue
        item = stats.setdefault(
            (charge.source, charge.subscription_external_id),
            {"attempts": 0, "last_paid": None, "paid_amount": None, "last_rejected": None},
        )
        item["attempts"] += 1
        cdate = str(charge.charge_date or "")
        status = str(charge.status or "").strip().lower()
        if status in PAID_STATUSES and (item["last_paid"] is None or cdate > item["last_paid"]):
            item["last_paid"], item["paid_amount"] = cdate, _num(charge.amount)
        if status in _REJECTED and (item["last_rejected"] is None or cdate > str(item["last_rejected"].charge_date or "")):
            item["last_rejected"] = charge
    return stats


def _rejection_fields(charge: Charge | None, core: CoreCharge | None) -> dict:
    if charge is None:
        return {"rejection_code": None, "rejection_reason_raw": None, "rejection_reason": None, "rejection_at": None}
    code, raw = _reason(charge, core)
    at = core.latest_rejection_at.date().isoformat() if core is not None and core.latest_rejection_at else charge.charge_date
    return {"rejection_code": code, "rejection_reason_raw": raw, "rejection_reason": format_rejection_reason(code, raw), "rejection_at": at}


def _vigente(vigentes: dict[tuple[str, str], Decimal], source: str, sub_id: str | None, sub: Subscription | None) -> float | None:
    """Monto vigente (helper vp_current_amount): ultimo cargo pagado/procesando con fecha <= hoy, else monto de suscripcion/plan."""
    value = vigentes.get((source, sub_id or ""))
    if value is not None:
        return float(value)
    return _num(sub.amount) if sub is not None else None


def _clients(db: Session) -> dict[tuple[str, str], Client]:
    return {(row.source, row.external_id): row for row in db.scalars(select(Client).where(Client.source.in_(_SOURCES)))}


def _recovery_client(
    charge: Charge | None,
    subscription_external_id: str | None,
    clients: dict[tuple[str, str], Client],
    subscriptions: dict[tuple[str, str], Subscription],
    unique_clients_by_rut: dict[tuple[str, str], Client],
    source: str,
) -> Client | None:
    subscription_id = subscription_external_id or (charge.subscription_external_id if charge else None)
    subscription = subscriptions.get((source, subscription_id or ""))
    if subscription is not None:
        if subscription.client_external_id:
            return clients.get((source, subscription.client_external_id))
        if subscription.client_social_id:
            return unique_clients_by_rut.get((source, subscription.client_social_id))
    if charge is not None and charge.client_external_id:
        return clients.get((source, charge.client_external_id))
    return None


def _load_clients(db: Session, ext_ids_by_source: dict[str, list[str]], social_ids_by_source: dict[str, list[str]]) -> tuple[
    dict[tuple[str, str], Client],
    dict[tuple[str, str], Client],
]:
    """Load clients by external_id and unique-per-source clients by social_id."""
    clients: dict[tuple[str, str], Client] = {}
    for source, ext_ids in ext_ids_by_source.items():
        for c in db.scalars(select(Client).where(Client.source == source, Client.external_id.in_(ext_ids))):
            clients[(c.source, c.external_id)] = c
    unique_by_rut: dict[tuple[str, str], Client] = {}
    for source, social_ids in social_ids_by_source.items():
        groups: dict[tuple[str, str], list[Client]] = {}
        for c in db.scalars(select(Client).where(Client.source == source, Client.social_id.in_(social_ids))):
            groups.setdefault((c.source, c.social_id), []).append(c)
        unique_by_rut.update({k: v[0] for k, v in groups.items() if len(v) == 1})
    return clients, unique_by_rut


def _name(client: Client | None) -> str | None:
    if client is None:
        return None
    return " ".join(value for value in (client.first_name, client.last_name) if value) or None


def _subscription_client_name(subscription: Subscription | None) -> str | None:
    if subscription is None or not isinstance(subscription.raw_payload, dict):
        return None
    client = subscription.raw_payload.get("client")
    if not isinstance(client, dict):
        return None
    return " ".join(str(value) for value in (client.get("first_name"), client.get("last_name")) if value) or None


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


def _cancelled_rows(db: Session, start: date | None, end: date | None, filters: RecoveryFilters | None = None) -> list[dict]:
    subscriptions = [
        sub for sub in db.scalars(select(Subscription).where(Subscription.source.in_(_SOURCES)))
        if _in_range(sub.canceled_at, start, end)
    ]
    clients = _clients(db)
    charges = db.scalars(select(Charge).where(Charge.source.in_(_SOURCES))).all()
    charge_subscriptions = {(charge.source, charge.external_id): charge.subscription_external_id for charge in charges}
    stats = _charge_stats(list(charges))
    vigentes = load_monto_vigente(db, family="crm", sources=_SOURCES)
    core = _core_rejections(db)
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
        stat = stats.get((sub.source, sub.external_id))
        last_rej = stat["last_rejected"] if stat else None
        rows.append({
            "source": sub.source, "account": sub.source, "subscription_id": sub.external_id, "external_id": sub.external_id,
            "charge_id": None, "source_record_id": str(sub.source_record_id) if sub.source_record_id else None,
            "rut": client.social_id if client else sub.client_social_id,
            "client_name": _name(client) or _subscription_client_name(sub), "started_at": sub.suscription_date, "cancelled_at": sub.canceled_at,
            "antiquity_days": days, "amount": paid_by_subscription.get((sub.source, sub.external_id), 0),
            "monto": _num(sub.amount), "monto_vigente": _vigente(vigentes, sub.source, sub.external_id, sub),
            "estado": "inactiva", "secondary_status": "inactiva",
            "attempts": stat["attempts"] if stat else 0, "last_paid_date": stat["last_paid"] if stat else None,
            **_rejection_fields(last_rej, core.get((last_rej.source, last_rej.external_id)) if last_rej else None),
            "currency": sub.currency, "email": client.email if client else None, "phone": client.phone_number if client else None,
        })
    rows = _apply_filters(rows, filters)
    return sorted(rows, key=lambda row: str(row["cancelled_at"]), reverse=True)


def _rejected_rows(db: Session, start: date | None, end: date | None, bucket: str, filters: RecoveryFilters | None = None) -> list[dict]:
    # Filter by status and date in SQL; bucket (is_card) stays in Python (depends on raw_payload)
    charge_q = select(Charge).where(Charge.source.in_(_SOURCES), func.lower(Charge.status).in_(_REJECTED))
    if start is not None:
        charge_q = charge_q.where(Charge.charge_date >= str(start))
    if end is not None:
        charge_q = charge_q.where(Charge.charge_date <= str(end))
    filtered_charges = db.scalars(charge_q).all()
    if not filtered_charges:
        return []

    # Load only subscriptions referenced by these charges
    sub_ids_by_source: dict[str, list[str]] = {}
    for c in filtered_charges:
        if c.subscription_external_id:
            sub_ids_by_source.setdefault(c.source, []).append(c.subscription_external_id)
    subscriptions: dict[tuple[str, str], Subscription] = {}
    for source, ext_ids in sub_ids_by_source.items():
        for sub in db.scalars(select(Subscription).where(Subscription.source == source, Subscription.external_id.in_(ext_ids))):
            subscriptions[(sub.source, sub.external_id)] = sub

    # Collect which client IDs we actually need
    client_ext: dict[str, list[str]] = {}
    client_rut: dict[str, list[str]] = {}
    for c in filtered_charges:
        sub = subscriptions.get((c.source, c.subscription_external_id or ""))
        if sub and sub.client_external_id:
            client_ext.setdefault(c.source, []).append(sub.client_external_id)
        elif sub and sub.client_social_id:
            client_rut.setdefault(c.source, []).append(sub.client_social_id)
        elif c.client_external_id:
            client_ext.setdefault(c.source, []).append(c.client_external_id)
    clients, unique_clients_by_rut = _load_clients(db, client_ext, client_rut)

    # Attempts / last paid / monto vigente per subscription (all charges of the referenced subscriptions)
    all_sub_charges: list[Charge] = []
    for source, ext_ids in sub_ids_by_source.items():
        all_sub_charges.extend(db.scalars(select(Charge).where(Charge.source == source, Charge.subscription_external_id.in_(set(ext_ids)))))
    stats = _charge_stats(all_sub_charges)
    vigentes = load_monto_vigente(db, family="crm", sources=_SOURCES)
    core = _core_rejections(db)

    rows = []
    for charge in filtered_charges:
        core_charge = core.get((charge.source, charge.external_id))
        code, reason = _reason(charge, core_charge)
        is_card = needs_card_change(code, reason)
        if (bucket == "card") != is_card:
            continue
        subscription = subscriptions.get((charge.source, charge.subscription_external_id or ""))
        client = _recovery_client(charge, charge.subscription_external_id, clients, subscriptions, unique_clients_by_rut, charge.source)
        stat = stats.get((charge.source, charge.subscription_external_id or ""))
        rejection = _rejection_fields(charge, core_charge)
        rows.append({
            "source": charge.source, "account": charge.source, "external_id": charge.external_id, "charge_id": charge.external_id,
            "subscription_id": charge.subscription_external_id, "source_record_id": str(charge.source_record_id) if charge.source_record_id else None,
            "rut": client.social_id if client else (subscription.client_social_id if subscription else None),
            "email": client.email if client else None, "phone": client.phone_number if client else None,
            "client_name": _name(client) or _subscription_client_name(subscription), "charge_date": charge.charge_date, "amount": charge.amount,
            "monto": _num(charge.amount), "monto_vigente": _vigente(vigentes, charge.source, charge.subscription_external_id, subscription),
            "currency": charge.currency, **rejection,
            "estado": charge.status,
            "secondary_status": _secondary_status(subscription.status or "", stat["last_paid"] if stat else None) if subscription else None,
            "attempts": stat["attempts"] if stat else 1, "last_paid_date": stat["last_paid"] if stat else None,
            "cancelled_at": subscription.canceled_at if subscription else None,
            "card_expiration": _card_expiration(client),
        })
    rows = _apply_filters(rows, filters)
    return sorted(rows, key=lambda row: str(row["charge_date"]), reverse=True)


def _retry_history_rows(db: Session, start: date | None, end: date | None) -> list[dict]:
    # Apply date filter on WriteRun in SQL using func.date() to extract date from timestamptz
    wr_q = select(WriteRun).where(
        WriteRun.source.in_(_SOURCES),
        WriteRun.resource_type == "charge",
        WriteRun.operation == "retry_charge",
    )
    if start is not None:
        wr_q = wr_q.where(func.date(WriteRun.started_at) >= start)
    if end is not None:
        wr_q = wr_q.where(func.date(WriteRun.started_at) <= end)
    write_runs = db.scalars(wr_q).all()
    if not write_runs:
        return []

    # Load only ChargeRecovery records for these write_run IDs
    write_run_ids = [wr.id for wr in write_runs]
    recoveries = {
        recovery.write_run_id: recovery
        for recovery in db.scalars(select(ChargeRecovery).where(ChargeRecovery.write_run_id.in_(write_run_ids)))
    }

    # Load only charges referenced by these write_runs
    charge_ids_by_source: dict[str, list[str]] = {}
    for wr in write_runs:
        if wr.external_id:
            charge_ids_by_source.setdefault(wr.source, []).append(wr.external_id)
    charges: dict[tuple[str, str], Charge] = {}
    for source, ext_ids in charge_ids_by_source.items():
        for charge in db.scalars(select(Charge).where(Charge.source == source, Charge.external_id.in_(ext_ids))):
            charges[(charge.source, charge.external_id)] = charge

    # Load only subscriptions referenced
    sub_ids_by_source: dict[str, set[str]] = {}
    for wr in write_runs:
        recovery = recoveries.get(wr.id)
        charge = charges.get((wr.source, wr.external_id))
        sub_id = (recovery.subscription_external_id if recovery else None) or (charge.subscription_external_id if charge else None)
        if sub_id:
            sub_ids_by_source.setdefault(wr.source, set()).add(sub_id)
    subscriptions: dict[tuple[str, str], Subscription] = {}
    for source, ext_ids in sub_ids_by_source.items():
        for sub in db.scalars(select(Subscription).where(Subscription.source == source, Subscription.external_id.in_(ext_ids))):
            subscriptions[(sub.source, sub.external_id)] = sub

    # Collect client IDs needed
    client_ext: dict[str, list[str]] = {}
    client_rut: dict[str, list[str]] = {}
    for wr in write_runs:
        recovery = recoveries.get(wr.id)
        charge = charges.get((wr.source, wr.external_id))
        sub_id = (recovery.subscription_external_id if recovery else None) or (charge.subscription_external_id if charge else None)
        sub = subscriptions.get((wr.source, sub_id or ""))
        if sub and sub.client_external_id:
            client_ext.setdefault(wr.source, []).append(sub.client_external_id)
        elif sub and sub.client_social_id:
            client_rut.setdefault(wr.source, []).append(sub.client_social_id)
        elif charge and charge.client_external_id:
            client_ext.setdefault(wr.source, []).append(charge.client_external_id)
    clients, unique_clients_by_rut = _load_clients(db, client_ext, client_rut)

    rows = []
    for write_run in write_runs:
        recovery = recoveries.get(write_run.id)
        charge = charges.get((write_run.source, write_run.external_id))
        subscription_id = (recovery.subscription_external_id if recovery else None) or (charge.subscription_external_id if charge else None)
        subscription = subscriptions.get((write_run.source, subscription_id or ""))
        client = _recovery_client(charge, subscription_id, clients, subscriptions, unique_clients_by_rut, write_run.source)
        if recovery is not None:
            result = recovery.status
            observed_status = recovery.observed_charge_status
            observed_at = recovery.observed_at
        elif write_run.status == "failed":
            result = "rechazado_inmediato"
            observed_status = None
            observed_at = write_run.finished_at
        else:
            result = "pendiente_de_conciliacion"
            observed_status = None
            observed_at = None
        rows.append({
            "source": write_run.source,
            "external_id": write_run.external_id,
            "subscription_id": subscription_id,
            "client_name": _name(client) or _subscription_client_name(subscription),
            "charge_date": charge.charge_date if charge else None,
            "amount": charge.amount if charge else None,
            "currency": charge.currency if charge else None,
            "requested_at": write_run.started_at.isoformat() if write_run.started_at else None,
            "result": result,
            "observed_charge_status": observed_status,
            "observed_at": observed_at.isoformat() if observed_at else None,
        })
    return sorted(rows, key=lambda row: str(row["requested_at"]), reverse=True)


@router.get("/cancelled", dependencies=[Depends(require_permissions("virtualpos.recovery.view"))], tags=["Recovery"])
def cancelled_subscriptions(db: Annotated[Session, Depends(get_db)], filters: Filters, date_from: str | None = None, date_to: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)) -> dict:
    return _page(_cancelled_rows(db, _date(date_from, "date_from"), _date(date_to, "date_to"), filters), offset, limit)


def _group_rows(db: Session, group: str, start: date | None, end: date | None, filters: RecoveryFilters | None = None) -> list[dict]:
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

    stats = _charge_stats(list(charges))
    vigentes = load_monto_vigente(db, family="crm", sources=_SOURCES)
    core = _core_rejections(db)
    rows = []
    for sub in candidates:
        last_paid = last_paid_map.get((sub.source, sub.external_id))
        stat = stats.get((sub.source, sub.external_id))
        last_rej = stat["last_rejected"] if stat else None
        # Dual client lookup: external_id first, then RUT fallback
        client: Client | None = clients_by_id.get((sub.source, sub.client_external_id or "")) if sub.client_external_id else None
        if client is None and sub.client_social_id:
            client = clients_by_rut.get((sub.source, sub.client_social_id))
        antiquity_days = None
        try:
            ref_end = date.fromisoformat(str(sub.canceled_at)[:10]) if group == "inactiva" else datetime.now(tz=timezone.utc).date()
            antiquity_days = (ref_end - date.fromisoformat(str(sub.suscription_date)[:10])).days
        except (TypeError, ValueError):
            pass

        rows.append({
            "source": sub.source,
            "account": sub.source,
            "subscription_id": sub.external_id,
            "external_id": sub.external_id,
            "charge_id": None,
            "source_record_id": str(sub.source_record_id) if sub.source_record_id else None,
            "secondary_status": group,
            "estado": group,
            "monto": _num(sub.amount),
            "monto_vigente": _vigente(vigentes, sub.source, sub.external_id, sub),
            "attempts": stat["attempts"] if stat else 0,
            **_rejection_fields(last_rej, core.get((last_rej.source, last_rej.external_id)) if last_rej else None),
            "rut": client.social_id if client else sub.client_social_id,
            "client_name": _name(client) or _subscription_client_name(sub),
            "started_at": sub.suscription_date,
            "cancelled_at": sub.canceled_at,
            "last_paid_date": last_paid,
            "antiquity_days": antiquity_days,
            "amount": sub.amount,
            "currency": sub.currency,
            "email": client.email if client else None,
            "phone": client.phone_number if client else None,
        })

    rows = _apply_filters(rows, filters)
    sort_key = "cancelled_at" if group == "inactiva" else "started_at"
    return sorted(rows, key=lambda r: str(r.get(sort_key) or ""), reverse=True)


@router.get("/group", dependencies=[Depends(require_permissions("virtualpos.recovery.view"))], tags=["Recovery"])
def group_subscriptions(
    db: Annotated[Session, Depends(get_db)],
    filters: Filters,
    group: Literal["inactiva", "incobrable", "nunca_cobrado"] = "inactiva",
    date_from: str | None = None,
    date_to: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    return _page(_group_rows(db, group, _date(date_from, "date_from"), _date(date_to, "date_to"), filters), offset, limit)


CSV_COLUMNS = (
    "cuenta", "id_suscripcion", "id_cargo", "monto", "fecha_rechazo", "codigo_rechazo", "motivo_rechazo", "estado",
    "intentos", "ultimo_cobro", "fecha_cancelacion", "source_record_id", "external_id", "rut", "nombre", "email", "telefono",
)
PII_COLUMNS = ("rut", "nombre", "email", "telefono")
_CSV_ROW_KEYS = {
    "cuenta": "account", "id_suscripcion": "subscription_id", "id_cargo": "charge_id", "monto": "monto",
    "fecha_rechazo": "rejection_at", "codigo_rechazo": "rejection_code", "motivo_rechazo": "rejection_reason",
    "estado": "estado", "intentos": "attempts", "ultimo_cobro": "last_paid_date", "fecha_cancelacion": "cancelled_at",
    "source_record_id": "source_record_id", "external_id": "external_id", "rut": "rut", "nombre": "client_name",
    "email": "email", "telefono": "phone",
}


def _csv_safe(value: Any) -> Any:
    """Neutralize CSV formula injection in text cells (leading = + - @, tab or CR)."""
    if isinstance(value, str) and value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _csv_response(rows: list[dict], filename: str, include_pii: bool) -> Response:
    columns = [c for c in CSV_COLUMNS if include_pii or c not in PII_COLUMNS]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_csv_safe(row.get(_CSV_ROW_KEYS[c])) for c in columns])
    return Response(output.getvalue().encode("utf-8-sig"), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}"})


def _audit_export(db: Session, user: User, endpoint: str, filters: dict, row_count: int, include_pii: bool) -> None:
    """Export audit trail in write_runs: who, when (started_at), endpoint, filters and row count. No content, no PII."""
    now = datetime.now().astimezone()
    db.add(WriteRun(
        source="virtualpos", resource_type="recovery_export", external_id=endpoint, operation="export_csv", status="completed",
        request_payload={"user_id": str(user.id), "username": user.username, "endpoint": endpoint, "filters": filters, "rows": row_count, "pii_included": include_pii},
        finished_at=now,
    ))
    db.commit()


def _export(db: Session, user: User, endpoint: str, rows: list[dict], filename: str, filters: dict) -> Response:
    include_pii = "virtualpos.recovery.export" in permission_codes(user)
    _audit_export(db, user, endpoint, filters, len(rows), include_pii)
    return _csv_response(rows, filename, include_pii)


ExportUser = Annotated[User, Depends(require_permissions("virtualpos.recovery.export"))]


@router.get("/group/export", tags=["Recovery"])
def export_group_subscriptions(
    db: Annotated[Session, Depends(get_db)],
    user: ExportUser,
    filters: Filters,
    group: Literal["inactiva", "incobrable", "nunca_cobrado"] = "inactiva",
    date_from: str | None = None,
    date_to: str | None = None,
) -> Response:
    rows = _group_rows(db, group, _date(date_from, "date_from"), _date(date_to, "date_to"), filters)
    audit = {"group": group, "date_from": date_from, "date_to": date_to, **filters.as_audit()}
    return _export(db, user, "recovery/group/export", rows, f"socios-{group}.csv", {k: v for k, v in audit.items() if v is not None})


@router.get("/cancelled/export", tags=["Recovery"])
def export_cancelled_subscriptions(db: Annotated[Session, Depends(get_db)], user: ExportUser, filters: Filters, date_from: str | None = None, date_to: str | None = None) -> Response:
    rows = _cancelled_rows(db, _date(date_from, "date_from"), _date(date_to, "date_to"), filters)
    audit = {"date_from": date_from, "date_to": date_to, **filters.as_audit()}
    return _export(db, user, "recovery/cancelled/export", rows, "socios-cancelados.csv", {k: v for k, v in audit.items() if v is not None})


@router.get("/rejected/export", tags=["Recovery"])
def export_rejected_charges(db: Annotated[Session, Depends(get_db)], user: ExportUser, filters: Filters, bucket: Literal["retry", "card"] = "retry", date_from: str | None = None, date_to: str | None = None) -> Response:
    rows = _rejected_rows(db, _date(date_from, "date_from"), _date(date_to, "date_to"), bucket, filters)
    audit = {"bucket": bucket, "date_from": date_from, "date_to": date_to, **filters.as_audit()}
    return _export(db, user, "recovery/rejected/export", rows, f"cargos-rechazados-{bucket}.csv", {k: v for k, v in audit.items() if v is not None})


@router.get("/rejected", dependencies=[Depends(require_permissions("virtualpos.recovery.view"))], tags=["Recovery"])
def rejected_charges(db: Annotated[Session, Depends(get_db)], filters: Filters, bucket: Literal["retry", "card"] = "retry", date_from: str | None = None, date_to: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)) -> dict:
    return _page(_rejected_rows(db, _date(date_from, "date_from"), _date(date_to, "date_to"), bucket, filters), offset, limit)


@router.get("/retry-history", dependencies=[Depends(require_permissions("virtualpos.recovery.view"))], tags=["Recovery"])
def retry_history(db: Annotated[Session, Depends(get_db)], date_from: str | None = None, date_to: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)) -> dict:
    return _page(_retry_history_rows(db, _date(date_from, "date_from"), _date(date_to, "date_to")), offset, limit)


@router.get("/card-expirations", dependencies=[Depends(require_permissions("virtualpos.recovery.view"))], tags=["Recovery"])
def expired_card_charges(db: Annotated[Session, Depends(get_db)], filters: Filters, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)) -> dict:
    return _page(_rejected_rows(db, None, None, "card", filters), offset, limit)


class RetryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["virtualpos1", "virtualpos2"]
    external_id: str = Field(min_length=1, max_length=255)


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[RetryItem] = Field(min_length=1, max_length=200)


def _vp_error_label(exc: HTTPStatusError | VirtualPOSAPIError) -> str:
    if isinstance(exc, VirtualPOSAPIError):
        return f"VirtualPOS {exc.error_code}" if exc.error_code else "VirtualPOS NOK"
    return f"HTTP {exc.response.status_code}"


@router.post("/retries", dependencies=[Depends(require_permissions("virtualpos.charges.retry")), Depends(require_csrf)], tags=["Recovery"])
async def request_retries(body: RetryRequest, db: Annotated[Session, Depends(get_db)]) -> dict:
    results = []
    for item in body.items:
        try:
            charge = await retry_charge(db, item.external_id, item.source)
            results.append({"source": item.source, "external_id": item.external_id, "success": True, "status": charge.status})
        except (ChargeNotFoundError, WriteDisabledError) as exc:
            results.append({"source": item.source, "external_id": item.external_id, "success": False, "error": type(exc).__name__})
        except (HTTPStatusError, VirtualPOSAPIError) as exc:
            results.append({"source": item.source, "external_id": item.external_id, "success": False, "error": _vp_error_label(exc)})
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
    url = response.get("url") or response.get("link") or response.get("change_card_url") if isinstance(response, dict) else None
    expires_at = response.get("expires_at") or response.get("expiration") if isinstance(response, dict) else None
    run.status = "completed"
    run.response_payload = {"expires_at": expires_at, "link_generated": bool(url)}
    run.finished_at = datetime.now().astimezone()
    db.commit()
    return {"url": url, "expires_at": expires_at}
