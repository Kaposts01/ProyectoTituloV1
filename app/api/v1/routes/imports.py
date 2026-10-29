"""Cargas manuales de reportes descargados (VP-PAR-02): `POST /api/v1/imports/virtualpos-reports`.

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
from app.services import vp_report_import
from app.services.vp_report_parser import ReportFormatError

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_REPORT_BYTES = 100 * 1024 * 1024
_CHUNK = 1024 * 1024


def _error(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


def _audit(db: Session, user: User, status: str, payload: dict[str, Any], error: str | None = None) -> None:
    db.add(
        WriteRun(
            source="virtualpos",
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
