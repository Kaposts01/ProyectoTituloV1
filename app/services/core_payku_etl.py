"""Materialize Payku provider tables (p_*) into Core entities.

Run order: client attributes → normalized statuses → subscriptions → cycles → charges → payments → charge links →
rejection fallback. Idempotent: safe to re-run.

Payku has no charge resource. PK-06: the billing cycles of `paid[]` (V3, stored in `p_cycles`) are the closest thing
and become CoreCharge (source=payku); without V3 data `p_cycles` stays empty and p_transactions map directly to
CorePayment, as before. Payments are linked to their cycle only through `paid[].transactions[]` (no guessing).
Rejected transactions carry amount=0; the embedded payload has no rejection code/reason. As a fallback
(PK-PAR-06 / RJ-10) the latest rejection of each subscription takes its `last_status_current_payment`.
occurred_at keeps the transaction time in Chile (PK-PAR-04).
"""

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.core import (
    CoreCharge,
    CoreClientAttribute,
    CorePayment,
    CoreSubscription,
    ExternalIdentity,
)
from app.models.payku_channel import (
    PaykuClient,
    PaykuCycle,
    PaykuPlan,
    PaykuSubscription,
    PaykuTransaction,
)
from app.services.channel_consolidation import _payku_last_transition_date
from app.services.channel_store import extract_payku_cycles
from app.services.core_materialization import materialize_core_clients
from app.services.payku_rejection_codes import (
    payku_gateway_rejection,
    payku_subscription_rejection_status,
)
from app.services.payku_status import (
    COMMON_STATUS_UNKNOWN,
    PAYKU_COMMON_STATUS,
    normalize_payku_charge_status,
    normalize_payku_status,
)
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
                parsed = datetime.strptime(raw, fmt).replace(tzinfo=CHILE_TZ)
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


# Taxonomia comun de estados (PK-PAR-07): vive en `payku_status` para que la usen tambien los extractores de
# `channel_store` sin importacion circular; se reexporta aqui con los nombres de siempre.
_PAYKU_COMMON_STATUS = PAYKU_COMMON_STATUS


def _plan_amounts(db: Session) -> dict[str, Decimal]:
    """external_id del plan -> monto, solo planes con monto valido."""
    out: dict[str, Decimal] = {}
    for external_id, amount in db.execute(select(PaykuPlan.external_id, PaykuPlan.amount)):
        parsed = _parse_amount(amount)
        if parsed is not None:
            out[external_id] = parsed
    return out


def _subscription_amount(s: PaykuSubscription, plan_amounts: dict[str, Decimal]) -> Decimal | None:
    """Monto de la suscripcion; una `register` sin monto (inscripcion sin completar) toma el de su plan (PK-PAR-07)."""
    amount = _parse_amount(s.amount)
    if amount is None and (s.status or "").strip().lower() == "register" and s.plan_id:
        return plan_amounts.get(s.plan_id)
    return amount


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


# ── Paso 1b: estado normalizado en las tablas de canal (PK-PAR-07 / PK-06) ────

def _refresh_normalized_statuses(db: Session) -> int:
    """Recalcula `status_normalized` de `p_subscriptions` y `p_transactions` desde el estado crudo.

    Los extractores ya la escriben al sincronizar; esto cubre filas antiguas y cambios de la taxonomia. Solo toca
    filas cuyo valor difiere (UPDATE explicito, idempotente). Devuelve las filas actualizadas.
    """
    changed = 0
    pairs = ((PaykuSubscription, normalize_payku_status), (PaykuTransaction, normalize_payku_charge_status))
    for model, normalize in pairs:
        updates = [
            {"id": row.id, "status_normalized": common}
            for row in db.execute(select(model.id, model.status, model.status_normalized))
            if (common := normalize(row.status)) != row.status_normalized
        ]
        for i in range(0, len(updates), 1000):
            db.execute(update(model), updates[i : i + 1000])
        changed += len(updates)
    return changed


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
    plan_amounts = _plan_amounts(db)

    rows = []
    unknown_statuses: set[str] = set()
    for s in subscriptions:
        if normalize_payku_status(s.status) == COMMON_STATUS_UNKNOWN:
            unknown_statuses.add(str(s.status or "")[:50])
        client_id = identity_index.get(s.client_id) if s.client_id else None
        rows.append({
            "id": uuid.uuid4(),
            "client_id": client_id,
            "source": _SOURCE,
            "external_id": s.external_id,
            "status": s.status,
            "last_payment_status": s.last_status_current_payment,
            "amount": _subscription_amount(s, plan_amounts),
            "currency": s.currency or _DEFAULT_CURRENCY,
            "started_at": _parse_date(s.start_date),
            "ended_at": _ended_at(s),
        })

    if unknown_statuses:
        log.warning("Payku Core ETL: estados de suscripción fuera de la taxonomía común: %s", sorted(unknown_statuses))

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


# ── Paso 2b: ciclos y cargos (PK-06) ─────────────────────────────────────────

def _materialize_cycles(db: Session) -> int:
    """`paid[]` del payload de cada suscripcion -> `p_cycles` (upsert por clave de ciclo). Idempotente."""
    rows: dict[str, dict] = {}
    for external_id, payload in db.execute(select(PaykuSubscription.external_id, PaykuSubscription.raw_payload)):
        if not isinstance(payload, dict) or not isinstance(payload.get("paid"), list):
            continue
        for row in extract_payku_cycles({**payload, "__external_id": external_id}):
            rows[row["external_id"]] = {"id": uuid.uuid4(), **row}
    values = list(rows.values())
    for i in range(0, len(values), _BATCH):
        ins = insert(PaykuCycle).values(values[i : i + _BATCH])
        db.execute(ins.on_conflict_do_update(
            index_elements=["external_id"],
            set_={key: ins.excluded[key] for key in values[0] if key not in ("id", "external_id")}
            | {"updated_at": datetime.now(tz=timezone.utc)},
        ))
    return len(values)


def _materialize_charges(db: Session) -> int:
    """`p_cycles` -> `core_charges` (source=payku). `source_status` guarda el estado crudo del ciclo; un ciclo
    rechazado deja `latest_rejection_at` (dia de pago o del ciclo) y, si el estado es de la Lista A, su texto crudo
    como motivo (la etiqueta la pone `rejection_format`). Upsert por (source, external_id); idempotente."""
    sub_index = {
        row.external_id: row.id
        for row in db.execute(
            select(CoreSubscription.external_id, CoreSubscription.id).where(CoreSubscription.source == _SOURCE)
        )
    }
    rows = []
    for c in db.scalars(select(PaykuCycle)).all():
        due_at = _parse_datetime_cl(c.cycle_day)
        rejected = c.status_normalized == "rejected"
        rows.append({
            "id": uuid.uuid4(),
            "subscription_id": sub_index.get(c.subscription_id),
            "source": _SOURCE,
            "external_id": c.external_id,
            "period_reference": (c.cycle_day or "")[:7] or None,
            "due_at": due_at,
            "amount": _parse_amount(c.amount_paid),
            "currency": _DEFAULT_CURRENCY,
            "source_status": c.status,
            "latest_rejection_reason": payku_subscription_rejection_status(c.status) if rejected else None,
            "latest_rejection_at": (_parse_datetime_cl(c.payment_day) or due_at) if rejected else None,
        })
    updatable = ("subscription_id", "period_reference", "due_at", "amount", "currency", "source_status",
                 "latest_rejection_reason", "latest_rejection_at")
    for i in range(0, len(rows), _BATCH):
        ins = insert(CoreCharge).values(rows[i : i + _BATCH])
        db.execute(ins.on_conflict_do_update(
            constraint="uq_core_charge_source_external_id",
            set_={key: ins.excluded[key] for key in updatable} | {"updated_at": datetime.now(tz=timezone.utc)},
        ))
    return len(rows)


def _link_payments_to_charges(db: Session) -> int:
    """`core_payments.charge_id` desde `p_cycles.transaction_ids` (solo enlaces explicitos). Idempotente."""
    charge_by_tx: dict[str, uuid.UUID] = {}
    for charge_id, tx_ids in db.execute(
        select(CoreCharge.id, PaykuCycle.transaction_ids)
        .join(PaykuCycle, PaykuCycle.external_id == CoreCharge.external_id)
        .where(CoreCharge.source == _SOURCE)
    ):
        for tx in tx_ids or []:
            charge_by_tx[str(tx)] = charge_id
    if not charge_by_tx:
        return 0
    updates = [
        {"id": row.id, "charge_id": charge_by_tx[row.external_id]}
        for row in db.execute(
            select(CorePayment.id, CorePayment.external_id, CorePayment.charge_id).where(
                CorePayment.source == _SOURCE, CorePayment.external_id.in_(list(charge_by_tx))
            )
        )
        if row.charge_id != charge_by_tx[row.external_id]
    ]
    for i in range(0, len(updates), 1000):
        db.execute(update(CorePayment), updates[i : i + 1000])
    return len(updates)


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
        code, reason = _gateway_rejection(t) if is_rejected else (None, None)
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
            "rejection_code": code,
            "rejection_reason": reason,
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
    _refresh_payment_rejections(db, {
        r["external_id"]: (r["rejection_code"], r["rejection_reason"])
        for r in rows if r["rejection_code"] is not None or r["rejection_reason"] is not None
    })
    return after - before


def _gateway_rejection(t: PaykuTransaction) -> tuple[str | None, str | None]:
    """(codigo, glosa) del `gateway_response` de la transaccion, si el payload lo trae (CRM-15C).

    El payload embebido de la suscripcion (`transactions[]`, lo que hoy guarda el sync) NO lo trae; solo
    `GET /api/transaction/{id}` y su listado. Asi, el mapeo queda listo para cuando el sync o un enriquecimiento
    (PK-PAR-05) guarde esa respuesta en `p_transactions.raw_payload`, sin inventar nada mientras tanto.
    """
    payload = t.raw_payload if isinstance(t.raw_payload, dict) else {}
    return payku_gateway_rejection(payload.get("gateway_response"))


def _refresh_payment_rejections(db: Session, found: dict[str, tuple[str | None, str | None]]) -> int:
    """UPDATE explicito de `rejection_code`/`rejection_reason` de pagos ya existentes desde el `gateway_response`.

    El insert usa `on_conflict_do_nothing`; sin este paso un pago cargado antes del dato nunca lo tomaria. Solo escribe
    valores no nulos (nunca borra un motivo ya guardado) y solo filas que cambian. Idempotente.
    """
    if not found:
        return 0
    updates: list[dict] = []
    for row in db.execute(
        select(CorePayment.id, CorePayment.external_id, CorePayment.rejection_code, CorePayment.rejection_reason)
        .where(CorePayment.source == _SOURCE, CorePayment.external_id.in_(list(found)))
    ):
        code, reason = found[row.external_id]
        target = (code or row.rejection_code, reason or row.rejection_reason)
        if target != (row.rejection_code, row.rejection_reason):
            updates.append({"id": row.id, "rejection_code": target[0], "rejection_reason": target[1]})
    for i in range(0, len(updates), 1000):
        db.execute(update(CorePayment), updates[i : i + 1000])
    return len(updates)


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


# ── Paso 4: motivo minimo de rechazo por suscripcion (PK-PAR-06 / RJ-10) ─────

def _apply_subscription_rejection_fallback(db: Session) -> int:
    """Llena `core_payments.rejection_reason` del rechazo mas reciente de cada suscripcion desde su
    `last_status_current_payment` (`maximum attempt limit`, `first payment rejected`, `payment consumes failed`).

    Respaldo mientras no exista la glosa por cobro (PK-PAR-05): guarda el valor crudo de Payku (la etiqueta legible
    la pone `rejection_format`), sin codigo. Solo el rechazo mas reciente, porque el campo describe el ultimo estado
    de cobro de la suscripcion, no cada intento. Nunca pisa un motivo ya guardado. UPDATE explicito, idempotente.
    """
    statuses = {
        row.id: status
        for row in db.execute(
            select(CoreSubscription.id, PaykuSubscription.last_status_current_payment)
            .join(PaykuSubscription, PaykuSubscription.external_id == CoreSubscription.external_id)
            .where(CoreSubscription.source == _SOURCE, PaykuSubscription.last_status_current_payment.is_not(None))
        )
        if (status := payku_subscription_rejection_status(row.last_status_current_payment))
    }
    if not statuses:
        return 0
    latest: dict = {}
    for p in db.execute(
        select(CorePayment.id, CorePayment.subscription_id, CorePayment.occurred_at, CorePayment.external_id,
               CorePayment.rejection_reason)
        .where(CorePayment.source == _SOURCE, func.lower(CorePayment.source_status) == "rejected",
               CorePayment.subscription_id.in_(list(statuses)))
    ):
        key = (p.occurred_at or datetime.min.replace(tzinfo=timezone.utc), p.external_id)
        prev = latest.get(p.subscription_id)
        if prev is None or key > prev[0]:
            latest[p.subscription_id] = (key, p)
    updates = [
        {"id": p.id, "rejection_reason": statuses[sub_id]}
        for sub_id, (_key, p) in latest.items()
        if p.rejection_reason is None
    ]
    if updates:
        db.execute(update(CorePayment), updates)
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

    normalized = _refresh_normalized_statuses(db)
    log.info("Payku Core ETL — estados normalizados actualizados: %d", normalized)

    log.info("Payku Core ETL — materializando suscripciones")
    subs = _materialize_subscriptions(db)
    log.info("Payku Core ETL — suscripciones upserted: %d", subs)

    cycles = _materialize_cycles(db)
    charges = _materialize_charges(db)
    log.info("Payku Core ETL — ciclos: %d, cargos upserted: %d", cycles, charges)

    log.info("Payku Core ETL — materializando pagos")
    payments = _materialize_payments(db)
    log.info("Payku Core ETL — pagos insertados: %d", payments)
    linked = _link_payments_to_charges(db)
    log.info("Payku Core ETL — pagos enlazados a su ciclo: %d", linked)

    reasons = _apply_subscription_rejection_fallback(db)
    log.info("Payku Core ETL — rechazos con motivo de respaldo por suscripción: %d", reasons)

    db.commit()
    return {
        "clients_created": clients_created,
        "attributes_inserted": attrs,
        "subscriptions_upserted": subs,
        "payments_inserted": payments,
        "payments_rejection_reason_fallback": reasons,
        "statuses_normalized": normalized,
        "cycles_upserted": cycles,
        "charges_upserted": charges,
        "payments_linked_to_charge": linked,
        "subscriptions_unknown_status": db.scalar(
            select(func.count()).select_from(PaykuSubscription)
            .where(PaykuSubscription.status_normalized == COMMON_STATUS_UNKNOWN)
        ) or 0,
    }
