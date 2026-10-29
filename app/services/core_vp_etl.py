"""Materialize VirtualPOS provider tables (vp_*) into Core entities.

Covers both platforms: virtualpos1 and virtualpos2.
Run order: client attributes → subscriptions → charges → payments → rejections
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

from sqlalchemy import and_, func, or_, select, update
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
from app.services.vp_current_amount import load_monto_vigente

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
    # Monto vigente = ultimo monto cobrado (plan fijo no editable en VP); fallback al monto de la suscripcion/plan.
    vigentes = load_monto_vigente(db, family="vp")
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
            "amount": vigentes.get((s.platform, s.external_id), _parse_amount(s.amount)),
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
    unlinked = 0
    for c in charges:
        sub_id = sub_index.get((c.platform, c.subscription_external_id)) if c.subscription_external_id else None
        if sub_id is None:
            unlinked += 1
        due = _parse_date(c.charge_date)
        rows.append({
            "id": uuid.uuid4(),
            "subscription_id": sub_id,
            "source": c.platform,
            "external_id": c.external_id,
            "period_reference": due.strftime("%Y-%m") if due else None,
            "due_at": due,
            "amount": _parse_amount(c.amount),
            "currency": c.currency or _DEFAULT_CURRENCY,
            "source_status": c.status,
        })

    if unlinked:
        log.info("VP Core ETL: %d cargos sin suscripción Core identificada (subscription_id=NULL)", unlinked)

    before = db.scalar(
        select(func.count()).select_from(CoreCharge).where(CoreCharge.source.in_(_VP_SOURCES))
    ) or 0
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
    after = db.scalar(
        select(func.count()).select_from(CoreCharge).where(CoreCharge.source.in_(_VP_SOURCES))
    ) or 0
    return after - before


# ── Paso 5: pagos ─────────────────────────────────────────────────────────────

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
    payments = db.scalars(select(VpPayment)).all()

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


# ── Paso 6: enriquecer cobros y pagos con el último rechazo verificable ──────

def _extract_rejection(payload: object) -> tuple[str, str | None] | None:
    """(código, mensaje) del `rejected_object` de un detalle de pago de VirtualPOS, o None.

    En `GET /v3/payment/{uuid}` el objeto viene en el nivel superior de la respuesta (hermano de
    `payment`). Por compatibilidad también se lee dentro de `payment.order` y de `order`. El código
    puede llegar como `code` o `error_code`. El código `0` es «Operación exitosa», no un rechazo.
    """
    if not isinstance(payload, dict):
        return None
    inner = payload.get("payment") if isinstance(payload.get("payment"), dict) else payload
    candidates = (
        payload.get("rejected_object"),
        ((inner.get("order") if isinstance(inner.get("order"), dict) else None) or {}).get("rejected_object"),
        ((payload.get("order") if isinstance(payload.get("order"), dict) else None) or {}).get("rejected_object"),
    )
    for rejected in candidates:
        if not isinstance(rejected, dict) or not rejected:
            continue
        raw_code = rejected.get("code") if rejected.get("code") not in (None, "") else rejected.get("error_code")
        code = str(raw_code).strip() if raw_code not in (None, "") else ""
        if not code or code == "0":
            continue
        message = str(rejected.get("message") or "").strip()
        return code, (message or None)
    return None


def _rejected_vp_payments(db: Session, extra_keys: set[tuple[str, str]]):
    """VpPayment cuyo `raw_payload` trae `rejected_object` (en cualquiera de las formas conocidas)."""
    has_object = or_(
        VpPayment.raw_payload.has_key("rejected_object"),
        VpPayment.raw_payload["payment"]["order"].has_key("rejected_object"),
        VpPayment.raw_payload["order"].has_key("rejected_object"),
    )
    query = select(VpPayment).where(VpPayment.platform.in_(_VP_SOURCES), has_object)
    for p in db.scalars(query):
        found = _extract_rejection(p.raw_payload)
        if found is not None:
            yield p, found[0], found[1]


def _enrich_charges_with_rejections(
    db: Session,
    payment_charge_links: dict[tuple[str, str], str] | None = None,
) -> int:
    """Actualiza CoreCharge.latest_rejection_* con el rechazo más reciente de sus pagos.

    - `rejected_object` se lee en el nivel superior del detalle del pago (ver `_extract_rejection`).
    - El vínculo pago -> cobro sale de `VpPayment.charge_external_id` (hoy NULL en todas las filas) o
      de `payment_charge_links` {(plataforma, id de pago): id de cobro}, que entregarán RJ-06 / RJ-04.
      Sin vínculo no se inventa nada.
    - UPDATE explícito por clave primaria: los ETL insertan con `on_conflict_do_nothing`, así que una
      fila existente nunca se corregiría sola. Solo cambia filas cuyo rechazo difiere y nunca reemplaza
      un rechazo más reciente por uno más antiguo. Idempotente. Retorna los cobros actualizados.
    """
    links = payment_charge_links or {}
    best: dict[tuple[str, str], dict] = {}
    for p, code, reason in _rejected_vp_payments(db, set(links)):
        charge_ext = p.charge_external_id or links.get((p.platform, p.external_id))
        if not charge_ext:
            continue
        occurred = _parse_date(p.payment_date)
        key = (p.platform, charge_ext)
        prev = best.get(key)
        newer = prev is None or (occurred is not None and (prev["occurred_at"] is None or occurred > prev["occurred_at"]))
        if newer:
            best[key] = {"payment_external_id": p.external_id, "code": code, "reason": reason, "occurred_at": occurred}
    if not best:
        return 0

    core_payment_ids = {
        (row.source, row.external_id): row.id
        for row in db.execute(select(CorePayment.source, CorePayment.external_id, CorePayment.id).where(CorePayment.source.in_(_VP_SOURCES)))
    }
    updates: list[dict] = []
    for (platform, charge_ext), rej in best.items():
        current = db.execute(
            select(
                CoreCharge.id, CoreCharge.latest_rejection_payment_id, CoreCharge.latest_rejection_code,
                CoreCharge.latest_rejection_reason, CoreCharge.latest_rejection_at,
            ).where(CoreCharge.source == platform, CoreCharge.external_id == charge_ext)
        ).first()
        if current is None:
            continue
        if current.latest_rejection_at is not None and (rej["occurred_at"] is None or rej["occurred_at"] < current.latest_rejection_at):
            continue
        new_values = {
            "latest_rejection_payment_id": core_payment_ids.get((platform, rej["payment_external_id"])),
            "latest_rejection_code": rej["code"],
            "latest_rejection_reason": rej["reason"],
            "latest_rejection_at": rej["occurred_at"],
        }
        old_values = {
            "latest_rejection_payment_id": current.latest_rejection_payment_id,
            "latest_rejection_code": current.latest_rejection_code,
            "latest_rejection_reason": current.latest_rejection_reason,
            "latest_rejection_at": current.latest_rejection_at,
        }
        if new_values != old_values:
            updates.append({"id": current.id, **new_values})
    if updates:
        db.execute(update(CoreCharge), updates)
    return len(updates)


def _enrich_payments_with_rejections(db: Session) -> int:
    """Actualiza CorePayment.rejection_* desde el `rejected_object` del pago (no necesita vínculo a cobro).

    UPDATE explícito por clave primaria (el ETL inserta pagos con `on_conflict_do_nothing`). Idempotente.
    """
    found: dict[tuple[str, str], tuple[str, str | None, datetime | None]] = {}
    for p, code, reason in _rejected_vp_payments(db, set()):
        found[(p.platform, p.external_id)] = (code, reason, _parse_date(p.payment_date))
    if not found:
        return 0
    updates: list[dict] = []
    for row in db.execute(
        select(CorePayment.id, CorePayment.source, CorePayment.external_id, CorePayment.rejection_code,
               CorePayment.rejection_reason, CorePayment.rejection_reported_at).where(CorePayment.source.in_(_VP_SOURCES))
    ):
        hit = found.get((row.source, row.external_id))
        if hit is None:
            continue
        code, reason, at = hit
        if (row.rejection_code, row.rejection_reason, row.rejection_reported_at) != (code, reason, at):
            updates.append({"id": row.id, "rejection_code": code, "rejection_reason": reason, "rejection_reported_at": at})
    if updates:
        db.execute(update(CorePayment), updates)
    return len(updates)


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

    log.info("VP Core ETL — enriqueciendo pagos y cobros con el último rechazo")
    payment_rejections = _enrich_payments_with_rejections(db)
    rejections = _enrich_charges_with_rejections(db)
    log.info("VP Core ETL — pagos con rechazo: %d; cobros con rechazo enriquecido: %d", payment_rejections, rejections)

    db.commit()
    return {
        "clients_created": clients_created,
        "attributes_inserted": attrs,
        "subscriptions_upserted": subs,
        "charges_upserted": charges,
        "charges_rejection_enriched": rejections,
        "payments_rejection_enriched": payment_rejections,
        "payments_inserted": payments,
        "payments_unlinked_ambiguous_rut": ambiguous,
    }
