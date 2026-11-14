"""Recuperador general, pestaña Payku (REC-05). SOLO LECTURA: no llama a Payku ni escribe nada.

Cobertura limitada: Payku no tiene sandbox (DEC-10), asi que el modelo de cargos (PK-06) y los estados solo se
validaron con fixtures sinteticas; la interfaz lo avisa. Los datos salen del modelo central (`core_*`, source=payku) y
del estado normalizado de las tablas de canal (`p_subscriptions.status_normalized`, `p_transactions.status_normalized`,
PK-PAR-07), nunca del estado crudo.

Vistas
------
* **cancelled** (dadas de baja): suscripciones con estado comun `cancelled` (`cancel`, `delete`, `finish`). Filtro de
  fechas sobre `ended_at` (fecha de termino del ETL: logs de estado o `end_date`).
* **suspended** (suspendidas): estado comun `suspended` (Payku agoto los reintentos, p. ej. `maximum attempt limit`).
  Filtro sobre `ended_at`. Es el universo a contactar; «recuperable» como en Toku aun no esta definido para Payku.
* **rejected** (cobros rechazados): `core_payments` de Payku cuya transaccion tiene estado comun `rejected`; si el
  pago esta enlazado a un ciclo (`core_charges`, PK-06) se muestra su periodo. Filtro sobre `occurred_at`.
  CRM-15C: Payku entrega los rechazos con `amount = 0` en el payload de la suscripcion y sin `paid[]` (sin ciclos), asi
  que la vista mostraba $0 y periodo «—». Ahora: periodo = el del ciclo enlazado o, si no hay, el mes (Chile) del
  intento (`period_source`); monto = el del intento si es > 0 o, si no, el monto vigente de la suscripcion
  (`amount_source`: `transaction` | `subscription`). El monto real del intento solo lo trae `GET /api/transaction/{id}`.

Datos personales (d119, opcion b): `rut` y `name` solo con el permiso de clientes de Payku (`recovery_pii`); sin el
van en `null`. El resto: ids de Payku, montos y estados. Paginacion y filtros en SQL.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.models.core import CoreCharge, CorePayment, CoreSubscription
from app.models.payku_channel import PaykuSubscription, PaykuTransaction
from app.services.recovery_pii import attach_people
from app.services.rejected_month import CHILE_TZ
from app.services.rejection_format import format_rejection_reason

SOURCE = "payku"


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


def _attempt_amount(payment_amount: Any, subscription_amount: Any) -> tuple[float | None, str | None]:
    """(monto, fuente): el del intento si es > 0; si no, el monto vigente de la suscripcion; si no, (None, None)."""
    if payment_amount is not None and float(payment_amount) > 0:
        return float(payment_amount), "transaction"
    if subscription_amount is not None and float(subscription_amount) > 0:
        return float(subscription_amount), "subscription"
    return None, None


def _attempt_period(charge_period: str | None, occurred_at: datetime | None) -> tuple[str | None, str | None]:
    """(periodo `AAAA-MM`, fuente): el del ciclo enlazado; si no, el mes en Chile del intento."""
    if charge_period:
        return charge_period, "cycle"
    if occurred_at is not None:
        local = occurred_at.astimezone(CHILE_TZ) if occurred_at.tzinfo else occurred_at
        return local.strftime("%Y-%m"), "attempt"
    return None, None


def _page(db: Session, query, offset: int, limit: int) -> tuple[list[Any], int]:
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    return db.execute(query.offset(offset).limit(limit)).all(), total


def _subscriptions(db: Session, common_status: str, start: date | None, end: date | None, offset: int, limit: int,
                   include_pii: bool) -> dict:
    query = (
        select(CoreSubscription, PaykuSubscription.status_normalized)
        .join(PaykuSubscription, PaykuSubscription.external_id == CoreSubscription.external_id)
        .where(
            CoreSubscription.source == SOURCE,
            PaykuSubscription.status_normalized == common_status,
            *_date_range(CoreSubscription.ended_at, start, end),
        )
        .order_by(CoreSubscription.ended_at.desc().nulls_last(), CoreSubscription.external_id)
    )
    rows, total = _page(db, query, offset, limit)
    items = [
        {
            "source": SOURCE,
            "subscription_id": sub.external_id,
            "status": sub.status,
            "status_normalized": normalized,
            "started_at": _iso(sub.started_at),
            "cancelled_at": _iso(sub.ended_at),
            "antiquity_days": (sub.ended_at - sub.started_at).days if sub.ended_at and sub.started_at else None,
            "amount": _num(sub.amount),
            "currency": sub.currency,
            "last_payment_status": sub.last_payment_status,
        }
        for sub, normalized in rows
    ]
    return attach_people(db, SOURCE, {"items": items, "total": total, "offset": offset, "limit": limit, "empty_reason": None},
                         include_pii)


def cancelled(db: Session, start: date | None, end: date | None, offset: int, limit: int, *, include_pii: bool = False) -> dict:
    return _subscriptions(db, "cancelled", start, end, offset, limit, include_pii)


def suspended(db: Session, start: date | None, end: date | None, offset: int, limit: int, *, include_pii: bool = False) -> dict:
    return _subscriptions(db, "suspended", start, end, offset, limit, include_pii)


def rejected(db: Session, start: date | None, end: date | None, offset: int, limit: int, *, include_pii: bool = False) -> dict:
    query = (
        select(CorePayment, CoreSubscription.external_id, CoreCharge.period_reference, CoreSubscription.amount)
        .join(PaykuTransaction, PaykuTransaction.external_id == CorePayment.external_id)
        .outerjoin(CoreSubscription, CoreSubscription.id == CorePayment.subscription_id)
        .outerjoin(CoreCharge, CoreCharge.id == CorePayment.charge_id)
        .where(
            CorePayment.source == SOURCE,
            PaykuTransaction.status_normalized == "rejected",
            *_date_range(CorePayment.occurred_at, start, end),
        )
        .order_by(CorePayment.occurred_at.desc().nulls_last(), CorePayment.external_id)
    )
    rows, total = _page(db, query, offset, limit)
    items = []
    for payment, sub_external_id, charge_period, sub_amount in rows:
        amount, amount_source = _attempt_amount(payment.amount, sub_amount)
        period, period_source = _attempt_period(charge_period, payment.occurred_at)
        items.append({
            "source": SOURCE,
            "charge_id": payment.external_id,
            "subscription_id": sub_external_id,
            "period": period,
            "period_source": period_source,
            "charge_date": _iso(payment.occurred_at),
            "amount": amount,
            "amount_source": amount_source,
            "currency": payment.currency,
            "status": payment.source_status,
            "rejection_code": payment.rejection_code,
            "rejection_reason": format_rejection_reason(SOURCE, payment.rejection_code, payment.rejection_reason),
        })
    return attach_people(db, SOURCE, {"items": items, "total": total, "offset": offset, "limit": limit, "empty_reason": None},
                         include_pii)
