"""Materialize Toku provider tables (tk_*) into Core entities.

Run order: client attributes → subscriptions → charges → payments
Idempotent: safe to re-run.

tk_invoices  → CoreCharge  (linked to CoreSubscription)
tk_payments  → CorePayment (linked to CoreCharge, subscription via charge)
tk_transactions are card-tokenization/method events and are not materialized here.
"""

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import distinct, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.core import (
    CoreCharge,
    CoreClientAttribute,
    CorePayment,
    CoreSubscription,
    ExternalIdentity,
)
from app.models.toku_channel import (
    TokuCustomer,
    TokuInvoice,
    TokuPayment,
    TokuSubscription,
)
from app.services.core_materialization import materialize_core_clients

log = logging.getLogger(__name__)

_BATCH = 500
_SOURCE = "toku"
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
        return Decimal(str(value).replace(",", ".").strip()).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


# ── Paso 1: atributos de cliente ──────────────────────────────────────────────

def _materialize_client_attributes(db: Session) -> int:
    clientes = db.scalars(select(TokuCustomer)).all()

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
            ("phone", c.phone_number),
            ("rut", c.government_id),
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

    suscripciones = db.scalars(select(TokuSubscription)).all()

    rows = []
    for s in suscripciones:
        client_id = identity_index.get(s.customer_id) if s.customer_id else None
        rows.append({
            "id": uuid.uuid4(),
            "client_id": client_id,
            "source": _SOURCE,
            "external_id": s.external_id,
            "status": s.status,
            "amount": _parse_amount(s.amount),
            "currency": s.currency_code or _DEFAULT_CURRENCY,
            "started_at": _parse_date(s.anchor),
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


# ── Paso 2.5: stubs para suscripciones eliminadas en el origen ───────────────

def _materialize_stub_subscriptions(db: Session) -> int:
    """Create minimal CoreSubscription stubs for invoices whose subscription no longer
    exists in the Toku API (typically cancelled/deleted before or between syncs).

    Chosen approach — Option A: create stubs with status='deleted_at_source'.
    Rejected alternative — Option B: leave the 564 PAID invoices/payments with
    charge_id=NULL and subscription_id=NULL (floated payments with no traceability).
    Option A was preferred to preserve the payment→charge→subscription chain for
    financial reporting. Stubs can be enriched if the Toku sync is extended to
    capture historical cancelled subscriptions.
    See: docs/integrations/toku.md § Suscripciones eliminadas en el origen.
    """
    orphan_ids = db.scalars(
        select(distinct(TokuInvoice.subscription_id)).where(
            TokuInvoice.subscription_id.isnot(None),
            ~exists(
                select(CoreSubscription.id).where(
                    CoreSubscription.source == _SOURCE,
                    CoreSubscription.external_id == TokuInvoice.subscription_id,
                )
            ),
        )
    ).all()

    if not orphan_ids:
        return 0

    stubs = [
        {
            "id": uuid.uuid4(),
            "client_id": None,
            "source": _SOURCE,
            "external_id": sub_id,
            "status": "deleted_at_source",
            "amount": None,
            "currency": _DEFAULT_CURRENCY,
            "started_at": None,
            "ended_at": None,
        }
        for sub_id in orphan_ids
    ]

    before = db.scalar(
        select(func.count()).select_from(CoreSubscription).where(
            CoreSubscription.source == _SOURCE,
            CoreSubscription.status == "deleted_at_source",
        )
    ) or 0
    for i in range(0, len(stubs), _BATCH):
        db.execute(
            insert(CoreSubscription)
            .values(stubs[i : i + _BATCH])
            .on_conflict_do_nothing(constraint="uq_core_subscription_source_external_id")
        )
    after = db.scalar(
        select(func.count()).select_from(CoreSubscription).where(
            CoreSubscription.source == _SOURCE,
            CoreSubscription.status == "deleted_at_source",
        )
    ) or 0
    return after - before


# ── Paso 3: cargos (invoices) ─────────────────────────────────────────────────

def _materialize_charges(db: Session) -> int:
    sub_index: dict[str, uuid.UUID] = {}
    for row in db.execute(
        select(CoreSubscription.external_id, CoreSubscription.id).where(
            CoreSubscription.source == _SOURCE
        )
    ):
        sub_index[row.external_id] = row.id

    invoices = db.scalars(select(TokuInvoice)).all()

    rows = []
    skipped = 0
    for inv in invoices:
        sub_id = sub_index.get(inv.subscription_id) if inv.subscription_id else None
        if sub_id is None:
            skipped += 1
            continue
        rows.append({
            "id": uuid.uuid4(),
            "subscription_id": sub_id,
            "source": _SOURCE,
            "external_id": inv.external_id,
            "period_reference": None,
            "due_at": _parse_date(inv.due_date),
            "amount": _parse_amount(inv.amount),
            "currency": _DEFAULT_CURRENCY,
        })

    if skipped:
        log.warning("Toku Core ETL: %d invoices sin suscripción Core omitidos", skipped)

    before = db.scalar(select(func.count()).select_from(CoreCharge).where(CoreCharge.source == _SOURCE)) or 0
    for i in range(0, len(rows), _BATCH):
        ins = insert(CoreCharge).values(rows[i : i + _BATCH])
        db.execute(ins.on_conflict_do_update(
            constraint="uq_core_charge_source_external_id",
            set_={
                "due_at": ins.excluded.due_at,
                "amount": ins.excluded.amount,
                "currency": ins.excluded.currency,
                "updated_at": datetime.now(tz=timezone.utc),
            },
        ))
    after = db.scalar(select(func.count()).select_from(CoreCharge).where(CoreCharge.source == _SOURCE)) or 0
    return after - before


# ── Paso 4: pagos ─────────────────────────────────────────────────────────────

def _materialize_payments(db: Session) -> int:
    # Índice CoreCharge: invoice external_id → (charge_id, subscription_id)
    charge_index: dict[str, tuple[uuid.UUID, uuid.UUID | None]] = {}
    for row in db.execute(
        select(CoreCharge.external_id, CoreCharge.id, CoreCharge.subscription_id).where(
            CoreCharge.source == _SOURCE
        )
    ):
        charge_index[row.external_id] = (row.id, row.subscription_id)

    payments = db.scalars(select(TokuPayment)).all()

    rows = []
    for p in payments:
        charge_entry = charge_index.get(p.invoice_id) if p.invoice_id else None
        charge_id = charge_entry[0] if charge_entry else None
        subscription_id = charge_entry[1] if charge_entry else None
        rows.append({
            "id": uuid.uuid4(),
            "source": _SOURCE,
            "external_id": p.external_id,
            "subscription_id": subscription_id,
            "charge_id": charge_id,
            "source_status": None,
            "occurred_at": _parse_date(p.transaction_date),
            "amount": _parse_amount(p.amount),
            "currency": _DEFAULT_CURRENCY,
            "rejection_code": None,
            "rejection_reason": None,
            "rejection_reported_at": None,
        })

    unlinked_before = db.scalar(
        select(func.count()).select_from(CorePayment).where(
            CorePayment.source == _SOURCE, CorePayment.charge_id.is_(None)
        )
    ) or 0
    total_before = db.scalar(select(func.count()).select_from(CorePayment).where(CorePayment.source == _SOURCE)) or 0
    for i in range(0, len(rows), _BATCH):
        ins = insert(CorePayment).values(rows[i : i + _BATCH])
        db.execute(ins.on_conflict_do_update(
            constraint="uq_core_payment_source_external_id",
            set_={
                "charge_id": ins.excluded.charge_id,
                "subscription_id": ins.excluded.subscription_id,
                "updated_at": datetime.now(tz=timezone.utc),
            },
            where=CorePayment.charge_id.is_(None),
        ))
    total_after = db.scalar(select(func.count()).select_from(CorePayment).where(CorePayment.source == _SOURCE)) or 0
    unlinked_after = db.scalar(
        select(func.count()).select_from(CorePayment).where(
            CorePayment.source == _SOURCE, CorePayment.charge_id.is_(None)
        )
    ) or 0
    return (total_after - total_before) + (unlinked_before - unlinked_after)


# ── Punto de entrada ──────────────────────────────────────────────────────────

def run_toku_core_etl(db: Session) -> dict[str, int]:
    """Materialize all Toku data into Core. Returns counts per entity."""
    log.info("Toku Core ETL — materializando clientes")
    clients_created = materialize_core_clients(db, ["toku"])
    log.info("Toku Core ETL — clientes nuevos: %d", clients_created)

    log.info("Toku Core ETL — materializando atributos de cliente")
    attrs = _materialize_client_attributes(db)
    log.info("Toku Core ETL — atributos insertados: %d", attrs)

    log.info("Toku Core ETL — materializando suscripciones")
    subs = _materialize_subscriptions(db)
    log.info("Toku Core ETL — suscripciones upserted: %d", subs)

    log.info("Toku Core ETL — creando stubs para suscripciones eliminadas en origen")
    stubs = _materialize_stub_subscriptions(db)
    log.info("Toku Core ETL — stubs creados: %d", stubs)

    log.info("Toku Core ETL — materializando cargos (invoices)")
    charges = _materialize_charges(db)
    log.info("Toku Core ETL — cargos upserted: %d", charges)

    log.info("Toku Core ETL — materializando pagos")
    payments = _materialize_payments(db)
    log.info("Toku Core ETL — pagos insertados: %d", payments)

    db.commit()
    return {
        "clients_created": clients_created,
        "attributes_inserted": attrs,
        "subscriptions_upserted": subs,
        "stub_subscriptions_created": stubs,
        "charges_upserted": charges,
        "payments_inserted_or_linked": payments,
    }
