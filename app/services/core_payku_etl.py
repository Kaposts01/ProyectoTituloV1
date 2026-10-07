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

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.core import (
    CoreClientAttribute,
    CorePayment,
    CoreSubscription,
    ExternalIdentity,
)
from app.models.payku_channel import PaykuClient, PaykuSubscription, PaykuTransaction
from app.services.core_materialization import materialize_core_clients

log = logging.getLogger(__name__)

_BATCH = 500
_SOURCE = "payku"
_DEFAULT_CURRENCY = "CLP"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value)[:10])
        return d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _parse_amount(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(str(value).strip())
    except InvalidOperation:
        return None


# ── Paso 1: atributos de cliente ──────────────────────────────────────────────

def _materialize_client_attributes(db: Session) -> int:
    clientes = db.scalars(select(PaykuClient)).all()

    identity_index: dict[str, uuid.UUID | None] = {}
    for row in db.execute(
        select(ExternalIdentity.external_id, ExternalIdentity.client_id).where(
            ExternalIdentity.source == _SOURCE,
            ExternalIdentity.resource_type == "client",
        )
    ):
        identity_index[row.external_id] = row.client_id

    rows: list[dict] = []
    for c in clientes:
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

    suscripciones = db.scalars(select(PaykuSubscription)).all()

    rows = []
    for s in suscripciones:
        client_id = identity_index.get(s.client_id) if s.client_id else None
        rows.append({
            "id": uuid.uuid4(),
            "client_id": client_id,
            "source": _SOURCE,
            "external_id": s.external_id,
            "status": s.status,
            "amount": _parse_amount(s.amount),
            "currency": s.currency or _DEFAULT_CURRENCY,
            "started_at": _parse_date(s.start_date),
            "ended_at": _parse_date(s.end_date),
        })

    before = db.scalar(select(func.count()).select_from(CoreSubscription).where(CoreSubscription.source == _SOURCE)) or 0
    for i in range(0, len(rows), _BATCH):
        ins = insert(CoreSubscription).values(rows[i : i + _BATCH])
        db.execute(ins.on_conflict_do_update(
            constraint="uq_core_subscription_source_external_id",
            set_={
                "status": ins.excluded.status,
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

    transacciones = db.scalars(select(PaykuTransaction)).all()

    rows = []
    skipped = 0
    for t in transacciones:
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
            "occurred_at": _parse_date(t.created_at_api),
            "amount": _parse_amount(t.amount),
            "currency": _DEFAULT_CURRENCY,
            "rejection_code": None,
            "rejection_reason": None,
            "rejection_reported_at": _parse_date(t.created_at_api) if is_rejected else None,
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
    return after - before


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
