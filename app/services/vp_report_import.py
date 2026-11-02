"""Carga de los reportes PAT de VirtualPOS a las tablas `vp_report_*` (VP-PAR-02 / RJ-04). Servicio sin HTTP.

`import_report(db, path, *, filename, uploaded_by_user_id)` -> `ImportSummary`. Patron: `toku_report_import` (TK-18).

Reglas
------
* Idempotencia: `vp_report_files.file_sha256` es UNICO. Un archivo con el mismo contenido (aunque cambie el nombre)
  que uno completado responde «ya cargado» sin reprocesar (la ruta lo traduce a 409). Un intento previo `failed`
  (o `running` abandonado hace mas de 30 min) se reutiliza. Un `running` reciente es `carga_en_curso`.
* Upsert por clave natural (`Id cargo` / `Id de suscripcion`), en trozos de hasta 2000 filas con
  `INSERT ... ON CONFLICT DO UPDATE`. Guarda de frescura: cada columna se actualiza con
  `CASE WHEN excluded.source_generated_at >= tabla.source_generated_at THEN nuevo ELSE actual END`, asi un reporte
  mas viejo nunca pisa a uno mas nuevo y el resultado final no depende del orden de carga. `source_generated_at` es el
  epoch del nombre del archivo (o «ahora» si no se puede leer; ver el parser). `payment_external_id` y
  `subscription_external_id` son «pegajosos» (un NULL posterior no borra un valor ya conocido).
* Plataforma (virtualpos1/virtualpos2): los PAT no la traen. Se deduce de `vp_charges` (por `Id cargo`),
  `vp_payments` (por `UUID transaccion`) y `vp_subscriptions` (por `Id suscripcion`; en suscripciones tambien por los
  cobros). Si todas las senales coinciden -> `resolved`; si discrepan -> `ambiguous` (NO se fuerza); sin senal ->
  `unresolved`. `reconcile()` reevalua lo pendiente y es idempotente (se puede correr tras cada sync).
* Glosa de rechazo (decision D6): solo para cobros `rechazado` con plataforma resuelta se escribe
  `payment_rejection_details` con `capture_source = 'report_pat'` (el codigo `''` queda como marcador). Si la API ya
  guardo una glosa real del cobro, la API manda y no se duplica; un marcador de la API se reemplaza por la glosa real.
  Las glosas nuevas alimentan `rejection_reason_catalog` y el evento `reason_changed` (`status_events`, como RJ-06).
* Vinculo pago -> cobro: `UUID transaccion` -> `Id cargo` (1 a 1) con UPDATE explicito solo donde esta NULL:
  `vp_payments.charge_external_id` y `core_payments.charge_id`. Un UUID asociado a mas de un cobro no se vincula.
* Una transaccion por archivo: ante cualquier error, rollback total y `vp_report_files.status = 'failed'` con un
  `error_label` tecnico corto (`etapa:ClaseDeExcepcion[/ClaseDriver]`), sin texto libre ni PII. La excepcion
  `ReportImportError` se levanta `from None` y nunca lleva el mensaje original.
* Sin pepper (`VP_REPORT_HASH_PEPPER`) se carga igual pero sin hash de vendedor (advertencia en el resumen).
* Los errores de formato se levantan antes de crear la fila de `vp_report_files`.
"""

import hashlib
import logging
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import (
    DateTime,
    case,
    func,
    literal,
    literal_column,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.vp_report import VpReportFile, VpReportPayment, VpReportSubscription
from app.services import status_events
from app.services.vp_report_parser import (
    ParsedReport,
    ReportFormatError,
    UnsupportedReportError,
    open_report,
)

__all__ = [
    "CHUNK_SIZE",
    "ImportSummary",
    "ReportFormatError",
    "ReportImportError",
    "UnsupportedReportError",
    "import_report",
    "link_payments_from_reports",
    "reconcile",
    "resolve_platforms",
    "subscription_report_fields",
]

logger = logging.getLogger(__name__)

CHUNK_SIZE = 2000
MAX_BIND_PARAMS = 60_000  # psycopg admite 65.535 parametros por sentencia
STALE_RUNNING_AFTER = timedelta(minutes=30)
CAPTURE_SOURCE = "report_pat"
VP_PLATFORMS_SQL = "('virtualpos1', 'virtualpos2')"


class ReportImportError(Exception):
    """Fallo de carga. `str(exc)` y `label` no contienen PII ni texto del error original."""

    def __init__(self, label: str, *, file_id: uuid.UUID | None = None) -> None:
        super().__init__(f"fallo la carga del reporte ({label})")
        self.label = label
        self.file_id = file_id
        self.detail = None


@dataclass
class ImportSummary:
    report_type: str
    file_id: uuid.UUID
    already_loaded: bool = False
    status: str = "completed"
    generated_at: datetime | None = None
    window_start: date | None = None
    window_end: date | None = None
    rows_total: int = 0
    rows_new: int = 0
    rows_updated: int = 0
    rows_skipped: int = 0
    rows_stale: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    discarded_card_values: int = 0
    platforms: dict[str, int] = field(default_factory=dict)  # estado de la tabla del reporte tras la carga
    rejections: dict[str, int] = field(default_factory=dict)
    links: dict[str, int] = field(default_factory=dict)
    extra_columns: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Spec:
    model: type
    key: str
    sticky: frozenset[str]


_SPECS = {
    "transacciones": _Spec(VpReportPayment, "charge_external_id", frozenset({"payment_external_id", "subscription_external_id"})),
    "suscriptores": _Spec(VpReportSubscription, "subscription_external_id", frozenset()),
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _upsert_rows(db: Session, spec: _Spec, rows: list[dict[str, Any]], generated_at: datetime) -> tuple[int, int, int]:
    """(nuevas, actualizadas, obsoletas) para un trozo. `rows` homogeneas y sin claves repetidas."""
    table = spec.model.__table__
    stmt = pg_insert(spec.model).values(rows)
    exc = stmt.excluded
    newer = exc.source_generated_at >= table.c.source_generated_at
    set_: dict[str, Any] = {}
    for col in rows[0]:
        if col == spec.key:
            continue
        ec, tc = exc[col], table.c[col]
        if col == "source_generated_at":
            set_[col] = func.greatest(ec, tc)
        elif col in spec.sticky:
            set_[col] = case((newer, func.coalesce(ec, tc)), else_=func.coalesce(tc, ec))
        else:
            set_[col] = case((newer, ec), else_=tc)
    set_["updated_at"] = case((newer, func.now()), else_=table.c.updated_at)
    stmt = stmt.on_conflict_do_update(index_elements=[spec.key], set_=set_).returning(
        literal_column("(xmax = 0)").label("inserted"),
        (table.c.source_generated_at > literal(generated_at, DateTime(timezone=True))).label("stale"),
    )
    new = updated = stale = 0
    for inserted, is_stale in db.execute(stmt):
        if inserted:
            new += 1
        elif is_stale:
            stale += 1
        else:
            updated += 1
    return new, updated, stale


def _register_file(db: Session, parsed: ParsedReport, sha: str, filename: str, user_id) -> VpReportFile | ImportSummary:
    meta = parsed.meta
    existing = db.scalar(select(VpReportFile).where(VpReportFile.file_sha256 == sha))
    now = datetime.now(UTC)
    if existing is not None:
        if existing.status == "completed":
            return ImportSummary(
                report_type=existing.report_type,
                file_id=existing.id,
                already_loaded=True,
                status="already_loaded",
                generated_at=existing.generated_at,
                window_start=existing.window_start,
                window_end=existing.window_end,
                rows_total=existing.rows_total,
                rows_new=existing.rows_new,
                rows_updated=existing.rows_updated,
                rows_skipped=existing.rows_skipped,
            )
        if existing.status == "running" and now - existing.loaded_at < STALE_RUNNING_AFTER:
            raise ReportImportError("carga_en_curso", file_id=existing.id)
        record = existing
    else:
        record = VpReportFile(file_sha256=sha)
        db.add(record)
    record.report_type = meta.report_type
    record.filename = Path(filename.replace("\\", "/")).name[:255] or "reporte.csv"
    record.generated_at = meta.generated_at
    record.window_start = record.window_end = None
    record.rows_total = record.rows_new = record.rows_updated = record.rows_skipped = 0
    record.status = "running"
    record.error_label = None
    record.uploaded_by_user_id = user_id
    record.loaded_at = now
    record.finished_at = None
    db.flush()
    db.commit()  # la fila queda visible aunque la carga de datos haga rollback
    return record


def _failure_label(stage: str, exc: Exception) -> str:
    label = f"{stage}:{type(exc).__name__}"
    orig = getattr(exc, "orig", None)
    if isinstance(exc, DBAPIError) and orig is not None:
        label += f"/{type(orig).__name__}"
    return label[:100]


# ---- resolucion de plataforma -------------------------------------------------------------------------------

_RESOLVE_PAYMENTS_SQL = f"""
WITH sig AS (
    SELECT r.id AS rid, c.platform FROM vp_report_payments r
        JOIN vp_charges c ON c.external_id = r.charge_external_id
    WHERE r.platform_status <> 'resolved' AND c.platform IN {VP_PLATFORMS_SQL}
    UNION
    SELECT r.id, p.platform FROM vp_report_payments r
        JOIN vp_payments p ON p.external_id = r.payment_external_id
    WHERE r.platform_status <> 'resolved' AND r.payment_external_id IS NOT NULL AND p.platform IN {VP_PLATFORMS_SQL}
    UNION
    SELECT r.id, s.platform FROM vp_report_payments r
        JOIN vp_subscriptions s ON s.external_id = r.subscription_external_id
    WHERE r.platform_status <> 'resolved' AND r.subscription_external_id IS NOT NULL AND s.platform IN {VP_PLATFORMS_SQL}
), agg AS (
    SELECT rid, count(DISTINCT platform) AS n, min(platform) AS p FROM sig GROUP BY rid
)
UPDATE vp_report_payments r
SET platform = CASE WHEN agg.n = 1 THEN agg.p END,
    platform_status = CASE WHEN agg.n = 1 THEN 'resolved' ELSE 'ambiguous' END,
    updated_at = now()
FROM agg
WHERE r.id = agg.rid AND r.platform_status <> 'resolved'
  AND r.platform_status IS DISTINCT FROM (CASE WHEN agg.n = 1 THEN 'resolved' ELSE 'ambiguous' END)
RETURNING r.platform_status
"""

_RESOLVE_SUBSCRIPTIONS_SQL = f"""
WITH sig AS (
    SELECT r.id AS rid, s.platform FROM vp_report_subscriptions r
        JOIN vp_subscriptions s ON s.external_id = r.subscription_external_id
    WHERE r.platform_status <> 'resolved' AND s.platform IN {VP_PLATFORMS_SQL}
    UNION
    SELECT r.id, c.platform FROM vp_report_subscriptions r
        JOIN vp_charges c ON c.subscription_external_id = r.subscription_external_id
    WHERE r.platform_status <> 'resolved' AND c.platform IN {VP_PLATFORMS_SQL}
), agg AS (
    SELECT rid, count(DISTINCT platform) AS n, min(platform) AS p FROM sig GROUP BY rid
)
UPDATE vp_report_subscriptions r
SET platform = CASE WHEN agg.n = 1 THEN agg.p END,
    platform_status = CASE WHEN agg.n = 1 THEN 'resolved' ELSE 'ambiguous' END,
    updated_at = now()
FROM agg
WHERE r.id = agg.rid AND r.platform_status <> 'resolved'
  AND r.platform_status IS DISTINCT FROM (CASE WHEN agg.n = 1 THEN 'resolved' ELSE 'ambiguous' END)
RETURNING r.platform_status
"""


def resolve_platforms(db: Session) -> dict[str, int]:
    """Reevalua las filas no resueltas con las senales de `vp_*`. Devuelve los CAMBIOS: {resolved, ambiguous}."""
    changes: Counter = Counter()
    for sql in (_RESOLVE_PAYMENTS_SQL, _RESOLVE_SUBSCRIPTIONS_SQL):
        changes.update(status for (status,) in db.execute(text(sql)))
    return {"resolved": changes["resolved"], "ambiguous": changes["ambiguous"]}


def _platform_counts(db: Session, model: type) -> dict[str, int]:
    rows = dict(db.execute(select(model.platform_status, func.count()).group_by(model.platform_status)).all())
    return {k: int(rows.get(k, 0)) for k in ("resolved", "ambiguous", "unresolved")}


# ---- glosa de rechazo (RJ-04) ---------------------------------------------------------------------------------

_DELETE_MARKERS_SQL = """
DELETE FROM payment_rejection_details d
USING vp_report_payments r
WHERE r.platform_status = 'resolved' AND r.charge_status = 'rechazado' AND coalesce(r.response_code, '') <> ''
  AND d.source = r.platform AND d.charge_external_id = r.charge_external_id AND d.code = ''
"""

_INSERT_DETAILS_SQL = """
INSERT INTO payment_rejection_details
    (id, source, charge_external_id, payment_external_id, subscription_external_id, code, reason, acquirer_code,
     amount, rejected_at, captured_at, capture_source, checked_at)
SELECT gen_random_uuid(), r.platform, r.charge_external_id, r.payment_external_id, r.subscription_external_id,
       coalesce(r.response_code, ''),
       CASE WHEN coalesce(r.response_code, '') <> '' THEN r.response_text END,
       CASE WHEN r.response_code ~ '^-2[0-9]{3}$' THEN r.response_code END,
       r.amount,
       (r.scheduled_date::timestamp AT TIME ZONE 'America/Santiago'),
       now(), 'report_pat', now()
FROM vp_report_payments r
WHERE r.platform_status = 'resolved' AND r.charge_status = 'rechazado'
  AND NOT EXISTS (
      SELECT 1 FROM payment_rejection_details d
      WHERE d.source = r.platform AND d.charge_external_id = r.charge_external_id
        AND (d.code <> '' OR coalesce(r.response_code, '') = '')
  )
ON CONFLICT DO NOTHING
RETURNING source, charge_external_id, subscription_external_id, amount, code, reason
"""


def _apply_rejection_details(db: Session) -> dict[str, int]:
    """Escribe `payment_rejection_details` (capture_source `report_pat`) para cobros rechazados con plataforma resuelta."""
    markers = db.execute(text(_DELETE_MARKERS_SQL)).rowcount or 0
    inserted = db.execute(text(_INSERT_DETAILS_SQL)).all()
    entries = [
        {
            "source": row.source,
            "external_id": row.charge_external_id,
            "subscription_external_id": row.subscription_external_id,
            "amount": row.amount,
            "code": row.code,
            "reason": row.reason,
        }
        for row in inserted
        if row.code
    ]
    reasons_new = status_events.emit_reason_events(db, entries) if entries else 0
    return {"inserted": len(inserted), "markers_replaced": markers, "reasons_new": reasons_new}


# ---- vinculo pago -> cobro -------------------------------------------------------------------------------------

_LINK_CTE = """
WITH link AS (
    SELECT platform, payment_external_id, min(charge_external_id) AS charge_external_id
    FROM vp_report_payments
    WHERE platform_status = 'resolved' AND payment_external_id IS NOT NULL
    GROUP BY platform, payment_external_id
    HAVING count(DISTINCT charge_external_id) = 1
)
"""

_LINK_VP_SQL = (
    _LINK_CTE
    + """
UPDATE vp_payments p SET charge_external_id = link.charge_external_id, updated_at = now()
FROM link
WHERE p.platform = link.platform AND p.external_id = link.payment_external_id AND p.charge_external_id IS NULL
  AND EXISTS (SELECT 1 FROM vp_charges c WHERE c.platform = link.platform AND c.external_id = link.charge_external_id)
"""
)

_LINK_CORE_SQL = (
    _LINK_CTE
    + """
UPDATE core_payments cp SET charge_id = cc.id, updated_at = now()
FROM link JOIN core_charges cc ON cc.source = link.platform AND cc.external_id = link.charge_external_id
WHERE cp.source = link.platform AND cp.external_id = link.payment_external_id AND cp.charge_id IS NULL
"""
)


def link_payments_from_reports(db: Session) -> dict[str, int]:
    """UPDATE explicito e idempotente del vinculo pago -> cobro desde el cruce exacto UUID -> Id cargo del reporte.

    Solo donde el vinculo esta NULL (`vp_payments.charge_external_id`, `core_payments.charge_id`). Nunca por RUT ni
    por inferencia. Desde VP-PAR-06 el sync ya no reescribe `vp_payments.charge_external_id` a NULL, y el ETL Core
    (`core_vp_etl._link_payments_to_charges`) repite este paso en cada corrida para los pagos que llegan despues.
    """
    vp = db.execute(text(_LINK_VP_SQL)).rowcount or 0
    core = db.execute(text(_LINK_CORE_SQL)).rowcount or 0
    return {"vp_payments": vp, "core_payments": core}


# ---- campos de suscripcion (VP-PAR-09) ---------------------------------------------------------------------------


def subscription_report_fields(db: Session) -> dict[tuple[str, str], dict[str, str | None]]:
    """Motivo de rechazo y tarjeta de `SuscriptoresPAT` por (plataforma, suscripcion). Solo filas `resolved`.

    `{(platform, subscription_external_id): {rejection_reason, card_last4, card_type, card_brand}}`, sin claves vacias
    (una fila sin motivo ni tarjeta no aparece). Solo lectura; la proyeccion a `core_*` la decide `core_vp_etl`.
    """
    rows = db.execute(
        select(
            VpReportSubscription.platform, VpReportSubscription.subscription_external_id,
            VpReportSubscription.rejection_reason, VpReportSubscription.card_last4,
            VpReportSubscription.card_type, VpReportSubscription.card_brand,
        ).where(VpReportSubscription.platform_status == "resolved")
    )
    out: dict[tuple[str, str], dict[str, str | None]] = {}
    for platform, sub, reason, last4, card_type, brand in rows:
        values = {
            "rejection_reason": (reason or "").strip() or None,
            "card_last4": last4 or None,
            "card_type": (card_type or "").strip() or None,
            "card_brand": (brand or "").strip() or None,
        }
        if any(values.values()):
            out[(platform, sub)] = values
    return out


def reconcile(db: Session, *, commit: bool = True) -> dict[str, Any]:
    """Resolucion de plataforma + glosas + vinculos sobre lo ya cargado. Idempotente."""
    out: dict[str, Any] = {
        "platform_changes": resolve_platforms(db),
        "rejections": _apply_rejection_details(db),
        "links": link_payments_from_reports(db),
    }
    if commit:
        db.commit()
    return out


# ---- carga ------------------------------------------------------------------------------------------------------


def import_report(
    db: Session,
    path: str | Path,
    *,
    filename: str,
    uploaded_by_user_id: uuid.UUID | None,
) -> ImportSummary:
    path = Path(path)
    sha = _sha256_file(path)
    parsed = open_report(path, pepper=settings.vp_report_hash_pepper, filename=filename)
    with parsed:
        meta = parsed.meta
        registered = _register_file(db, parsed, sha, filename, uploaded_by_user_id)
        if isinstance(registered, ImportSummary):
            registered.extra_columns = meta.extra_columns
            registered.warnings = meta.warnings
            return registered
        file_id = registered.id
        summary = ImportSummary(
            report_type=meta.report_type,
            file_id=file_id,
            generated_at=meta.generated_at,
            extra_columns=meta.extra_columns,
            warnings=meta.warnings,
        )
        stage = "load"
        try:
            spec = _SPECS[meta.report_type]
            buffer: list = []
            chunk_size = CHUNK_SIZE

            def flush() -> None:
                if not buffer:
                    return
                rows = []
                for rec in buffer:
                    row = dict(vars(rec))
                    row["source_generated_at"] = meta.generated_at
                    row["last_file_id"] = file_id
                    rows.append(row)
                buffer.clear()
                new, upd, stale = _upsert_rows(db, spec, rows, meta.generated_at)
                summary.rows_new += new
                summary.rows_updated += upd
                summary.rows_stale += stale

            for rec in parsed.records():
                if not buffer:
                    chunk_size = max(1, min(CHUNK_SIZE, MAX_BIND_PARAMS // (len(vars(rec)) + 2)))
                buffer.append(rec)
                if len(buffer) >= chunk_size:
                    flush()
            flush()

            summary.rows_total = parsed.stats.rows_total
            summary.rows_skipped = parsed.stats.rows_skipped
            summary.skip_reasons = dict(parsed.stats.skip_reasons)
            summary.discarded_card_values = parsed.stats.discarded_card_values
            summary.window_start, summary.window_end = parsed.stats.window_start, parsed.stats.window_end

            stage = "resolve"
            resolve_platforms(db)
            summary.platforms = _platform_counts(db, spec.model)
            if meta.report_type == "transacciones":
                stage = "rejections"
                summary.rejections = _apply_rejection_details(db)
                stage = "link"
                summary.links = link_payments_from_reports(db)

            stage = "finalize"
            db.execute(
                update(VpReportFile)
                .where(VpReportFile.id == file_id)
                .values(
                    status="completed",
                    rows_total=summary.rows_total,
                    rows_new=summary.rows_new,
                    rows_updated=summary.rows_updated,
                    rows_skipped=summary.rows_skipped,
                    window_start=summary.window_start,
                    window_end=summary.window_end,
                    finished_at=datetime.now(UTC),
                    error_label=None,
                )
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001 - cualquier falla revierte el archivo y se etiqueta sin PII
            db.rollback()
            label = _failure_label(stage, exc)
            logger.warning("Importacion de reporte PAT de VirtualPOS fallida (%s)", label)
            db.execute(
                update(VpReportFile)
                .where(VpReportFile.id == file_id)
                .values(status="failed", error_label=label, finished_at=datetime.now(UTC))
            )
            db.commit()
            raise ReportImportError(label, file_id=file_id) from None
    return summary
