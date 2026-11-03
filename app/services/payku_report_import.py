"""Carga de reportes de Payku (PK-PAR-10) y proyeccion de sus campos financieros a `p_*` (PK-PAR-11). Sin HTTP.

`import_report(db, path, *, filename, uploaded_by_user_id)` -> `PaykuImportSummary`.

Reglas
------
* Idempotencia: `p_report_files(report_type, file_sha256)` completado -> «ya cargado» sin reprocesar; un intento previo
  fallido se reutiliza. El archivo no se guarda (solo su sha256).
* Transacciones -> `p_report_transactions` (upsert por `row_key`); Liquidaciones -> `p_report_settlements` (upsert por
  id de liquidacion). Suscripciones no tiene tabla propia: solo proyecta la proxima fecha de cobro.
* Proyeccion PK-PAR-11 (misma transaccion):
  - `p_transactions.commission`, `net_amount` y `payment_method` (medio de pago; si no hay, tipo de pago) desde el
    reporte, solo para vouchers que aparecen UNA vez en el reporte (en anos antiguos el voucher se repite y el cruce
    seria ambiguo). El reporte es la unica fuente de esos campos, asi que los escribe.
  - `p_transactions.installment_number`: se completa si esta vacio, desde el reporte o desde «Cobro: # n» del
    concepto del API (`description`).
  - `p_subscriptions.next_charge_date`: desde el reporte de suscripciones (la API no lo trae).
* Una transaccion por archivo: ante un error, rollback y `p_report_files.status='failed'` con etiqueta tecnica
  (`etapa:Clase`), sin texto libre ni PII. Los logs solo llevan tipo, id de archivo y contadores.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import literal_column, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models.payku_report import (
    PkReportFile,
    PkReportSettlement,
    PkReportTransaction,
)
from app.services.payku_report_parser import iter_records, parse_report, report_type_for

logger = logging.getLogger(__name__)

CHUNK_SIZE = 2000


class PaykuReportImportError(Exception):
    """Fallo de carga. `str(exc)` y `label` no contienen PII."""

    def __init__(self, label: str, *, file_id: uuid.UUID | None = None) -> None:
        super().__init__(f"fallo la carga del reporte Payku ({label})")
        self.label = label
        self.file_id = file_id


@dataclass
class PaykuImportSummary:
    report_type: str
    file_id: uuid.UUID
    already_loaded: bool = False
    sheets: tuple[str, ...] = ()
    rows_total: int = 0
    rows_new: int = 0
    rows_updated: int = 0
    rows_skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)
    extra_columns: tuple[str, ...] = ()
    transactions_enriched: int = 0
    installments_filled: int = 0
    subscriptions_next_date: int = 0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _upsert(db: Session, model: type, key: str, rows: list[dict[str, Any]]) -> tuple[int, int]:
    new = updated = 0
    for i in range(0, len(rows), CHUNK_SIZE):
        chunk = rows[i : i + CHUNK_SIZE]
        stmt = pg_insert(model).values(chunk)
        set_ = {col: stmt.excluded[col] for col in chunk[0] if col != key}
        set_["updated_at"] = text("now()")
        stmt = stmt.on_conflict_do_update(index_elements=[key], set_=set_).returning(
            literal_column("(xmax = 0)").label("inserted")
        )
        for (inserted,) in db.execute(stmt):
            if inserted:
                new += 1
            else:
                updated += 1
    return new, updated


_ENRICH_SQL = text(
    """
    WITH unique_vouchers AS (
        SELECT transaction_external_id
        FROM p_report_transactions
        GROUP BY transaction_external_id
        HAVING COUNT(*) = 1
    )
    UPDATE p_transactions t
    SET commission = r.commission,
        net_amount = r.net_amount,
        payment_method = COALESCE(r.payment_method, r.payment_type, t.payment_method),
        installment_number = COALESCE(t.installment_number, r.installment_number),
        updated_at = now()
    FROM p_report_transactions r
    JOIN unique_vouchers u ON u.transaction_external_id = r.transaction_external_id
    WHERE t.external_id = r.transaction_external_id
      AND (t.commission IS DISTINCT FROM r.commission
           OR t.net_amount IS DISTINCT FROM r.net_amount
           OR t.payment_method IS DISTINCT FROM COALESCE(r.payment_method, r.payment_type, t.payment_method)
           OR (t.installment_number IS NULL AND r.installment_number IS NOT NULL))
    """
)

_INSTALLMENT_SQL = text(
    """
    UPDATE p_transactions
    SET installment_number = (substring(description from '(?i)cobro\\s*:?\\s*#\\s*([0-9]{1,4})'))::int,
        updated_at = now()
    WHERE installment_number IS NULL
      AND description ~* 'cobro\\s*:?\\s*#\\s*[0-9]{1,4}'
    """
)


def project_transactions(db: Session) -> tuple[int, int]:
    """PK-PAR-11: comision, neto, medio de pago y numero de cuota en `p_transactions`. (enriquecidas, cuotas)."""
    enriched = db.execute(_ENRICH_SQL).rowcount or 0
    installments = db.execute(_INSTALLMENT_SQL).rowcount or 0
    return enriched, installments


def project_next_charge_dates(db: Session, records: list) -> int:
    """PK-PAR-11: `p_subscriptions.next_charge_date` desde el reporte de suscripciones."""
    total = 0
    for record in records:
        result = db.execute(
            text(
                "UPDATE p_subscriptions SET next_charge_date = :d, updated_at = now() "
                "WHERE external_id = :ext AND next_charge_date IS DISTINCT FROM :d"
            ),
            {"d": record.next_charge_date, "ext": record.subscription_external_id},
        )
        total += result.rowcount or 0
    return total


def _failure_label(stage: str, exc: Exception) -> str:
    label = f"{stage}:{type(exc).__name__}"
    orig = getattr(exc, "orig", None)
    if isinstance(exc, DBAPIError) and orig is not None:
        label += f"/{type(orig).__name__}"
    return label[:100]


def import_report(
    db: Session, path: str | Path, *, filename: str, uploaded_by_user_id: uuid.UUID | None,
) -> PaykuImportSummary:
    path = Path(path)
    sha = _sha256_file(path)
    sheets = parse_report(path)  # errores de formato antes de registrar el archivo
    report_type = report_type_for(sheets)
    existing = db.scalar(
        select(PkReportFile).where(PkReportFile.report_type == report_type, PkReportFile.file_sha256 == sha)
    )
    if existing is not None and existing.status == "completed":
        return PaykuImportSummary(
            report_type=report_type, file_id=existing.id, already_loaded=True,
            sheets=tuple((existing.sheets or "").split(",")) if existing.sheets else (),
            rows_total=existing.rows_total, rows_new=existing.rows_new, rows_updated=existing.rows_updated,
            rows_skipped=existing.rows_skipped,
        )
    record = existing or PkReportFile(report_type=report_type, file_sha256=sha)
    record.filename = Path(filename.replace("\\", "/")).name[:255] or "reporte.xlsx"
    record.sheets = ",".join(sheet.layout for sheet in sheets)[:255]
    record.status, record.error_label = "running", None
    record.uploaded_by_user_id = uploaded_by_user_id
    record.started_at, record.finished_at = datetime.now(UTC), None
    db.add(record)
    db.flush()
    db.commit()
    file_id = record.id

    summary = PaykuImportSummary(
        report_type=report_type, file_id=file_id, sheets=tuple(sheet.layout for sheet in sheets),
        rows_total=sum(s.rows_total for s in sheets), rows_skipped=sum(s.rows_skipped for s in sheets),
        extra_columns=tuple(sorted({c for s in sheets for c in s.extra_columns})),
    )
    for sheet in sheets:
        for reason, count in sheet.skip_reasons.items():
            summary.skip_reasons[reason] = summary.skip_reasons.get(reason, 0) + count
    stage = "load"
    try:
        tx_rows = [{**vars(r), "last_file_id": file_id} for r in iter_records(sheets, "transacciones")]
        st_rows = [{**vars(r), "last_file_id": file_id} for r in iter_records(sheets, "liquidaciones")]
        for model, key, rows in ((PkReportTransaction, "row_key", tx_rows),
                                 (PkReportSettlement, "settlement_external_id", st_rows)):
            if rows:
                new, upd = _upsert(db, model, key, rows)
                summary.rows_new += new
                summary.rows_updated += upd
        stage = "project"
        if tx_rows:
            summary.transactions_enriched, summary.installments_filled = project_transactions(db)
        subs = list(iter_records(sheets, "suscripciones"))
        if subs:
            summary.subscriptions_next_date = project_next_charge_dates(db, subs)
            summary.rows_updated += len(subs)
        stage = "finalize"
        db.execute(
            update(PkReportFile).where(PkReportFile.id == file_id).values(
                status="completed", rows_total=summary.rows_total, rows_new=summary.rows_new,
                rows_updated=summary.rows_updated, rows_skipped=summary.rows_skipped,
                finished_at=datetime.now(UTC), error_label=None,
            )
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001 - revierte el archivo y se etiqueta sin PII
        db.rollback()
        label = _failure_label(stage, exc)
        logger.warning("Importacion de reporte Payku fallida (%s)", label)
        db.execute(
            update(PkReportFile).where(PkReportFile.id == file_id).values(
                status="failed", error_label=label, finished_at=datetime.now(UTC)
            )
        )
        db.commit()
        raise PaykuReportImportError(label, file_id=file_id) from None
    logger.info(
        "Reporte Payku %s cargado (%s): %d filas, %d nuevas, %d omitidas", file_id, report_type, summary.rows_total,
        summary.rows_new, summary.rows_skipped,
    )
    return summary
