"""Carga de reportes de Toku a las tablas `tk_report_*` (TK-18, fase CARGA). Servicio sin HTTP.

`import_report(db, path, *, filename, uploaded_by_user_id, etl_run_id=None)` -> `ImportSummary`.

Reglas
------
* D2 / DEC-17: `ID Producto` (contiene el RUT) solo se persiste como `product_key_hash` (HMAC-SHA256 con el
  pepper `TOKU_REPORT_HASH_PEPPER`) mas el `sub_` resuelto. Sin pepper: `MissingPepperError` («falta
  TOKU_REPORT_HASH_PEPPER») ANTES de abrir el archivo y sin tocar la base (falla cerrada). El archivo no se
  guarda; solo se calcula su sha256 en streaming.
* Idempotencia: `tk_report_files(report_type, file_sha256)` completado -> resultado «ya cargado» sin
  reprocesar. Un intento previo `failed` (o `running` abandonado hace mas de 30 min) se reutiliza.
* Orden dentro del archivo: catalogo de codigos (hoja «Codigos de Error Toku», solo en Intentos), luego datos.
  Chunks de 2000 filas con `INSERT ... ON CONFLICT DO UPDATE` por la clave natural de cada tabla (TK-17).
* Frescura: un reporte mas viejo no pisa a uno mas nuevo y el resultado final no depende del orden de carga.
  Implementacion: cada columna se actualiza con `CASE WHEN excluded.source_generated_at >= tabla.source_generated_at
  THEN excluded.col ELSE tabla.col END` (equivale a la guarda `WHERE excluded >= tabla` para las columnas
  normales; la forma CASE ademas permite que `deleted_at_source` sea pegajoso en ambos ordenes, ver abajo).
  `source_generated_at` = GREATEST de ambos. El catalogo de codigos se protege con la fecha de generacion del
  archivo que lo cargo por ultima vez (`tk_report_response_codes.source_file_id`).
* `deleted_at_source` nunca se «des-elimina»: `coalesce(nuevo, existente)` si el reporte es mas nuevo y
  `coalesce(existente, nuevo)` si es mas viejo; si ambos tienen valor gana el del reporte mas nuevo.
  Lo mismo para `subscription_external_id` (una resolucion previa no se borra con un NULL).
* Resolucion producto -> `sub_`: por `product_key_hash` contra `tk_report_products` (si un hash tiene varios
  `sub_`, gana el no eliminado y luego el de creacion mas reciente). Intentos y Deudas guardan el `sub_` (NULL si
  no resuelve, contador `unresolved_product`); `resolve_subscriptions(db)` (idempotente) completa los NULL cuando
  llega Productos, y se invoca automaticamente al final de cada carga de Productos. Medios de pago NO tiene
  columna `subscription_external_id` en TK-17: se relaciona por `product_key_hash`. Inscripciones trae su
  `id_subscription` directo.
* Una transaccion por archivo: ante cualquier error, rollback total y `tk_report_files.status='failed'` con
  `error_label` tecnico corto (`etapa:ClaseDeExcepcion[/ClaseDriver]`), sin texto libre ni PII. La excepcion
  `ReportImportError` se levanta `from None` (los mensajes de SQLAlchemy incluyen parametros).
* Contadores: rows_total (filas con datos), rows_new, rows_updated, rows_skipped (invalidas + duplicadas, por
  motivo en `skip_reasons`), mas `rows_stale` (filas no aplicadas por ser el archivo mas viejo que el dato
  guardado; no se persiste en `tk_report_files`). total = new + updated + skipped + stale.
* Los errores de formato (`ReportFormatError`, `UnsupportedReportError`) se levantan antes de crear la fila de
  `tk_report_files` (aun no hay tipo valido); TK-19 deberia mapearlos a 422.
"""

import hashlib
import logging
import re
import uuid
from collections.abc import Iterable
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
from app.models.toku_report import (
    TkReportAttempt,
    TkReportDebt,
    TkReportFile,
    TkReportInscription,
    TkReportPaymentMethod,
    TkReportProduct,
    TkReportResponseCode,
)
from app.services.read_only_provider_sync import safe_error_message
from app.services.toku_report_parser import (
    MissingPepperError,
    ParsedReport,
    ReportFormatError,
    UnsupportedReportError,
    open_report,
    read_response_catalog,
)

__all__ = [
    "CHUNK_SIZE",
    "ImportSummary",
    "MissingPepperError",
    "ReportFormatError",
    "ReportImportError",
    "UnsupportedReportError",
    "import_report",
    "resolve_subscriptions",
    "safe_report_error_message",
]

logger = logging.getLogger(__name__)

CHUNK_SIZE = 2000
STALE_RUNNING_AFTER = timedelta(minutes=30)
_RUT_RE = re.compile(r"\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


class ReportImportError(Exception):
    """Fallo de carga. `str(exc)` y `label` no contienen PII; `detail` es opcional y esta redactado."""

    def __init__(self, label: str, *, file_id: uuid.UUID | None = None, detail: str | None = None) -> None:
        super().__init__(f"fallo la carga del reporte ({label})")
        self.label = label
        self.file_id = file_id
        self.detail = detail


def safe_report_error_message(exc: Exception, secrets: Iterable[str] = ()) -> str:
    """`safe_error_message` ampliado: ademas de numeros largos, redacta RUT y correos."""
    message = safe_error_message(exc, secrets)
    return _EMAIL_RE.sub("[redacted]", _RUT_RE.sub("[redacted]", message))


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
    unresolved_product: int = 0
    resolved_later: dict[str, int] = field(default_factory=dict)
    catalog_codes: int = 0
    catalog_skipped: int = 0
    extra_columns: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Spec:
    model: type
    keys: tuple[str, ...]
    resolves_product: bool = False


_SPECS = {
    "productos": _Spec(TkReportProduct, ("subscription_external_id",)),
    "medios_pago": _Spec(TkReportPaymentMethod, ("payment_method_external_id", "product_key_hash")),
    "intentos": _Spec(TkReportAttempt, ("attempt_external_id",), resolves_product=True),
    "deudas": _Spec(TkReportDebt, ("debt_external_id",), resolves_product=True),
    "inscripciones": _Spec(TkReportInscription, ("inscription_external_id",)),
}
_STICKY = {"deleted_at_source", "subscription_external_id"}

_BRIDGE_SQL = """
SELECT DISTINCT ON (product_key_hash) product_key_hash AS h, subscription_external_id AS s
FROM tk_report_products
WHERE product_key_hash <> ''
ORDER BY product_key_hash, (deleted_at_source IS NULL) DESC, created_at_source DESC NULLS LAST,
         subscription_external_id
"""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_bridge(db: Session) -> dict[str, str]:
    return {row.h: row.s for row in db.execute(text(_BRIDGE_SQL))}


def resolve_subscriptions(db: Session, *, commit: bool = True) -> dict[str, int]:
    """Completa `subscription_external_id` NULL de intentos y deudas usando Productos. Idempotente."""
    out: dict[str, int] = {}
    for label, table in (("attempts", "tk_report_attempts"), ("debts", "tk_report_debts")):
        result = db.execute(
            text(
                f"UPDATE {table} t SET subscription_external_id = b.s, updated_at = now() "
                f"FROM ({_BRIDGE_SQL}) b "
                "WHERE t.subscription_external_id IS NULL AND t.product_key_hash <> '' AND t.product_key_hash = b.h"
            )
        )
        out[label] = result.rowcount or 0
    if commit:
        db.commit()
    return out


def _upsert_rows(db: Session, spec: _Spec, rows: list[dict[str, Any]], generated_at: datetime) -> tuple[int, int, int]:
    """(nuevas, actualizadas, obsoletas) para un chunk. `rows` homogeneas y sin claves repetidas."""
    model = spec.model
    table = model.__table__
    stmt = pg_insert(model).values(rows)
    exc = stmt.excluded
    newer = exc.source_generated_at >= table.c.source_generated_at
    set_: dict[str, Any] = {}
    for col in rows[0]:
        if col in spec.keys:
            continue
        ec, tc = exc[col], table.c[col]
        if col == "source_generated_at":
            set_[col] = func.greatest(ec, tc)
        elif col in _STICKY:
            set_[col] = case((newer, func.coalesce(ec, tc)), else_=func.coalesce(tc, ec))
        else:
            set_[col] = case((newer, ec), else_=tc)
    set_["updated_at"] = case((newer, func.now()), else_=table.c.updated_at)
    stmt = stmt.on_conflict_do_update(index_elements=list(spec.keys), set_=set_).returning(
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


def _upsert_catalog(db: Session, records: list, file_id: uuid.UUID, generated_at: datetime) -> int:
    if not records:
        return 0
    rows = [
        {
            "code": r.code,
            "severity": r.severity,
            "message": r.message,
            "description": r.description,
            "source_file_id": file_id,
        }
        for r in records
    ]
    stmt = pg_insert(TkReportResponseCode).values(rows)
    exc = stmt.excluded
    # Solo gana el catalogo de un archivo igual o mas nuevo que el que cargo el codigo por ultima vez.
    owner_generated = literal_column(
        "(SELECT f.generated_at FROM tk_report_files f WHERE f.id = tk_report_response_codes.source_file_id)", type_=DateTime(timezone=True)
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["code"],
        set_={
            "severity": exc.severity,
            "message": exc.message,
            "description": exc.description,
            "source_file_id": exc.source_file_id,
            "updated_at": func.now(),
        },
        where=func.coalesce(owner_generated, literal(datetime.min.replace(tzinfo=UTC), DateTime(timezone=True)))
        <= literal(generated_at, DateTime(timezone=True)),
    )
    db.execute(stmt)
    return len(rows)


def _register_file(db: Session, parsed: ParsedReport, sha: str, filename: str, user_id, etl_run_id) -> TkReportFile | ImportSummary:
    meta = parsed.meta
    existing = db.scalar(
        select(TkReportFile).where(TkReportFile.report_type == meta.report_type, TkReportFile.file_sha256 == sha)
    )
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
        if existing.status == "running" and now - existing.started_at < STALE_RUNNING_AFTER:
            raise ReportImportError("carga_en_curso", file_id=existing.id)
        record = existing
    else:
        record = TkReportFile(report_type=meta.report_type, file_sha256=sha)
        db.add(record)
    record.filename = Path(filename.replace("\\", "/")).name[:255] or "reporte.xlsx"
    record.generated_at = meta.generated_at
    record.window_start = meta.window_start
    record.window_end = meta.window_end
    record.rows_total = record.rows_new = record.rows_updated = record.rows_skipped = 0
    record.status = "running"
    record.error_label = None
    record.etl_run_id = etl_run_id
    record.uploaded_by_user_id = user_id
    record.started_at = now
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


def import_report(
    db: Session,
    path: str | Path,
    *,
    filename: str,
    uploaded_by_user_id: uuid.UUID | None,
    etl_run_id: uuid.UUID | None = None,
) -> ImportSummary:
    pepper = settings.toku_report_hash_pepper
    if not pepper:  # falla cerrada: antes de abrir el archivo
        raise MissingPepperError("falta TOKU_REPORT_HASH_PEPPER")
    path = Path(path)
    sha = _sha256_file(path)
    severity: dict[str, str] = {}
    parsed = open_report(path, pepper=pepper, severity_lookup=severity)
    with parsed:
        meta = parsed.meta
        registered = _register_file(db, parsed, sha, filename, uploaded_by_user_id, etl_run_id)
        if isinstance(registered, ImportSummary):
            registered.extra_columns = meta.extra_columns
            registered.warnings = meta.warnings
            return registered
        file_id = registered.id
        summary = ImportSummary(
            report_type=meta.report_type,
            file_id=file_id,
            generated_at=meta.generated_at,
            window_start=meta.window_start,
            window_end=meta.window_end,
            extra_columns=meta.extra_columns,
            warnings=meta.warnings,
        )
        stage = "catalog"
        try:
            if meta.report_type == "intentos":
                catalog, catalog_stats = read_response_catalog(path)
                summary.catalog_codes = _upsert_catalog(db, catalog, file_id, meta.generated_at)
                summary.catalog_skipped = catalog_stats.rows_skipped
                severity.update(db.execute(select(TkReportResponseCode.code, TkReportResponseCode.severity)).all())
            stage = "load"
            spec = _SPECS[meta.report_type]
            bridge = _load_bridge(db) if spec.resolves_product else {}
            buffer: list = []

            def flush() -> None:
                if not buffer:
                    return
                rows = []
                for rec in buffer:
                    row = dict(vars(rec))
                    if spec.resolves_product:
                        sub = bridge.get(row["product_key_hash"]) if row["product_key_hash"] else None
                        row["subscription_external_id"] = sub
                        if sub is None:
                            summary.unresolved_product += 1
                    row["source_generated_at"] = meta.generated_at
                    row["last_file_id"] = file_id
                    rows.append(row)
                buffer.clear()
                new, upd, stale = _upsert_rows(db, spec, rows, meta.generated_at)
                summary.rows_new += new
                summary.rows_updated += upd
                summary.rows_stale += stale

            for rec in parsed.records():
                buffer.append(rec)
                if len(buffer) >= CHUNK_SIZE:
                    flush()
            flush()

            stage = "finalize"
            summary.rows_total = parsed.stats.rows_total
            summary.rows_skipped = parsed.stats.rows_skipped
            summary.skip_reasons = dict(parsed.stats.skip_reasons)
            if meta.report_type == "productos":
                summary.resolved_later = resolve_subscriptions(db, commit=False)
            db.execute(
                update(TkReportFile)
                .where(TkReportFile.id == file_id)
                .values(
                    status="completed",
                    rows_total=summary.rows_total,
                    rows_new=summary.rows_new,
                    rows_updated=summary.rows_updated,
                    rows_skipped=summary.rows_skipped,
                    finished_at=datetime.now(UTC),
                    error_label=None,
                )
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001 - cualquier falla revierte el archivo y se etiqueta sin PII
            db.rollback()
            label = _failure_label(stage, exc)
            logger.warning("Importacion de reporte Toku fallida (%s)", label)
            db.execute(
                update(TkReportFile)
                .where(TkReportFile.id == file_id)
                .values(status="failed", error_label=label, finished_at=datetime.now(UTC))
            )
            db.commit()
            detail = None if isinstance(exc, DBAPIError) else safe_report_error_message(exc)[:300]
            raise ReportImportError(label, file_id=file_id, detail=detail) from None
    return summary

