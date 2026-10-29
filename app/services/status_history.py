"""Resumen diario de cambios (SYNC-D-04) sobre `status_change_events`: "que cambio ese dia" en hora de Chile.

Excluye siempre `is_baseline`. Solo ids externos, estados, montos y glosas de rechazo (sin datos personales).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Numeric, Select, and_, case, cast, func, select
from sqlalchemy.orm import Session

from app.models.status_change import RejectionReasonCatalog, StatusChangeEvent

CHILE_TZ = ZoneInfo("America/Santiago")
E = StatusChangeEvent

# Estados (en minusculas) de una suscripcion que cuentan como BAJA, por canal. `removed` siempre es baja.
BAJA_STATES: dict[str, frozenset[str]] = {
    "virtualpos1": frozenset({"cancelada", "cancelado", "cancelled", "canceled"}),
    "virtualpos2": frozenset({"cancelada", "cancelado", "cancelled", "canceled"}),
    "toku": frozenset({"cancelled", "canceled", "cancelada", "deleted", "ended"}),
    "payku": frozenset({"cancel", "delete", "suspended"}),  # los mismos estados que usa el churn del dashboard
    "tch": frozenset({"baja"}),
}

_NUMERIC = r"^-?[0-9]+(\.[0-9]+)?$"
_NUMERIC_TYPE = Numeric()


def chile_day_bounds(day: date) -> tuple[datetime, datetime]:
    """[inicio, fin) del dia calendario en America/Santiago, expresado en UTC (respeta el cambio de horario)."""
    start = datetime(day.year, day.month, day.day, tzinfo=CHILE_TZ)
    end_day = day + timedelta(days=1)
    end = datetime(end_day.year, end_day.month, end_day.day, tzinfo=CHILE_TZ)
    return start.astimezone(UTC), end.astimezone(UTC)


def _base(stmt: Select, start: datetime, end: datetime, source: str | None, entity_type: str | None) -> Select:
    stmt = stmt.where(E.detected_at >= start, E.detected_at < end, E.is_baseline.is_(False))
    if source:
        stmt = stmt.where(E.source == source)
    if entity_type:
        stmt = stmt.where(E.entity_type == entity_type)
    return stmt


def _num(value: Any) -> float | int | None:
    if value is None:
        return None
    dec = Decimal(value)
    return int(dec) if dec == dec.to_integral_value() else float(dec)


def daily_changes(
    db: Session,
    day: date,
    *,
    source: str | None = None,
    entity_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    start, end = chile_day_bounds(day)

    def q(*cols) -> Select:
        return _base(select(*cols), start, end, source, entity_type)

    by_kind = {kind: n for kind, n in db.execute(q(E.event_kind, func.count()).group_by(E.event_kind))}

    # Matriz de transiciones from -> to (paginada).
    groups = (
        q(E.entity_type, E.source, E.from_value, E.to_value, func.count().label("n"))
        .where(E.event_kind == "status_changed")
        .group_by(E.entity_type, E.source, E.from_value, E.to_value)
    )
    transitions_total = db.scalar(select(func.count()).select_from(groups.subquery())) or 0
    transitions = [
        {"entity_type": et, "source": s, "from": fv, "to": tv, "count": n}
        for et, s, fv, tv, n in db.execute(
            groups.order_by(func.count().desc(), E.entity_type, E.source, E.from_value, E.to_value)
            .limit(limit)
            .offset(offset)
        )
    ]

    created = [
        {"entity_type": et, "source": s, "count": n}
        for et, s, n in db.execute(
            q(E.entity_type, E.source, func.count())
            .where(E.event_kind == "created")
            .group_by(E.entity_type, E.source)
            .order_by(E.entity_type, E.source)
        )
    ]

    # Altas y bajas de suscripciones.
    altas = [c for c in created if c["entity_type"] == "subscription"]
    bajas_acc: dict[str, dict[str, int]] = {}
    for s, kind, to_value, n in db.execute(
        q(E.source, E.event_kind, E.to_value, func.count())
        .where(E.entity_type == "subscription", E.event_kind.in_(("status_changed", "removed")))
        .group_by(E.source, E.event_kind, E.to_value)
    ):
        if kind == "removed":
            label = "removed"
        elif (to_value or "").strip().lower() in BAJA_STATES.get(s, frozenset()):
            label = to_value or ""
        else:
            continue
        bajas_acc.setdefault(s, {})
        bajas_acc[s][label] = bajas_acc[s].get(label, 0) + n
    bajas = [
        {"source": s, "count": sum(states.values()),
         "by_state": [{"state": k, "count": v} for k, v in sorted(states.items())]}
        for s, states in sorted(bajas_acc.items())
    ]

    # Cambios de monto con delta (solo cuando ambos valores son numericos).
    numeric = and_(E.from_value.op("~")(_NUMERIC), E.to_value.op("~")(_NUMERIC))
    delta = case((numeric, cast(E.to_value, _NUMERIC_TYPE) - cast(E.from_value, _NUMERIC_TYPE)), else_=None)
    amount_rows = db.execute(
        q(
            E.entity_type, E.source, func.count(),
            func.count().filter(delta > 0), func.count().filter(delta < 0), func.sum(delta),
        )
        .where(E.event_kind == "amount_changed")
        .group_by(E.entity_type, E.source)
        .order_by(E.entity_type, E.source)
    )
    amount_summary = [
        {"entity_type": et, "source": s, "count": n, "increases": up, "decreases": down, "net_delta": _num(total)}
        for et, s, n, up, down, total in amount_rows
    ]
    top_amount = [
        {"entity_type": et, "source": s, "external_id": ext, "subscription_external_id": sub, "from": fv, "to": tv,
         "delta": _num(d)}
        for et, s, ext, sub, fv, tv, d in db.execute(
            q(E.entity_type, E.source, E.external_id, E.subscription_external_id, E.from_value, E.to_value, delta)
            .where(E.event_kind == "amount_changed")
            .order_by(func.abs(delta).desc().nulls_last(), E.source, E.external_id)
            .limit(min(limit, 20))
        )
    ]

    # Glosas nuevas del dia (eventos reason_changed no baseline + detalle del catalogo).
    reasons_q = (
        q(E.source, E.to_value, E.detected_at, RejectionReasonCatalog.code, RejectionReasonCatalog.occurrences)
        .select_from(E)
        .join(
            RejectionReasonCatalog,
            and_(
                RejectionReasonCatalog.source == E.source,
                case(
                    (RejectionReasonCatalog.reason == "", RejectionReasonCatalog.code),
                    else_=RejectionReasonCatalog.reason,
                ) == E.to_value,
            ),
            isouter=True,
        )
        .where(E.event_kind == "reason_changed")
    )
    reasons_total = db.scalar(select(func.count()).select_from(reasons_q.subquery())) or 0
    new_reasons = [
        {"source": s, "reason": reason, "code": code, "first_seen_at": at.isoformat(), "occurrences": occ}
        for s, reason, at, code, occ in db.execute(reasons_q.order_by(E.detected_at, E.source, E.to_value).limit(limit))
    ]

    return {
        "date": day.isoformat(),
        "timezone": "America/Santiago",
        "window": {"from": start.isoformat(), "to": end.isoformat()},
        "filters": {"source": source, "entity_type": entity_type},
        "totals": {"events": sum(by_kind.values()), "by_kind": dict(sorted(by_kind.items()))},
        "transitions": {"items": transitions, "total": transitions_total, "limit": limit, "offset": offset},
        "created": created,
        "subscriptions": {"altas": altas, "bajas": bajas},
        "amount_changes": {"summary": amount_summary, "top": top_amount},
        "new_reasons": {"items": new_reasons, "total": reasons_total, "limit": limit},
    }
