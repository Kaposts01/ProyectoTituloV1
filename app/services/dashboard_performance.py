"""Observed monthly KPIs; subscriptions are counted per source, never as unique people."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.crm import Payment, Subscription
from app.models.tch import TchRecaudacionMensual, TchSuscripcion, TchTransaccion

SOURCES = {
    "virtualpos1": "VirtualPOS",
    "virtualpos2": "VirtualPOS",
    "toku": "Toku",
    "payku": "Payku",
    "tch": "TCH",
}
ACCEPTED = {
    "pagado",
    "pago",
    "aceptado",
    "accepted",
    "paid",
    "success",
    "aprobada",
    "aceptada",
}
REJECTED = {
    "rechazado",
    "rejected",
    "failed",
    "failure",
    "declined",
    "error",
    "rechazada",
}
ACTIVE = {"activa", "active", "vigente"}


def _date(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo:
            result = result.astimezone(ZoneInfo("America/Santiago"))
        return result.date() if result.year >= 1900 else None
    except (ValueError, TypeError):
        return None


def _money(value):
    try:
        amount = Decimal(str(value))
        return amount if amount.is_finite() and amount >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def build_monthly_performance(payments, subscriptions, controls, as_of: date) -> dict:
    """TCH controls replace detail only for the same month; absent observations stay null."""
    periods = defaultdict(
        lambda: {
            "accepted": Decimal(0),
            "rejected": Decimal(0),
            "observations": 0,
            "channels": defaultdict(Decimal),
        }
    )
    excluded = defaultdict(int)
    valid_controls = {}
    for control in controls:
        period = _date(str(control["period"]) + "-01")
        if (
            period
            and period <= as_of
            and _money(control["accepted"]) is not None
            and _money(control["rejected"]) is not None
            and (
                control.get("count", 0) > 0
                or _money(control["accepted"]) + _money(control["rejected"]) > 0
            )
        ):
            valid_controls[(period.year, period.month)] = control
        else:
            excluded["invalid_or_future_controls"] += 1
    for control_key, control in valid_controls.items():
        accepted, rejected = _money(control["accepted"]), _money(control["rejected"])
        if accepted is None or rejected is None:
            excluded["invalid_amount"] += 1
            continue
        bucket = periods[control_key]
        bucket["accepted"] += accepted
        bucket["rejected"] += rejected
        bucket["channels"]["TCH"] += accepted
        bucket["observations"] += 1
    for payment in payments:
        observed = _date(payment["date"])
        if not observed or observed > as_of:
            excluded["undated_or_future_payments"] += 1
            continue
        key = (observed.year, observed.month)
        if payment["source"] == "tch" and key in valid_controls:
            continue
        if str(payment.get("currency") or "").upper() != "CLP":
            excluded["other_or_missing_currency"] += 1
            continue
        amount = _money(payment["amount"])
        if amount is None:
            excluded["invalid_amount"] += 1
            continue
        status = str(payment["status"] or "").lower()
        if status not in ACCEPTED | REJECTED:
            continue
        bucket = periods[key]
        bucket["observations"] += 1
        bucket["channels"].setdefault(SOURCES[payment["source"]], Decimal(0))
        if status in ACCEPTED:
            bucket["accepted"] += amount
            bucket["channels"][SOURCES[payment["source"]]] += amount
        else:
            bucket["rejected"] += amount
    intervals = []
    for subscription in subscriptions:
        started, ended = _date(subscription["start"]), _date(subscription["end"])
        if (
            not started
            or started > as_of
            or (ended and ended < started)
            or (subscription["end"] and ended is None)
        ):
            excluded["subscriptions_without_valid_interval"] += 1
            continue
        if ended is None and str(subscription["status"] or "").lower() not in ACTIVE:
            excluded["subscriptions_without_valid_interval"] += 1
            continue
        intervals.append((started, ended))
    keys = list(periods) + [(start.year, start.month) for start, _ in intervals]
    first = min(keys) if keys else (as_of.year, as_of.month)
    cursor = date(*first, 1)
    monthly = []
    while cursor <= as_of:
        next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        cutoff = min(as_of, next_month - timedelta(days=1))
        key = (cursor.year, cursor.month)
        bucket = periods.get(key)
        opening = sum(
            start < cursor and (end is None or end >= cursor)
            for start, end in intervals
        )
        closing = sum(
            start <= cutoff and (end is None or end > cutoff)
            for start, end in intervals
        )
        activations = sum(cursor <= start <= cutoff for start, _ in intervals)
        cancellations = sum(
            end is not None and cursor <= end <= cutoff for _, end in intervals
        )
        opening_cancellations = sum(
            start < cursor and end is not None and cursor <= end <= cutoff
            for start, end in intervals
        )
        accepted = bucket["accepted"] if bucket else None
        rejected = bucket["rejected"] if bucket else None
        attempts = accepted + rejected if bucket else Decimal(0)
        monthly.append(
            {
                "period": cursor.strftime("%Y-%m"),
                "year": cursor.year,
                "month": cursor.month,
                "revenue": float(accepted) if accepted is not None else None,
                "rejected_amount": float(rejected) if rejected is not None else None,
                "collection_rate": round(float(accepted / attempts * 100), 2)
                if attempts
                else None,
                "opening": opening if intervals else None,
                "active": closing if intervals else None,
                "activations": activations if intervals else None,
                "cancellations": cancellations if intervals else None,
                "net_growth": activations - cancellations if intervals else None,
                "churn": round(opening_cancellations / opening * 100, 2)
                if opening
                else None,
                "channels": {
                    label: float(bucket["channels"][label])
                    if bucket and label in bucket["channels"]
                    else None
                    for label in dict.fromkeys(SOURCES.values())
                },
                "partial_month": cutoff == as_of
                and next_month > as_of + timedelta(days=1),
            }
        )
        cursor = next_month
    observed = [row["period"] for row in monthly if row["revenue"] is not None]
    return {
        "as_of": as_of.isoformat(),
        "currency": "CLP",
        "monthly": monthly,
        "default_period": observed[-1] if observed else monthly[-1]["period"],
        "excluded": dict(excluded),
        "coverage": "Datos locales observados. Cobertura parcial de proveedores; no certifica recaudación completa. Base reconstruida de suscripciones por origen, sin deduplicar personas. TCH usa control mensual cuando existe; en otros meses usa detalle. Mes sin observaciones se muestra como no disponible.",
    }


def monthly_performance(db: Session, as_of: date | None = None) -> dict:
    cutoff = as_of or datetime.now(ZoneInfo("America/Santiago")).date()
    online_sources = tuple(source for source in SOURCES if source != "tch")
    # TCH is read from channel tables only, never from both copies of its projection.
    payments = list(
        db.execute(
            select(
                Payment.source,
                Payment.status,
                Payment.amount,
                Payment.currency,
                Payment.payment_date.label("date"),
            ).where(Payment.source.in_(online_sources))
        ).mappings()
    )
    controls = [
        {
            "period": row.periodo,
            "accepted": row.aceptadas_monto,
            "rejected": row.rechazadas_monto,
            "count": row.aceptadas_cantidad + row.rechazadas_cantidad,
        }
        for row in db.execute(
            select(
                TchRecaudacionMensual.periodo,
                TchRecaudacionMensual.aceptadas_monto,
                TchRecaudacionMensual.rechazadas_monto,
                TchRecaudacionMensual.aceptadas_cantidad,
                TchRecaudacionMensual.rechazadas_cantidad,
            )
        )
    ]
    controlled_periods = [
        control["period"]
        for control in controls
        if (period := _date(str(control["period"]) + "-01"))
        and period <= cutoff
        and _money(control["accepted"]) is not None
        and _money(control["rejected"]) is not None
        and (
            control.get("count", 0) > 0
            or _money(control["accepted"]) + _money(control["rejected"]) > 0
        )
    ]
    detail_query = select(
        TchTransaccion.estado,
        TchTransaccion.monto,
        TchTransaccion.periodo,
        TchTransaccion.fecha_cargo,
    )
    if controlled_periods:
        detail_query = detail_query.where(
            or_(
                TchTransaccion.periodo.is_(None),
                TchTransaccion.periodo.not_in(controlled_periods),
            )
        )
    payments.extend(
        {
            "source": "tch",
            "status": row.estado,
            "amount": row.monto,
            "currency": "CLP",
            "date": row.periodo + "-01" if row.periodo else row.fecha_cargo,
        }
        for row in db.execute(detail_query)
    )
    subscriptions = list(
        db.execute(
            select(
                Subscription.suscription_date.label("start"),
                Subscription.canceled_at.label("end"),
                Subscription.status,
            ).where(Subscription.source.in_(online_sources))
        ).mappings()
    )
    subscriptions.extend(
        {
            "start": row.fecha_activacion,
            "end": row.fecha_eliminacion,
            "status": row.estado,
        }
        for row in db.execute(
            select(
                TchSuscripcion.fecha_activacion,
                TchSuscripcion.fecha_eliminacion,
                TchSuscripcion.estado,
            )
        )
    )
    return build_monthly_performance(payments, subscriptions, controls, cutoff)
