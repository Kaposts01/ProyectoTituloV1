"""Materialize TCH provider tables (tch_*) into Core entities.

Run order: client attributes → subscriptions → charges (cuotas) → payments
Idempotent: safe to re-run; uses ON CONFLICT DO NOTHING / DO UPDATE per entity.

TCH-PAR-12: each installment of tch_transacciones (ficha|periodo|cuota, D13) is a CoreCharge with the real period
(``period_reference``) and its latest attempt is a CorePayment linked through ``charge_id``.
"""

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, case, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.core import (
    CoreCharge,
    CoreClientAttribute,
    CorePayment,
    CoreSubscription,
    ExternalIdentity,
)
from app.models.tch import TchClient, TchSubscription, TchTransaction
from app.services.core_materialization import materialize_core_clients
from app.services.tch_rut import identity_rut, is_valid_rut

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
            # TCH-PAR-14 / ADR-001: el RUT solo es senal de identidad si su verificador es correcto.
            ("rut", identity_rut(c.rut)),
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

    isolated = _prune_invalid_rut_attributes(db)
    if isolated:
        log.info("TCH Core ETL: %d atributos rut sin verificador valido retirados del matching", isolated)
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


def _prune_invalid_rut_attributes(db: Session) -> int:
    """Quita los atributos ``rut`` de TCH cuyo valor no es un RUT valido (cargados antes de TCH-PAR-14). Idempotente."""
    invalid = [
        attr_id
        for attr_id, value in db.execute(
            select(CoreClientAttribute.id, CoreClientAttribute.attribute_value).where(
                CoreClientAttribute.source == _SOURCE, CoreClientAttribute.attribute_type == "rut"
            )
        )
        if not is_valid_rut(value)
    ]
    for i in range(0, len(invalid), _BATCH):
        db.execute(delete(CoreClientAttribute).where(CoreClientAttribute.id.in_(invalid[i : i + _BATCH])))
    return len(invalid)


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


def _prune_legacy_charges(db: Session) -> int:
    result = db.execute(delete(CoreCharge).where(legacy_key_filter(CoreCharge, CoreCharge.external_id)))
    return result.rowcount or 0


_PAGE = 5000  # filas de tch_transacciones por pagina (paginacion por id: memoria acotada con 1,47 M filas)

_TX_COLUMNS = (
    TchTransaction.id,
    TchTransaction.file_number,
    TchTransaction.dedupe_key,
    TchTransaction.period,
    TchTransaction.status,
    TchTransaction.amount,
    TchTransaction.charge_date,
    TchTransaction.response_code,
    TchTransaction.rejection_reason,
    TchTransaction.previous_rejection_reason,
    TchTransaction.previous_rejection_at,
)

_CHARGE_UPDATABLE = (
    "subscription_id", "period_reference", "due_at", "amount", "currency", "source_status",
    "latest_rejection_code", "latest_rejection_reason", "latest_rejection_at",
)
_PAYMENT_UPDATABLE = (
    "subscription_id", "charge_id", "source_status", "occurred_at", "amount", "rejection_code", "rejection_reason",
)


def _is_rejected(status: str | None) -> bool:
    return bool(status) and "RECHAZ" in status.upper()


def _period_start(period: str | None) -> datetime | None:
    return _parse_date(f"{period}-01") if period and len(period) == 7 else None


def _charge_row(t, subscription_id: uuid.UUID | None) -> dict:
    """La cuota TCH como CoreCharge: una por (ficha, periodo real, cuota), con su ultimo estado (D13).

    ``latest_rejection_*``: el rechazo vigente si la cuota esta RECHAZADA; si se pago despues de un rechazo, el
    rechazo previo (``rechazo_previo*``) para no perder el intento fallido.
    """
    rejected = _is_rejected(t.status)
    return {
        "id": uuid.uuid4(),
        "subscription_id": subscription_id,
        "source": _SOURCE,
        "external_id": t.dedupe_key,
        "period_reference": t.period,
        "due_at": _parse_date(t.charge_date) or _period_start(t.period),
        "amount": _parse_amount(t.amount),
        "currency": "CLP",
        "source_status": t.status,
        "latest_rejection_code": t.response_code if rejected else None,
        "latest_rejection_reason": t.rejection_reason if rejected else t.previous_rejection_reason,
        "latest_rejection_at": _parse_date(t.charge_date if rejected else t.previous_rejection_at),
    }


def _payment_row(t, subscription_id: uuid.UUID | None, charge_id: uuid.UUID | None) -> dict:
    rejected = _is_rejected(t.status)
    return {
        "id": uuid.uuid4(),
        "source": _SOURCE,
        "external_id": t.dedupe_key,
        "subscription_id": subscription_id,
        "charge_id": charge_id,
        "source_status": t.status,
        "occurred_at": _parse_date(t.charge_date),
        "amount": _parse_amount(t.amount),
        "currency": "CLP",
        "rejection_code": t.response_code if rejected else None,
        "rejection_reason": t.rejection_reason if rejected else None,
        "rejection_reported_at": None,
    }


def _upsert_changed(db: Session, model, constraint: str, rows: list[dict], columns: tuple[str, ...]) -> None:
    """INSERT .. ON CONFLICT DO UPDATE que solo reescribe las filas que cambiaron (una segunda corrida no toca nada)."""
    table = model.__table__
    for i in range(0, len(rows), _BATCH):
        ins = insert(model).values(rows[i : i + _BATCH])
        set_ = {column: ins.excluded[column] for column in columns}
        set_["updated_at"] = func.now()
        changed = or_(*(table.c[column].is_distinct_from(ins.excluded[column]) for column in columns))
        db.execute(ins.on_conflict_do_update(constraint=constraint, set_=set_, where=changed))


def _materialize_charges_and_payments(db: Session) -> tuple[int, int]:
    """TCH-PAR-12: cada cuota de ``tch_transacciones`` es un CoreCharge y su ultimo intento un CorePayment ligado.

    Idempotente: claves estables (``dedupe_key``), upsert que solo toca filas cambiadas y vinculo del pago de rechazo
    recalculado al final. Las filas se leen por paginas ordenadas por id (no se cargan 1,47 M objetos en memoria).
    """
    pruned_payments = _prune_legacy_payments(db)
    pruned_charges = _prune_legacy_charges(db)
    if pruned_payments or pruned_charges:
        log.info(
            "TCH Core ETL: %d pagos y %d cuotas con clave antigua eliminados (la clave ahora es ficha|periodo|cuota)",
            pruned_payments,
            pruned_charges,
        )
    sub_index: dict[str, uuid.UUID] = {
        row.external_id: row.id
        for row in db.execute(
            select(CoreSubscription.external_id, CoreSubscription.id).where(CoreSubscription.source == _SOURCE)
        )
    }

    count_charges = select(func.count()).select_from(CoreCharge).where(CoreCharge.source == _SOURCE)
    count_payments = select(func.count()).select_from(CorePayment).where(CorePayment.source == _SOURCE)
    charges_before = db.scalar(count_charges) or 0
    payments_before = db.scalar(count_payments) or 0

    skipped = 0
    last_id = None
    while True:
        page_query = select(*_TX_COLUMNS).order_by(TchTransaction.id).limit(_PAGE)
        if last_id is not None:
            page_query = page_query.where(TchTransaction.id > last_id)
        page = db.execute(page_query).all()
        if not page:
            break
        last_id = page[-1].id
        valid = [t for t in page if t.dedupe_key]
        skipped += len(page) - len(valid)
        if valid:
            charges = [_charge_row(t, sub_index.get(str(t.file_number))) for t in valid]
            _upsert_changed(db, CoreCharge, "uq_core_charge_source_external_id", charges, _CHARGE_UPDATABLE)
            charge_ids = dict(
                db.execute(
                    select(CoreCharge.external_id, CoreCharge.id).where(
                        CoreCharge.source == _SOURCE, CoreCharge.external_id.in_([t.dedupe_key for t in valid])
                    )
                ).all()
            )
            # Con la clave estable una cuota cambia de estado (rechazada -> aceptada) o de monto en reportes
            # posteriores: el pago refleja el ultimo estado, no el primero.
            payments = [
                _payment_row(t, sub_index.get(str(t.file_number)), charge_ids.get(t.dedupe_key)) for t in valid
            ]
            _upsert_changed(db, CorePayment, "uq_core_payment_source_external_id", payments, _PAYMENT_UPDATABLE)
        if len(page) < _PAGE:
            break

    if skipped:
        log.warning("TCH Core ETL: %d transacciones sin dedupe_key omitidas", skipped)
    _link_rejection_payments(db)
    return (db.scalar(count_charges) or 0) - charges_before, (db.scalar(count_payments) or 0) - payments_before


def _link_rejection_payments(db: Session) -> int:
    """``latest_rejection_payment_id`` = el pago de la cuota si su ultimo estado es un rechazo; NULL si no."""
    charges, payments = CoreCharge.__table__, CorePayment.__table__
    wanted = case((charges.c.source_status.ilike("%RECHAZ%"), payments.c.id), else_=None)
    result = db.execute(
        charges.update()
        .where(
            charges.c.source == _SOURCE,
            payments.c.source == _SOURCE,
            payments.c.charge_id == charges.c.id,
            charges.c.latest_rejection_payment_id.is_distinct_from(wanted),
        )
        .values(latest_rejection_payment_id=wanted, updated_at=func.now())
    )
    return result.rowcount or 0


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

    log.info("TCH Core ETL — materializando cuotas (core_charges) y pagos")
    charges, payments = _materialize_charges_and_payments(db)
    log.info("TCH Core ETL — cuotas insertadas: %d, pagos insertados: %d", charges, payments)

    db.commit()
    return {
        "clients_created": clients_created,
        "attributes_inserted": attrs,
        "subscriptions_upserted": subs,
        "charges_inserted": charges,
        "payments_inserted": payments,
    }
