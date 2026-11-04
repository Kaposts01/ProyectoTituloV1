"""Materialize Toku provider tables (tk_*) into Core entities.

Run order: client attributes → subscriptions → charges → payments
Idempotent: safe to re-run.

tk_invoices  → CoreCharge  (linked to CoreSubscription)
tk_payments  → CorePayment (linked to CoreCharge, subscription via charge)
tk_transactions are not materialized as entities by default; the FAILED ones feed
core_charges.latest_rejection_* (see toku_rejection_projection.py) and, only with
TOKU_MATERIALIZE_FAILED_PAYMENTS=true (RJ-15), also become core_payments with
source_status='FAILED' (see toku_failed_payments.py).

Las senales del reporte (`compute_report_signals`, TK-20) alimentan la «suscripcion activa efectiva» de los KPIs de Toku
(MRR, ARPU y activas; TK-13, DEC-18): ver toku_active.py. Con TOKU_REPORT_SIGNALS_ENABLED apagada manda la API.
"""

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import distinct, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
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
from app.services.toku_failed_payments import materialize_failed_toku_payments
from app.services.toku_rejection_projection import project_toku_rejections
from app.services.toku_report_lifecycle import report_product_dates
from app.services.toku_report_signals import compute_report_signals

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
    customers = db.scalars(select(TokuCustomer)).all()

    identity_index: dict[str, uuid.UUID | None] = {}
    for row in db.execute(
        select(ExternalIdentity.external_id, ExternalIdentity.client_id).where(
            ExternalIdentity.source == _SOURCE,
            ExternalIdentity.resource_type == "client",
        )
    ):
        identity_index[row.external_id] = row.client_id

    rows: list[dict] = []
    for c in customers:
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

    # last_payment_status: status of most recent invoice per subscription (by due_date)
    _inv_latest: dict[str, tuple[str, str | None]] = {}
    for row in db.execute(
        select(TokuInvoice.subscription_id, TokuInvoice.due_date, TokuInvoice.status)
        .where(TokuInvoice.subscription_id.is_not(None))
    ):
        prev = _inv_latest.get(row.subscription_id)
        inv_due = row.due_date or ""
        if prev is None or inv_due > prev[0]:
            _inv_latest[row.subscription_id] = (inv_due, row.status)
    last_invoice_status: dict[str, str | None] = {k: v[1] for k, v in _inv_latest.items()}

    subscriptions = db.scalars(select(TokuSubscription)).all()

    rows = []
    for s in subscriptions:
        client_id = identity_index.get(s.customer_id) if s.customer_id else None
        rows.append({
            "id": uuid.uuid4(),
            "client_id": client_id,
            "source": _SOURCE,
            "external_id": s.external_id,
            "status": s.status,
            "last_payment_status": last_invoice_status.get(s.external_id),
            "amount": _parse_amount(s.amount),
            "currency": s.currency_code or _DEFAULT_CURRENCY,
            "started_at": None,  # anchor = próximo cobro, no fecha de inicio; la fecha real sale del reporte (PAR-05)
            "ended_at": _parse_date(s.end_date),
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
                # `started_at` solo lo escribe el reporte (materialize_report_dates); un sync de la API nunca lo borra.
                # `ended_at` de la API (mas confiable) se respeta, pero un NULL de la API no borra la baja del reporte.
                "ended_at": func.coalesce(ins.excluded.ended_at, CoreSubscription.ended_at),
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


# ── Paso 2.6: fechas reales de alta y baja desde el reporte de Productos (TK-PAR-05) ──

def materialize_report_dates(db: Session, *, dry_run: bool = False) -> dict[str, int | bool]:
    """Completa `core_subscriptions.started_at/ended_at` y crea las bajas que la API ya no lista.

    Fuente: `tk_report_products` (cargado con el importador de reportes; sin datos personales).
    * `started_at` = `Fecha de Creacion` del producto (la API solo trae el proximo cobro).
    * `ended_at` = `Fecha de Eliminacion`, SOLO si esta vacio: una fecha de baja de la API es mas confiable y no se pisa.
    * Un producto eliminado que no existe en core (la API no lo lista) se crea como registro de baja
      (`status='deleted_at_source'`, mismas reglas que los stubs), con su fecha de alta y de baja, monto del reporte y el
      cliente si su identidad ya existe. Un producto vivo ausente de core se cuenta y se omite (lo traera el sync).
    Idempotente. `dry_run=True` calcula los mismos contadores sin escribir nada.
    """
    stats: dict[str, int | bool] = {
        "products_in_report": 0,
        "started_at_set": 0,
        "ended_at_set": 0,
        "deleted_created": 0,
        "live_not_in_core": 0,
        "dry_run": dry_run,
    }
    products = report_product_dates(db)
    stats["products_in_report"] = len(products)
    if not products:
        return stats

    core = {
        row.external_id: row
        for row in db.execute(
            select(CoreSubscription.id, CoreSubscription.external_id, CoreSubscription.started_at, CoreSubscription.ended_at)
            .where(CoreSubscription.source == _SOURCE)
        )
    }
    identity_index = {
        row.external_id: row.client_id
        for row in db.execute(
            select(ExternalIdentity.external_id, ExternalIdentity.client_id).where(
                ExternalIdentity.source == _SOURCE, ExternalIdentity.resource_type == "client"
            )
        )
    }

    updates: list[dict] = []
    creates: list[dict] = []
    for sub_id, product in products.items():
        existing = core.get(sub_id)
        if existing is None:
            if product.deleted_at is None:
                stats["live_not_in_core"] += 1
                continue
            creates.append({
                "id": uuid.uuid4(),
                "client_id": identity_index.get(product.customer_external_id),
                "source": _SOURCE,
                "external_id": sub_id,
                "status": "deleted_at_source",
                "amount": product.amount,
                "currency": _DEFAULT_CURRENCY,
                "started_at": product.created_at,
                "ended_at": product.deleted_at,
            })
            continue
        change: dict = {}
        if product.created_at is not None and existing.started_at != product.created_at:
            change["started_at"] = product.created_at
        if product.deleted_at is not None and existing.ended_at is None:
            change["ended_at"] = product.deleted_at
        if change:
            updates.append({"id": existing.id, **change})

    stats["started_at_set"] = sum(1 for u in updates if "started_at" in u) + sum(1 for c in creates if c["started_at"])
    stats["ended_at_set"] = sum(1 for u in updates if "ended_at" in u) + len(creates)
    stats["deleted_created"] = len(creates)
    if dry_run:
        return stats

    for i in range(0, len(creates), _BATCH):
        db.execute(
            insert(CoreSubscription)
            .values(creates[i : i + _BATCH])
            .on_conflict_do_nothing(constraint="uq_core_subscription_source_external_id")
        )
    now = datetime.now(tz=timezone.utc)
    for u in updates:
        db.execute(
            update(CoreSubscription)
            .where(CoreSubscription.id == u["id"])
            .values({**{k: v for k, v in u.items() if k != "id"}, "updated_at": now})
        )
    return stats


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
        due = _parse_date(inv.due_date)
        rows.append({
            "id": uuid.uuid4(),
            "subscription_id": sub_id,
            "source": _SOURCE,
            "external_id": inv.external_id,
            "period_reference": due.strftime("%Y-%m") if due else None,
            "due_at": due,
            "amount": _parse_amount(inv.amount),
            "currency": _DEFAULT_CURRENCY,
            "source_status": inv.status,
        })

    if skipped:
        log.warning("Toku Core ETL: %d invoices sin suscripción Core omitidos", skipped)

    before = db.scalar(select(func.count()).select_from(CoreCharge).where(CoreCharge.source == _SOURCE)) or 0
    for i in range(0, len(rows), _BATCH):
        ins = insert(CoreCharge).values(rows[i : i + _BATCH])
        db.execute(ins.on_conflict_do_update(
            constraint="uq_core_charge_source_external_id",
            set_={
                "period_reference": ins.excluded.period_reference,
                "due_at": ins.excluded.due_at,
                "amount": ins.excluded.amount,
                "currency": ins.excluded.currency,
                "source_status": ins.excluded.source_status,
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

    report_dates: dict[str, int | bool] = {"started_at_set": 0, "ended_at_set": 0, "deleted_created": 0}
    log.info("Toku Core ETL — fechas de alta y baja desde el reporte de Productos")
    try:
        with db.begin_nested():
            report_dates = materialize_report_dates(db)
    except Exception:
        log.exception("Toku Core ETL — no se pudieron aplicar las fechas del reporte de Productos")
    log.info("Toku Core ETL — fechas del reporte: %s", report_dates)

    report_signals: dict | None = None
    if settings.toku_report_signals_enabled:  # TK-20: apagada por defecto; ver toku_report_signals.py
        log.info("Toku Core ETL — señales y estado desde los reportes")
        try:
            with db.begin_nested():
                report_signals = compute_report_signals(db)
        except Exception:
            log.exception("Toku Core ETL — no se pudieron calcular las señales de los reportes")
            report_signals = {"error": True}

    log.info("Toku Core ETL — materializando cargos (invoices)")
    charges = _materialize_charges(db)
    log.info("Toku Core ETL — cargos upserted: %d", charges)

    log.info("Toku Core ETL — materializando pagos")
    payments = _materialize_payments(db)
    log.info("Toku Core ETL — pagos insertados: %d", payments)

    log.info("Toku Core ETL — proyectando último rechazo a los cargos")
    rejections = project_toku_rejections(db)
    log.info("Toku Core ETL — cargos con rechazo proyectado: %d", rejections["charges_updated"])

    failed_written: int | None = None
    if settings.toku_materialize_failed_payments:  # RJ-15 (D4): apagada por defecto; ver toku_failed_payments.py
        log.info("Toku Core ETL — materializando intentos FAILED como pagos")
        try:
            with db.begin_nested():
                failed_written = materialize_failed_toku_payments(db)["written"]
        except Exception:
            log.exception("Toku Core ETL — no se pudieron materializar los intentos FAILED")
            failed_written = 0

    db.commit()
    result = {
        "clients_created": clients_created,
        "attributes_inserted": attrs,
        "subscriptions_upserted": subs,
        "stub_subscriptions_created": stubs,
        "report_started_at_set": report_dates["started_at_set"],
        "report_ended_at_set": report_dates["ended_at_set"],
        "report_deleted_created": report_dates["deleted_created"],
        "charges_upserted": charges,
        "payments_inserted_or_linked": payments,
        "charges_rejection_projected": rejections["charges_updated"],
    }
    if failed_written is not None:
        result["failed_payments_materialized"] = failed_written
    if report_signals is not None:
        result["report_signals"] = report_signals
    return result
