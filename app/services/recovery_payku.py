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
        select(CorePayment, CoreSubscription.external_id, CoreCharge.period_reference)
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
    items = [
        {
            "source": SOURCE,
            "charge_id": payment.external_id,
            "subscription_id": sub_external_id,
            "period": period,
            "charge_date": _iso(payment.occurred_at),
            "amount": _num(payment.amount),
            "currency": payment.currency,
            "status": payment.source_status,
            "rejection_code": payment.rejection_code,
            "rejection_reason": format_rejection_reason(SOURCE, payment.rejection_code, payment.rejection_reason),
        }
        for payment, sub_external_id, period in rows
    ]
    return attach_people(db, SOURCE, {"items": items, "total": total, "offset": offset, "limit": limit, "empty_reason": None},
                         include_pii)
