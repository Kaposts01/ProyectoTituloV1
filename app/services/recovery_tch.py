"""Recuperador general, pestaña TCH (REC-06). SOLO LECTURA: TCH es un Excel, no hay acciones remotas.

Vistas
------
* **deleted** (mandatos eliminados): `core_subscriptions` de TCH (`external_id` = número de ficha) con fecha de
  eliminación (`ended_at`, del Excel) o con estado que empieza por «ELIMIN». El filtro de fechas es sobre `ended_at`.
* **rejected** (cargos rechazados): `core_payments` de TCH cuyo estado contiene «RECHAZ» (misma regla que el ETL core,
  `core_tch_etl`). El filtro de fechas es sobre `occurred_at`.

TCH no define todavía qué es «recuperable» (no hay señales como las de Toku): esa vista no existe aquí y la interfaz
lo dice. Datos personales (d119, opción b): `rut` y `name` solo con el permiso de clientes de TCH (`recovery_pii`);
sin él van en `null` (la clave del pago es ficha|periodo|cuota). Paginación y filtros en SQL: TCH tiene más de
un millón de pagos, nada se arma en memoria.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models.core import CorePayment, CoreSubscription
from app.services.recovery_pii import attach_people
from app.services.rejection_format import format_rejection_reason

SOURCE = "tch"


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


def deleted(db: Session, start: date | None, end: date | None, offset: int, limit: int, *, include_pii: bool = False) -> dict:
    query = (
        select(CoreSubscription)
        .where(
            CoreSubscription.source == SOURCE,
            or_(CoreSubscription.ended_at.is_not(None), func.upper(CoreSubscription.status).like("ELIMIN%")),
            *_date_range(CoreSubscription.ended_at, start, end),
        )
        .order_by(CoreSubscription.ended_at.desc().nulls_last(), CoreSubscription.external_id)
    )
    rows, total = _page(db, query, offset, limit)
    items = []
    for (sub,) in rows:
        items.append({
            "source": SOURCE,
            "subscription_id": sub.external_id,
            "status": sub.status,
            "started_at": _iso(sub.started_at),
            "cancelled_at": _iso(sub.ended_at),
            "antiquity_days": (sub.ended_at - sub.started_at).days if sub.ended_at and sub.started_at else None,
            "amount": _num(sub.amount),
            "currency": sub.currency,
            "last_payment_status": sub.last_payment_status,
        })
    return attach_people(db, SOURCE, {"items": items, "total": total, "offset": offset, "limit": limit, "empty_reason": None},
                         include_pii)


def rejected(db: Session, start: date | None, end: date | None, offset: int, limit: int, *, include_pii: bool = False) -> dict:
    query = (
        select(CorePayment, CoreSubscription.external_id)
        .outerjoin(CoreSubscription, CoreSubscription.id == CorePayment.subscription_id)
        .where(
            CorePayment.source == SOURCE,
            func.upper(CorePayment.source_status).like("%RECHAZ%"),
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
            "charge_date": _iso(payment.occurred_at),
            "amount": _num(payment.amount),
            "currency": payment.currency,
            "status": payment.source_status,
            "rejection_code": payment.rejection_code,
            "rejection_reason": format_rejection_reason(SOURCE, payment.rejection_code, payment.rejection_reason),
        }
        for payment, sub_external_id in rows
    ]
    return attach_people(db, SOURCE, {"items": items, "total": total, "offset": offset, "limit": limit, "empty_reason": None},
                         include_pii)
