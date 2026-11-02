"""Cargas manuales de reportes descargados: `POST /api/v1/imports/virtualpos-reports` (VP-PAR-02) y
`POST /api/v1/imports/toku-reports` (TK-19, al final del archivo).

Ruta fina: la logica vive en `app/services/vp_report_import.py`. Solo `admin` (permiso `virtualpos.reports.import`),
con CSRF. El archivo se guarda en un temporal que se borra siempre; la auditoria queda en `write_runs` SIN contenido
(solo tipo, nombre de archivo, sha256 y contadores). Los errores salen como `detail = {code, message}` y nunca
incluyen filas del archivo, PII ni el mensaje de la excepcion original.
"""

import hashlib
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db
from app.core.security import require_csrf, require_permissions
from app.models.auth import User
from app.models.write_run import WriteRun
from app.services import toku_report_import, vp_report_import
from app.services.toku_report_parser import MissingPepperError
from app.services.toku_report_parser import ReportFormatError as TokuReportFormatError
from app.services.vp_report_parser import ReportFormatError

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_REPORT_BYTES = 100 * 1024 * 1024
MAX_TOKU_REPORT_BYTES = 100 * 1024 * 1024
_CHUNK = 1024 * 1024


def _error(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


def _audit(
    db: Session, user: User, status: str, payload: dict[str, Any], error: str | None = None, source: str = "virtualpos"
) -> None:
    db.add(
        WriteRun(
            source=source,
            resource_type="report_import",
            external_id=str(payload.get("sha256") or "n/a")[:255],
            operation="import_report",
            status=status,
            request_payload=payload,
            error_message=error,
            finished_at=datetime.now(UTC),
            requested_by_user_id=user.id,
        )
    )
    db.commit()


def _summary_json(summary: vp_report_import.ImportSummary) -> dict[str, Any]:
    return {
        "file_id": str(summary.file_id),
        "report_type": summary.report_type,
        "status": summary.status,
        "already_loaded": summary.already_loaded,
        "generated_at": summary.generated_at.isoformat() if summary.generated_at else None,
        "window_start": summary.window_start.isoformat() if summary.window_start else None,
        "window_end": summary.window_end.isoformat() if summary.window_end else None,
        "rows_total": summary.rows_total,
        "rows_new": summary.rows_new,
        "rows_updated": summary.rows_updated,
        "rows_skipped": summary.rows_skipped,
        "rows_stale": summary.rows_stale,
        "skip_reasons": summary.skip_reasons,
        "platforms": summary.platforms,
        "rejections": summary.rejections,
        "links": summary.links,
        "discarded_card_values": summary.discarded_card_values,
        "extra_columns_count": len(summary.extra_columns),
        "warnings": list(summary.warnings),
    }


@router.post("/virtualpos-reports", dependencies=[Depends(require_csrf)], tags=["Imports"])
def import_virtualpos_report(
    report: Annotated[UploadFile, File(description="Reporte PAT de VirtualPOS (.csv): TransaccionesPAT o SuscriptoresPAT")],
    user: Annotated[User, Depends(require_permissions("virtualpos.reports.import"))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    filename = Path((report.filename or "").replace("\\", "/")).name[:255]
    payload: dict[str, Any] = {"filename": filename}
    if Path(filename).suffix.lower() != ".csv":
        _audit(db, user, "rejected", payload, "invalid_extension")
        raise _error(422, "invalid_format", "Seleccione un reporte .csv de VirtualPOS.")

    temporary: str | None = None
    try:
        digest = hashlib.sha256()
        size = 0
        with tempfile.NamedTemporaryFile(prefix="synkmetrix-vp-", suffix=".csv", delete=False) as tmp:
            temporary = tmp.name
            while chunk := report.file.read(_CHUNK):
                size += len(chunk)
                if size > MAX_REPORT_BYTES:
                    _audit(db, user, "rejected", payload, "too_large")
                    raise _error(413, "too_large", "El reporte supera el tamano maximo permitido.")
                digest.update(chunk)
                tmp.write(chunk)
        if size == 0:
            _audit(db, user, "rejected", payload, "empty_file")
            raise _error(422, "invalid_format", "El archivo esta vacio.")
        payload["sha256"] = digest.hexdigest()

        try:
            summary = vp_report_import.import_report(
                db, temporary, filename=filename or "reporte.csv", uploaded_by_user_id=user.id
            )
        except ReportFormatError as exc:  # solo nombres de columnas/tipos, nunca valores de filas
            _audit(db, user, "rejected", payload, "invalid_format")
            raise _error(422, "invalid_format", str(exc)) from None
        except vp_report_import.ReportImportError as exc:
            if exc.label == "carga_en_curso":
                _audit(db, user, "rejected", payload, "load_in_progress")
                raise _error(409, "load_in_progress", "Este archivo ya se esta cargando.") from None
            _audit(db, user, "failed", payload, exc.label)
            raise _error(500, "import_failed", "No se pudo cargar el reporte.", label=exc.label) from None

        payload.update(
            report_type=summary.report_type,
            file_id=str(summary.file_id),
            rows_total=summary.rows_total,
            rows_new=summary.rows_new,
            rows_updated=summary.rows_updated,
            rows_skipped=summary.rows_skipped,
            rows_stale=summary.rows_stale,
        )
        if summary.already_loaded:
            _audit(db, user, "already_loaded", payload)
            raise _error(
                409,
                "already_loaded",
                "Este reporte ya fue cargado (mismo contenido que un archivo anterior).",
                file_id=str(summary.file_id),
                report_type=summary.report_type,
            )
        _audit(db, user, "completed", payload)
        return _summary_json(summary)
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


# ---- Toku (TK-19) ---------------------------------------------------------------------------------------------


def _toku_summary_json(summary: toku_report_import.ImportSummary) -> dict[str, Any]:
    """Solo contadores y metadatos del archivo: nunca filas, IDs de producto ni hashes."""
    warnings = list(summary.warnings)
    if summary.rows_stale:
        warnings.append("stale_report")  # archivo mas viejo que el dato guardado: esas filas no se aplicaron
    if toku_report_import.is_older_than_max_age(summary.generated_at):
        # DEC-21: el dato del archivo (fecha de generacion) tiene mas de 7 dias. Distinto de `stale_report`.
        warnings.append("data_older_than_max_age")
    return {
        "file_id": str(summary.file_id),
        "report_type": summary.report_type,
        "status": summary.status,
        "already_loaded": summary.already_loaded,
        "generated_at": summary.generated_at.isoformat() if summary.generated_at else None,
        "window_start": summary.window_start.isoformat() if summary.window_start else None,
        "window_end": summary.window_end.isoformat() if summary.window_end else None,
        "rows_total": summary.rows_total,
        "rows_new": summary.rows_new,
        "rows_updated": summary.rows_updated,
        "rows_skipped": summary.rows_skipped,
        "rows_stale": summary.rows_stale,
        "skip_reasons": summary.skip_reasons,
        "unresolved_product": summary.unresolved_product,
        "resolved_later": summary.resolved_later,
        "catalog_codes": summary.catalog_codes,
        "catalog_skipped": summary.catalog_skipped,
        "extra_columns_count": len(summary.extra_columns),
        "data_age_days": toku_report_import.data_age_days(summary.generated_at),
        "warnings": warnings,
    }


@router.get("/toku-reports/status", tags=["Imports"])
def toku_reports_status(
    _user: Annotated[User, Depends(require_permissions("toku.reports.import"))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Frescura del ultimo reporte cargado por tipo (DEC-21: aviso si el dato tiene mas de 7 dias). Solo metadatos."""
    reports = toku_report_import.report_freshness(db)
    return {
        "max_age_days": toku_report_import.REPORT_MAX_AGE_DAYS,
        "reports": reports,
        "stale_types": [r["report_type"] for r in reports if r["is_stale"]],
    }


@router.post("/toku-reports", dependencies=[Depends(require_csrf)], tags=["Imports"])
def import_toku_report(
    report: Annotated[UploadFile, File(description="Reporte del Backoffice de Toku (.xlsx): Productos, Medios de pago, Intentos, Deudas, Inscripciones, Clientes, Pagos v2 o Liquidaciones")],
    user: Annotated[User, Depends(require_permissions("toku.reports.import"))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    filename = Path((report.filename or "").replace("\\", "/")).name[:255]
    payload: dict[str, Any] = {"filename": filename}

    def audit(status: str, error: str | None = None) -> None:
        _audit(db, user, status, payload, error, source="toku")

    if Path(filename).suffix.lower() != ".xlsx":
        audit("rejected", "invalid_extension")
        raise _error(422, "invalid_format", "Seleccione un reporte .xlsx de Toku.")

    temporary: str | None = None
    try:
        digest = hashlib.sha256()
        size = 0
        with tempfile.NamedTemporaryFile(prefix="synkmetrix-tk-", suffix=".xlsx", delete=False) as tmp:
            temporary = tmp.name
            while chunk := report.file.read(_CHUNK):
                size += len(chunk)
                if size > MAX_TOKU_REPORT_BYTES:
                    audit("rejected", "too_large")
                    raise _error(413, "too_large", "El reporte supera el tamano maximo permitido.")
                digest.update(chunk)
                tmp.write(chunk)
        if size == 0:
            audit("rejected", "empty_file")
            raise _error(422, "invalid_format", "El archivo esta vacio.")
        payload["sha256"] = digest.hexdigest()

        try:
            summary = toku_report_import.import_report(
                db, temporary, filename=filename or "reporte.xlsx", uploaded_by_user_id=user.id
            )
        except MissingPepperError:  # el importador falla cerrado antes de abrir el archivo; codigo fijo
            audit("rejected", "pepper_not_configured")
            raise _error(
                503,
                "pepper_not_configured",
                "El importador de reportes de Toku no esta configurado (falta TOKU_REPORT_HASH_PEPPER).",
            ) from None
        except TokuReportFormatError as exc:  # solo nombres de columnas/tipos, nunca valores de filas
            audit("rejected", "invalid_format")
            raise _error(422, "invalid_format", str(exc)) from None
        except toku_report_import.ReportImportError as exc:
            if exc.label == "carga_en_curso":
                audit("rejected", "load_in_progress")
                raise _error(409, "load_in_progress", "Este archivo ya se esta cargando.") from None
            audit("failed", exc.label)
            raise _error(500, "import_failed", "No se pudo cargar el reporte.", label=exc.label) from None

        payload.update(
            report_type=summary.report_type,
            file_id=str(summary.file_id),
            rows_total=summary.rows_total,
            rows_new=summary.rows_new,
            rows_updated=summary.rows_updated,
            rows_skipped=summary.rows_skipped,
            rows_stale=summary.rows_stale,
        )
        if summary.already_loaded:
            audit("already_loaded")
            raise _error(
                409,
                "already_loaded",
                "Este reporte ya fue cargado (mismo contenido que un archivo anterior).",
                file_id=str(summary.file_id),
                report_type=summary.report_type,
            )
        audit("completed")
        return _toku_summary_json(summary)
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)
