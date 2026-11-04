"""Ultima carga manual por canal y tipo de archivo (L7-IMPORT, d151). Solo lectura, solo metadatos.

Panel «Importar reportes de plataformas» de Administracion. Para cada canal reutiliza su registro de archivos:

* Toku -> `tk_report_files`; VirtualPOS (PAT) -> `vp_report_files`; Payku -> `p_report_files`; TCH -> `tch_file_loads`.

Por tipo de archivo devuelve la ULTIMA carga intentada (fecha, nombre de archivo, filas y resultado) y la frescura
del dato de la ultima carga COMPLETADA: aviso si tiene mas de `REPORT_MAX_AGE_DAYS` dias (DEC-21). La fecha del dato
es la de generacion del archivo cuando se conoce (Toku, VirtualPOS); si no (Payku, TCH), la de la carga.

Nunca devuelve filas, hashes, ids de usuario ni datos personales: solo tipo, nombre del archivo, fechas, contadores y
una etiqueta tecnica de error.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.payku_report import PkReportFile
from app.models.tch import TchFileLoad
from app.models.toku_report import TkReportFile
from app.models.vp_report import VpReportFile
from app.services import tch_report_registry
from app.services.toku_report_import import (
    REPORT_MAX_AGE_DAYS,
    data_age_days,
    is_older_than_max_age,
)

__all__ = ["CHANNELS", "EXPECTED_TYPES", "REPORT_MAX_AGE_DAYS", "channel_status"]

CHANNELS = ("toku", "virtualpos", "payku", "tch")

# Tipos que el panel muestra aunque nunca se hayan cargado (fila «sin cargas»).
EXPECTED_TYPES: dict[str, tuple[str, ...]] = {
    "toku": ("productos", "intentos", "deudas", "clientes", "pagos", "liquidaciones"),
    "virtualpos": ("transacciones", "suscriptores"),
    "payku": ("transacciones", "liquidaciones", "suscripciones", "consolidado"),
    "tch": ("reporte",),
}

TCH_REPORT_TYPE = "reporte"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _row(
    report_type: str,
    *,
    filename: str | None,
    loaded_at: datetime | None,
    rows_total: int | None,
    rows_new: int | None,
    rows_updated: int | None,
    rows_skipped: int | None,
    result: str | None,
    error_label: str | None,
    data_at: datetime | None,
    now: datetime,
) -> dict[str, Any]:
    return {
        "report_type": report_type,
        "filename": filename,
        "loaded_at": _iso(loaded_at),
        "rows_total": rows_total,
        "rows_new": rows_new,
        "rows_updated": rows_updated,
        "rows_skipped": rows_skipped,
        "result": result,
        "error_label": error_label,
        "data_at": _iso(data_at),
        "age_days": data_age_days(data_at, now),
        "is_stale": is_older_than_max_age(data_at, now),
    }


def _empty(report_type: str) -> dict[str, Any]:
    return {
        "report_type": report_type, "filename": None, "loaded_at": None, "rows_total": None, "rows_new": None,
        "rows_updated": None, "rows_skipped": None, "result": None, "error_label": None, "data_at": None,
        "age_days": None, "is_stale": False,
    }


def _file_model_rows(db: Session, model: type, started_col, data_col, now: datetime) -> dict[str, dict[str, Any]]:
    """Ultimo intento y ultimo completado por `report_type` de una tabla de archivos de reporte."""
    latest = db.scalars(
        select(model).distinct(model.report_type).order_by(model.report_type, started_col.desc().nulls_last())
    ).all()
    completed = {
        record.report_type: record
        for record in db.scalars(
            select(model)
            .where(model.status == "completed")
            .distinct(model.report_type)
            .order_by(model.report_type, data_col.desc().nulls_last())
        )
    }
    out: dict[str, dict[str, Any]] = {}
    for record in latest:
        ok = completed.get(record.report_type)
        data_at = None
        if ok is not None:
            data_at = getattr(ok, "generated_at", None) or ok.finished_at
        out[record.report_type] = _row(
            record.report_type,
            filename=record.filename,
            loaded_at=record.finished_at or getattr(record, "loaded_at", None) or getattr(record, "started_at", None),
            rows_total=record.rows_total,
            rows_new=record.rows_new,
            rows_updated=record.rows_updated,
            rows_skipped=record.rows_skipped,
            result=record.status,
            error_label=record.error_label,
            data_at=data_at,
            now=now,
        )
    return out


def _tch_rows(db: Session, now: datetime) -> dict[str, dict[str, Any]]:
    last = db.scalar(select(TchFileLoad).order_by(TchFileLoad.loaded_at.desc()).limit(1))
    if last is None:
        return {}
    last_ok = db.scalar(
        select(func.max(TchFileLoad.loaded_at)).where(TchFileLoad.result != tch_report_registry.RESULT_FAILED)
    )
    return {
        TCH_REPORT_TYPE: _row(
            TCH_REPORT_TYPE,
            filename=last.file_name,
            loaded_at=last.loaded_at,
            rows_total=last.rows_loaded,
            rows_new=None,
            rows_updated=None,
            rows_skipped=None,
            result=tch_report_registry.display_result(last),
            error_label=None,  # `error_message` es texto libre del ETL: no se expone en este panel
            data_at=last_ok,
            now=now,
        )
    }


def channel_status(db: Session, channel: str, now: datetime | None = None) -> dict[str, Any]:
    """`{channel, reports: [...], stale_types: [...]}` con los tipos esperados primero y luego los demas cargados."""
    now = now or datetime.now(UTC)
    if channel == "toku":
        found = _file_model_rows(db, TkReportFile, TkReportFile.started_at,
                                 func.coalesce(TkReportFile.generated_at, TkReportFile.finished_at), now)
    elif channel == "virtualpos":
        found = _file_model_rows(db, VpReportFile, VpReportFile.loaded_at,
                                 func.coalesce(VpReportFile.generated_at, VpReportFile.finished_at), now)
    elif channel == "payku":
        found = _file_model_rows(db, PkReportFile, PkReportFile.started_at, PkReportFile.finished_at, now)
    elif channel == "tch":
        found = _tch_rows(db, now)
    else:  # pragma: no cover - la ruta solo pasa canales conocidos
        raise ValueError(channel)
    expected = EXPECTED_TYPES[channel]
    order = list(expected) + sorted(t for t in found if t not in expected)
    reports = [found.get(t) or _empty(t) for t in order]
    return {
        "channel": channel,
        "reports": reports,
        "stale_types": [r["report_type"] for r in reports if r["is_stale"]],
    }
