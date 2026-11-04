"""Recuperador general, pestaña Toku (REC-04). Solo lectura sobre `core_*` y `core_subscription_signals`.

Vistas
------
* **cancelled** (suscripciones dadas de baja): `core_subscriptions` de Toku con fecha de baja (`ended_at`, que el ETL
  toma de la API o de la `Fecha de Eliminación` del reporte) o con estado de baja (`deleted_at_source` de los stubs y
  del reporte, o `CANCELED`/`DELETED` de la API). El filtro de fechas es sobre `ended_at`.
* **rejected** (cobros rechazados): `core_charges` de Toku con un rechazo proyectado (`latest_rejection_*`, RJ-01) que
  no quedaron pagados. El filtro de fechas es sobre `latest_rejection_at`.
* **recoverable** (recuperables): `core_subscription_signals.is_recoverable` (TK-20; definición en DEC-25: racha de 3 o
  más cuotas impagas en firme, tarjeta bloqueada o vencida). Las señales dependen de la bandera
  `TOKU_REPORT_SIGNALS_ENABLED` (apagada por defecto): con ella apagada la vista devuelve un estado vacío explícito
  (`empty_reason="signals_disabled"`) en vez de señales posiblemente viejas; encendida y sin señales calculadas,
  `empty_reason="no_signals"`.

Datos personales (d119, opción b): `rut` y `name` solo con el permiso de clientes de Toku (`recovery_pii`); sin él van en
`null`. El resto: IDs externos, montos, fechas, estados y códigos. Paginación y filtros en SQL.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models.core import CoreCharge, CoreSubscription
from app.models.toku_report import CoreSubscriptionSignal
from app.services.charge_stats import PAID_STATES
from app.services.recovery_pii import attach_people
from app.services.rejection_format import format_rejection_reason
from app.services.toku_report_signals import signals_enabled

SOURCE = "toku"
CANCELLED_STATUSES = ("deleted_at_source", "canceled", "cancelled", "deleted")
RECOVERABLE_REASONS = ("blocked_card", "expired_card", "streak")


def _iso(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()


def _num(value: Any) -> float | None:
    return float(value) if value is not None else None


def _date_range(column, start: date | None, end: date | None) -> list:
    conditions = []
    if start is not None:
        conditions.append(cast(column, Date) >= start)
    if end is not None:
        conditions.append(cast(column, Date) <= end)
    return conditions


def _page(db: Session, query, offset: int, limit: int) -> tuple[list[Any], int]:
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    return db.execute(query.offset(offset).limit(limit)).all(), total


def _result(items: list[dict], total: int, offset: int, limit: int, empty_reason: str | None = None) -> dict:
    return {"items": items, "total": total, "offset": offset, "limit": limit, "empty_reason": empty_reason}


def cancelled(db: Session, start: date | None, end: date | None, offset: int, limit: int, *, include_pii: bool = False) -> dict:
    query = (
        select(CoreSubscription, CoreSubscriptionSignal.payment_method_status)
        .outerjoin(CoreSubscriptionSignal, CoreSubscriptionSignal.subscription_id == CoreSubscription.id)
        .where(
            CoreSubscription.source == SOURCE,
            or_(CoreSubscription.ended_at.is_not(None), func.lower(CoreSubscription.status).in_(CANCELLED_STATUSES)),
            *_date_range(CoreSubscription.ended_at, start, end),
        )
        .order_by(CoreSubscription.ended_at.desc().nulls_last(), CoreSubscription.external_id)
    )
    rows, total = _page(db, query, offset, limit)
    items = []
    for sub, pm_status in rows:
        antiquity = (sub.ended_at - sub.started_at).days if sub.ended_at and sub.started_at else None
        items.append({
            "source": SOURCE,
            "subscription_id": sub.external_id,
            "status": sub.status,
            "started_at": _iso(sub.started_at),
            "cancelled_at": _iso(sub.ended_at),
            "antiquity_days": antiquity,
            "amount": _num(sub.amount),
            "currency": sub.currency,
            "last_payment_status": sub.last_payment_status,
            "payment_method_status": pm_status,
        })
    return attach_people(db, SOURCE, _result(items, total, offset, limit), include_pii)


def rejected(db: Session, start: date | None, end: date | None, offset: int, limit: int, *, include_pii: bool = False) -> dict:
    query = (
        select(CoreCharge, CoreSubscription.external_id)
        .outerjoin(CoreSubscription, CoreSubscription.id == CoreCharge.subscription_id)
        .where(
            CoreCharge.source == SOURCE,
            or_(CoreCharge.latest_rejection_code.is_not(None), CoreCharge.latest_rejection_at.is_not(None)),
            or_(CoreCharge.source_status.is_(None), func.lower(CoreCharge.source_status).not_in(PAID_STATES)),
            *_date_range(CoreCharge.latest_rejection_at, start, end),
        )
        .order_by(CoreCharge.latest_rejection_at.desc().nulls_last(), CoreCharge.external_id)
    )
    rows, total = _page(db, query, offset, limit)
    items = [
        {
            "source": SOURCE,
            "charge_id": charge.external_id,
            "subscription_id": sub_external_id,
            "due_at": _iso(charge.due_at),
            "period": charge.period_reference,
            "amount": _num(charge.amount),
            "currency": charge.currency,
            "status": charge.source_status,
            "rejection_code": charge.latest_rejection_code,
            "rejection_reason": format_rejection_reason(SOURCE, charge.latest_rejection_code, charge.latest_rejection_reason),
            "rejection_at": _iso(charge.latest_rejection_at),
        }
        for charge, sub_external_id in rows
    ]
    return attach_people(db, SOURCE, _result(items, total, offset, limit), include_pii)


def recoverable(db: Session, reason: str | None, offset: int, limit: int, *, include_pii: bool = False) -> dict:
    if not signals_enabled():
        return attach_people(db, SOURCE, _result([], 0, offset, limit, "signals_disabled"), include_pii)
    query = (
        select(CoreSubscriptionSignal, CoreSubscription.amount, CoreSubscription.currency)
        .join(CoreSubscription, CoreSubscription.id == CoreSubscriptionSignal.subscription_id)
        .where(CoreSubscriptionSignal.source == SOURCE, CoreSubscriptionSignal.is_recoverable.is_(True))
        .order_by(CoreSubscriptionSignal.consecutive_failed_debts.desc(), CoreSubscriptionSignal.external_id)
    )
    if reason:
        query = query.where(CoreSubscriptionSignal.recoverable_reason == reason)
    rows, total = _page(db, query, offset, limit)
    empty_reason = None
    if total == 0 and not db.scalar(select(func.count()).select_from(CoreSubscriptionSignal).where(CoreSubscriptionSignal.source == SOURCE)):
        empty_reason = "no_signals"
    items = [
        {
            "source": SOURCE,
            "subscription_id": signal.external_id,
            "recoverable_reason": signal.recoverable_reason,
            "consecutive_failed_debts": signal.consecutive_failed_debts,
            "payment_method_status": signal.payment_method_status,
            "last_response_code": signal.last_response_code,
            "last_response_severity": signal.last_response_severity,
            "last_attempt_at": _iso(signal.last_attempt_at),
            "report_generated_at": _iso(signal.report_generated_at),
            "amount": _num(amount),
            "currency": currency,
        }
        for signal, amount, currency in rows
    ]
    return attach_people(db, SOURCE, _result(items, total, offset, limit, empty_reason), include_pii)
