import html
import json
import re
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import Numeric, case, cast, func, select
from sqlalchemy.orm import Session

from app.api.v1.routes import staging, tch
from app.core.security import get_current_user
from app.db.session import SessionLocal
from app.models.auth import User
from app.models.crm import Charge, Client, Payment, Plan, Subscription
from app.models.tch import TchSuscripcion, TchTransaccion
from app.services.rbac import permission_codes, source_permission

router = APIRouter()

_SCOPES = {"general", "virtualpos", "toku", "payku", "tch"}
_LABELS = {"general": "Operación consolidada", "virtualpos": "VirtualPOS", "toku": "Toku", "payku": "Payku", "tch": "TCH"}
_VP_SOURCES = ("virtualpos1", "virtualpos2")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{name} must use YYYY-MM-DD") from exc


def _require_report_access(user: User, scope: str) -> None:
    codes = permission_codes(user)
    permission = "dashboard.view" if scope == "general" else "tch.dashboard.view" if scope == "tch" else source_permission(scope)
    if permission not in codes:
        raise HTTPException(status_code=403, detail="Missing required permission")


def _status(value: Any) -> str:
    return staging._general_transaction_status(value)


def _amount(value: Any) -> float:
    return staging._amount(value)


def _text(value: Any) -> str:
    return html.escape(str(value or "—"), quote=True)


def _source_filter(scope: str):
    if scope == "general":
        return None
    return _VP_SOURCES if scope == "virtualpos" else (scope,)


def _as_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _month_keys(start: date, end: date) -> list[str]:
    year, month = start.year, start.month
    keys = []
    while (year, month) <= (end.year, end.month):
        keys.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return keys


def _series(db: Session, scope: str, start: date, end: date) -> dict[str, list[dict[str, Any]]]:
    """Build date-range event series while snapshots remain intentionally current."""
    result: dict[str, defaultdict[tuple[int, int, str], dict[str, float]]] = {
        "transactions": defaultdict(lambda: {"count": 0, "amount": 0}),
        "activations": defaultdict(lambda: {"count": 0, "amount": 0}),
        "cancellations": defaultdict(lambda: {"count": 0, "amount": 0}),
        "charges": defaultdict(lambda: {"count": 0, "amount": 0}),
    }
    numeric_payment = case((Payment.amount.op("~")(r"^\d+(\.\d+)?$"), cast(Payment.amount, Numeric)), else_=0)
    numeric_charge = case((Charge.amount.op("~")(r"^\d+(\.\d+)?$"), cast(Charge.amount, Numeric)), else_=0)
    numeric_subscription = case((Subscription.amount.op("~")(r"^\d+(\.\d+)?$"), cast(Subscription.amount, Numeric)), else_=0)
    sources = _source_filter(scope)

    def add(kind: str, value: str | None, status: str, count: int, amount: Any) -> None:
        if not value:
            return
        try:
            event_date = date.fromisoformat(value[:10])
        except ValueError:
            return
        if start <= event_date <= end:
            bucket = result[kind][(event_date.year, event_date.month, status)]
            bucket["count"] += count
            bucket["amount"] += _amount(amount)

    start_value, end_value = start.isoformat(), end.isoformat()
    payment_query = select(Payment.payment_date, Payment.status, func.count(), func.coalesce(func.sum(numeric_payment), 0)).where(func.substring(Payment.payment_date, 1, 10).between(start_value, end_value)).group_by(Payment.payment_date, Payment.status)
    charge_query = select(Charge.charge_date, Charge.status, func.count(), func.coalesce(func.sum(numeric_charge), 0)).where(func.substring(Charge.charge_date, 1, 10).between(start_value, end_value)).group_by(Charge.charge_date, Charge.status)
    activation_query = select(Subscription.suscription_date, func.count(), func.coalesce(func.sum(numeric_subscription), 0)).where(func.substring(Subscription.suscription_date, 1, 10).between(start_value, end_value)).group_by(Subscription.suscription_date)
    cancellation_query = select(Subscription.canceled_at, func.count(), func.coalesce(func.sum(numeric_subscription), 0)).where(func.substring(Subscription.canceled_at, 1, 10).between(start_value, end_value)).group_by(Subscription.canceled_at)
    if sources:
        payment_query = payment_query.where(Payment.source.in_(sources))
        charge_query = charge_query.where(Charge.source.in_(sources))
        activation_query = activation_query.where(Subscription.source.in_(sources))
        cancellation_query = cancellation_query.where(Subscription.source.in_(sources))
    if scope != "tch":
        for event_date, status, count, amount in db.execute(payment_query):
            add("transactions", event_date, _status(status), count, amount)
        for event_date, status, count, amount in db.execute(charge_query):
            add("charges", event_date, _status(status), count, amount)
        for event_date, count, amount in db.execute(activation_query):
            add("activations", event_date, "Altas", count, amount)
        for event_date, count, amount in db.execute(cancellation_query):
            add("cancellations", event_date, "Bajas", count, amount)
    if scope in {"general", "tch"}:
        for transaction in db.scalars(select(TchTransaccion).where(func.substring(TchTransaccion.fecha_cargo, 1, 10).between(start_value, end_value))):
            add("transactions", transaction.fecha_cargo, _status(transaction.estado), 1, transaction.monto)
            add("charges", transaction.fecha_cargo, _status(transaction.estado), 1, transaction.monto)
        for subscription in db.scalars(select(TchSuscripcion).where(func.substring(TchSuscripcion.fecha_activacion, 1, 10).between(start_value, end_value))):
            add("activations", subscription.fecha_activacion, "Altas", 1, subscription.equivalente_pesos or subscription.monto)
        for subscription in db.scalars(select(TchSuscripcion).where(func.substring(TchSuscripcion.fecha_eliminacion, 1, 10).between(start_value, end_value))):
            add("cancellations", subscription.fecha_eliminacion, "Bajas", 1, subscription.equivalente_pesos or subscription.monto)

    return {
        kind: [
            {"year": year, "month": month, "status": status, "count": int(values["count"]), "amount": round(values["amount"], 2)}
            for (year, month, status), values in sorted(entries.items())
        ]
        for kind, entries in result.items()
    }


def _virtualpos_report_data(db: Session, start: date, end: date) -> dict[str, Any]:
    """Calculate the VirtualPOS report from centralized local records only."""
    subscriptions = db.scalars(select(Subscription).where(Subscription.source.in_(_VP_SOURCES))).all()
    clients = {
        (client.source, client.external_id): client
        for client in db.scalars(select(Client).where(Client.source.in_(_VP_SOURCES)))
    }
    plans = {
        (plan.source, plan.external_id): plan.name or plan.external_id
        for plan in db.scalars(select(Plan).where(Plan.source.in_(_VP_SOURCES)))
    }
    months = _month_keys(start, end)
    active_at_end = [
        subscription for subscription in subscriptions
        if (created := _as_date(subscription.suscription_date)) and created <= end
        and (not (cancelled := _as_date(subscription.canceled_at)) or cancelled > end)
    ]
    historical_subscriptions = [
        subscription for subscription in subscriptions
        if (created := _as_date(subscription.suscription_date)) and created <= end
    ]
    clients_at_end = [
        client for client in clients.values()
        if (created := _as_date(client.provider_created_at)) and created <= end
    ]
    charges = db.scalars(
        select(Charge).where(
            Charge.source.in_(_VP_SOURCES),
            func.substring(Charge.charge_date, 1, 10).between(start.isoformat(), end.isoformat()),
        )
    ).all()
    paid_charges = [charge for charge in charges if _status(charge.status) == "Aceptadas"]
    rejected_charges = [charge for charge in charges if _status(charge.status) == "Rechazadas"]
    charge_by_month: dict[str, list[Charge]] = defaultdict(list)
    for charge in charges:
        if charge_date := _as_date(charge.charge_date):
            charge_by_month[charge_date.strftime("%Y-%m")].append(charge)
    subscription_by_id = {(subscription.source, subscription.external_id): subscription for subscription in subscriptions}
    paid_amounts = {
        (source, subscription_id): {"amount": _amount(amount), "last_payment": last_payment}
        for source, subscription_id, amount, last_payment in db.execute(
            select(Charge.source, Charge.subscription_external_id, func.coalesce(func.sum(cast(Charge.amount, Numeric)), 0), func.max(Charge.charge_date))
            .where(
                Charge.source.in_(_VP_SOURCES),
                func.substring(Charge.charge_date, 1, 10) <= end.isoformat(),
                Charge.subscription_external_id.isnot(None),
                func.lower(Charge.status).in_(("pagado", "aceptado", "accepted", "paid")),
                Charge.amount.op("~")(r"^\d+(\.\d+)?$"),
            )
            .group_by(Charge.source, Charge.subscription_external_id)
        )
    }
    active_count_by_month = []
    churn = []
    altas, bajas = [], []
    deu_pag, deu_nop, int_ok, int_fail, cg_can, cg_pro, rec_mes, pagos_mes = [], [], [], [], [], [], [], []
    for month in months:
        month_end = date.fromisoformat(f"{month}-28")
        while month_end.month == int(month[5:]):
            next_day = date.fromordinal(month_end.toordinal() + 1)
            if next_day.month != month_end.month:
                break
            month_end = next_day
        month_start = date.fromisoformat(f"{month}-01")
        month_subs = [subscription for subscription in subscriptions if _as_date(subscription.suscription_date) and month_start <= _as_date(subscription.suscription_date) <= month_end]
        month_cancellations = [subscription for subscription in subscriptions if _as_date(subscription.canceled_at) and month_start <= _as_date(subscription.canceled_at) <= month_end]
        active_start = sum(1 for subscription in subscriptions if (created := _as_date(subscription.suscription_date)) and created < month_start and (not (cancelled := _as_date(subscription.canceled_at)) or cancelled >= month_start))
        active_end = sum(1 for subscription in subscriptions if (created := _as_date(subscription.suscription_date)) and created <= month_end and (not (cancelled := _as_date(subscription.canceled_at)) or cancelled > month_end))
        statuses = charge_by_month[month]
        paid = [charge for charge in statuses if _status(charge.status) == "Aceptadas"]
        rejected = [charge for charge in statuses if _status(charge.status) == "Rechazadas"]
        cancelled = [charge for charge in statuses if str(charge.status or "").lower() == "cancelado"]
        processing = [charge for charge in statuses if str(charge.status or "").lower() in {"pendiente", "procesando"}]
        altas.append(len(month_subs))
        bajas.append(len(month_cancellations))
        active_count_by_month.append(active_end)
        churn.append(round(100 * len(month_cancellations) / active_start, 2) if active_start else 0)
        deu_pag.append(len(paid)); deu_nop.append(len(rejected)); int_ok.append(len(paid)); int_fail.append(len(rejected))
        cg_can.append(len(cancelled)); cg_pro.append(len(processing))
        rec_mes.append(round(sum(_amount(charge.amount) for charge in paid), 2)); pagos_mes.append(len(paid))
    account_labels = {"virtualpos1": "Cuenta 1", "virtualpos2": "Cuenta 2"}
    account_revenue = {label: 0.0 for label in account_labels.values()}
    account_subscriptions = {label: 0 for label in account_labels.values()}
    for charge in paid_charges:
        account_revenue[account_labels[charge.source]] += _amount(charge.amount)
    for subscription in active_at_end:
        account_subscriptions[account_labels[subscription.source]] += 1
    # ── vida promedio ─────────────────────────────────────────────────────────
    def _lifetime_months(sub: Subscription) -> float:
        s = _as_date(sub.suscription_date)
        if not s:
            return 0.0
        e = _as_date(sub.canceled_at) or end
        return max(0.0, (e - s).days / 30.44)

    vida_prom_val = round(sum(_lifetime_months(s) for s in historical_subscriptions) / len(historical_subscriptions), 1) if historical_subscriptions else 0
    vida_prom_activas_val = round(sum(_lifetime_months(s) for s in active_at_end) / len(active_at_end), 1) if active_at_end else 0

    # ── tabla activas ─────────────────────────────────────────────────────────
    active_table = []
    for subscription in active_at_end:
        client = clients.get((subscription.source, subscription.client_external_id or ""))
        payment = paid_amounts.get((subscription.source, subscription.external_id), {"amount": 0, "last_payment": "—"})
        active_table.append({"cliente": _text(" ".join(part for part in ((client.first_name if client else None), (client.last_name if client else None)) if part) or "Sin cliente"), "cuenta": account_labels[subscription.source], "plan": _text(plans.get((subscription.source, subscription.plan_external_id or ""))), "producto": _text(subscription.external_id), "alta": _text(subscription.suscription_date), "ult_pago": _text(payment["last_payment"]), "total_pagado": payment["amount"]})
    active_table.sort(key=lambda row: row["total_pagado"], reverse=True)

    # ── alertas (5 tipos) ─────────────────────────────────────────────────────
    def _cname(source: str, cid: str | None, sub: Subscription | None = None) -> str:
        c = clients.get((source, cid or (sub.client_external_id if sub else "") or ""))
        if c:
            parts = [p for p in (c.first_name, c.last_name) if p]
            return _text(" ".join(parts)) if parts else "Sin nombre"
        return "Sin cliente"

    alerts: list[dict[str, Any]] = []
    alert_counts: dict[str, int] = {}

    # 1. Activa sin cobro reciente (alta)
    cutoff_str = (end - timedelta(days=60)).isoformat()
    no_recent: list[dict[str, Any]] = []
    for sub in active_at_end:
        last = str(paid_amounts.get((sub.source, sub.external_id), {}).get("last_payment") or "")[:10]
        if not last or last < cutoff_str:
            no_recent.append({"sev": "alta", "tipo": "Activa sin cobro reciente", "cliente": _cname(sub.source, sub.client_external_id, sub), "cuenta": account_labels[sub.source], "producto": _text(sub.external_id), "monto": _amount(sub.amount), "detalle": "Sin cobro aceptado en los últimos 60 días"})
    alert_counts["Activa sin cobro reciente"] = len(no_recent)
    alerts.extend(no_recent[:100])

    # 2. Racha de rechazos — 3+ consecutivos (alta)
    sub_charges_map: dict[tuple[str, str], list[Charge]] = defaultdict(list)
    for charge in sorted(charges, key=lambda c: (c.charge_date or "")):
        sub_charges_map[(charge.source, charge.subscription_external_id or "")].append(charge)
    racha_list: list[dict[str, Any]] = []
    for (src, sid), clist in sub_charges_map.items():
        streak = 0
        for charge in clist:
            if _status(charge.status) == "Rechazadas":
                streak += 1
            else:
                streak = 0
            if streak >= 3:
                sub = subscription_by_id.get((src, sid))
                racha_list.append({"sev": "alta", "tipo": "Racha de rechazos", "cliente": _cname(src, sub.client_external_id if sub else None, sub), "cuenta": account_labels.get(src, src), "producto": _text(sid), "monto": _amount(charge.amount), "detalle": f"{streak} rechazos consecutivos — riesgo de caída"})
                break
    alert_counts["Racha de rechazos"] = len(racha_list)
    alerts.extend(racha_list[:100])

    # 3. Suscripción fallida — nunca cobró (media)
    paid_sub_keys = {(c.source, c.subscription_external_id) for c in paid_charges}
    fallidas: list[dict[str, Any]] = []
    for sub in historical_subscriptions:
        if (sub.source, sub.external_id) not in paid_sub_keys:
            fallidas.append({"sev": "media", "tipo": "Suscripción fallida", "cliente": _cname(sub.source, sub.client_external_id, sub), "cuenta": account_labels[sub.source], "producto": _text(sub.external_id), "monto": _amount(sub.amount), "detalle": "Nunca registró un cobro aceptado"})
    alert_counts["Suscripción fallida"] = len(fallidas)
    alerts.extend(fallidas[:100])

    # 4. Cobro múltiple en el mes (media)
    paid_per_sub_month: dict[tuple[str, str, str], int] = defaultdict(int)
    for charge in paid_charges:
        if charge.charge_date:
            paid_per_sub_month[(charge.source, charge.subscription_external_id or "", charge.charge_date[:7])] += 1
    multiples: list[dict[str, Any]] = []
    seen_mult: set[tuple[str, str]] = set()
    for (src, sid, month), count in sorted(paid_per_sub_month.items()):
        if count >= 2 and (src, sid) not in seen_mult:
            seen_mult.add((src, sid))
            sub = subscription_by_id.get((src, sid))
            multiples.append({"sev": "media", "tipo": "Cobro múltiple en el mes", "cliente": _cname(src, sub.client_external_id if sub else None, sub), "cuenta": account_labels.get(src, src), "producto": _text(sid), "monto": 0.0, "detalle": f"{count} cobros aceptados en {month}"})
    alert_counts["Cobro múltiple en el mes"] = len(multiples)
    alerts.extend(multiples[:80])

    # 5. Cliente con múltiples activas (baja)
    client_active_map: dict[tuple[str, str], list[Subscription]] = defaultdict(list)
    for sub in active_at_end:
        client_active_map[(sub.source, sub.client_external_id or "")].append(sub)
    multi_activas: list[dict[str, Any]] = []
    for (src, cid), subs in client_active_map.items():
        if len(subs) >= 2:
            multi_activas.append({"sev": "baja", "tipo": "Cliente con múltiples activas", "cliente": _cname(src, cid), "cuenta": account_labels.get(src, src), "producto": _text(", ".join(s.external_id or "" for s in subs[:3])), "monto": 0.0, "detalle": f"{len(subs)} suscripciones activas simultáneas"})
    alert_counts["Cliente con múltiples activas"] = len(multi_activas)
    alerts.extend(multi_activas[:50])

    total_revenue = round(sum(_amount(charge.amount) for charge in paid_charges), 2)
    total_attempts = len(paid_charges) + len(rejected_charges)
    return {
        "kpis": {"total_subs": len(historical_subscriptions), "n_activas": len(active_at_end), "total_clientes": len(clients_at_end), "total_recaudado": total_revenue, "total_comision": 0, "total_abono": total_revenue, "cobrabilidad": round(100 * len(paid_charges) / total_attempts, 1) if total_attempts else 0, "vida_prom": vida_prom_val, "vida_prom_activas": vida_prom_activas_val, "recaud_prom_sub": round(total_revenue / len(historical_subscriptions), 0) if historical_subscriptions else 0, "recaud_prom_activa": round(total_revenue / len(active_at_end), 0) if active_at_end else 0, "churn_prom": round(sum(churn) / len(churn), 2) if churn else 0, "total_cargos": len(charges), "cargos_pag": len(paid_charges), "cargos_rec": len(rejected_charges), "ticket_prom": round(total_revenue / len(paid_charges), 0) if paid_charges else 0, "pct_comision": 0},
        "meses": months, "altas": altas, "bajas": bajas, "activas_acum": active_count_by_month, "churn": churn, "deu_pag": deu_pag, "deu_nop": deu_nop, "int_ok": int_ok, "int_fail": int_fail, "cg_can": cg_can, "cg_pro": cg_pro, "rec_mes": rec_mes, "com_mes": [0] * len(months), "pagos_mes": pagos_mes,
        "estado_dist": {"ACTIVA": len(active_at_end), "CANCELADA": len(historical_subscriptions) - len(active_at_end)}, "rec_cuenta": account_revenue, "subs_cuenta": account_subscriptions, "alertas_resumen": alert_counts, "n_alertas": sum(alert_counts.values()), "alertas": alerts, "tabla_activas": active_table[:200],
    }


def _snapshot(db: Session, scope: str) -> dict[str, Any]:
    if scope == "general":
        return staging._general_dashboard(db)
    if scope == "virtualpos":
        return staging._vp_centralized_dashboard(scope, db)
    if scope == "toku":
        return staging._toku_centralized_dashboard(db)
    if scope == "payku":
        return staging._payku_centralized_dashboard(db)
    return tch.tch_summary()


def _virtualpos_report_html(start: date, end: date, data: dict[str, Any]) -> str:
    template_path = Path(__file__).resolve().parents[4] / "docs" / "ReporteEjemplo_VirtualPOS.html"
    template = template_path.read_text(encoding="utf-8")
    payload = json.dumps(data, default=str).replace("</", "<\\/")
    template, replacements = re.subn(
        r"const D = .*?;\nconst fmt",
        lambda _: f"const D = {payload};\nconst fmt",
        template,
        flags=re.DOTALL,
    )
    if replacements != 1:
        raise RuntimeError("VirtualPOS report template has an invalid data placeholder")
    template = re.sub(
        r'<div class="sub">.*?</div>',
        f'<div class="sub">Operación consolidada · datos locales · período analizado: {start.isoformat()} a {end.isoformat()}</div>',
        template,
        count=1,
    )
    template = template.replace("Actualizado 2026-08-09", f"Generado {datetime.now(UTC).astimezone():%Y-%m-%d %H:%M}")
    template = template.replace(
        "{lbl:'Comisión VirtualPOS',val:clp(k.total_comision),hint:k.pct_comision+'% del bruto',cls:'red'},",
        "{lbl:'Comisión VirtualPOS',val:'No disponible',hint:'No existe en los datos locales',cls:'red'},",
    )
    template = template.replace(
        "</header>",
        '<button onclick="downloadReport()">Descargar HTML</button></header>',
        1,
    )
    download_script = f"""
function downloadReport(){{const blob=new Blob([document.documentElement.outerHTML],{{type:'text/html'}});const link=document.createElement('a');link.href=URL.createObjectURL(blob);link.download='reporte-virtualpos-{start.isoformat()}-{end.isoformat()}.html';link.click();URL.revokeObjectURL(link.href);}}
"""
    return template.replace("</script>", f"{download_script}</script>", 1)


def _generic_alerts(scope: str, snapshot: dict[str, Any], series: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Derive alerts from series data — no extra DB queries."""
    alerts: list[dict[str, Any]] = []

    # 1. Alta tasa de rechazo por mes
    charge_by_month: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "fail": 0})
    for entry in series.get("charges", []):
        key = f"{entry['year']}-{int(entry['month']):02d}"
        st = str(entry.get("status", "")).lower()
        if any(w in st for w in ("aceptad", "pagad", "accepted", "paid")):
            charge_by_month[key]["ok"] += int(entry.get("count", 0))
        elif any(w in st for w in ("rechazad", "rejected", "fail")):
            charge_by_month[key]["fail"] += int(entry.get("count", 0))
    for month, counts in sorted(charge_by_month.items()):
        total = counts["ok"] + counts["fail"]
        if total > 0:
            rate = 100 * counts["fail"] / total
            if rate > 30:
                alerts.append({"sev": "alta" if rate > 50 else "media", "tipo": "Alta tasa de rechazo", "detalle": f"{month}: {rate:.0f}% de rechazos ({counts['fail']} de {total} cargos)"})

    # 2. Declive: meses donde bajas > altas
    act_by_month: dict[str, int] = defaultdict(int)
    can_by_month: dict[str, int] = defaultdict(int)
    for entry in series.get("activations", []):
        act_by_month[f"{entry['year']}-{int(entry['month']):02d}"] += int(entry.get("count", 0))
    for entry in series.get("cancellations", []):
        can_by_month[f"{entry['year']}-{int(entry['month']):02d}"] += int(entry.get("count", 0))
    all_months = sorted(set(act_by_month) | set(can_by_month))
    for month in all_months:
        altas = act_by_month[month]
        bajas = can_by_month[month]
        if bajas > altas and bajas > 0:
            alerts.append({"sev": "media", "tipo": "Saldo negativo de suscripciones", "detalle": f"{month}: {bajas} bajas vs {altas} altas"})

    # 3. Tasa de rechazo global del período
    total_ok = sum(v["ok"] for v in charge_by_month.values())
    total_fail = sum(v["fail"] for v in charge_by_month.values())
    total_all = total_ok + total_fail
    if total_all > 0:
        global_rate = 100 * total_fail / total_all
        if global_rate > 35:
            alerts.insert(0, {"sev": "alta" if global_rate > 50 else "media", "tipo": "Tasa de rechazo global elevada", "detalle": f"Período completo: {global_rate:.1f}% de rechazos ({total_fail} de {total_all} cargos)"})

    if scope == "tch":
        tasa = snapshot.get("tasa_rechazo", 0)
        if isinstance(tasa, (int, float)) and tasa > 15:
            alerts.insert(0, {"sev": "alta" if tasa > 30 else "media", "tipo": "Tasa de rechazo operacional", "detalle": f"Tasa histórica global: {tasa}% — supera umbral de alerta"})
    return alerts


def _report_html(scope: str, start: date, end: date, snapshot: dict[str, Any], series: dict[str, list[dict[str, Any]]]) -> str:
    alerts = _generic_alerts(scope, snapshot, series)
    payload = json.dumps({"snapshot": snapshot, "series": series, "alerts": alerts}, default=str).replace("</", "<\\/")
    label = html.escape(_LABELS[scope])
    generated = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M")
    css = (
        ":root{--bg:#0d1117;--card:#161b22;--card2:#1c2230;--border:#2b3140;--txt:#e6edf3;--muted:#8b949e;"
        "--accent:#3b82f6;--green:#22c55e;--red:#ef4444;--amber:#f59e0b;--purple:#a855f7;--cyan:#06b6d4}"
        "body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--txt);padding:24px;line-height:1.4;margin:0}"
        "main{max-width:1200px;margin:auto}"
        "header{display:flex;justify-content:space-between;align-items:start;gap:16px;padding-bottom:24px;"
        "border-bottom:1px solid var(--border);margin-bottom:24px}"
        "h1{margin:0;font-size:24px}.sub{color:var(--muted);font-size:13px;margin:4px 0 0}"
        "button{padding:9px 14px;background:var(--card);border:1px solid var(--border);border-radius:8px;"
        "color:var(--txt);cursor:pointer;font-size:13px}button:hover{border-color:var(--accent)}"
        ".kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-bottom:28px}"
        ".kpi{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px 18px;"
        "position:relative;overflow:hidden}"
        ".kpi::before{content:'';position:absolute;top:0;left:0;width:3px;height:100%}"
        ".kpi.green::before{background:var(--green)}.kpi.blue::before{background:var(--accent)}"
        ".kpi.amber::before{background:var(--amber)}.kpi.red::before{background:var(--red)}"
        ".kpi.purple::before{background:var(--purple)}.kpi.cyan::before{background:var(--cyan)}"
        ".kpi-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px}"
        ".kpi-value{font-size:26px;font-weight:700;line-height:1}.kpi-hint{font-size:11px;color:var(--muted);margin-top:4px}"
        ".charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:16px;margin-bottom:28px}"
        ".card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px}"
        ".card h3{margin:0 0 16px;font-size:14px;font-weight:600}"
        ".chart-box{height:260px;position:relative}"
        ".sec{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin:28px 0 12px;font-weight:600}"
        ".alerts-grid{display:flex;flex-direction:column;gap:8px}"
        ".alert-row{background:var(--card2);border:1px solid var(--border);border-left:3px solid var(--amber);"
        "border-radius:8px;padding:10px 14px;font-size:13px;display:flex;gap:12px;align-items:center}"
        ".alert-row.alta{border-left-color:var(--red)}.alert-row.baja{border-left-color:var(--muted)}"
        ".sev{font-size:10px;text-transform:uppercase;letter-spacing:.3px;font-weight:700;padding:2px 6px;"
        "border-radius:4px;white-space:nowrap}"
        ".sev-alta{background:rgba(239,68,68,.15);color:var(--red)}"
        ".sev-media{background:rgba(245,158,11,.15);color:var(--amber)}"
        ".sev-baja{background:rgba(139,148,158,.15);color:var(--muted)}"
        ".foot{color:var(--muted);font-size:12px;margin-top:32px;padding-top:16px;border-top:1px solid var(--border)}"
        "@media print{body{background:white;color:#172033}button{display:none}.card,.kpi{border:1px solid #e2e8f0;background:white}}"
    )
    js = (
        f"const D={payload};\n"
        "const C={mut:'#8b949e',grid:'rgba(43,49,64,.6)',accent:'#3b82f6',green:'#22c55e',"
        "red:'#ef4444',amber:'#f59e0b',purple:'#a855f7',cyan:'#06b6d4'};\n"
        "Chart.defaults.color=C.mut;Chart.defaults.borderColor=C.grid;\n"
        "const money=n=>'$'+Math.round(Number(n||0)).toLocaleString('es-CL');\n"
        "const fmt=n=>Number(n||0).toLocaleString('es-CL');\n"
        "const s=D.snapshot;\n"
        "const tr=s.transactions||s.transacciones||{};\n"
        "const subs=s.subscriptions||s.suscripciones||{};\n"
        "const active=s.total_vigentes??subs.active??subs.vigentes??s.kpis?.active_subscribers??0;\n"
        "const clientes=s.clients??s.clientes??'—';\n"
        "const recaudado=tr.amount??tr.monto??s.total_recaudado??0;\n"
        "const aceptadas=s.total_aceptadas??tr.accepted??tr.aceptadas??0;\n"
        "const rechazadas=s.total_rechazadas??tr.rejected??tr.rechazadas??0;\n"
        "const tasa_r=(s.tasa_rechazo??0);\n"
        "const kpiCards=[\n"
        "  {cls:'green',lbl:'Suscripciones activas',val:fmt(active),hint:'al cierre del período'},\n"
        "  {cls:'blue', lbl:'Clientes',             val:fmt(clientes),hint:'registrados'},\n"
        "  {cls:'green',lbl:'Total recaudado',       val:money(recaudado),hint:fmt(aceptadas)+' cargos pagados'},\n"
        "  {cls:'red',  lbl:'Rechazadas',            val:fmt(rechazadas),hint:'intentos fallidos'},\n"
        "  {cls:'amber',lbl:'Tasa de rechazo',       val:tasa_r+'%',hint:'rechazadas / total'},\n"
        "  ...(s.kpis?[\n"
        "    {cls:'purple',lbl:'MRR',  val:money(s.kpis.mrr||0),       hint:'ingreso mensual recurrente'},\n"
        "    {cls:'cyan',  lbl:'ARPU', val:money(s.kpis.arpu||0),      hint:'ingreso prom. por activo'},\n"
        "    {cls:'red',   lbl:'Churn',val:(s.kpis.churn_rate||0)+'%', hint:'mensual promedio'},\n"
        "  ]:[]),\n"
        "];\n"
        "document.getElementById('kpis').innerHTML=kpiCards.map(c=>"
        "`<article class=\"kpi ${c.cls}\"><div class=\"kpi-label\">${c.lbl}</div>"
        "<div class=\"kpi-value\">${c.val}</div><div class=\"kpi-hint\">${c.hint}</div></article>`"
        ").join('');\n"
        "const MONTHS=['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];\n"
        "const PAL=[C.accent,C.green,C.red,C.amber,C.purple,C.cyan];\n"
        "function mkChart(title,rows,id,type='bar'){\n"
        "  const box=document.createElement('article');box.className='card';\n"
        "  box.innerHTML=`<h3>${title}</h3><div class=\"chart-box\"><canvas id=\"${id}\"></canvas></div>`;\n"
        "  document.getElementById('charts').append(box);\n"
        "  const keys=[...new Set(rows.map(r=>`${r.year}-${String(r.month).padStart(2,'0')}`)  )].sort();\n"
        "  const states=[...new Set(rows.map(r=>r.status))];\n"
        "  new Chart(document.getElementById(id),{\n"
        "    type,data:{labels:keys.map(x=>MONTHS[Number(x.slice(5))-1]+' '+x.slice(2,4)),\n"
        "    datasets:states.map((st,i)=>{\n"
        "      const col=PAL[i%PAL.length];\n"
        "      return {label:st,data:keys.map(k=>"
        "rows.filter(r=>`${r.year}-${String(r.month).padStart(2,'0')}`===k&&r.status===st)"
        ".reduce((a,r)=>a+r.count,0)),"
        "backgroundColor:type==='line'?col+'22':col,borderColor:col,"
        "borderWidth:type==='line'?2:0,fill:type==='line',tension:.3,pointRadius:2};\n"
        "    })},\n"
        "    options:{responsive:true,maintainAspectRatio:false,"
        "plugins:{legend:{labels:{boxWidth:12,font:{size:11}}}},"
        "scales:{x:{grid:{color:C.grid}},y:{grid:{color:C.grid}}}}\n"
        "  });\n"
        "}\n"
        "if(D.series.transactions?.length)  mkChart('Transacciones por estado',D.series.transactions,'txChart');\n"
        "if(D.series.activations?.length)   mkChart('Altas de suscripciones',D.series.activations,'actChart','line');\n"
        "if(D.series.cancellations?.length) mkChart('Bajas de suscripciones',D.series.cancellations,'canChart','line');\n"
        "if(D.series.charges?.length)       mkChart('Cargos por estado',D.series.charges,'chgChart');\n"
        "const alPeriod=D.alerts||[];\n"
        "if(alPeriod.length){\n"
        "  document.getElementById('alertsTitle').style.display='';\n"
        "  document.getElementById('alertsGrid').innerHTML=alPeriod.map(a=>"
        "`<div class=\"alert-row ${a.sev}\"><span class=\"sev sev-${a.sev}\">${a.sev}</span>"
        "<strong style=\"min-width:200px\">${a.tipo}</strong>"
        "<span style=\"color:var(--muted)\">${a.detalle}</span></div>`"
        ").join('');\n"
        "}\n"
        f"function downloadReport(){{const blob=new Blob([document.documentElement.outerHTML],"
        f"{{type:'text/html'}});const a=document.createElement('a');"
        f"a.href=URL.createObjectURL(blob);"
        f"a.download='reporte-{scope}-{start.isoformat()}-{end.isoformat()}.html';"
        f"a.click();URL.revokeObjectURL(a.href);}}\n"
    )
    return (
        f'<!doctype html><html lang="es"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Reporte operativo · {label}</title>'
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>'
        f'<style>{css}</style></head><body><main>'
        '<header><div>'
        '<p style="color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin:0 0 4px">'
        'REPORTE OPERATIVO</p>'
        f'<h1>{label}</h1>'
        f'<p class="sub">Período analizado: {start.isoformat()} → {end.isoformat()}</p>'
        '</div><button onclick="downloadReport()">Descargar HTML</button></header>'
        '<section class="kpis" id="kpis"></section>'
        '<p class="sec">Series del período</p>'
        '<section class="charts" id="charts"></section>'
        '<p class="sec" id="alertsTitle" style="display:none">Alertas del período</p>'
        '<section class="alerts-grid" id="alertsGrid"></section>'
        f'<p class="foot">Generado: {generated} · Fuente: base de datos local CRM.</p>'
        f'</main><script>{js}</script></body></html>'
    )


@router.get("/{scope}", response_class=HTMLResponse, tags=["Reports"])
def operational_report(
    scope: str,
    date_from: str = Query(...),
    date_to: str = Query(...),
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> HTMLResponse:
    if scope not in _SCOPES:
        raise HTTPException(status_code=404, detail="Unknown report scope")
    start = _parse_date(date_from, "date_from")
    end = _parse_date(date_to, "date_to")
    if start >= end:
        raise HTTPException(status_code=422, detail="date_from must be earlier than date_to")
    _require_report_access(current_user, scope)
    if scope == "virtualpos":
        return HTMLResponse(_virtualpos_report_html(start, end, _virtualpos_report_data(db, start, end)))
    return HTMLResponse(_report_html(scope, start, end, _snapshot(db, scope), _series(db, scope, start, end)))
