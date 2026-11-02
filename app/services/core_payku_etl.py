"""Materialize Payku provider tables (p_*) into Core entities.

Run order: client attributes → subscriptions → payments
Idempotent: safe to re-run.

Payku has no CoreCharge concept — p_transactions map directly to CorePayment.
Rejected transactions carry amount=0; no rejection code/reason is available
in the current payload format.
"""

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.core import (
    CoreClientAttribute,
    CorePayment,
    CoreSubscription,
    ExternalIdentity,
)
from app.models.payku_channel import PaykuClient, PaykuSubscription, PaykuTransaction
from app.services.channel_consolidation import _payku_last_transition_date
from app.services.core_materialization import materialize_core_clients
from app.services.rejected_month import CHILE_TZ

log = logging.getLogger(__name__)

_BATCH = 500
_SOURCE = "payku"
_DEFAULT_CURRENCY = "CLP"
# Estados vigentes: una transicion hacia ellos es un alta, no un termino.
_ACTIVE_STATUSES = frozenset({"active", "register", "suspended_awaits_change_plan"})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value)[:10])
        return d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _parse_datetime_cl(value: str | None) -> datetime | None:
    """Fecha y hora de una transaccion Payku como instante con zona (PK-PAR-04).

    Payku entrega `created_at` sin zona (`2023-09-30 19:58:35`, hora de Chile); antes se truncaba a la fecha y se
    asumia UTC, lo que perdia la hora y corria al mes anterior los cobros de la noche del ultimo dia. Ahora:
    - texto sin zona -> hora local de America/Santiago (con su horario de verano);
    - texto con zona (`Z`, `+00:00`) -> se respeta;
    - solo fecha -> 00:00 de Chile; tambien acepta `DD-MM-AAAA HH:MM:SS` (formato de las notificaciones).
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=CHILE_TZ)


def _parse_amount(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(str(value).strip())
    except InvalidOperation:
        return None


def _ended_at(s: PaykuSubscription) -> datetime | None:
    """Fecha de termino (PK-PAR-03): `change_date` mas reciente de `logs.status[]` con `final_status` igual al
    estado actual; sin esa transicion, `end_date`. Para estados vigentes solo `end_date` (como antes)."""
    status = (s.status or "").lower()
    if status and status not in _ACTIVE_STATUSES:
        payload = s.raw_payload if isinstance(s.raw_payload, dict) else {}
        transition = _parse_date(_payku_last_transition_date(payload, status))
        if transition is not None:
            return transition
    return _parse_date(s.end_date)


# ── Paso 1: atributos de cliente ──────────────────────────────────────────────

def _materialize_client_attributes(db: Session) -> int:
    clients = db.scalars(select(PaykuClient)).all()

    identity_index: dict[str, uuid.UUID | None] = {}
    for row in db.execute(
        select(ExternalIdentity.external_id, ExternalIdentity.client_id).where(
            ExternalIdentity.source == _SOURCE,
            ExternalIdentity.resource_type == "client",
        )
    ):
        identity_index[row.external_id] = row.client_id

    rows: list[dict] = []
    for c in clients:
        client_id = identity_index.get(c.external_id)
        observed = c.updated_at or c.created_at
        for attr_type, attr_val in [
            ("name", c.name),
            ("email", c.email),
            ("phone", c.phone),
            ("rut", c.rut),
        ]:
            if attr_val and str(attr_val).strip():
                rows.append({
                    "id": uuid.uuid4(),
                    "client_id": client_id,
                    "source": _SOURCE,
                    "attribute_type": attr_type,
                    "attribute_value": str(attr_val).strip(),
                    "observed_at": observed,
                })

    before = db.scalar(select(func.count()).select_from(CoreClientAttribute).where(CoreClientAttribute.source == _SOURCE)) or 0
    for i in range(0, len(rows), _BATCH):
        db.execute(
            insert(CoreClientAttribute)
            .values(rows[i : i + _BATCH])
            .on_conflict_do_nothing(constraint="uq_core_client_attribute")
        )
    after = db.scalar(select(func.count()).select_from(CoreClientAttribute).where(CoreClientAttribute.source == _SOURCE)) or 0
    return after - before


# ── Paso 2: suscripciones ─────────────────────────────────────────────────────

def _materialize_subscriptions(db: Session) -> int:
    identity_index: dict[str, uuid.UUID | None] = {}
    for row in db.execute(
        select(ExternalIdentity.external_id, ExternalIdentity.client_id).where(
            ExternalIdentity.source == _SOURCE,
            ExternalIdentity.resource_type == "client",
        )
    ):
        identity_index[row.external_id] = row.client_id

    subscriptions = db.scalars(select(PaykuSubscription)).all()

    rows = []
    for s in subscriptions:
        client_id = identity_index.get(s.client_id) if s.client_id else None
        rows.append({
            "id": uuid.uuid4(),
            "client_id": client_id,
            "source": _SOURCE,
            "external_id": s.external_id,
            "status": s.status,
            "last_payment_status": s.last_status_current_payment,
            "amount": _parse_amount(s.amount),
            "currency": s.currency or _DEFAULT_CURRENCY,
            "started_at": _parse_date(s.start_date),
            "ended_at": _ended_at(s),
        })

    before = db.scalar(select(func.count()).select_from(CoreSubscription).where(CoreSubscription.source == _SOURCE)) or 0
    for i in range(0, len(rows), _BATCH):
        ins = insert(CoreSubscription).values(rows[i : i + _BATCH])
        db.execute(ins.on_conflict_do_update(
            constraint="uq_core_subscription_source_external_id",
            set_={
                "status": ins.excluded.status,
                "last_payment_status": ins.excluded.last_payment_status,
                "amount": ins.excluded.amount,
                "currency": ins.excluded.currency,
                "started_at": ins.excluded.started_at,
                "ended_at": ins.excluded.ended_at,
                "updated_at": datetime.now(tz=timezone.utc),
            },
        ))
    after = db.scalar(select(func.count()).select_from(CoreSubscription).where(CoreSubscription.source == _SOURCE)) or 0
    return after - before


# ── Paso 3: pagos ─────────────────────────────────────────────────────────────

def _materialize_payments(db: Session) -> int:
    sub_index: dict[str, uuid.UUID] = {}
    for row in db.execute(
        select(CoreSubscription.external_id, CoreSubscription.id).where(
            CoreSubscription.source == _SOURCE
        )
    ):
        sub_index[row.external_id] = row.id

    transactions = db.scalars(select(PaykuTransaction)).all()

    rows = []
    skipped = 0
    for t in transactions:
        sub_id = sub_index.get(t.subscription_id) if t.subscription_id else None
        if sub_id is None:
            skipped += 1
            continue
        is_rejected = (t.status or "").lower() == "rejected"
        rows.append({
            "id": uuid.uuid4(),
            "source": _SOURCE,
            "external_id": t.external_id,
            "subscription_id": sub_id,
            "charge_id": None,
            "source_status": t.status,
            "occurred_at": _parse_datetime_cl(t.created_at_api),
            "amount": _parse_amount(t.amount),
            "currency": _DEFAULT_CURRENCY,
            "rejection_code": None,
            "rejection_reason": None,
            "rejection_reported_at": _parse_datetime_cl(t.created_at_api) if is_rejected else None,
        })

    if skipped:
        log.warning("Payku Core ETL: %d transacciones sin suscripción Core omitidas", skipped)

    before = db.scalar(select(func.count()).select_from(CorePayment).where(CorePayment.source == _SOURCE)) or 0
    for i in range(0, len(rows), _BATCH):
        db.execute(
            insert(CorePayment)
            .values(rows[i : i + _BATCH])
            .on_conflict_do_nothing(constraint="uq_core_payment_source_external_id")
        )
    after = db.scalar(select(func.count()).select_from(CorePayment).where(CorePayment.source == _SOURCE)) or 0
    _refresh_payment_times(db, {r["external_id"]: (r["occurred_at"], r["rejection_reported_at"]) for r in rows})
    return after - before


def _refresh_payment_times(db: Session, times: dict[str, tuple[datetime | None, datetime | None]]) -> int:
    """UPDATE explicito de `occurred_at`/`rejection_reported_at` de pagos ya existentes (PK-PAR-04).

    El insert usa `on_conflict_do_nothing`, asi que los pagos cargados con la fecha truncada a UTC nunca se
    corregirian solos. Solo cambia filas cuyo instante difiere. Idempotente. Devuelve las filas actualizadas.
    """
    updates: list[dict] = []
    for row in db.execute(
        select(CorePayment.id, CorePayment.external_id, CorePayment.occurred_at, CorePayment.rejection_reported_at)
        .where(CorePayment.source == _SOURCE)
    ):
        new = times.get(row.external_id)
        if new is None or new[0] is None:
            continue
        if (row.occurred_at, row.rejection_reported_at) != new:
            updates.append({"id": row.id, "occurred_at": new[0], "rejection_reported_at": new[1]})
    for i in range(0, len(updates), 1000):
        db.execute(update(CorePayment), updates[i : i + 1000])
    return len(updates)


# ── Punto de entrada ──────────────────────────────────────────────────────────

def run_payku_core_etl(db: Session) -> dict[str, int]:
    """Materialize all Payku data into Core. Returns counts per entity."""
    log.info("Payku Core ETL — materializando clientes")
    clients_created = materialize_core_clients(db, ["payku"])
    log.info("Payku Core ETL — clientes nuevos: %d", clients_created)

    log.info("Payku Core ETL — materializando atributos de cliente")
    attrs = _materialize_client_attributes(db)
    log.info("Payku Core ETL — atributos insertados: %d", attrs)

    log.info("Payku Core ETL — materializando suscripciones")
    subs = _materialize_subscriptions(db)
    log.info("Payku Core ETL — suscripciones upserted: %d", subs)

    log.info("Payku Core ETL — materializando pagos")
    payments = _materialize_payments(db)
    log.info("Payku Core ETL — pagos insertados: %d", payments)

    db.commit()
    return {
        "clients_created": clients_created,
        "attributes_inserted": attrs,
        "subscriptions_upserted": subs,
        "payments_inserted": payments,
    }
