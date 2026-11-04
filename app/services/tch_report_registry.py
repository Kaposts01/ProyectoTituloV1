"""Registro de reportes TCH ya cargados, identificados por el sha256 de su contenido.

SYNC-O-08: cada reporte es una fila de ``tch_file_loads`` (``file_sha256`` PK, nombre, tamano, filas cargadas,
``loaded_at`` y ``consolidated_at``). Antes vivia en ``source_records`` (``source='tch_report'``,
``resource_type='file'``); la migracion 20261102_0053 movio esas filas. Una carga completa reinicia el registro.
El sha256 repetido sigue siendo un bloqueo duro en la importacion incremental (TCH-PAR-15), como antes.

SYNC-O-03: ademas guarda una marca de "ultima consolidacion TCH exitosa" (``source_records``,
``source='tch_report'``, ``resource_type='consolidation_mark'``) para que la corrida nocturna consolide TCH solo si
llego algun reporte nuevo desde entonces. La marca es una foto del registro tomada ANTES de consolidar: un reporte
que llega mientras se consolida no se pierde (queda fuera de la foto y dispara la siguiente consolidacion).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.source_record import SourceRecord
from app.models.tch import TchFileLoad

SOURCE = "tch_report"
MARK_RESOURCE_TYPE = "consolidation_mark"
MARK_EXTERNAL_ID = "tch"
# TCH-PAR-11: conciliacion por archivo (filas leidas/insertadas/actualizadas/omitidas/con error y control del propio
# Excel), una fila de ``source_records`` por sha256. Sin migracion: ``tch_file_loads`` no tiene columna para esto.
# Solo conteos y periodos: nada del contenido del reporte ni datos personales.
STATS_RESOURCE_TYPE = "file_stats"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


RESULT_LOADED = "cargado"
RESULT_FAILED = "fallido"
RESULT_CONSOLIDATED = "consolidado"  # derivado de `consolidated_at`; no se guarda en `result`

_LOADED = TchFileLoad.result != RESULT_FAILED


def is_registered(db: Session, sha256: str) -> bool:
    """True si el contenido ya se cargo bien. Un intento fallido no bloquea reintentar el mismo archivo."""
    return db.scalar(select(TchFileLoad.file_sha256).where(TchFileLoad.file_sha256 == sha256, _LOADED)) is not None


def register(
    db: Session,
    sha256: str,
    filename: str,
    size_bytes: int,
    rows_loaded: int | None = None,
    *,
    report_period: str | None = None,
    etl_run_id: uuid.UUID | None = None,
    stats: dict | None = None,
) -> None:
    """Registra el reporte cargado; idempotente por sha256. Guarda solo nombre, tamano, mes y conteo, no su contenido.

    Si el mismo contenido tenia un intento fallido, la fila pasa a 'cargado' con los datos de esta carga. ``stats``
    (TCH-PAR-11) es la conciliacion del archivo y se guarda aparte (``source_records``).
    """
    values = {
        "file_sha256": sha256,
        "file_name": filename[:255],
        "size_bytes": size_bytes,
        "rows_loaded": rows_loaded,
        "report_period": report_period,
        "etl_run_id": etl_run_id,
        "result": RESULT_LOADED,
        "error_message": None,
    }
    statement = insert(TchFileLoad).values(**values)
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[TchFileLoad.file_sha256],
            set_={**{key: statement.excluded[key] for key in values if key != "file_sha256"}, "loaded_at": func.now()},
            where=TchFileLoad.result == RESULT_FAILED,
        )
    )
    db.flush()
    if stats is not None:
        record_stats(db, sha256, stats)


def _only_counts(value):
    """Copia de la conciliacion con solo claves de texto y valores enteros, booleanos, None o texto corto."""
    if isinstance(value, dict):
        return {str(key): _only_counts(item) for key, item in value.items()}
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    return str(value)[:40]


def record_stats(db: Session, sha256: str, stats: dict) -> None:
    """Guarda (o reemplaza) la conciliacion de un archivo. No hace commit."""
    statement = insert(SourceRecord).values(
        source=SOURCE, resource_type=STATS_RESOURCE_TYPE, external_id=sha256, payload=_only_counts(stats)
    )
    db.execute(statement.on_conflict_do_update(constraint="uq_source_record", set_={"payload": statement.excluded.payload}))
    db.flush()


def stats_by_sha(db: Session, sha256s: list[str]) -> dict[str, dict]:
    """Conciliacion guardada por sha256 (los archivos sin ella, p. ej. cargados antes de TCH-PAR-11, no aparecen)."""
    if not sha256s:
        return {}
    rows = db.execute(
        select(SourceRecord.external_id, SourceRecord.payload).where(
            SourceRecord.source == SOURCE,
            SourceRecord.resource_type == STATS_RESOURCE_TYPE,
            SourceRecord.external_id.in_(sha256s),
        )
    )
    return {row.external_id: row.payload for row in rows if isinstance(row.payload, dict)}


def register_failure(
    db: Session,
    sha256: str,
    filename: str,
    size_bytes: int | None,
    error_message: str,
    *,
    report_period: str | None = None,
    etl_run_id: uuid.UUID | None = None,
) -> None:
    """Registra un intento fallido (TCH-PAR-11). Nunca pisa un archivo ya cargado bien. No hace commit."""
    values = {
        "file_sha256": sha256,
        "file_name": filename[:255],
        "size_bytes": size_bytes,
        "rows_loaded": None,
        "report_period": report_period,
        "etl_run_id": etl_run_id,
        "result": RESULT_FAILED,
        "error_message": error_message[:500],
    }
    statement = insert(TchFileLoad).values(**values)
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[TchFileLoad.file_sha256],
            set_={**{key: statement.excluded[key] for key in values if key != "file_sha256"}, "loaded_at": func.now()},
            where=TchFileLoad.result == RESULT_FAILED,
        )
    )
    db.flush()


def list_loads(db: Session, limit: int = 50) -> list[TchFileLoad]:
    """Archivos registrados, del mas reciente al mas antiguo (pantalla de archivos cargados, TCH-PAR-11)."""
    return list(db.scalars(select(TchFileLoad).order_by(TchFileLoad.loaded_at.desc()).limit(limit)))


def display_result(load: TchFileLoad) -> str:
    if load.result == RESULT_FAILED:
        return RESULT_FAILED
    return RESULT_CONSOLIDATED if load.consolidated_at is not None else RESULT_LOADED


def clear(db: Session) -> None:
    db.execute(delete(TchFileLoad))
    db.execute(
        delete(SourceRecord).where(SourceRecord.source == SOURCE, SourceRecord.resource_type == STATS_RESOURCE_TYPE)
    )
    db.flush()


def last_loaded_at(db: Session) -> datetime | None:
    """Instante de la carga de reporte mas reciente (salud por recurso de TCH)."""
    return db.scalar(select(func.max(TchFileLoad.loaded_at)).where(_LOADED))


def consolidation_snapshot(db: Session) -> dict:
    """Foto del registro: sha256 de los reportes cargados y el instante del mas reciente (ISO o None)."""
    rows = db.execute(select(TchFileLoad.file_sha256, TchFileLoad.loaded_at).where(_LOADED)).all()
    latest = max((row.loaded_at for row in rows if row.loaded_at is not None), default=None)
    return {"sha256s": sorted(row.file_sha256 for row in rows), "latest_load_at": latest.isoformat() if latest else None}


def needs_consolidation(db: Session, snapshot: dict) -> bool:
    """True si hay un reporte cargado que la ultima consolidacion TCH exitosa no vio (o si nunca hubo marca)."""
    mark = db.scalar(
        select(SourceRecord.payload).where(
            SourceRecord.source == SOURCE,
            SourceRecord.resource_type == MARK_RESOURCE_TYPE,
            SourceRecord.external_id == MARK_EXTERNAL_ID,
        )
    )
    if mark is None:
        return True
    if set(snapshot["sha256s"]) - set(mark.get("sha256s", [])):
        return True
    # Una carga completa (clear + recarga) vuelve a registrar los mismos archivos con otro instante.
    return snapshot["latest_load_at"] != mark.get("latest_load_at")


def mark_consolidated(db: Session, snapshot: dict) -> None:
    """Guarda la foto como "ultima consolidacion TCH exitosa" y fija `consolidated_at` de sus archivos.

    Idempotente. No hace commit.
    """
    statement = insert(SourceRecord).values(
        source=SOURCE,
        resource_type=MARK_RESOURCE_TYPE,
        external_id=MARK_EXTERNAL_ID,
        payload=snapshot,
    )
    db.execute(statement.on_conflict_do_update(constraint="uq_source_record", set_={"payload": statement.excluded.payload}))
    if snapshot.get("sha256s"):
        db.execute(
            update(TchFileLoad)
            .where(TchFileLoad.file_sha256.in_(snapshot["sha256s"]), TchFileLoad.consolidated_at.is_(None))
            .values(consolidated_at=datetime.now(UTC))
        )
    db.flush()
