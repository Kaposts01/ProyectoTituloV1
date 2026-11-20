"""Cifras de reportes por rango de fechas (REP-01), extraidas de la ruta `/reports/automatic` para reutilizarlas en los
reportes programados por correo (REP-02). Solo agregados: conteos y montos por canal, nunca datos personales."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import Numeric, case, cast, func, or_, select, text
from sqlalchemy.orm import Session

from app.models.crm import Charge, Subscription
from app.models.tch import TchSubscription, TchTransaction
from app.services.charge_stats import charge_rejection_stats, chile_today


def auto_period_data(db: Session, dfrom: date, dto: date) -> dict[str, Any]:
    start_iso = dfrom.isoformat()
    end_iso = dto.isoformat()
    numeric_charge = case((Charge.amount.op("~")(r"^\d+(\.\d+)?$"), cast(Charge.amount, Numeric)), else_=0)
    numeric_tch = case((TchTransaction.amount.op("~")(r"^\d+(\.\d+)?$"), cast(TchTransaction.amount, Numeric)), else_=0)

    # Payku statuses that are never real active subscriptions.
    # "register": payment method setup never completed.
    # "suspended", "delete", "cancel": no longer active, may lack a canceled_at date for historical data.
    _not_payku_register = or_(
        Subscription.source != "payku",
        func.lower(Subscription.status) != "register",
    )
    _not_payku_suspended = or_(
        Subscription.source != "payku",
        func.lower(Subscription.status) != "suspended",
    )
    # Used only for active_start / active_end: exclude ALL Payku non-active statuses explicitly
    # so that delete/cancel/suspended with missing canceled_at don't inflate the active count.
    _payku_only_active = or_(
        Subscription.source != "payku",
        func.lower(Subscription.status).in_(["active", "suspended_awaits_change_plan"]),
    )

    # New subscriptions: count by suscription_date within the period (excludes Payku register).
    new_subs = dict(db.execute(
        select(Subscription.source, func.count())
        .where(
            _not_payku_register,
            func.substring(Subscription.suscription_date, 1, 10).between(start_iso, end_iso),
        )
        .group_by(Subscription.source)
    ).all())

    # Cancellations via canceled_at (covers all sources except Payku suspended,
    # which has canceled_at=None by design and is counted separately via JSON logs).
    cancelled_subs = dict(db.execute(
        select(Subscription.source, func.count())
        .where(
            _not_payku_register,
            _not_payku_suspended,
            Subscription.canceled_at.isnot(None),
            Subscription.canceled_at != "",
            func.substring(Subscription.canceled_at, 1, 10).between(start_iso, end_iso),
        )
        .group_by(Subscription.source)
    ).all())
    # Payku suspended bajas: count via status logs (suspended has no canceled_at by design).
    payku_suspended_in_period = db.scalar(text(
        "SELECT COUNT(*) FROM subscriptions "
        "WHERE source = 'payku' AND lower(status) = 'suspended' "
        "AND ( "
        "  SELECT MAX(substring(elem->>'change_date', 1, 10)) "
        "  FROM jsonb_array_elements(COALESCE(raw_payload->'logs'->'status', '[]'::jsonb)) AS elem "
        "  WHERE elem->>'final_status' = 'suspended' "
        ") BETWEEN :start_iso AND :end_iso"
    ), {"start_iso": start_iso, "end_iso": end_iso}) or 0
    if payku_suspended_in_period:
        cancelled_subs["payku"] = cancelled_subs.get("payku", 0) + int(payku_suspended_in_period)

    # Active counts: non-Payku uses standard canceled_at logic; Payku requires special handling
    # because suspended subs have canceled_at=None by design, and historical delete/cancel subs
    # may lack dates. We reconstruct "was active at boundary" per subscription:
    #   - currently active/suspended_awaits_change_plan → was active at start/end (no extra check)
    #   - currently delete/cancel with dated canceled_at → active before that date
    #   - currently suspended → active before the last suspension log date
    active_start_non_payku = dict(db.execute(
        select(Subscription.source, func.count())
        .where(
            Subscription.source != "payku",
            func.substring(Subscription.suscription_date, 1, 10) < start_iso,
            or_(
                Subscription.canceled_at.is_(None),
                Subscription.canceled_at == "",
                func.substring(Subscription.canceled_at, 1, 10) >= start_iso,
            ),
        )
        .group_by(Subscription.source)
    ).all())
    payku_active_start = db.scalar(text(
        "SELECT COUNT(*) FROM subscriptions "
        "WHERE source = 'payku' AND lower(status) != 'register' "
        "AND substring(suscription_date, 1, 10) < :start_iso "
        "AND ( "
        "  lower(status) IN ('active', 'suspended_awaits_change_plan') "
        "  OR (lower(status) IN ('delete', 'cancel') "
        "      AND canceled_at IS NOT NULL AND canceled_at != '' "
        "      AND substring(canceled_at, 1, 10) >= :start_iso) "
        "  OR (lower(status) = 'suspended' "
        "      AND (SELECT MAX(substring(elem->>'change_date', 1, 10)) "
        "           FROM jsonb_array_elements(COALESCE(raw_payload->'logs'->'status', '[]'::jsonb)) AS elem "
        "           WHERE elem->>'final_status' = 'suspended') >= :start_iso) "
        ")"
    ), {"start_iso": start_iso}) or 0
    active_start = dict(active_start_non_payku)
    active_start["payku"] = int(payku_active_start)

    active_end_non_payku = dict(db.execute(
        select(Subscription.source, func.count())
        .where(
            Subscription.source != "payku",
            func.substring(Subscription.suscription_date, 1, 10) <= end_iso,
            or_(
                Subscription.canceled_at.is_(None),
                Subscription.canceled_at == "",
                func.substring(Subscription.canceled_at, 1, 10) > end_iso,
            ),
        )
        .group_by(Subscription.source)
    ).all())
    payku_active_end = db.scalar(text(
        "SELECT COUNT(*) FROM subscriptions "
        "WHERE source = 'payku' AND lower(status) != 'register' "
        "AND substring(suscription_date, 1, 10) <= :end_iso "
        "AND ( "
        "  (lower(status) IN ('active', 'suspended_awaits_change_plan') "
        "   AND (canceled_at IS NULL OR canceled_at = '' OR substring(canceled_at, 1, 10) > :end_iso)) "
        "  OR (lower(status) IN ('delete', 'cancel') "
        "      AND canceled_at IS NOT NULL AND canceled_at != '' "
        "      AND substring(canceled_at, 1, 10) > :end_iso) "
        "  OR (lower(status) = 'suspended' "
        "      AND (SELECT MAX(substring(elem->>'change_date', 1, 10)) "
        "           FROM jsonb_array_elements(COALESCE(raw_payload->'logs'->'status', '[]'::jsonb)) AS elem "
        "           WHERE elem->>'final_status' = 'suspended') > :end_iso) "
        ")"
    ), {"end_iso": end_iso}) or 0
    active_end = dict(active_end_non_payku)
    active_end["payku"] = int(payku_active_end)

    revenue_rows = {
        src: (int(cnt), float(amt))
        for src, cnt, amt in db.execute(
            select(Charge.source, func.count(), func.coalesce(func.sum(numeric_charge), 0))
            .where(
                func.substring(Charge.charge_date, 1, 10).between(start_iso, end_iso),
                func.lower(Charge.status).in_(("pagado", "aceptado", "accepted", "paid")),
            )
            .group_by(Charge.source)
        ).all()
    }

    # UI-30: rechazo con la definicion unica de charge_stats (fecha <= hoy en Chile, sin cancelados/expirados/anulados;
    # tasa = rechazados / (pagados + rechazados)). Antes el denominador eran TODOS los cargos del rango.
    charge_day = func.substring(Charge.charge_date, 1, 10)
    charge_rows_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for src, day, status, cnt in db.execute(
        select(Charge.source, charge_day, Charge.status, func.count())
        .where(charge_day.between(start_iso, end_iso))
        .group_by(Charge.source, charge_day, Charge.status)
    ).all():
        charge_rows_by_source[src].append({"date": day, "status": status, "count": int(cnt)})
    stats_until = min(dto, chile_today())
    charge_stats_by_source = {
        src: charge_rejection_stats(rows, stats_until, since=dfrom) for src, rows in charge_rows_by_source.items()
    }
    rejected = {src: s["rejected"] for src, s in charge_stats_by_source.items()}
    total_charges = {src: s["evaluable"] for src, s in charge_stats_by_source.items()}

    tch_new = db.scalar(select(func.count()).select_from(TchSubscription).where(
        TchSubscription.activation_date.isnot(None),
        func.substring(TchSubscription.activation_date, 1, 10).between(start_iso, end_iso),
    )) or 0
    tch_can = db.scalar(select(func.count()).select_from(TchSubscription).where(
        TchSubscription.deletion_date.isnot(None),
        func.substring(TchSubscription.deletion_date, 1, 10).between(start_iso, end_iso),
    )) or 0
    tch_act_start = db.scalar(select(func.count()).select_from(TchSubscription).where(
        TchSubscription.activation_date.isnot(None),
        func.substring(TchSubscription.activation_date, 1, 10) < start_iso,
        or_(TchSubscription.deletion_date.is_(None), func.substring(TchSubscription.deletion_date, 1, 10) >= start_iso),
    )) or 0
    tch_act_end = db.scalar(select(func.count()).select_from(TchSubscription).where(
        TchSubscription.activation_date.isnot(None),
        func.substring(TchSubscription.activation_date, 1, 10) <= end_iso,
        or_(TchSubscription.deletion_date.is_(None), func.substring(TchSubscription.deletion_date, 1, 10) > end_iso),
    )) or 0
    tch_rev_row = db.execute(
        select(func.count(), func.coalesce(func.sum(numeric_tch), 0))
        .select_from(TchTransaction)
        .where(
            TchTransaction.charge_date.isnot(None),
            func.substring(TchTransaction.charge_date, 1, 10).between(start_iso, end_iso),
            func.upper(TchTransaction.status) == "ACEPTADA",
        )
    ).one()
    tch_rev_count, tch_rev_amount = int(tch_rev_row[0] or 0), float(tch_rev_row[1] or 0)
    tch_day = func.substring(TchTransaction.charge_date, 1, 10)
    tch_charge_stats = charge_rejection_stats(
        (
            {"date": day, "status": status, "count": int(cnt)}
            for day, status, cnt in db.execute(
                select(tch_day, TchTransaction.status, func.count())
                .where(TchTransaction.charge_date.isnot(None), tch_day.between(start_iso, end_iso))
                .group_by(tch_day, TchTransaction.status)
            ).all()
        ),
        stats_until,
        since=dfrom,
    )
    tch_rejected, tch_total = tch_charge_stats["rejected"], tch_charge_stats["evaluable"]
    tch_reasons = db.execute(
        select(TchTransaction.rejection_reason, func.count())
        .where(
            TchTransaction.charge_date.isnot(None),
            func.substring(TchTransaction.charge_date, 1, 10).between(start_iso, end_iso),
            func.upper(TchTransaction.status) == "RECHAZADA",
            TchTransaction.rejection_reason.isnot(None),
        )
        .group_by(TchTransaction.rejection_reason)
        .order_by(func.count().desc())
        .limit(15)
    ).all()

    def _stats(sources: tuple[str, ...] | None = None, *, tch_mode: bool = False) -> dict[str, Any]:
        if tch_mode:
            ns, ca, as_, ae = tch_new, tch_can, tch_act_start, tch_act_end
            rc, ra, rj, tc = tch_rev_count, tch_rev_amount, int(tch_rejected), int(tch_total)
        else:
            srcs = sources or ()
            ns = sum(new_subs.get(s, 0) for s in srcs)
            ca = sum(cancelled_subs.get(s, 0) for s in srcs)
            as_ = sum(active_start.get(s, 0) for s in srcs)
            ae = sum(active_end.get(s, 0) for s in srcs)
            rc = sum(revenue_rows.get(s, (0, 0))[0] for s in srcs)
            ra = sum(revenue_rows.get(s, (0, 0))[1] for s in srcs)
            rj = sum(rejected.get(s, 0) for s in srcs)
            tc = sum(total_charges.get(s, 0) for s in srcs)
        return {
            "new_subscriptions": ns,
            "cancellations": ca,
            "active_start": as_,
            "active_end": ae,
            "revenue": round(ra, 2),
            "revenue_count": rc,
            "rejected": rj,
            "total_charges": tc,
            "rejection_rate": round(100.0 * rj / tc, 1) if tc > 0 else 0.0,
            "churn_rate": round(100.0 * ca / as_, 2) if as_ > 0 else 0.0,
        }

    channels: dict[str, Any] = {
        "virtualpos": _stats(("virtualpos1", "virtualpos2")),
        "toku": _stats(("toku",)),
        "payku": _stats(("payku",)),
        "tch": _stats(tch_mode=True),
    }
    channels["global"] = {
        k: sum(channels[ch][k] for ch in ("virtualpos", "toku", "payku", "tch"))
        if k in ("new_subscriptions", "cancellations", "active_start", "active_end", "revenue_count", "rejected", "total_charges")
        else round(sum(channels[ch]["revenue"] for ch in ("virtualpos", "toku", "payku", "tch")), 2)
        if k == "revenue"
        else 0.0
        for k in channels["virtualpos"]
    }
    g = channels["global"]
    channels["global"]["rejection_rate"] = round(100.0 * g["rejected"] / g["total_charges"], 1) if g["total_charges"] > 0 else 0.0
    channels["global"]["churn_rate"] = round(100.0 * g["cancellations"] / g["active_start"], 2) if g["active_start"] > 0 else 0.0

    rejection_reasons = [
        {"reason": str(r or "Sin motivo"), "count": int(c), "channel": "tch"}
        for r, c in tch_reasons
    ]

    alerts: list[dict[str, Any]] = []
    for ch_name, stats in channels.items():
        if stats["total_charges"] > 0 and stats["rejection_rate"] > 50:
            alerts.append({"sev": "alta", "tipo": "Alta tasa de rechazo", "detalle": f"{ch_name.capitalize()}: {stats['rejection_rate']}% ({stats['rejected']} de {stats['total_charges']} cargos)"})
        if stats["cancellations"] > stats["new_subscriptions"] and stats["cancellations"] > 0:
            alerts.append({"sev": "media", "tipo": "Saldo negativo de suscripciones", "detalle": f"{ch_name.capitalize()}: {stats['cancellations']} bajas vs {stats['new_subscriptions']} altas"})
        if stats["churn_rate"] > 5:
            alerts.append({"sev": "alta" if stats["churn_rate"] > 10 else "media", "tipo": "Churn elevado", "detalle": f"{ch_name.capitalize()}: churn {stats['churn_rate']}%"})

    sev_order = {"alta": 0, "media": 1, "baja": 2}
    alerts.sort(key=lambda a: sev_order.get(a["sev"], 3))

    return {
        "date_from": dfrom.isoformat(),
        "date_to": dto.isoformat(),
        "channels": channels,
        "rejection_reasons": rejection_reasons,
        "alerts": alerts,
    }
