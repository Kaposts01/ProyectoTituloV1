"""Materialize VirtualPOS provider tables (vp_*) into Core entities.

Covers both platforms: virtualpos1 and virtualpos2.
Run order: client attributes → subscriptions → charges → payments
Idempotent: safe to re-run.

Client linkage in subscriptions goes through social_id (RUT) because
vp_subscriptions.client_external_id is NULL for all records.

Payment → subscription linkage uses client RUT from the payment payload:
  - Exactly 1 subscription for that RUT on that platform → link it
  - 0 or 2+ subscriptions → subscription_id left NULL (ambiguous)
charge_id is always NULL for VP payments (no cross-reference exists in
the current payload format; see docs/integrations/virtualpos.md).
"""

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.core import (
    CoreCharge,
    CoreClientAttribute,
    CorePayment,
    CoreSubscription,
    ExternalIdentity,
)
from app.models.vp import VpCharge, VpClient, VpPayment, VpSubscription
from app.services.core_materialization import materialize_core_clients

log = logging.getLogger(__name__)

_BATCH = 500
_VP_SOURCES = ("virtualpos1", "virtualpos2")
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


# ── Índices compartidos ───────────────────────────────────────────────────────

def _build_identity_index(db: Session) -> dict[tuple[str, str], uuid.UUID | None]:
    """(source, external_id) → CoreClient.id"""
    return {
        (row.source, row.external_id): row.client_id
        for row in db.execute(
            select(ExternalIdentity.source, ExternalIdentity.external_id, ExternalIdentity.client_id).where(
                ExternalIdentity.source.in_(_VP_SOURCES),
                ExternalIdentity.resource_type == "client",
            )
        )
    }


def _build_social_id_index(db: Session) -> dict[tuple[str, str], str]:
    """(platform, social_id/RUT) → vp_client.external_id  (first match wins for rare duplicates)"""
    index: dict[tuple[str, str], str] = {}
    for c in db.scalars(select(VpClient).where(VpClient.social_id.isnot(None))):
        key = (c.platform, c.social_id)
        if key not in index:
            index[key] = c.external_id
    return index


# ── Paso 1: atributos de cliente ──────────────────────────────────────────────

def _materialize_client_attributes(db: Session, ext_to_core: dict) -> int:
    clientes = db.scalars(select(VpClient)).all()
    rows: list[dict] = []
    for c in clientes:
        client_id = ext_to_core.get((c.platform, c.external_id))
        observed = c.updated_at or c.created_at
        nombre = " ".join(filter(None, [c.first_name, c.last_name])).strip() or None
        for attr_type, attr_val in [
            ("name", nombre),
            ("email", c.email),
            ("phone", c.phone_number),
            ("rut", c.social_id),
        ]:
            if attr_val and str(attr_val).strip():
                rows.append({
                    "id": uuid.uuid4(),
                    "client_id": client_id,
                    "source": c.platform,
                    "attribute_type": attr_type,
                    "attribute_value": str(attr_val).strip(),
                    "observed_at": observed,
                })

    before = db.scalar(
        select(func.count()).select_from(CoreClientAttribute).where(
            CoreClientAttribute.source.in_(_VP_SOURCES)
        )
    ) or 0
    for i in range(0, len(rows), _BATCH):
        db.execute(
            insert(CoreClientAttribute)
            .values(rows[i : i + _BATCH])
            .on_conflict_do_nothing(constraint="uq_core_client_attribute")
        )
    after = db.scalar(
        select(func.count()).select_from(CoreClientAttribute).where(
            CoreClientAttribute.source.in_(_VP_SOURCES)
        )
    ) or 0
    return after - before


# ── Paso 2: suscripciones ─────────────────────────────────────────────────────

def _materialize_subscriptions(
    db: Session,
    social_to_ext: dict[tuple[str, str], str],
    ext_to_core: dict[tuple[str, str], uuid.UUID | None],
) -> int:
    suscripciones = db.scalars(select(VpSubscription)).all()
    rows = []
    for s in suscripciones:
        ext_id = social_to_ext.get((s.platform, s.client_social_id)) if s.client_social_id else None
        client_id = ext_to_core.get((s.platform, ext_id)) if ext_id else None
        rows.append({
            "id": uuid.uuid4(),
            "client_id": client_id,
            "source": s.platform,
            "external_id": s.external_id,
            "status": s.status,
            "amount": _parse_amount(s.amount),
            "currency": s.currency or _DEFAULT_CURRENCY,
            "started_at": _parse_date(s.suscription_date),
            "ended_at": _parse_date(s.canceled_at),
        })

    before = db.scalar(
        select(func.count()).select_from(CoreSubscription).where(
            CoreSubscription.source.in_(_VP_SOURCES)
        )
    ) or 0
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
    after = db.scalar(
        select(func.count()).select_from(CoreSubscription).where(
            CoreSubscription.source.in_(_VP_SOURCES)
        )
    ) or 0
    return after - before


# ── Paso 3: cargos ────────────────────────────────────────────────────────────

def _materialize_charges(db: Session) -> int:
    sub_index: dict[tuple[str, str], uuid.UUID] = {
        (row.source, row.external_id): row.id
        for row in db.execute(
            select(CoreSubscription.source, CoreSubscription.external_id, CoreSubscription.id).where(
                CoreSubscription.source.in_(_VP_SOURCES)
            )
        )
    }

    charges = db.scalars(select(VpCharge)).all()
    rows = []
    skipped = 0
    for c in charges:
        sub_id = sub_index.get((c.platform, c.subscription_external_id)) if c.subscription_external_id else None
        if sub_id is None:
            skipped += 1
            continue
        rows.append({
            "id": uuid.uuid4(),
            "subscription_id": sub_id,
            "source": c.platform,
            "external_id": c.external_id,
            "period_reference": None,
            "due_at": _parse_date(c.charge_date),
            "amount": _parse_amount(c.amount),
            "currency": c.currency or _DEFAULT_CURRENCY,
        })

    if skipped:
        log.warning("VP Core ETL: %d cargos sin suscripción Core omitidos", skipped)

    before = db.scalar(
        select(func.count()).select_from(CoreCharge).where(CoreCharge.source.in_(_VP_SOURCES))
    ) or 0
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
    after = db.scalar(
        select(func.count()).select_from(CoreCharge).where(CoreCharge.source.in_(_VP_SOURCES))
    ) or 0
    return after - before


# ── Paso 4: pagos ─────────────────────────────────────────────────────────────

def _build_rut_to_sub_index(db: Session) -> dict[tuple[str, str], list[uuid.UUID]]:
    """(platform, rut) → list of CoreSubscription.id for that platform+rut."""
    index: dict[tuple[str, str], list[uuid.UUID]] = {}
    for row in db.execute(
        select(VpSubscription.platform, VpSubscription.client_social_id, CoreSubscription.id)
        .join(
            CoreSubscription,
            and_(
                CoreSubscription.source == VpSubscription.platform,
                CoreSubscription.external_id == VpSubscription.external_id,
            ),
        )
        .where(
            VpSubscription.client_social_id.isnot(None),
            VpSubscription.platform.in_(_VP_SOURCES),
        )
        .distinct(VpSubscription.platform, VpSubscription.client_social_id, CoreSubscription.id)
    ):
        key = (row.platform, row.client_social_id)
        index.setdefault(key, []).append(row.id)
    return index


def _materialize_payments(db: Session, rut_to_sub: dict) -> tuple[int, int]:
    """Returns (inserted, ambiguous_count)."""
    payments = db.scalars(select(VpPayment).where(VpPayment.status.ilike("pagado"))).all()

    rows = []
    ambiguous = 0
    for p in payments:
        rut = None
        if p.raw_payload and isinstance(p.raw_payload, dict):
            rut = (p.raw_payload.get("client") or {}).get("social_id")
        candidates = rut_to_sub.get((p.platform, rut), []) if rut else []
        sub_id = candidates[0] if len(candidates) == 1 else None
        if len(candidates) != 1:
            ambiguous += 1
        rows.append({
            "id": uuid.uuid4(),
            "source": p.platform,
            "external_id": p.external_id,
            "subscription_id": sub_id,
            "charge_id": None,
            "source_status": p.status,
            "occurred_at": _parse_date(p.payment_date),
            "amount": _parse_amount(p.amount),
            "currency": p.currency or _DEFAULT_CURRENCY,
            "rejection_code": None,
            "rejection_reason": None,
            "rejection_reported_at": None,
        })

    before = db.scalar(
        select(func.count()).select_from(CorePayment).where(CorePayment.source.in_(_VP_SOURCES))
    ) or 0
    for i in range(0, len(rows), _BATCH):
        db.execute(
            insert(CorePayment)
            .values(rows[i : i + _BATCH])
            .on_conflict_do_nothing(constraint="uq_core_payment_source_external_id")
        )
    after = db.scalar(
        select(func.count()).select_from(CorePayment).where(CorePayment.source.in_(_VP_SOURCES))
    ) or 0
    return after - before, ambiguous


# ── Punto de entrada ──────────────────────────────────────────────────────────

def run_vp_core_etl(db: Session) -> dict[str, int]:
    """Materialize all VirtualPOS data into Core. Returns counts per entity."""
    log.info("VP Core ETL — materializando clientes (virtualpos1 + virtualpos2)")
    clients_created = materialize_core_clients(db, ["virtualpos"])
    log.info("VP Core ETL — clientes nuevos: %d", clients_created)

    ext_to_core = _build_identity_index(db)
    social_to_ext = _build_social_id_index(db)

    log.info("VP Core ETL — materializando atributos de cliente")
    attrs = _materialize_client_attributes(db, ext_to_core)
    log.info("VP Core ETL — atributos insertados: %d", attrs)

    log.info("VP Core ETL — materializando suscripciones")
    subs = _materialize_subscriptions(db, social_to_ext, ext_to_core)
    log.info("VP Core ETL — suscripciones upserted: %d", subs)

    log.info("VP Core ETL — materializando cargos (~230k registros, puede tardar)")
    charges = _materialize_charges(db)
    log.info("VP Core ETL — cargos upserted: %d", charges)

    log.info("VP Core ETL — construyendo índice RUT→suscripción para pagos")
    rut_to_sub = _build_rut_to_sub_index(db)

    log.info("VP Core ETL — materializando pagos")
    payments, ambiguous = _materialize_payments(db, rut_to_sub)
    log.info("VP Core ETL — pagos insertados: %d (sin suscripción por ambigüedad RUT: %d)", payments, ambiguous)

    db.commit()
    return {
        "clients_created": clients_created,
        "attributes_inserted": attrs,
        "subscriptions_upserted": subs,
        "charges_upserted": charges,
        "payments_inserted": payments,
        "payments_unlinked_ambiguous_rut": ambiguous,
    }
