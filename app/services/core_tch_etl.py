"""Materialize TCH provider tables (tch_*) into Core entities.

Run order: client attributes → subscriptions → payments
Idempotent: safe to re-run; uses ON CONFLICT DO NOTHING / DO UPDATE per entity.

TCH has no CoreCharge concept — tch_transacciones map directly to CorePayment.
"""

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.core import (
    CoreClientAttribute,
    CorePayment,
    CoreSubscription,
    ExternalIdentity,
)
from app.models.tch import TchClient, TchSubscription, TchTransaction
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


def normalize_tch_currency(value: object) -> str | None:
    """Convierte el texto de "Moneda Vigente" ("Pesos", "UF", ...) a codigo de moneda."""
    text = str(value).strip().upper() if value is not None else ""
    if not text:
        return None
    if text == "UF" or text.split()[0] == "UF":
        return "UF"
    if text in {"CLP", "$"} or text.startswith("PESO"):
        return "CLP"
    if text in {"USD", "US$"} or text.startswith("DOLAR") or text.startswith("DÓLAR"):
        return "USD"
    return None


def _resolve_currency(subscription: TchSubscription) -> str:
    """Moneda del mandato desde "Moneda Vigente" (TCH-PAR-05); CLP si el reporte no la trae.

    El campo ``reajuste`` ("SI" o vacio) indica reajuste del monto, no la moneda.
    Se lee la columna ``moneda`` (migracion 0047); en filas cargadas antes de ella, del payload, donde el ETL deja
    la clave ``moneda_vigente`` y, en filas aun mas antiguas, el rotulo crudo de la columna.
    """
    from_column = normalize_tch_currency(getattr(subscription, "currency", None))
    if from_column:
        return from_column
    payload = getattr(subscription, "raw_payload", None) or {}
    value = payload.get("moneda_vigente")
    if value is None:
        for key, raw in payload.items():
            if "moneda vigente" in str(key).lower():
                value = raw
                break
    return normalize_tch_currency(value) or "CLP"


# ── Paso 1: atributos de cliente ──────────────────────────────────────────────

def _materialize_client_attributes(db: Session) -> int:
    """Upsert observable PII attributes for each TCH client."""
    clients = db.scalars(select(TchClient)).all()

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
        if not c.rut:
            continue
        client_id = identity_index.get(c.rut)
        observed = c.updated_at or c.created_at

        full_name = " ".join(filter(None, [c.name, c.last_name])).strip() or None
        for attr_type, attr_val in [
            ("name", full_name),
            ("rut", c.rut),
            ("email", c.email),
            ("phone", c.phone),
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

    # Índice de último estado de transacción por ficha (para last_payment_status)
    _tx_latest: dict[int, tuple[str, str]] = {}
    for row in db.execute(
        select(TchTransaction.file_number, TchTransaction.charge_date, TchTransaction.status)
        .where(TchTransaction.file_number.isnot(None))
    ):
        prev = _tx_latest.get(row.file_number)
        charge_day = row.charge_date or ""
        if prev is None or charge_day > prev[0]:
            _tx_latest[row.file_number] = (charge_day, row.status)
    last_tx_status: dict[int, str] = {k: v[1] for k, v in _tx_latest.items()}

    subscriptions = db.scalars(select(TchSubscription)).all()

    rows = []
    for s in subscriptions:
        client_id = identity_index.get(s.client_rut) if s.client_rut else None
        rows.append({
            "id": uuid.uuid4(),
            "client_id": client_id,
            "source": _SOURCE,
            "external_id": str(s.file_number),
            "status": s.status,
            "amount": _parse_amount(s.amount),
            "currency": _resolve_currency(s),
            "started_at": _parse_date(s.activation_date),
            "ended_at": _parse_date(s.deletion_date),
            "last_payment_status": last_tx_status.get(s.file_number),
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
                "last_payment_status": ins.excluded.last_payment_status,
                "updated_at": datetime.now(tz=timezone.utc),
            },
        ))
    after = db.scalar(select(func.count()).select_from(CoreSubscription).where(CoreSubscription.source == _SOURCE)) or 0
    return after - before


# ── Paso 3: pagos ─────────────────────────────────────────────────────────────

def legacy_key_filter(model, key_column):
    """Filas TCH con la clave antigua (ficha|periodo|cuota|estado|monto) que ya no existe en ``tch_transacciones``.

    Con la clave estable (ficha|periodo|cuota, D13) esas filas no se vuelven a generar: tras la recarga completa
    quedarian como duplicados. Solo se consideran las de la forma antigua (4 separadores) y solo si su clave ya no
    esta en ``tch_transacciones`` (si la recarga aun no ocurrio, siguen vigentes y no se tocan).
    """
    return and_(
        model.source == _SOURCE,
        key_column.like("%|%|%|%|%"),
        ~exists().where(TchTransaction.dedupe_key == key_column),
    )


def _prune_legacy_payments(db: Session) -> int:
    result = db.execute(delete(CorePayment).where(legacy_key_filter(CorePayment, CorePayment.external_id)))
    return result.rowcount or 0


def _materialize_payments(db: Session) -> int:
    pruned = _prune_legacy_payments(db)
    if pruned:
        log.info("TCH Core ETL: %d pagos con clave antigua eliminados (la clave ahora es ficha|periodo|cuota)", pruned)
    sub_index: dict[str, uuid.UUID] = {}
    for row in db.execute(
        select(CoreSubscription.external_id, CoreSubscription.id).where(
            CoreSubscription.source == _SOURCE
        )
    ):
        sub_index[row.external_id] = row.id

    transacciones = db.scalars(select(TchTransaction)).all()

    rows = []
    skipped = 0
    for t in transacciones:
        if not t.dedupe_key:
            skipped += 1
            continue
        sub_id = sub_index.get(str(t.file_number))
        rows.append({
            "id": uuid.uuid4(),
            "source": _SOURCE,
            "external_id": t.dedupe_key,
            "subscription_id": sub_id,
            "charge_id": None,
            "source_status": t.status,
            "occurred_at": _parse_date(t.charge_date),
            "amount": _parse_amount(t.amount),
            "currency": "CLP",
            "rejection_code": t.response_code if t.status and "RECHAZ" in t.status.upper() else None,
            "rejection_reason": t.rejection_reason if t.status and "RECHAZ" in t.status.upper() else None,
            "rejection_reported_at": None,
        })

    if skipped:
        log.warning("TCH Core ETL: %d transacciones sin dedupe_key omitidas", skipped)

    before = db.scalar(select(func.count()).select_from(CorePayment).where(CorePayment.source == _SOURCE)) or 0
    for i in range(0, len(rows), _BATCH):
        batch = rows[i : i + _BATCH]
        ins = insert(CorePayment).values(batch)
        # Con la clave estable una cuota cambia de estado (rechazada -> aceptada) o de monto en reportes posteriores:
        # el pago debe reflejar el ultimo estado, no quedarse con el primero.
        db.execute(
            ins.on_conflict_do_update(
                constraint="uq_core_payment_source_external_id",
                set_={
                    "subscription_id": ins.excluded.subscription_id,
                    "source_status": ins.excluded.source_status,
                    "occurred_at": ins.excluded.occurred_at,
                    "amount": ins.excluded.amount,
                    "rejection_code": ins.excluded.rejection_code,
                    "rejection_reason": ins.excluded.rejection_reason,
                },
            )
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
