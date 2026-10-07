"""Materialize TCH provider tables (tch_*) into Core entities.

Run order: client attributes → subscriptions → payments
Idempotent: safe to re-run; uses ON CONFLICT DO NOTHING / DO UPDATE per entity.

TCH has no CoreCharge concept — tch_transacciones map directly to CorePayment.
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
from app.models.tch import TchCliente, TchSuscripcion, TchTransaccion
from app.services.core_materialization import materialize_core_clients

log = logging.getLogger(__name__)

_BATCH = 500
_SOURCE = "tch"


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
        return Decimal(str(value).replace(".", "").replace(",", ".").strip())
    except InvalidOperation:
        return None


def _resolve_currency(suscripcion: TchSuscripcion) -> str:
    reajuste = (suscripcion.reajuste or "").strip().upper()
    return "UF" if reajuste == "UF" else "CLP"


# ── Paso 1: atributos de cliente ──────────────────────────────────────────────

def _materialize_client_attributes(db: Session) -> int:
    """Upsert observable PII attributes for each TCH client."""
    clientes = db.scalars(select(TchCliente)).all()

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
        if not c.rut:
            continue
        client_id = identity_index.get(c.rut)
        observed = c.updated_at or c.created_at

        nombre_completo = " ".join(filter(None, [c.nombre, c.apellido])).strip() or None
        for attr_type, attr_val in [
            ("name", nombre_completo),
            ("rut", c.rut),
            ("email", c.email),
            ("phone", c.telefono),
        ]:
            if attr_val and attr_val.strip():
                rows.append({
                    "id": uuid.uuid4(),
                    "client_id": client_id,
                    "source": _SOURCE,
                    "attribute_type": attr_type,
                    "attribute_value": attr_val.strip(),
                    "observed_at": observed,
                })

    before = db.scalar(select(func.count()).select_from(CoreClientAttribute).where(CoreClientAttribute.source == _SOURCE)) or 0
    for i in range(0, len(rows), _BATCH):
        batch = rows[i : i + _BATCH]
        db.execute(
            insert(CoreClientAttribute)
            .values(batch)
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

    suscripciones = db.scalars(select(TchSuscripcion)).all()

    rows = []
    for s in suscripciones:
        client_id = identity_index.get(s.cliente_rut) if s.cliente_rut else None
        rows.append({
            "id": uuid.uuid4(),
            "client_id": client_id,
            "source": _SOURCE,
            "external_id": str(s.numero_ficha),
            "status": s.estado,
            "amount": _parse_amount(s.monto),
            "currency": _resolve_currency(s),
            "started_at": _parse_date(s.fecha_activacion),
            "ended_at": _parse_date(s.fecha_eliminacion),
        })

    before = db.scalar(select(func.count()).select_from(CoreSubscription).where(CoreSubscription.source == _SOURCE)) or 0
    for i in range(0, len(rows), _BATCH):
        batch = rows[i : i + _BATCH]
        ins = insert(CoreSubscription).values(batch)
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

    transacciones = db.scalars(select(TchTransaccion)).all()

    rows = []
    skipped = 0
    for t in transacciones:
        if not t.dedupe_key:
            skipped += 1
            continue
        sub_id = sub_index.get(str(t.numero_ficha))
        rows.append({
            "id": uuid.uuid4(),
            "source": _SOURCE,
            "external_id": t.dedupe_key,
            "subscription_id": sub_id,
            "charge_id": None,
            "source_status": t.estado,
            "occurred_at": _parse_date(t.fecha_cargo),
            "amount": _parse_amount(t.monto),
            "currency": "CLP",
            "rejection_code": t.codigo_respuesta if t.estado and "RECHAZ" in t.estado.upper() else None,
            "rejection_reason": t.razon_rechazo if t.estado and "RECHAZ" in t.estado.upper() else None,
            "rejection_reported_at": None,
        })

    if skipped:
        log.warning("TCH Core ETL: %d transacciones sin dedupe_key omitidas", skipped)

    before = db.scalar(select(func.count()).select_from(CorePayment).where(CorePayment.source == _SOURCE)) or 0
    for i in range(0, len(rows), _BATCH):
        batch = rows[i : i + _BATCH]
        db.execute(
            insert(CorePayment)
            .values(batch)
            .on_conflict_do_nothing(constraint="uq_core_payment_source_external_id")
        )
    after = db.scalar(select(func.count()).select_from(CorePayment).where(CorePayment.source == _SOURCE)) or 0
    return after - before


# ── Punto de entrada ──────────────────────────────────────────────────────────

def run_tch_core_etl(db: Session) -> dict[str, int]:
    """Materialize all TCH data into Core. Returns counts per entity."""
    log.info("TCH Core ETL — iniciando materialización de clientes")
    clients_created = materialize_core_clients(db, ["tch"])
    log.info("TCH Core ETL — clientes nuevos: %d", clients_created)

    log.info("TCH Core ETL — materializando atributos de cliente")
    attrs = _materialize_client_attributes(db)
    log.info("TCH Core ETL — atributos insertados: %d", attrs)

    log.info("TCH Core ETL — materializando suscripciones")
    subs = _materialize_subscriptions(db)
    log.info("TCH Core ETL — suscripciones upserted: %d", subs)

    log.info("TCH Core ETL — materializando pagos")
    payments = _materialize_payments(db)
    log.info("TCH Core ETL — pagos insertados: %d", payments)

    db.commit()
    return {
        "clients_created": clients_created,
        "attributes_inserted": attrs,
        "subscriptions_upserted": subs,
        "payments_inserted": payments,
    }
