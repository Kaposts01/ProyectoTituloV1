import re
from collections import Counter, defaultdict
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Numeric, String, and_, case, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_csrf, require_permissions
from app.db.session import SessionLocal
from app.models.auth import User
from app.models.crm import Charge as CCharge
from app.models.crm import Client as CClient
from app.models.crm import Payment as CPayment
from app.models.crm import PaymentMethod as CPaymentMethod
from app.models.crm import Plan as CPlan
from app.models.crm import Subscription as CSub
from app.models.source_record import SourceRecord
from app.models.sync_run import SyncRun
from app.models.tch import (
    TchCliente,
    TchRecaudacionMensual,
    TchSuscripcion,
    TchTransaccion,
)
from app.services.channel_consolidation import consolidate_to_canonical
from app.services.payku_sync import sync_payku
from app.services.rbac import permission_codes, source_permission
from app.services.toku_sync import sync_toku
from app.services.virtualpos_sync import sync_virtualpos

router = APIRouter()
SOURCES = ("virtualpos", "toku", "payku")
PaginationOffset = Annotated[int, Query(ge=0)]
PaginationLimit = Annotated[int, Query(ge=1, le=100)]
ACTIVITY_FIELDS = {
    "virtualpos": ("payment", ("order", "authorized_at"), ("order", "amount"), ("order", "status")),
    "toku": ("invoice", ("due_date",), ("amount",), ("status",)),
    "payku": ("transaction", ("created_at",), ("amount",), ("status",)),
}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _serialize(record: SourceRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "source": record.source,
        "resource_type": record.resource_type,
        "external_id": record.external_id,
        "payload": record.payload,
        "sync_context": record.sync_context,
        "first_seen_at": record.first_seen_at,
        "last_seen_at": record.last_seen_at,
    }


def _payload_value(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _amount(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _month(value: Any) -> tuple[int, int] | None:
    match = re.match(r"(\d{4})-(\d{2})", str(value or ""))
    if not match:
        return None
    year, month = (int(part) for part in match.groups())
    return (year, month) if 1 <= month <= 12 else None


def _general_transaction_status(status: Any) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"pagado", "pago", "aceptado", "accepted", "paid", "success", "aprobada", "aceptada"}:
        return "Aceptadas"
    if normalized in {"rechazado", "rejected", "failed", "failure", "declined", "error", "rechazada"}:
        return "Rechazadas"
    return "Pendientes"


def _general_dashboard(db: Session) -> dict[str, Any]:
    amount = case(
        (CPayment.amount.op("~")(r"^\d+(\.\d+)?$"), cast(CPayment.amount, Numeric)),
        else_=0,
    )
    tch_amount = case(
        (TchTransaccion.monto.op("~")(r"^\d+(\.\d+)?$"), cast(TchTransaccion.monto, Numeric)),
        else_=0,
    )
    subscription_amount = case(
        (CSub.amount.op("~")(r"^\d+(\.\d+)?$"), cast(CSub.amount, Numeric)),
        else_=0,
    )
    tch_subscription_amount = case(
        (TchSuscripcion.monto.op("~")(r"^\d+(\.\d+)?$"), cast(TchSuscripcion.monto, Numeric)),
        else_=0,
    )
    payment_period = func.substring(CPayment.payment_date, 1, 7)
    subscription_period = func.substring(CSub.suscription_date, 1, 7)
    tch_subscription_period = func.substring(TchSuscripcion.fecha_activacion, 1, 7)

    chargeable_subscription_ids = {
        subscription_id
        for method in db.scalars(
            select(CPaymentMethod).where(
                CPaymentMethod.source == "toku", func.lower(CPaymentMethod.status) == "chargeable"
            )
        )
        for subscription_id in _toku_subscription_ids(method)
    }

    active_subscriptions = {
        "virtualpos": db.scalar(
            select(func.count()).select_from(CSub).where(
                CSub.source.in_(_VP_SRCS), func.lower(CSub.status) == "activa"
            )
        ) or 0,
        "toku": (
            db.scalar(
                select(func.count()).select_from(CSub).where(
                    CSub.source == "toku",
                    func.lower(CSub.status) == "active",
                    CSub.external_id.in_(chargeable_subscription_ids),
                )
            )
            if chargeable_subscription_ids
            else 0
        ) or 0,
        "payku": db.scalar(
            select(func.count()).select_from(CSub).where(
                CSub.source == "payku", func.lower(CSub.status) == "active"
            )
        ) or 0,
        "tch": db.scalar(
            select(func.count()).select_from(TchSuscripcion).where(TchSuscripcion.estado == "VIGENTE")
        ) or 0,
    }
    tch_equivalente_vigente = case(
        (TchSuscripcion.equivalente_pesos.op("~")(r"^\d+(\.\d+)?$"), cast(TchSuscripcion.equivalente_pesos, Numeric)),
        else_=0,
    )
    sub_amounts = {
        "virtualpos": float(db.scalar(
            select(func.coalesce(func.sum(subscription_amount), 0))
            .select_from(CSub)
            .where(CSub.source.in_(_VP_SRCS), func.lower(CSub.status) == "activa")
        ) or 0),
        "toku": (float(db.scalar(
            select(func.coalesce(func.sum(subscription_amount), 0))
            .select_from(CSub)
            .where(CSub.source == "toku", func.lower(CSub.status) == "active",
                   CSub.external_id.in_(chargeable_subscription_ids))
        ) or 0) if chargeable_subscription_ids else 0.0),
        "payku": float(db.scalar(
            select(func.coalesce(func.sum(subscription_amount), 0))
            .select_from(CSub)
            .where(CSub.source == "payku", func.lower(CSub.status) == "active")
        ) or 0),
        "tch": float(db.scalar(
            select(func.coalesce(func.sum(tch_equivalente_vigente), 0))
            .select_from(TchSuscripcion)
            .where(TchSuscripcion.estado == "VIGENTE")
        ) or 0),
    }
    clients = {
        "virtualpos": db.scalar(select(func.count()).select_from(CClient).where(CClient.source.in_(_VP_SRCS))) or 0,
        "toku": db.scalar(select(func.count()).select_from(CClient).where(CClient.source == "toku")) or 0,
        "payku": db.scalar(select(func.count()).select_from(CClient).where(CClient.source == "payku")) or 0,
        "tch": db.scalar(select(func.count()).select_from(TchCliente)) or 0,
    }
    totals: Counter[str] = Counter()
    amounts: defaultdict[str, float] = defaultdict(float)
    by_source: dict[str, Counter[str]] = defaultdict(Counter)
    transaction_months: defaultdict[tuple[int, int, str], dict[str, float]] = defaultdict(
        lambda: {"count": 0, "amount": 0}
    )
    source_labels = {"virtualpos": "VirtualPOS", "virtualpos1": "VirtualPOS", "virtualpos2": "VirtualPOS", "toku": "Toku", "payku": "Payku", "tch": "TCH"}

    online_rows = db.execute(
        select(CPayment.source, CPayment.status, func.count(), func.coalesce(func.sum(amount), 0))
        .where(CPayment.source.in_((*_VP_SRCS, "toku", "payku")))
        .group_by(CPayment.source, CPayment.status)
    ).all()
    tch_controls = db.scalars(select(TchRecaudacionMensual)).all()
    tch_rows = (
        [
            ("ACEPTADA", control.aceptadas_cantidad, control.aceptadas_monto)
            for control in tch_controls
        ] + [
            ("RECHAZADA", control.rechazadas_cantidad, control.rechazadas_monto)
            for control in tch_controls
        ]
        if tch_controls
        else db.execute(
            select(TchTransaccion.estado, func.count(), func.coalesce(func.sum(tch_amount), 0)).group_by(TchTransaccion.estado)
        ).all()
    )
    for source, status, count, total_amount in online_rows:
        label = source_labels[source]
        outcome = _general_transaction_status(status)
        totals[outcome] += count
        by_source[label][outcome] += count
        if outcome == "Aceptadas":
            amounts[label] += _amount(total_amount)
    for status, count, total_amount in tch_rows:
        outcome = _general_transaction_status(status)
        totals[outcome] += count
        by_source["TCH"][outcome] += count
        if outcome == "Aceptadas":
            amounts["TCH"] += _amount(total_amount)

    online_months = db.execute(
        select(CPayment.source, payment_period, CPayment.status, func.count(), func.coalesce(func.sum(amount), 0))
        .where(CPayment.source.in_((*_VP_SRCS, "toku", "payku")), CPayment.payment_date.op("~")(r"^\d{4}-\d{2}"))
        .group_by(CPayment.source, payment_period, CPayment.status)
    ).all()
    tch_months = (
        [
            (control.periodo, "ACEPTADA", control.aceptadas_cantidad, control.aceptadas_monto)
            for control in tch_controls
        ] + [
            (control.periodo, "RECHAZADA", control.rechazadas_cantidad, control.rechazadas_monto)
            for control in tch_controls
        ]
        if tch_controls
        else db.execute(
            select(TchTransaccion.periodo, TchTransaccion.estado, func.count(), func.coalesce(func.sum(tch_amount), 0))
            .where(TchTransaccion.periodo.op("~")(r"^\d{4}-\d{2}$"))
            .group_by(TchTransaccion.periodo, TchTransaccion.estado)
        ).all()
    )
    for source, period, status, count, total_amount in online_months:
        month = _month(period)
        if month:
            bucket = transaction_months[(*month, _general_transaction_status(status))]
            bucket["count"] += count
            if _general_transaction_status(status) == "Aceptadas":
                bucket["amount"] += _amount(total_amount)
    for period, status, count, total_amount in tch_months:
        month = _month(period)
        if month:
            bucket = transaction_months[(*month, _general_transaction_status(status))]
            bucket["count"] += count
            if _general_transaction_status(status) == "Aceptadas":
                bucket["amount"] += _amount(total_amount)

    activation_months: defaultdict[tuple[int, int, str], dict[str, float]] = defaultdict(lambda: {"count": 0, "amount": 0})
    online_activations = db.execute(
        select(CSub.source, subscription_period, func.count(), func.coalesce(func.sum(subscription_amount), 0))
        .where(CSub.source.in_((*_VP_SRCS, "toku", "payku")), CSub.suscription_date.op("~")(r"^\d{4}-\d{2}"))
        .group_by(CSub.source, subscription_period)
    ).all()
    tch_activations = db.execute(
        select(tch_subscription_period, func.count(), func.coalesce(func.sum(tch_subscription_amount), 0))
        .where(TchSuscripcion.fecha_activacion.op("~")(r"^\d{4}-\d{2}"))
        .group_by(tch_subscription_period)
    ).all()
    for source, period, count, total_amount in online_activations:
        month = _month(period)
        if month:
            bucket = activation_months[(*month, source_labels[source])]
            bucket["count"] += count
            bucket["amount"] += _amount(total_amount)
    for period, count, total_amount in tch_activations:
        month = _month(period)
        if month:
            bucket = activation_months[(*month, "TCH")]
            bucket["count"] += count
            bucket["amount"] += _amount(total_amount)

    cancellation_period_col = func.substring(CSub.canceled_at, 1, 7)
    tch_cancellation_period_col = func.substring(TchSuscripcion.fecha_eliminacion, 1, 7)
    cancellation_months: defaultdict[tuple[int, int, str], dict[str, float]] = defaultdict(lambda: {"count": 0, "amount": 0})
    online_cancellations = db.execute(
        select(CSub.source, cancellation_period_col, func.count(), func.coalesce(func.sum(subscription_amount), 0))
        .where(CSub.source.in_((*_VP_SRCS, "toku", "payku")), CSub.canceled_at.op("~")(r"^\d{4}-\d{2}"))
        .group_by(CSub.source, cancellation_period_col)
    ).all()
    tch_cancellations = db.execute(
        select(tch_cancellation_period_col, func.count(), func.coalesce(func.sum(tch_equivalente_vigente), 0))
        .where(TchSuscripcion.fecha_eliminacion.op("~")(r"^\d{4}-\d{2}"))
        .group_by(tch_cancellation_period_col)
    ).all()
    for source, period, count, total_amount in online_cancellations:
        month = _month(period)
        if month:
            bucket = cancellation_months[(*month, source_labels[source])]
            bucket["count"] += count
            bucket["amount"] += _amount(total_amount)
    for period, count, total_amount in tch_cancellations:
        month = _month(period)
        if month:
            bucket = cancellation_months[(*month, "TCH")]
            bucket["count"] += count
            bucket["amount"] += _amount(total_amount)

    # ── Deudas mensuales por canal (CCharge) ─────────────────────────────
    charge_amount = case(
        (CCharge.amount.op("~")(r"^\d+(\.\d+)?$"), cast(CCharge.amount, Numeric)),
        else_=0,
    )
    charge_period_col = func.substring(CCharge.charge_date, 1, 7)
    # key = (year, month, channel, "pagada"|"rechazada")
    charge_months: defaultdict[tuple[int, int, str, str], dict[str, float]] = defaultdict(lambda: {"count": 0, "amount": 0})

    for source, period, raw_status, count, total_amount in db.execute(
        select(CCharge.source, charge_period_col, CCharge.status, func.count(), func.coalesce(func.sum(charge_amount), 0))
        .where(CCharge.source.in_((*_VP_SRCS, "toku", "payku")), CCharge.charge_date.op("~")(r"^\d{4}-\d{2}"))
        .group_by(CCharge.source, charge_period_col, CCharge.status)
    ).all():
        month = _month(period)
        if month:
            cs = "pagada" if _general_transaction_status(raw_status) == "Aceptadas" else "rechazada"
            charge_months[(*month, source_labels[source], cs)]["count"] += count
            charge_months[(*month, source_labels[source], cs)]["amount"] += _amount(total_amount)

    if tch_controls:
        for control in tch_controls:
            month = _month(control.periodo)
            if month:
                charge_months[(*month, "TCH", "pagada")]["count"] += control.aceptadas_cantidad
                charge_months[(*month, "TCH", "pagada")]["amount"] += _amount(control.aceptadas_monto)
                charge_months[(*month, "TCH", "rechazada")]["count"] += control.rechazadas_cantidad
                charge_months[(*month, "TCH", "rechazada")]["amount"] += _amount(control.rechazadas_monto)
    else:
        for period, raw_status, count, total_amount in tch_months:
            month = _month(period)
            if month:
                cs = "pagada" if _general_transaction_status(raw_status) == "Aceptadas" else "rechazada"
                charge_months[(*month, "TCH", cs)]["count"] += count
                charge_months[(*month, "TCH", cs)]["amount"] += _amount(total_amount)

    # ── Transacciones mensuales por canal (CPayment todas) ────────────────
    payment_months: defaultdict[tuple[int, int, str, str], dict[str, float]] = defaultdict(lambda: {"count": 0, "amount": 0})

    for source, period, raw_status, count, total_amount in online_months:
        outcome = _general_transaction_status(raw_status)
        if outcome in ("Aceptadas", "Rechazadas"):
            month = _month(period)
            if month:
                cs = "pagada" if outcome == "Aceptadas" else "rechazada"
                payment_months[(*month, source_labels[source], cs)]["count"] += count
                payment_months[(*month, source_labels[source], cs)]["amount"] += _amount(total_amount)

    if tch_controls:
        for control in tch_controls:
            month = _month(control.periodo)
            if month:
                payment_months[(*month, "TCH", "pagada")]["count"] += control.aceptadas_cantidad
                payment_months[(*month, "TCH", "pagada")]["amount"] += _amount(control.aceptadas_monto)
                payment_months[(*month, "TCH", "rechazada")]["count"] += control.rechazadas_cantidad
                payment_months[(*month, "TCH", "rechazada")]["amount"] += _amount(control.rechazadas_monto)
    else:
        for period, raw_status, count, total_amount in tch_months:
            outcome = _general_transaction_status(raw_status)
            if outcome in ("Aceptadas", "Rechazadas"):
                month = _month(period)
                if month:
                    cs = "pagada" if outcome == "Aceptadas" else "rechazada"
                    payment_months[(*month, "TCH", cs)]["count"] += count
                    payment_months[(*month, "TCH", cs)]["amount"] += _amount(total_amount)

    debts_monthly = [
        {"year": y, "month": m, "status": ch, "charge_status": cs, "count": int(v["count"]), "amount": round(v["amount"], 2)}
        for (y, m, ch, cs), v in sorted(charge_months.items())
    ]
    transactions_effective_monthly = [
        {"year": y, "month": m, "status": ch, "charge_status": cs, "count": int(v["count"]), "amount": round(v["amount"], 2)}
        for (y, m, ch, cs), v in sorted(payment_months.items())
    ]

    transactions_monthly = [
        {"year": year, "month": month, "status": status, "count": int(values["count"]), "amount": round(values["amount"], 2)}
        for (year, month, status), values in sorted(transaction_months.items())
    ]
    activations_monthly = [
        {"year": year, "month": month, "status": source, "count": int(values["count"]), "amount": round(values["amount"], 2)}
        for (year, month, source), values in sorted(activation_months.items())
    ]
    cancellations_monthly = [
        {"year": year, "month": month, "status": source, "count": int(values["count"]), "amount": round(values["amount"], 2)}
        for (year, month, source), values in sorted(cancellation_months.items())
    ]
    transaction_total = sum(totals.values())
    return {
        "clients": sum(clients.values()),
        "subscriptions": {"active": sum(active_subscriptions.values()), "amount": round(sum(sub_amounts.values()), 0)},
        "transactions": {
            "total": transaction_total,
            "accepted": totals["Aceptadas"],
            "rejected": totals["Rechazadas"],
            "amount": round(sum(amounts.values()), 2),
            "rejection_rate_pct": round(100 * totals["Rechazadas"] / transaction_total, 1) if transaction_total else 0,
        },
        "channels": [
            {"source": label, "clients": clients[key], "active_subscriptions": active_subscriptions[key], "accepted": by_source[label]["Aceptadas"], "amount": round(amounts[label], 2)}
            for key, label in (("virtualpos", "VirtualPOS"), ("toku", "Toku"), ("payku", "Payku"), ("tch", "TCH"))
        ],
        "years": sorted({entry["year"] for entry in transactions_monthly + activations_monthly + cancellations_monthly + debts_monthly + transactions_effective_monthly}, reverse=True),
        "transactions_monthly": transactions_monthly,
        "activations_monthly": activations_monthly,
        "cancellations_monthly": cancellations_monthly,
        "debts_monthly": debts_monthly,
        "transactions_effective_monthly": transactions_effective_monthly,
    }


def _rut_key(value: Any) -> str:
    return "".join(character for character in str(value or "").upper() if character.isdigit() or character == "K")


def _portal(source: str) -> str:
    return {"virtualpos": "VirtualPOS", "virtualpos1": "VirtualPOS", "virtualpos2": "VirtualPOS", "toku": "Toku", "payku": "Payku", "tch": "TCH"}[source]


def _general_clients(db: Session, query: str | None = None) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    client_keys: dict[tuple[str, str], str] = {}
    for client in db.scalars(select(CClient).where(CClient.social_id.isnot(None))):
        key = _rut_key(client.social_id)
        if key:
            item = grouped.setdefault(key, {"rut": client.social_id, "name": "", "origins": set(), "active_origins": set()})
            item["name"] = item["name"] or " ".join(part for part in (client.first_name, client.last_name) if part).strip()
            item["origins"].add(_portal(client.source))
            client_keys[(client.source, client.external_id)] = key
    for client in db.scalars(select(TchCliente)):
        key = _rut_key(client.rut)
        if key:
            item = grouped.setdefault(key, {"rut": client.rut, "name": "", "origins": set(), "active_origins": set()})
            item["name"] = item["name"] or " ".join(part for part in (client.nombre, client.apellido) if part).strip()
            item["origins"].add("TCH")
    for subscription in db.scalars(select(CSub)):
        key = _rut_key(subscription.client_social_id) or client_keys.get((subscription.source, subscription.client_external_id or ""))
        if key in grouped and str(subscription.status or "").lower() in {"activa", "active"}:
            grouped[key]["active_origins"].add(_portal(subscription.source))
    for subscription in db.scalars(select(TchSuscripcion).where(TchSuscripcion.estado == "VIGENTE")):
        key = _rut_key(subscription.cliente_rut)
        if key in grouped:
            grouped[key]["active_origins"].add("TCH")
    needle = _rut_key(query) if query else ""
    return sorted((
        {**item, "origins": sorted(item["origins"]), "active_origins": sorted(item["active_origins"])}
        for key, item in grouped.items()
        if not query or needle in key or query.lower() in item["name"].lower()
    ), key=lambda item: (item["name"] or item["rut"]).lower())


def _general_client_detail(db: Session, rut: str) -> dict[str, Any]:
    key = _rut_key(rut)
    clients = [item for item in db.scalars(select(CClient)) if _rut_key(item.social_id) == key]
    tch_clients = [item for item in db.scalars(select(TchCliente)) if _rut_key(item.rut) == key]
    client_ids = {(item.source, item.external_id) for item in clients}
    subscriptions = [item for item in db.scalars(select(CSub)) if _rut_key(item.client_social_id) == key or (item.source, item.client_external_id) in client_ids]
    tch_subscriptions = [item for item in db.scalars(select(TchSuscripcion)) if _rut_key(item.cliente_rut) == key]
    subscription_ids = {(item.source, item.external_id) for item in subscriptions}
    charge_filters = [and_(CCharge.source == source, CCharge.client_external_id == external_id) for source, external_id in client_ids]
    charge_filters += [and_(CCharge.source == source, CCharge.subscription_external_id == external_id) for source, external_id in subscription_ids]
    payment_filters = [and_(CPayment.source == source, CPayment.client_external_id == external_id) for source, external_id in client_ids]
    charges = db.scalars(select(CCharge).where(or_(*charge_filters))).all() if charge_filters else []
    payments = db.scalars(select(CPayment).where(or_(*payment_filters))).all() if payment_filters else []
    fichas = [item.numero_ficha for item in tch_subscriptions]
    tch_transactions = db.scalars(select(TchTransaccion).where(TchTransaccion.numero_ficha.in_(fichas))).all() if fichas else []
    return {"rut": rut, "clients": [{"portal": _portal(item.source), "id_cliente": str(item.id), "external_id": item.external_id} for item in clients] + [{"portal": "TCH", "id_cliente": str(item.id), "external_id": item.rut} for item in tch_clients], "subscriptions": [{"portal": _portal(item.source), "id_subscription": str(item.id), "external_id": item.external_id, "status": item.status} for item in subscriptions] + [{"portal": "TCH", "id_subscription": str(item.id), "external_id": str(item.numero_ficha), "status": item.estado} for item in tch_subscriptions], "charges": [{"portal": _portal(item.source), "id_cargo": str(item.id), "external_id": item.external_id, "status": item.status, "amount": item.amount} for item in charges], "transactions": [{"portal": _portal(item.source), "id_transaccion": str(item.id), "external_id": item.external_id, "status": item.status, "amount": item.amount} for item in payments] + [{"portal": "TCH", "id_transaccion": str(item.id), "external_id": str(item.numero_ficha), "status": item.estado, "amount": item.monto} for item in tch_transactions]}


def _staging_filter(source: str, resource_type: str, filter_field: str, query: str):
    payload = SourceRecord.payload
    fields = {
        "virtualpos": {
            "client": {
                "uuid": func.coalesce(payload["uuid"].astext, SourceRecord.external_id),
                "social_id": payload["social_id"].astext,
                "name": func.concat_ws(" ", payload["first_name"].astext, payload["last_name"].astext),
                "email": payload["email"].astext,
                "phone_number": payload["phone_number"].astext,
                "status": payload["status"].astext,
            },
            "plan": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "name": payload["name"].astext,
                "amount": payload["amount"].astext,
                "automatic_renewal": payload["automatic_renewal"].astext,
                "is_active": payload["is_active"].astext,
                "show_in_terminal": payload["show_in_terminal"].astext,
            },
            "subscription": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "status": payload["status"].astext,
                "social_id": payload["client"]["social_id"].astext,
                "amount": payload["amount"].astext,
                "suscription_date": payload["suscription_date"].astext,
                "canceled_at": payload["canceled_at"].astext,
            },
            "charge": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "status": payload["status"].astext,
                "social_id": payload["client"]["social_id"].astext,
                "amount": payload["amount"].astext,
                "charge_date": payload["charge_date"].astext,
            },
            "payment": {
                "uuid": func.coalesce(payload["order"]["uuid"].astext, SourceRecord.external_id),
                "status": payload["order"]["status"].astext,
                "social_id": payload["client"]["social_id"].astext,
                "amount": payload["order"]["amount"].astext,
                "authorized_at": payload["order"]["authorized_at"].astext,
            },
        },
        "toku": {
            "customer": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "government_id": payload["government_id"].astext,
                "name": payload["name"].astext,
                "mail": func.coalesce(payload["mail"].astext, payload["email"].astext),
                "phone_number": payload["phone_number"].astext,
            },
            "subscription": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "customer": func.coalesce(payload["customer"]["id"].astext, payload["customer"].astext),
                "amount": payload["amount"].astext,
                "status": payload["status"].astext,
                "anchor": payload["anchor"].astext,
                "end_date": payload["end_date"].astext,
            },
            "payment_method": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "status": payload["status"].astext,
                "created_at": payload["created_at"].astext,
                "bank_name": payload["bank_name"].astext,
                "card_type": payload["card_type"].astext,
                "customer_id": payload["customer_id"].astext,
                "external_id": SourceRecord.external_id,
                "subscription_ids": payload["subscription_ids"].astext,
            },
            "invoice": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "customer": func.coalesce(payload["customer"]["id"].astext, payload["customer"].astext),
                "subscription": func.coalesce(payload["subscription"]["id"].astext, payload["subscription"].astext),
                "amount": payload["amount"].astext,
                "is_paid": payload["is_paid"].astext,
                "status": payload["status"].astext,
                "due_date": payload["due_date"].astext,
            },
            "transaction": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "customer_id": payload["customer_id"].astext,
                "subscription_id": payload["subscription_id"].astext,
                "amount": payload["amount"].astext,
                "transaction_date": payload["transaction_date"].astext,
            },
        },
        "payku": {
            "client": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "rut": payload["rut"].astext,
                "name": func.coalesce(func.concat_ws(" ", payload["first_name"].astext, payload["last_name"].astext), payload["name"].astext),
                "email": payload["email"].astext,
                "phone": payload["phone"].astext,
            },
            "plan": {"id": func.coalesce(payload["id"].astext, SourceRecord.external_id), "status": payload["status"].astext, "name": payload["name"].astext},
            "subscription": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "status": payload["status"].astext,
                "rut": payload["client"]["rut"].astext,
                "start": payload["start"].astext,
                "end": payload["end"].astext,
            },
            "transaction": {
                "id": func.coalesce(payload["id"].astext, SourceRecord.external_id),
                "status": payload["status"].astext,
                "subscriptions": payload["subscriptions"].astext,
                "amount": payload["amount"].astext,
                "created_at": payload["created_at"].astext,
            },
        },
    }
    field = fields.get(source, {}).get(resource_type, {}).get(filter_field)
    if field is None:
        raise HTTPException(status_code=422, detail="Invalid staging filter field")
    normalized_query = query.strip().lower()
    if filter_field in {"automatic_renewal", "is_active", "show_in_terminal", "is_paid"}:
        if normalized_query in {"activo", "activa", "true", "t", "1", "si", "sí"}:
            return cast(field, String).ilike("%true%") | cast(field, String).ilike("%t%")
        if normalized_query in {"inactivo", "inactiva", "false", "f", "0", "no"}:
            return cast(field, String).ilike("%false%") | cast(field, String).ilike("%f%")
    return cast(field, String).ilike(f"%{query.strip()}%")


def _record_order(source: str, resource_type: str):
    if source == "virtualpos" and resource_type == "charge":
        return (SourceRecord.payload["charge_date"].astext.desc().nullslast(), SourceRecord.last_seen_at.desc())
    if source == "virtualpos" and resource_type == "payment":
        return (SourceRecord.payload["order"]["authorized_at"].astext.desc().nullslast(), SourceRecord.last_seen_at.desc())
    return (SourceRecord.last_seen_at.desc(),)


def _vp_extended_data(records: list[SourceRecord]) -> dict[str, Any]:
    charges_monthly: dict[tuple[int, int], dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"count": 0.0, "amount": 0.0})
    )
    payments_monthly: dict[tuple[int, int], dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"count": 0.0, "amount": 0.0})
    )
    activation_by_month: dict[tuple[int, int], dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"count": 0.0, "amount": 0.0})
    )
    churn_by_month: dict[tuple[int, int], dict[str, float]] = defaultdict(lambda: {"count": 0.0, "amount": 0.0})
    mrr = 0.0
    active_subs = 0
    active_ruts: set[str] = set()

    for record in records:
        rtype = record.resource_type
        payload = record.payload

        if rtype == "charge":
            month = _month(payload.get("charge_date"))
            if month:
                status = str(payload.get("status", "sin_estado")).upper()
                charges_monthly[month][status]["count"] += 1
                charges_monthly[month][status]["amount"] += _amount(payload.get("amount"))

        elif rtype == "payment":
            month = _month(_payload_value(payload, ("order", "authorized_at")))
            if month:
                status = str(_payload_value(payload, ("order", "status")) or "sin_estado").upper()
                payments_monthly[month][status]["count"] += 1
                payments_monthly[month][status]["amount"] += _amount(_payload_value(payload, ("order", "amount")))

        elif rtype == "subscription":
            status = str(payload.get("status", "")).upper()
            amount = _amount(payload.get("amount"))

            start = payload.get("suscription_date") or payload.get("created")
            month = _month(start)
            if month:
                activation_by_month[month][status or "SIN_ESTADO"]["count"] += 1
                activation_by_month[month][status or "SIN_ESTADO"]["amount"] += amount

            canceled_at = payload.get("canceled_at")
            if canceled_at:
                month = _month(canceled_at)
                if month:
                    churn_by_month[month]["count"] += 1
                    churn_by_month[month]["amount"] += amount

            if status == "ACTIVA":
                mrr += amount
                active_subs += 1
                social_id = (
                    _payload_value(payload, ("client", "social_id"))
                    or payload.get("social_id")
                )
                if social_id:
                    active_ruts.add(str(social_id))

    active_clients = len(active_ruts) or active_subs or 1
    arpu = round(mrr / active_clients, 0) if active_clients else 0.0
    total_subs = sum(1 for r in records if r.resource_type == "subscription")
    total_churned = sum(int(v["count"]) for v in churn_by_month.values())
    churn_rate = round(total_churned / total_subs * 100, 1) if total_subs > 0 else 0.0
    ltv = round(arpu / (churn_rate / 100), 0) if churn_rate > 0 else 0.0

    def _flatten_by_status(data: dict) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for (year, month), statuses in sorted(data.items()):
            for status, vals in sorted(statuses.items()):
                rows.append({
                    "year": year, "month": month, "status": status,
                    "count": int(vals["count"]), "amount": round(vals["amount"], 2),
                })
        return rows

    def _flatten_series(data: dict) -> list[dict[str, Any]]:
        return [
            {"year": year, "month": month, "count": int(vals["count"]), "amount": round(vals["amount"], 2)}
            for (year, month), vals in sorted(data.items())
        ]

    return {
        "kpis": {
            "mrr": round(mrr, 0),
            "active_subscribers": active_subs,
            "active_clients": active_clients,
            "arpu": round(arpu, 0),
            "churn_rate": churn_rate,
            "ltv": round(ltv, 0),
        },
        "charges_monthly": _flatten_by_status(charges_monthly),
        "payments_monthly": _flatten_by_status(payments_monthly),
        "activation_monthly": _flatten_by_status(activation_by_month),
        "churn_monthly": _flatten_series(churn_by_month),
    }


def _toku_extended_data(records: list[SourceRecord]) -> dict[str, Any]:
    invoices_monthly: dict[tuple[int, int], dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"count": 0.0, "amount": 0.0})
    )
    transactions_monthly: dict[tuple[int, int], dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"count": 0.0, "amount": 0.0})
    )
    activation_by_month: dict[tuple[int, int], dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"count": 0.0, "amount": 0.0})
    )
    churn_by_month: dict[tuple[int, int], dict[str, float]] = defaultdict(lambda: {"count": 0.0, "amount": 0.0})
    mrr = 0.0
    active_subs = 0
    active_customers: set[str] = set()

    for record in records:
        rtype = record.resource_type
        payload = record.payload

        if rtype == "invoice":
            month = _month(payload.get("due_date"))
            if month:
                status = str(payload.get("status") or ("PAGADO" if payload.get("is_paid") else "PENDIENTE")).upper()
                invoices_monthly[month][status]["count"] += 1
                invoices_monthly[month][status]["amount"] += _amount(payload.get("amount"))

        elif rtype == "transaction":
            month = _month(payload.get("transaction_date"))
            if month:
                status = str(payload.get("status") or "SIN_ESTADO").upper()
                transactions_monthly[month][status]["count"] += 1
                transactions_monthly[month][status]["amount"] += _amount(payload.get("amount"))

        elif rtype == "subscription":
            status = str(payload.get("status", "")).lower()
            amount = _amount(payload.get("amount"))

            anchor = payload.get("anchor")
            month = _month(anchor)
            if month:
                activation_by_month[month][status.upper() or "SIN_ESTADO"]["count"] += 1
                activation_by_month[month][status.upper() or "SIN_ESTADO"]["amount"] += amount

            end_date = payload.get("end_date")
            if end_date:
                month = _month(end_date)
                if month:
                    churn_by_month[month]["count"] += 1
                    churn_by_month[month]["amount"] += amount

            if status in ("active", "activa", "activo"):
                mrr += amount
                active_subs += 1
                customer = payload.get("customer")
                customer_id = _relationship_id(customer)
                if customer_id:
                    active_customers.add(customer_id)

    active_clients = len(active_customers) or active_subs or 1
    arpu = round(mrr / active_clients, 0) if active_clients else 0.0
    total_subs = sum(1 for r in records if r.resource_type == "subscription")
    total_churned = sum(int(v["count"]) for v in churn_by_month.values())
    churn_rate = round(total_churned / total_subs * 100, 1) if total_subs > 0 else 0.0
    ltv = round(arpu / (churn_rate / 100), 0) if churn_rate > 0 else 0.0

    def _flatten_by_status(data: dict) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for (year, month), statuses in sorted(data.items()):
            for status, vals in sorted(statuses.items()):
                rows.append({
                    "year": year, "month": month, "status": status,
                    "count": int(vals["count"]), "amount": round(vals["amount"], 2),
                })
        return rows

    def _flatten_series(data: dict) -> list[dict[str, Any]]:
        return [
            {"year": year, "month": month, "count": int(vals["count"]), "amount": round(vals["amount"], 2)}
            for (year, month), vals in sorted(data.items())
        ]

    return {
        "kpis": {
            "mrr": round(mrr, 0),
            "active_subscribers": active_subs,
            "active_clients": active_clients,
            "arpu": round(arpu, 0),
            "churn_rate": churn_rate,
            "ltv": round(ltv, 0),
        },
        "invoices_monthly": _flatten_by_status(invoices_monthly),
        "transactions_monthly": _flatten_by_status(transactions_monthly),
        "activation_monthly": _flatten_by_status(activation_by_month),
        "churn_monthly": _flatten_series(churn_by_month),
    }


def _payku_extended_data(records: list[SourceRecord]) -> dict[str, Any]:
    transactions_monthly: dict[tuple[int, int], dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"count": 0.0, "amount": 0.0})
    )
    activation_by_month: dict[tuple[int, int], dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"count": 0.0, "amount": 0.0})
    )
    churn_by_month: dict[tuple[int, int], dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"count": 0.0, "amount": 0.0})
    )
    mrr = 0.0
    active_subs = 0
    active_ruts: set[str] = set()

    for record in records:
        rtype = record.resource_type
        payload = record.payload

        if rtype == "transaction":
            month = _month(payload.get("created_at"))
            if month:
                status = str(payload.get("status", "sin_estado")).upper()
                transactions_monthly[month][status]["count"] += 1
                transactions_monthly[month][status]["amount"] += _amount(payload.get("amount"))

        elif rtype == "subscription":
            status = str(payload.get("status", "")).lower()

            start = payload.get("start")
            month = _month(start)
            if month:
                activation_by_month[month][status.upper() or "SIN_ESTADO"]["count"] += 1
                activation_by_month[month][status.upper() or "SIN_ESTADO"]["amount"] += _amount(payload.get("amount"))

            end = payload.get("end")
            if end and status in {"cancel", "delete", "suspended"}:
                month = _month(end)
                if month:
                    churn_by_month[month][status.upper()]["count"] += 1
                    churn_by_month[month][status.upper()]["amount"] += _amount(payload.get("amount"))

            if status in ("active", "activa", "activo"):
                active_subs += 1
                mrr += _amount(payload.get("amount"))
                rut = _payload_value(payload, ("client", "rut")) or payload.get("rut")
                if rut:
                    active_ruts.add(str(rut))

    active_clients = len(active_ruts) or active_subs or 1
    arpu = round(mrr / active_clients, 0) if active_clients else 0.0
    total_subs = sum(1 for r in records if r.resource_type == "subscription")
    total_churned = sum(int(values["count"]) for statuses in churn_by_month.values() for values in statuses.values())
    churn_rate = round(total_churned / total_subs * 100, 1) if total_subs > 0 else 0.0
    ltv = round(arpu / (churn_rate / 100), 0) if churn_rate > 0 else 0.0

    def _flatten_by_status(data: dict) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for (year, month), statuses in sorted(data.items()):
            for status, vals in sorted(statuses.items()):
                rows.append({
                    "year": year, "month": month, "status": status,
                    "count": int(vals["count"]), "amount": round(vals["amount"], 2),
                })
        return rows

    def _flatten_series(data: dict) -> list[dict[str, Any]]:
        return [
            {"year": year, "month": month, "count": int(vals["count"]), "amount": round(vals["amount"], 2)}
            for (year, month), vals in sorted(data.items())
        ]

    return {
        "kpis": {
            "mrr": round(mrr, 0),
            "active_subscribers": active_subs,
            "active_clients": active_clients,
            "arpu": round(arpu, 0),
            "churn_rate": churn_rate,
            "ltv": round(ltv, 0),
        },
        "transactions_monthly": _flatten_by_status(transactions_monthly),
        "activation_monthly": _flatten_by_status(activation_by_month),
        "churn_monthly": _flatten_by_status(churn_by_month),
    }


# ── Canonical VirtualPOS helpers ─────────────────────────────────────────────

_VP_SRCS = ("virtualpos1", "virtualpos2")
_VP_MODEL: dict[str, Any] = {
    "client": CClient,
    "plan": CPlan,
    "subscription": CSub,
    "charge": CCharge,
    "payment": CPayment,
}


def _require_source_access(user: User, source: str, resource_type: str | None = None) -> None:
    # Unit tests call handlers directly; HTTP requests always receive a resolved user dependency.
    if not isinstance(user, User):
        return
    try:
        required = source_permission(source, resource_type)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Provider resource not found") from exc
    if required not in permission_codes(user):
        raise HTTPException(status_code=403, detail="Permission denied")


def _permitted_related(user: User, source: str, related: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(user, User):
        return related
    codes = permission_codes(user)
    return [
        group
        for group in related
        if source_permission(source, group["resource_type"]) in codes
    ]
_TOKU_MODEL: dict[str, Any] = {
    "customer": CClient,
    "payment_method": CPaymentMethod,
    "subscription": CSub,
    "invoice": CCharge,
    "transaction": CPayment,
}
_PAYKU_MODEL: dict[str, Any] = {
    "client": CClient,
    "plan": CPlan,
    "subscription": CSub,
    "transaction": CPayment,
}


def _vp_src(source: str) -> list[str]:
    return [source] if source in _VP_SRCS else list(_VP_SRCS)


def _cstg(record: Any, rtype: str) -> dict[str, Any]:
    payload = dict(record.raw_payload or {})
    if rtype == "client" and getattr(record, "private_note", None):
        payload["private_note"] = record.private_note
    return {
        "id": str(record.id),
        "source": record.source,
        "resource_type": rtype,
        "external_id": record.external_id,
        "payload": payload,
        "sync_context": {},
        "first_seen_at": None,
        "last_seen_at": str(record.updated_at) if record.updated_at else None,
    }


def _vp_filter(model: Any, rtype: str, ff: str, q: str):
    """Build a JSONB search expression on raw_payload for canonical VirtualPOS records."""
    r = model.raw_payload
    fm: dict[str, dict[str, Any]] = {
        "client": {
            "uuid": func.coalesce(r["uuid"].astext, model.external_id),
            "social_id": r["social_id"].astext,
            "name": func.concat_ws(" ", r["first_name"].astext, r["last_name"].astext),
            "email": r["email"].astext,
            "phone_number": r["phone_number"].astext,
            "status": r["status"].astext,
        },
        "plan": {
            "id": func.coalesce(r["id"].astext, model.external_id),
            "name": r["name"].astext,
            "amount": r["amount"].astext,
            "automatic_renewal": r["automatic_renewal"].astext,
            "is_active": r["is_active"].astext,
            "show_in_terminal": r["show_in_terminal"].astext,
        },
        "subscription": {
            "id": func.coalesce(r["id"].astext, model.external_id),
            "status": r["status"].astext,
            "social_id": r["client"]["social_id"].astext,
            "amount": r["amount"].astext,
            "suscription_date": r["suscription_date"].astext,
            "canceled_at": r["canceled_at"].astext,
        },
        "charge": {
            "id": func.coalesce(r["id"].astext, model.external_id),
            "status": r["status"].astext,
            "subscription_id": r["suscription_id"].astext,
            "amount": r["amount"].astext,
            "charge_date": r["charge_date"].astext,
        },
        "payment": {
            "uuid": func.coalesce(r["order"]["uuid"].astext, model.external_id),
            "status": r["order"]["status"].astext,
            "social_id": r["client"]["social_id"].astext,
            "amount": r["order"]["amount"].astext,
            "authorized_at": r["order"]["authorized_at"].astext,
        },
    }
    field = fm.get(rtype, {}).get(ff)
    if field is None:
        raise HTTPException(status_code=422, detail="Invalid filter field")
    lo = q.strip().lower()
    if ff in {"automatic_renewal", "is_active", "show_in_terminal"}:
        if lo in {"activo", "activa", "true", "t", "1", "si", "sí"}:
            return cast(field, String).ilike("%true%") | cast(field, String).ilike("%t%")
        if lo in {"inactivo", "inactiva", "false", "f", "0", "no"}:
            return cast(field, String).ilike("%false%") | cast(field, String).ilike("%f%")
    return cast(field, String).ilike(f"%{q.strip()}%")


def _list_vp(
    source: str,
    db: Session,
    resource_type: str | None,
    filter_field: str | None,
    query: str | None,
    sort_field: str | None,
    sort_direction: Literal["asc", "desc"],
    offset: int,
    limit: int,
) -> dict[str, Any]:
    if not resource_type or resource_type not in _VP_MODEL:
        return {"items": [], "total": 0, "offset": offset, "limit": limit}
    model = _VP_MODEL[resource_type]
    sources = _vp_src(source)
    stmt = select(model).where(model.source.in_(sources))
    cnt = select(func.count()).select_from(model).where(model.source.in_(sources))
    if filter_field and query and resource_type:
        expr = _vp_filter(model, resource_type, filter_field, query)
        stmt = stmt.where(expr)
        cnt = cnt.where(expr)
    if sort_field:
        expression = _vp_sort_field(model, resource_type, sort_field)
        stmt = stmt.order_by(
            (expression.asc() if sort_direction == "asc" else expression.desc()).nullslast(),
            model.updated_at.desc(),
        )
    elif resource_type == "charge":
        stmt = stmt.order_by(model.charge_date.desc().nullslast(), model.updated_at.desc())
    elif resource_type == "payment":
        stmt = stmt.order_by(model.payment_date.desc().nullslast(), model.updated_at.desc())
    else:
        stmt = stmt.order_by(model.updated_at.desc())
    records = db.scalars(stmt.offset(offset).limit(limit)).all()
    return {
        "items": [_cstg(r, resource_type) for r in records],
        "total": db.scalar(cnt) or 0,
        "offset": offset,
        "limit": limit,
    }


def _toku_filter(model: Any, rtype: str, ff: str, q: str):
    raw = model.raw_payload
    fields: dict[str, dict[str, Any]] = {
        "customer": {
            "id": model.external_id,
            "government_id": CClient.social_id,
            "name": CClient.first_name,
            "mail": CClient.email,
            "phone_number": CClient.phone_number,
        },
        "subscription": {
            "id": model.external_id,
            "customer": CSub.client_external_id,
            "amount": CSub.amount,
            "status": CSub.status,
            "anchor": CSub.suscription_date,
            "end_date": CSub.canceled_at,
        },
        "payment_method": {
            "id": model.external_id,
            "status": CPaymentMethod.status,
            "created_at": func.coalesce(raw["created_at"].astext, raw["payment_method"]["created_at"].astext),
            "bank_name": func.coalesce(raw["bank_name"].astext, raw["payment_method"]["card"]["bank_name"].astext),
            "card_brand": func.coalesce(raw["card_brand"].astext, raw["payment_method"]["card"]["card_brand"].astext),
            "last_digits": func.coalesce(raw["last_digits"].astext, raw["payment_method"]["card"]["last_digits"].astext),
            "card_type": func.coalesce(raw["card_type"].astext, raw["payment_method"]["card"]["card_type"].astext),
            "customer_id": CPaymentMethod.client_external_id,
        },
        "invoice": {
            "id": model.external_id,
            "customer": CCharge.client_external_id,
            "subscription": CCharge.subscription_external_id,
            "amount": CCharge.amount,
            "is_paid": raw["is_paid"].astext,
            "status": CCharge.status,
            "due_date": CCharge.charge_date,
        },
        "transaction": {
            "id": model.external_id,
            "customer_id": CPayment.client_external_id,
            "subscription_id": func.coalesce(raw["subscription_id"].astext, raw["transaction"]["subscription_id"].astext),
            "amount": CPayment.amount,
            "transaction_date": CPayment.payment_date,
        },
    }
    field = fields.get(rtype, {}).get(ff)
    if field is None:
        raise HTTPException(status_code=422, detail="Invalid staging filter field")
    return cast(field, String).ilike(f"%{q.strip()}%")


def _toku_sort_field(model: Any, rtype: str, field_name: str):
    raw = model.raw_payload
    fields = {
        "customer": {"id": model.external_id, "government_id": CClient.social_id, "name": CClient.first_name, "mail": CClient.email, "phone_number": CClient.phone_number},
        "subscription": {"id": model.external_id, "customer": CSub.client_external_id, "amount": CSub.amount, "status": CSub.status, "anchor": CSub.suscription_date, "end_date": CSub.canceled_at},
        "payment_method": {"id": model.external_id, "status": CPaymentMethod.status, "created_at": func.coalesce(raw["created_at"].astext, raw["payment_method"]["created_at"].astext), "bank_name": func.coalesce(raw["bank_name"].astext, raw["payment_method"]["card"]["bank_name"].astext), "card_brand": func.coalesce(raw["card_brand"].astext, raw["payment_method"]["card"]["card_brand"].astext), "last_digits": func.coalesce(raw["last_digits"].astext, raw["payment_method"]["card"]["last_digits"].astext), "card_type": func.coalesce(raw["card_type"].astext, raw["payment_method"]["card"]["card_type"].astext), "customer_id": CPaymentMethod.client_external_id},
        "invoice": {"id": model.external_id, "customer": CCharge.client_external_id, "subscription": CCharge.subscription_external_id, "amount": CCharge.amount, "is_paid": raw["is_paid"].astext, "status": CCharge.status, "due_date": CCharge.charge_date},
        "transaction": {"id": model.external_id, "customer_id": CPayment.client_external_id, "subscription_id": func.coalesce(raw["subscription_id"].astext, raw["transaction"]["subscription_id"].astext), "amount": CPayment.amount, "transaction_date": CPayment.payment_date},
    }
    field = fields.get(rtype, {}).get(field_name)
    if field is None:
        raise HTTPException(status_code=422, detail="Invalid sort field")
    return field


def _vp_sort_field(model: Any, rtype: str, field_name: str):
    raw = model.raw_payload
    fields = {
        "client": {"uuid": func.coalesce(raw["uuid"].astext, model.external_id), "social_id": raw["social_id"].astext, "name": func.concat_ws(" ", raw["first_name"].astext, raw["last_name"].astext), "email": raw["email"].astext, "phone_number": raw["phone_number"].astext, "status": raw["status"].astext},
        "plan": {"id": func.coalesce(raw["id"].astext, model.external_id), "name": raw["name"].astext, "amount": raw["amount"].astext, "automatic_renewal": raw["automatic_renewal"].astext, "is_active": raw["is_active"].astext, "show_in_terminal": raw["show_in_terminal"].astext},
        "subscription": {"id": func.coalesce(raw["id"].astext, model.external_id), "status": raw["status"].astext, "social_id": raw["client"]["social_id"].astext, "amount": raw["amount"].astext, "suscription_date": raw["suscription_date"].astext, "canceled_at": raw["canceled_at"].astext},
        "charge": {"id": func.coalesce(raw["id"].astext, model.external_id), "status": raw["status"].astext, "subscription_id": raw["suscription_id"].astext, "amount": raw["amount"].astext, "charge_date": raw["charge_date"].astext},
        "payment": {"uuid": func.coalesce(raw["order"]["uuid"].astext, model.external_id), "status": raw["order"]["status"].astext, "social_id": raw["client"]["social_id"].astext, "amount": raw["order"]["amount"].astext, "authorized_at": raw["order"]["authorized_at"].astext},
    }
    field = fields.get(rtype, {}).get(field_name)
    if field is None:
        raise HTTPException(status_code=422, detail="Invalid sort field")
    return field


def _list_toku(
    db: Session,
    resource_type: str | None,
    filter_field: str | None,
    query: str | None,
    sort_field: str | None,
    sort_direction: Literal["asc", "desc"],
    offset: int,
    limit: int,
) -> dict[str, Any]:
    if not resource_type or resource_type not in _TOKU_MODEL:
        return {"items": [], "total": 0, "offset": offset, "limit": limit}
    model = _TOKU_MODEL[resource_type]
    statement = select(model).where(model.source == "toku")
    count_statement = select(func.count()).select_from(model).where(model.source == "toku")
    if filter_field and query:
        expression = _toku_filter(model, resource_type, filter_field, query)
        statement = statement.where(expression)
        count_statement = count_statement.where(expression)
    if sort_field:
        expression = _toku_sort_field(model, resource_type, sort_field)
        statement = statement.order_by((expression.asc() if sort_direction == "asc" else expression.desc()).nullslast(), model.updated_at.desc())
    else:
        date_fields = {
        "subscription": CSub.suscription_date,
        "invoice": CCharge.charge_date,
        "transaction": CPayment.payment_date,
    }
        date_field = date_fields.get(resource_type)
        if date_field is not None:
            statement = statement.order_by(date_field.desc().nullslast(), model.updated_at.desc())
        elif resource_type == "payment_method":
            created_at = func.coalesce(model.raw_payload["created_at"].astext, model.raw_payload["payment_method"]["created_at"].astext)
            statement = statement.order_by(created_at.desc().nullslast(), model.updated_at.desc())
        else:
            statement = statement.order_by(model.updated_at.desc())
    records = db.scalars(statement.offset(offset).limit(limit)).all()
    return {
        "items": [_cstg(record, resource_type) for record in records],
        "total": db.scalar(count_statement) or 0,
        "offset": offset,
        "limit": limit,
    }


def _payku_filter(model: Any, rtype: str, ff: str, q: str):
    raw = model.raw_payload
    fields: dict[str, dict[str, Any]] = {
        "client": {
            "id": model.external_id,
            "rut": CClient.social_id,
            "name": func.coalesce(func.nullif(func.concat_ws(" ", CClient.first_name, CClient.last_name), ""), raw["name"].astext),
            "email": CClient.email,
            "phone": CClient.phone_number,
        },
        "plan": {"id": model.external_id, "status": CPlan.status, "name": CPlan.name},
        "subscription": {
            "id": model.external_id,
            "status": CSub.status,
            "rut": CSub.client_social_id,
            "start": CSub.suscription_date,
            "end": CSub.canceled_at,
        },
        "transaction": {
            "id": model.external_id,
            "status": CPayment.status,
            "subscriptions": func.coalesce(raw["subscriptions"].astext, raw["transaction"]["subscriptions"].astext),
            "amount": CPayment.amount,
            "created_at": CPayment.payment_date,
        },
    }
    field = fields.get(rtype, {}).get(ff)
    if field is None:
        raise HTTPException(status_code=422, detail="Invalid staging filter field")
    return cast(field, String).ilike(f"%{q.strip()}%")


def _payku_sort_field(model: Any, rtype: str, field_name: str):
    raw = model.raw_payload
    fields = {
        "client": {"id": model.external_id, "rut": CClient.social_id, "name": func.coalesce(func.nullif(func.concat_ws(" ", CClient.first_name, CClient.last_name), ""), raw["name"].astext), "email": CClient.email, "phone": CClient.phone_number},
        "plan": {"id": model.external_id, "status": CPlan.status, "name": CPlan.name},
        "subscription": {"id": model.external_id, "status": CSub.status, "rut": CSub.client_social_id, "start": CSub.suscription_date, "end": CSub.canceled_at},
        "transaction": {"id": model.external_id, "status": CPayment.status, "subscriptions": func.coalesce(raw["subscriptions"].astext, raw["transaction"]["subscriptions"].astext), "amount": CPayment.amount, "created_at": CPayment.payment_date},
    }
    field = fields.get(rtype, {}).get(field_name)
    if field is None:
        raise HTTPException(status_code=422, detail="Invalid sort field")
    return field


def _list_payku(
    db: Session,
    resource_type: str | None,
    filter_field: str | None,
    query: str | None,
    sort_field: str | None,
    sort_direction: Literal["asc", "desc"],
    offset: int,
    limit: int,
) -> dict[str, Any]:
    if not resource_type or resource_type not in _PAYKU_MODEL:
        return {"items": [], "total": 0, "offset": offset, "limit": limit}
    model = _PAYKU_MODEL[resource_type]
    statement = select(model).where(model.source == "payku")
    count_statement = select(func.count()).select_from(model).where(model.source == "payku")
    if filter_field and query:
        expression = _payku_filter(model, resource_type, filter_field, query)
        statement = statement.where(expression)
        count_statement = count_statement.where(expression)
    if sort_field:
        expression = _payku_sort_field(model, resource_type, sort_field)
        statement = statement.order_by((expression.asc() if sort_direction == "asc" else expression.desc()).nullslast(), model.updated_at.desc())
    else:
        date_field = {"subscription": CSub.suscription_date, "transaction": CPayment.payment_date}.get(resource_type)
        if date_field is not None:
            statement = statement.order_by(date_field.desc().nullslast(), model.updated_at.desc())
        else:
            statement = statement.order_by(model.updated_at.desc())
    records = db.scalars(statement.offset(offset).limit(limit)).all()
    return {
        "items": [_cstg(record, resource_type) for record in records],
        "total": db.scalar(count_statement) or 0,
        "offset": offset,
        "limit": limit,
    }


def _vp_canonical_dashboard(source: str, db: Session) -> dict[str, Any]:
    """Build channel dashboard from canonical CRM tables for VirtualPOS."""
    sources = _vp_src(source)

    paid_statuses = ("pagado", "aceptado", "accepted", "paid")
    metric_filters = {
        "client": (func.lower(CClient.status) == "activo",),
        "plan": (func.lower(CPlan.is_active).in_(("true", "t", "1")),),
        "subscription": (func.lower(CSub.status) == "activa",),
        "charge": (func.lower(CCharge.status).in_(paid_statuses),),
        "payment": (func.lower(CPayment.status).in_(paid_statuses),),
    }


    resource_counts = {
        rtype: db.scalar(
            select(func.count()).select_from(model).where(model.source.in_(sources), *metric_filters[rtype])
        ) or 0
        for rtype, model in _VP_MODEL.items()
    }

    # Status distribution using canonical status columns
    statuses: list[dict[str, Any]] = []
    for rtype, model in _VP_MODEL.items():
        rows = db.execute(
            select(model.status, func.count().label("n"))
            .where(model.source.in_(sources), model.status.isnot(None))
            .group_by(model.status)
        ).all()
        for row in rows:
            statuses.append({"resource": rtype, "status": str(row[0]), "count": row[1]})

    # Resource amounts from canonical amount columns
    resource_amounts: dict[str, float] = {}
    for rtype, model in _VP_MODEL.items():
        if hasattr(model, "amount"):
            rows = db.execute(
                select(model.amount).where(
                    model.source.in_(sources), model.amount.isnot(None), *metric_filters[rtype]
                )
            ).scalars().all()
            total_amount = sum(_amount(v) for v in rows)
            if total_amount:
                resource_amounts[rtype] = round(total_amount, 2)

    # Activity: charges grouped by month using canonical charge_date
    activity_by_month: dict[tuple[int, int], dict[str, float]] = defaultdict(lambda: {"count": 0, "amount": 0})
    charge_rows = db.execute(
        select(CCharge.charge_date, CCharge.amount).where(CCharge.source.in_(sources))
    ).all()
    for charge_date, amount in charge_rows:
        month = _month(charge_date)
        if month:
            activity_by_month[month]["count"] += 1
            activity_by_month[month]["amount"] += _amount(amount)
    activity = [
        {"year": yr, "month": mo, "count": int(v["count"]), "amount": round(v["amount"], 2)}
        for (yr, mo), v in sorted(activity_by_month.items())
    ]

    # Extended data: load subscriptions (small set ~8k) for KPIs and monthly charts
    subs = db.scalars(select(CSub).where(CSub.source.in_(sources))).all()
    payments_rows = db.execute(
        select(CPayment.payment_date, CPayment.amount, CPayment.status).where(CPayment.source.in_(sources))
    ).all()
    charges_rows = db.execute(
        select(CCharge.charge_date, CCharge.amount, CCharge.status).where(CCharge.source.in_(sources))
    ).all()

    # Build adapter objects for _vp_extended_data reuse
    class _Rec:
        __slots__ = ("payload", "resource_type")
        def __init__(self, rt: str, p: dict):
            self.resource_type = rt
            self.payload = p

    vp_records: list[Any] = []
    for s in subs:
        raw = s.raw_payload or {}
        vp_records.append(_Rec("subscription", raw))
    for cd, amt, st in charges_rows:
        vp_records.append(_Rec("charge", {"charge_date": cd, "amount": amt, "status": st}))
    for pd, amt, st in payments_rows:
        vp_records.append(_Rec("payment", {"order": {"authorized_at": pd, "amount": amt, "status": st}}))

    extended = _vp_extended_data(vp_records)  # type: ignore[arg-type]

    return {
        "source": source,
        "records": sum(resource_counts.values()),
        "resources": resource_counts,
        "resource_amounts": resource_amounts,
        "statuses": statuses,
        "activity_resource": "charge",
        "activity": activity,
        "years": sorted({e["year"] for e in activity}, reverse=True),
        "last_sync": None,
        **extended,
    }


def _toku_canonical_dashboard(db: Session) -> dict[str, Any]:
    chargeable_subscription_ids = {
        subscription_id
        for method in db.scalars(
            select(CPaymentMethod).where(
                CPaymentMethod.source == "toku",
                func.lower(CPaymentMethod.status) == "chargeable",
            )
        )
        for subscription_id in _toku_subscription_ids(method)
    }
    active_subscriptions = [
        subscription
        for subscription in db.scalars(
            select(CSub).where(CSub.source == "toku", func.lower(CSub.status) == "active")
        )
        if subscription.external_id in chargeable_subscription_ids
    ]
    resource_counts = {
        rtype: db.scalar(select(func.count()).select_from(model).where(model.source == "toku")) or 0
        for rtype, model in _TOKU_MODEL.items()
    }
    resource_counts["subscription"] = len(active_subscriptions)
    resource_counts["invoice"] = db.scalar(
        select(func.count()).select_from(CCharge).where(
            CCharge.source == "toku", func.upper(CCharge.status) == "PAID"
        )
    ) or 0
    resource_counts["transaction"] = db.scalar(
        select(func.count()).select_from(CPayment).where(
            CPayment.source == "toku", func.upper(CPayment.status) == "SUCCESS"
        )
    ) or 0
    statuses: list[dict[str, Any]] = []
    for rtype, model in _TOKU_MODEL.items():
        rows = db.execute(
            select(model.status, func.count())
            .where(model.source == "toku", model.status.isnot(None))
            .group_by(model.status)
        ).all()
        statuses.extend({"resource": rtype, "status": str(status), "count": count} for status, count in rows)

    resource_amounts: dict[str, float] = {}
    for rtype, model in _TOKU_MODEL.items():
        if hasattr(model, "amount"):
            values = db.scalars(select(model.amount).where(model.source == "toku")).all()
            total = sum(_amount(value) for value in values)
            if total:
                resource_amounts[rtype] = round(total, 2)
    resource_amounts["subscription"] = round(sum(_amount(subscription.amount) for subscription in active_subscriptions), 2)
    resource_amounts["invoice"] = round(sum(
        _amount(amount)
        for amount in db.scalars(
            select(CCharge.amount).where(CCharge.source == "toku", func.upper(CCharge.status) == "PAID")
        )
    ), 2)
    resource_amounts["transaction"] = round(sum(
        _amount(amount)
        for amount in db.scalars(
            select(CPayment.amount).where(CPayment.source == "toku", func.upper(CPayment.status) == "SUCCESS")
        )
    ), 2)

    activity_by_month: dict[tuple[int, int], dict[str, float]] = defaultdict(lambda: {"count": 0, "amount": 0})
    invoice_rows = db.execute(select(CCharge.charge_date, CCharge.amount).where(CCharge.source == "toku"))
    for due_date, amount in invoice_rows:
        month = _month(due_date)
        if month:
            activity_by_month[month]["count"] += 1
            activity_by_month[month]["amount"] += _amount(amount)
    activity = [
        {"year": year, "month": month, "count": int(values["count"]), "amount": round(values["amount"], 2)}
        for (year, month), values in sorted(activity_by_month.items())
    ]

    class _Record:
        __slots__ = ("payload", "resource_type")

        def __init__(self, resource_type: str, payload: dict[str, Any]):
            self.resource_type = resource_type
            self.payload = payload

    records: list[Any] = []
    for subscription in db.scalars(select(CSub).where(CSub.source == "toku")):
        records.append(_Record("subscription", {
            **(subscription.raw_payload or {}), "customer": subscription.client_external_id,
            "amount": subscription.amount, "status": subscription.status,
            "anchor": subscription.suscription_date, "end_date": subscription.canceled_at,
        }))
    for invoice in db.scalars(select(CCharge).where(CCharge.source == "toku")):
        records.append(_Record("invoice", {
            **(invoice.raw_payload or {}), "amount": invoice.amount, "status": invoice.status,
            "due_date": invoice.charge_date,
        }))
    for transaction in db.scalars(select(CPayment).where(CPayment.source == "toku")):
        records.append(_Record("transaction", {
            **(transaction.raw_payload or {}), "amount": transaction.amount, "status": transaction.status,
            "transaction_date": transaction.payment_date,
        }))
    latest_run = db.scalars(
        select(SyncRun).where(SyncRun.source == "toku").order_by(SyncRun.started_at.desc()).limit(1)
    ).first()
    return {
        "source": "toku",
        "records": sum(resource_counts.values()),
        "resources": resource_counts,
        "resource_amounts": resource_amounts,
        "statuses": sorted(statuses, key=lambda item: (item["resource"], item["status"])),
        "activity_resource": "invoice",
        "activity": activity,
        "years": sorted({entry["year"] for entry in activity}, reverse=True),
        "last_sync": (
            {
                "status": latest_run.status,
                "started_at": latest_run.started_at,
                "finished_at": latest_run.finished_at,
                "records_processed": latest_run.records_processed,
            }
            if latest_run else None
        ),
        **_toku_extended_data(records),
    }


def _payku_canonical_dashboard(db: Session) -> dict[str, Any]:
    active_subscriptions = db.scalars(
        select(CSub).where(CSub.source == "payku", func.lower(CSub.status) == "active")
    ).all()
    successful_transactions = db.execute(
        select(CPayment.amount).where(CPayment.source == "payku", func.lower(CPayment.status) == "success")
    ).all()
    resource_counts = {
        rtype: db.scalar(select(func.count()).select_from(model).where(model.source == "payku")) or 0
        for rtype, model in _PAYKU_MODEL.items()
    }
    resource_counts["subscription"] = len(active_subscriptions)
    resource_counts["transaction"] = len(successful_transactions)
    statuses: list[dict[str, Any]] = []
    for rtype, model in _PAYKU_MODEL.items():
        rows = db.execute(
            select(model.status, func.count())
            .where(model.source == "payku", model.status.isnot(None))
            .group_by(model.status)
        ).all()
        statuses.extend({"resource": rtype, "status": str(status), "count": count} for status, count in rows)

    resource_amounts: dict[str, float] = {}
    for rtype, model in _PAYKU_MODEL.items():
        if hasattr(model, "amount"):
            total = sum(_amount(value) for value in db.scalars(select(model.amount).where(model.source == "payku")).all())
            if total:
                resource_amounts[rtype] = round(total, 2)
    resource_amounts["subscription"] = round(sum(_amount(subscription.amount) for subscription in active_subscriptions), 2)
    resource_amounts["transaction"] = round(sum(_amount(amount) for amount, in successful_transactions), 2)

    activity_by_month: dict[tuple[int, int], dict[str, float]] = defaultdict(lambda: {"count": 0, "amount": 0})
    for created_at, amount in db.execute(
        select(CPayment.payment_date, CPayment.amount).where(CPayment.source == "payku")
    ).all():
        month = _month(created_at)
        if month:
            activity_by_month[month]["count"] += 1
            activity_by_month[month]["amount"] += _amount(amount)
    activity = [
        {"year": year, "month": month, "count": int(values["count"]), "amount": round(values["amount"], 2)}
        for (year, month), values in sorted(activity_by_month.items())
    ]

    class _Record:
        __slots__ = ("payload", "resource_type")

        def __init__(self, resource_type: str, payload: dict[str, Any]):
            self.resource_type = resource_type
            self.payload = payload

    records: list[Any] = []
    for subscription in db.scalars(select(CSub).where(CSub.source == "payku")):
        records.append(_Record("subscription", {
            **(subscription.raw_payload or {}), "status": subscription.status,
            "start": subscription.suscription_date, "end": subscription.canceled_at,
            "amount": subscription.amount,
            "client": {"rut": subscription.client_social_id},
        }))
    for transaction in db.scalars(select(CPayment).where(CPayment.source == "payku")):
        records.append(_Record("transaction", {
            **(transaction.raw_payload or {}), "status": transaction.status,
            "amount": transaction.amount, "created_at": transaction.payment_date,
        }))
    latest_run = db.scalars(
        select(SyncRun).where(SyncRun.source == "payku").order_by(SyncRun.started_at.desc()).limit(1)
    ).first()
    return {
        "source": "payku",
        "records": sum(resource_counts.values()),
        "resources": resource_counts,
        "resource_amounts": resource_amounts,
        "statuses": sorted(statuses, key=lambda item: (item["resource"], item["status"])),
        "activity_resource": "transaction",
        "activity": activity,
        "years": sorted({entry["year"] for entry in activity}, reverse=True),
        "last_sync": (
            {
                "status": latest_run.status,
                "started_at": latest_run.started_at,
                "finished_at": latest_run.finished_at,
                "records_processed": latest_run.records_processed,
            }
            if latest_run else None
        ),
        **_payku_extended_data(records),
    }


@router.get("/records", tags=["Staging"])
def list_records(
    source: str,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
    resource_type: str | None = None,
    filter_field: str | None = None,
    query: str | None = None,
    sort_field: str | None = None,
    sort_direction: Literal["asc", "desc"] = "asc",
    offset: PaginationOffset = 0,
    limit: PaginationLimit = 50,
) -> dict[str, Any]:
    _require_source_access(current_user, source, resource_type)
    if source.startswith("virtualpos"):
        return _list_vp(source, db, resource_type, filter_field, query, sort_field, sort_direction, offset, limit)
    if source == "toku":
        return _list_toku(db, resource_type, filter_field, query, sort_field, sort_direction, offset, limit)
    if source == "payku":
        return _list_payku(db, resource_type, filter_field, query, sort_field, sort_direction, offset, limit)
    statement = select(SourceRecord).where(SourceRecord.source == source)
    count_statement = select(func.count()).select_from(SourceRecord).where(SourceRecord.source == source)
    if resource_type:
        statement = statement.where(SourceRecord.resource_type == resource_type)
        count_statement = count_statement.where(SourceRecord.resource_type == resource_type)
    if filter_field and query and resource_type:
        filter_expression = _staging_filter(source, resource_type, filter_field, query)
        statement = statement.where(filter_expression)
        count_statement = count_statement.where(filter_expression)
    records = db.scalars(statement.order_by(*_record_order(source, resource_type or "")).offset(offset).limit(limit)).all()
    return {
        "items": [_serialize(record) for record in records],
        "total": db.scalar(count_statement) or 0,
        "offset": offset,
        "limit": limit,
    }


@router.get("/records/filter-values", tags=["Staging"])
def list_record_filter_values(
    source: str,
    resource_type: str,
    filter_field: str,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, list[str]]:
    """Return distinct filter values without limiting them to the displayed page."""
    _require_source_access(current_user, source, resource_type)
    if filter_field != "status":
        raise HTTPException(status_code=422, detail="Unsupported filter value field")

    if source.startswith("virtualpos"):
        model = _VP_MODEL.get(resource_type)
        sources = _vp_src(source)
        statement = select(model.status).where(model.source.in_(sources)) if model else None
    elif source == "toku":
        model = _TOKU_MODEL.get(resource_type)
        statement = select(model.status).where(model.source == source) if model else None
    elif source == "payku":
        model = _PAYKU_MODEL.get(resource_type)
        statement = select(model.status).where(model.source == source) if model else None
    else:
        raise HTTPException(status_code=404, detail="Unknown staging source")

    if statement is None:
        raise HTTPException(status_code=422, detail="Invalid staging resource")
    values = db.scalars(statement.where(model.status.isnot(None)).distinct()).all()
    return {"values": sorted({str(value) for value in values if str(value).strip()}, key=str.lower)}


@router.get("/virtualpos/clients/{external_id}", tags=["Staging"])
def virtualpos_client_detail(
    external_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
    offset: PaginationOffset = 0,
    limit: PaginationLimit = 50,
) -> dict[str, Any]:
    _require_source_access(current_user, "virtualpos", "client")
    client = db.scalar(
        select(CClient).where(CClient.source.in_(_VP_SRCS), CClient.external_id == external_id)
    )
    if client is None:
        raise HTTPException(status_code=404, detail="VirtualPOS client not found")
    social_id = client.social_id
    if not social_id:
        return {"client": _cstg(client, "client"), "subscriptions": [], "subscription_total": 0}
    filters = (CSub.source == client.source, CSub.client_social_id == client.social_id)
    subscriptions = db.scalars(
        select(CSub).where(*filters).order_by(CSub.updated_at.desc()).offset(offset).limit(limit)
    ).all()
    total = db.scalar(select(func.count()).select_from(CSub).where(*filters)) or 0
    return {
        "client": _cstg(client, "client"),
        "subscriptions": [_cstg(s, "subscription") for s in subscriptions],
        "subscription_total": total,
    }


@router.get("/virtualpos/plans/{external_id}", tags=["Staging"])
def virtualpos_plan_detail(
    external_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
    offset: PaginationOffset = 0,
    limit: PaginationLimit = 50,
) -> dict[str, Any]:
    _require_source_access(current_user, "virtualpos", "plan")
    plan = db.scalar(
        select(CPlan).where(CPlan.source.in_(_VP_SRCS), CPlan.external_id == external_id)
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="VirtualPOS plan not found")
    filters = (CSub.source == plan.source, CSub.plan_external_id == plan.external_id)
    subscriptions = db.scalars(
        select(CSub).where(*filters).order_by(CSub.updated_at.desc()).offset(offset).limit(limit)
    ).all()
    total = db.scalar(select(func.count()).select_from(CSub).where(*filters)) or 0
    return {
        "plan": _cstg(plan, "plan"),
        "subscriptions": [_cstg(s, "subscription") for s in subscriptions],
        "subscription_total": total,
    }


@router.get("/virtualpos/subscriptions/{external_id}", tags=["Staging"])
def virtualpos_subscription_detail(
    external_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
    offset: PaginationOffset = 0,
    limit: PaginationLimit = 50,
) -> dict[str, Any]:
    _require_source_access(current_user, "virtualpos", "subscription")
    subscription = db.scalar(
        select(CSub).where(CSub.source.in_(_VP_SRCS), CSub.external_id == external_id)
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="VirtualPOS subscription not found")
    filters = (CCharge.source == subscription.source, CCharge.subscription_external_id == subscription.external_id)
    charges = db.scalars(
        select(CCharge)
        .where(*filters)
        .order_by(CCharge.charge_date.desc().nullslast(), CCharge.updated_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    total = db.scalar(select(func.count()).select_from(CCharge).where(*filters)) or 0
    raw = subscription.raw_payload or {}
    return {
        "subscription": _cstg(subscription, "subscription"),
        "payment_method": raw.get("payment_method"),
        "charges": [_cstg(c, "charge") for c in charges],
        "charge_total": total,
    }


@router.get("/virtualpos/charges/{external_id}", tags=["Staging"])
def virtualpos_charge_detail(
    external_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    _require_source_access(current_user, "virtualpos", "charge")
    charge = db.scalar(
        select(CCharge).where(CCharge.source.in_(_VP_SRCS), CCharge.external_id == external_id)
    )
    if charge is None:
        raise HTTPException(status_code=404, detail="VirtualPOS charge not found")
    return {"charge": _cstg(charge, "charge")}


@router.get("/virtualpos/payments/{external_id}", tags=["Staging"])
def virtualpos_payment_detail(
    external_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    _require_source_access(current_user, "virtualpos", "payment")
    payment = db.scalar(
        select(CPayment).where(CPayment.source.in_(_VP_SRCS), CPayment.external_id == external_id)
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="VirtualPOS payment not found")
    return {"payment": _cstg(payment, "payment")}


def _record_value(record: SourceRecord) -> str:
    return str(record.payload.get("id", record.external_id))


def _relationship_id(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("id")
    return str(value) if value is not None else None


def _matching_records(records: list[SourceRecord], resource_type: str, predicate: Any) -> list[dict[str, Any]]:
    return [_serialize(record) for record in records if record.resource_type == resource_type and predicate(record)]


def _related(label: str, resource_type: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"label": label, "resource_type": resource_type, "items": items}


def _toku_related(record: SourceRecord, records: list[SourceRecord]) -> list[dict[str, Any]]:
    record_id = _record_value(record)
    if record.resource_type == "customer":
        return [
            _related("Subscripciones", "subscription", _matching_records(records, "subscription", lambda item: _relationship_id(item.payload.get("customer")) == record_id)),
            _related("Métodos de pago", "payment_method", _matching_records(records, "payment_method", lambda item: _relationship_id(item.payload.get("customer_id")) == record_id)),
            _related("Deudas", "invoice", _matching_records(records, "invoice", lambda item: _relationship_id(item.payload.get("customer")) == record_id)),
            _related("Transacciones", "transaction", _matching_records(records, "transaction", lambda item: _relationship_id(item.payload.get("customer_id")) == record_id)),
        ]
    if record.resource_type == "subscription":
        return [
            _related("Cliente", "customer", _matching_records(records, "customer", lambda item: _record_value(item) == _relationship_id(record.payload.get("customer")))),
            _related("Métodos de pago", "payment_method", _matching_records(records, "payment_method", lambda item: record_id in item.payload.get("subscription_ids", []) if isinstance(item.payload.get("subscription_ids"), list) else False)),
            _related("Deudas", "invoice", _matching_records(records, "invoice", lambda item: _relationship_id(item.payload.get("subscription")) == record_id)),
            _related("Transacciones", "transaction", _matching_records(records, "transaction", lambda item: _relationship_id(item.payload.get("subscription_id")) == record_id)),
        ]
    if record.resource_type == "payment_method":
        subscription_ids = record.payload.get("subscription_ids", [])
        return [
            _related("Cliente", "customer", _matching_records(records, "customer", lambda item: _record_value(item) == _relationship_id(record.payload.get("customer_id")))),
            _related("Subscripciones", "subscription", _matching_records(records, "subscription", lambda item: _record_value(item) in subscription_ids if isinstance(subscription_ids, list) else False)),
        ]
    if record.resource_type == "invoice":
        return [
            _related("Cliente", "customer", _matching_records(records, "customer", lambda item: _record_value(item) == _relationship_id(record.payload.get("customer")))),
            _related("Subscripción", "subscription", _matching_records(records, "subscription", lambda item: _record_value(item) == _relationship_id(record.payload.get("subscription")))),
        ]
    if record.resource_type == "transaction":
        return [
            _related("Cliente", "customer", _matching_records(records, "customer", lambda item: _record_value(item) == _relationship_id(record.payload.get("customer_id")))),
            _related("Subscripción", "subscription", _matching_records(records, "subscription", lambda item: _record_value(item) == _relationship_id(record.payload.get("subscription_id")))),
        ]
    return []


def _toku_subscription_ids(record: CPaymentMethod) -> list[str]:
    payload = record.raw_payload or {}
    values = payload.get("subscription_ids")
    if not isinstance(values, list):
        method = payload.get("payment_method")
        values = method.get("subscription_ids") if isinstance(method, dict) else []
    return [str(value) for value in values if value is not None] if isinstance(values, list) else []


def _toku_transaction_subscription_id(record: CPayment) -> str | None:
    payload = record.raw_payload or {}
    value = payload.get("subscription_id")
    if value is None and isinstance(payload.get("transaction"), dict):
        value = payload["transaction"].get("subscription_id")
    return _relationship_id(value)


def _canonical_items(records: list[Any], resource_type: str) -> list[dict[str, Any]]:
    return [_cstg(record, resource_type) for record in records]


def _toku_canonical_related(record: Any, resource_type: str, db: Session) -> list[dict[str, Any]]:
    customers = db.scalars(select(CClient).where(CClient.source == "toku")).all()
    subscriptions = db.scalars(select(CSub).where(CSub.source == "toku")).all()
    methods = db.scalars(select(CPaymentMethod).where(CPaymentMethod.source == "toku")).all()
    invoices = db.scalars(select(CCharge).where(CCharge.source == "toku")).all()
    transactions = db.scalars(select(CPayment).where(CPayment.source == "toku")).all()
    record_id = record.external_id

    if resource_type == "customer":
        return [
            _related("Subscripciones", "subscription", _canonical_items([item for item in subscriptions if item.client_external_id == record_id], "subscription")),
            _related("Métodos de pago", "payment_method", _canonical_items([item for item in methods if item.client_external_id == record_id], "payment_method")),
            _related("Deudas", "invoice", _canonical_items([item for item in invoices if item.client_external_id == record_id], "invoice")),
            _related("Transacciones", "transaction", _canonical_items([item for item in transactions if item.client_external_id == record_id], "transaction")),
        ]
    if resource_type == "subscription":
        return [
            _related("Cliente", "customer", _canonical_items([item for item in customers if item.external_id == record.client_external_id], "customer")),
            _related("Métodos de pago", "payment_method", _canonical_items([item for item in methods if record_id in _toku_subscription_ids(item)], "payment_method")),
            _related("Deudas", "invoice", _canonical_items([item for item in invoices if item.subscription_external_id == record_id], "invoice")),
            _related("Transacciones", "transaction", _canonical_items([item for item in transactions if _toku_transaction_subscription_id(item) == record_id], "transaction")),
        ]
    if resource_type == "payment_method":
        subscription_ids = _toku_subscription_ids(record)
        return [
            _related("Cliente", "customer", _canonical_items([item for item in customers if item.external_id == record.client_external_id], "customer")),
            _related("Subscripciones", "subscription", _canonical_items([item for item in subscriptions if item.external_id in subscription_ids], "subscription")),
        ]
    if resource_type == "invoice":
        return [
            _related("Cliente", "customer", _canonical_items([item for item in customers if item.external_id == record.client_external_id], "customer")),
            _related("Subscripción", "subscription", _canonical_items([item for item in subscriptions if item.external_id == record.subscription_external_id], "subscription")),
        ]
    if resource_type == "transaction":
        subscription_id = _toku_transaction_subscription_id(record)
        return [
            _related("Cliente", "customer", _canonical_items([item for item in customers if item.external_id == record.client_external_id], "customer")),
            _related("Subscripción", "subscription", _canonical_items([item for item in subscriptions if item.external_id == subscription_id], "subscription")),
        ]
    return []


def _payku_related(record: SourceRecord, records: list[SourceRecord]) -> list[dict[str, Any]]:
    record_id = _record_value(record)
    if record.resource_type == "client":
        return [_related("Suscripciones", "subscription", _matching_records(records, "subscription", lambda item: _relationship_id(item.payload.get("client")) == record_id))]
    if record.resource_type == "plan":
        return [_related("Suscripciones", "subscription", _matching_records(records, "subscription", lambda item: _relationship_id(item.payload.get("plan")) == record_id))]
    if record.resource_type == "subscription":
        return [
            _related("Cliente", "client", _matching_records(records, "client", lambda item: _record_value(item) == _relationship_id(record.payload.get("client")))),
            _related("Plan", "plan", _matching_records(records, "plan", lambda item: _record_value(item) == _relationship_id(record.payload.get("plan")))),
        ]
    return []


def _payku_transaction_subscription_ids(record: CPayment) -> list[str]:
    payload = record.raw_payload or {}
    values = payload.get("subscriptions")
    if values is None and isinstance(payload.get("transaction"), dict):
        values = payload["transaction"].get("subscriptions")
    if values is None:
        values = payload.get("subscription")
    if values is None:
        values = payload.get("subscription_id")
    if not isinstance(values, list):
        values = [values]
    return [item_id for value in values if (item_id := _relationship_id(value)) is not None]


def _payku_canonical_related(record: Any, resource_type: str, db: Session) -> list[dict[str, Any]]:
    clients = db.scalars(select(CClient).where(CClient.source == "payku")).all()
    plans = db.scalars(select(CPlan).where(CPlan.source == "payku")).all()
    subscriptions = db.scalars(select(CSub).where(CSub.source == "payku")).all()
    transactions = db.scalars(select(CPayment).where(CPayment.source == "payku")).all()
    record_id = record.external_id

    if resource_type == "client":
        return [_related("Suscripciones", "subscription", _canonical_items(
            [item for item in subscriptions if item.client_external_id == record_id], "subscription"
        ))]
    if resource_type == "plan":
        return [_related("Suscripciones", "subscription", _canonical_items(
            [item for item in subscriptions if item.plan_external_id == record_id], "subscription"
        ))]
    if resource_type == "subscription":
        return [
            _related("Cliente", "client", _canonical_items(
                [item for item in clients if item.external_id == record.client_external_id], "client"
            )),
            _related("Plan", "plan", _canonical_items(
                [item for item in plans if item.external_id == record.plan_external_id], "plan"
            )),
            _related("Transacciones", "transaction", _canonical_items(
                [item for item in transactions if record_id in _payku_transaction_subscription_ids(item)], "transaction"
            )),
        ]
    if resource_type == "transaction":
        subscription_ids = _payku_transaction_subscription_ids(record)
        return [_related("Suscripciones", "subscription", _canonical_items(
            [item for item in subscriptions if item.external_id in subscription_ids], "subscription"
        ))]
    return []


@router.get("/{source}/{resource_type}/{external_id}", tags=["Staging"])
def provider_record_detail(
    source: str,
    resource_type: str,
    external_id: str,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    allowed_resources = {
        "toku": {"customer", "subscription", "payment_method", "invoice", "transaction"},
        "payku": {"client", "plan", "subscription", "transaction"},
    }
    if resource_type not in allowed_resources.get(source, set()):
        raise HTTPException(status_code=404, detail="Unknown staging resource")
    _require_source_access(current_user, source, resource_type)
    if source == "toku":
        model = _TOKU_MODEL[resource_type]
        record = db.scalar(select(model).where(model.source == "toku", model.external_id == external_id))
        if record is None:
            raise HTTPException(status_code=404, detail="Staging record not found")
        related = _toku_canonical_related(record, resource_type, db)
        return {"record": _cstg(record, resource_type), "related": _permitted_related(current_user, source, related)}
    if source == "payku":
        model = _PAYKU_MODEL[resource_type]
        record = db.scalar(select(model).where(model.source == "payku", model.external_id == external_id))
        if record is None:
            raise HTTPException(status_code=404, detail="Staging record not found")
        related = _payku_canonical_related(record, resource_type, db)
        return {"record": _cstg(record, resource_type), "related": _permitted_related(current_user, source, related)}
    records = db.scalars(select(SourceRecord).where(SourceRecord.source == source)).all()
    record = next((item for item in records if item.resource_type == resource_type and item.external_id == external_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail="Staging record not found")
    related = _toku_related(record, records) if source == "toku" else _payku_related(record, records)
    return {"record": _serialize(record), "related": _permitted_related(current_user, source, related)}


@router.get("/summary", dependencies=[Depends(require_permissions("dashboard.view"))], tags=["Staging"])
def staging_summary(db: Session = Depends(get_db)) -> dict[str, list[dict[str, Any]]]:  # noqa: B008
    sources = []
    for source in SOURCES:
        if source == "toku":
            resource_counts = {
                resource: db.scalar(select(func.count()).select_from(model).where(model.source == source)) or 0
                for resource, model in _TOKU_MODEL.items()
            }
        elif source == "payku":
            resource_counts = {
                resource: db.scalar(select(func.count()).select_from(model).where(model.source == source)) or 0
                for resource, model in _PAYKU_MODEL.items()
            }
        else:  # virtualpos
            resource_counts = {
                rtype: db.scalar(
                    select(func.count()).select_from(model).where(model.source.in_(_VP_SRCS))
                ) or 0
                for rtype, model in _VP_MODEL.items()
            }
        vp_sources = _VP_SRCS if source == "virtualpos" else (source,)
        latest_run = db.scalars(
            select(SyncRun).where(SyncRun.source.in_(vp_sources)).order_by(SyncRun.started_at.desc()).limit(1)
        ).first()
        sources.append(
            {
                "source": source,
                "records": sum(resource_counts.values()),
                "resources": resource_counts,
                "last_sync": (
                    {
                        "id": str(latest_run.id),
                        "status": latest_run.status,
                        "started_at": latest_run.started_at,
                        "finished_at": latest_run.finished_at,
                        "records_processed": latest_run.records_processed,
                    }
                    if latest_run
                    else None
                ),
            }
        )
    return {"sources": sources}


@router.get("/dashboard/general", dependencies=[Depends(require_permissions("dashboard.view"))], tags=["Staging"])
def general_dashboard(db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    """Aggregate operational metrics from every canonical channel."""
    return _general_dashboard(db)


@router.get("/dashboard/general/clients", dependencies=[Depends(require_permissions("dashboard.view"))], tags=["Staging"])
def general_clients(
    db: Session = Depends(get_db),  # noqa: B008
    query: str | None = None,
    offset: PaginationOffset = 0,
    limit: PaginationLimit = 50,
) -> dict[str, Any]:
    items = _general_clients(db, query)
    return {"items": items[offset : offset + limit], "total": len(items), "offset": offset, "limit": limit}


@router.get("/dashboard/general/clients/{rut}", dependencies=[Depends(require_permissions("dashboard.view"))], tags=["Staging"])
def general_client_detail(rut: str, db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    if not _general_clients(db, rut):
        raise HTTPException(status_code=404, detail="Client not found")
    return _general_client_detail(db, rut)


@router.get("/dashboard/{source}", tags=["Staging"])
def channel_dashboard(
    source: str,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    _require_source_access(current_user, source)
    if source.startswith("virtualpos"):
        return _vp_canonical_dashboard(source, db)
    if source == "toku":
        return _toku_canonical_dashboard(db)
    if source == "payku":
        return _payku_canonical_dashboard(db)
    if source not in SOURCES:
        raise HTTPException(status_code=404, detail="Unknown staging source")

    records = db.scalars(select(SourceRecord).where(SourceRecord.source == source)).all()
    resource_counts = Counter(record.resource_type for record in records)
    resource_amounts: dict[str, float] = defaultdict(float)
    status_counts: Counter[tuple[str, str]] = Counter()
    activity_by_month: dict[tuple[int, int], dict[str, float]] = defaultdict(lambda: {"count": 0, "amount": 0})
    activity_resource, date_path, amount_path, _ = ACTIVITY_FIELDS[source]

    for record in records:
        amount_value = _payload_value(record.payload, ("amount",))
        if amount_value is None:
            amount_value = _payload_value(record.payload, ("order", "amount"))
        if amount_value is not None:
            resource_amounts[record.resource_type] += _amount(amount_value)
        status = _payload_value(record.payload, ("status",))
        if status is None:
            status = _payload_value(record.payload, ("order", "status"))
        if status is not None:
            status_counts[(record.resource_type, str(status))] += 1
        if record.resource_type != activity_resource:
            continue
        month = _month(_payload_value(record.payload, date_path))
        if month is None:
            continue
        activity = activity_by_month[month]
        activity["count"] += 1
        activity["amount"] += _amount(_payload_value(record.payload, amount_path))

    latest_run = db.scalars(
        select(SyncRun).where(SyncRun.source == source).order_by(SyncRun.started_at.desc()).limit(1)
    ).first()
    activity = [
        {"year": year, "month": month, "count": int(values["count"]), "amount": values["amount"]}
        for (year, month), values in sorted(activity_by_month.items())
    ]
    extended: dict[str, Any] = {}
    if source == "virtualpos":
        extended = _vp_extended_data(records)
    elif source == "toku":
        extended = _toku_extended_data(records)
    elif source == "payku":
        extended = _payku_extended_data(records)
    return {
        "source": source,
        "records": len(records),
        "resources": dict(resource_counts),
        "resource_amounts": {resource: round(total, 2) for resource, total in resource_amounts.items()},
        "statuses": [
            {"resource": resource, "status": status, "count": count}
            for (resource, status), count in sorted(status_counts.items())
        ],
        "activity_resource": activity_resource,
        "activity": activity,
        "years": sorted({entry["year"] for entry in activity}, reverse=True),
        "last_sync": (
            {
                "status": latest_run.status,
                "started_at": latest_run.started_at,
                "finished_at": latest_run.finished_at,
                "records_processed": latest_run.records_processed,
            }
            if latest_run
            else None
        ),
        **extended,
    }


@router.post(
    "/sync/{source}",
    dependencies=[Depends(require_permissions("sync.run")), Depends(require_csrf)],
    tags=["Staging"],
)
async def trigger_channel_sync(
    source: str,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> dict[str, Any]:
    _require_source_access(current_user, source)
    if source not in SOURCES:
        raise HTTPException(status_code=404, detail="Unknown staging source")

    _sync_fn = {"virtualpos": sync_virtualpos, "toku": sync_toku, "payku": sync_payku}
    run = await _sync_fn[source](db)
    consolidate_to_canonical(db, [source])
    return {
        "run_id": str(run.id),
        "status": run.status,
        "records_processed": run.records_processed,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "error_message": run.error_message,
    }
