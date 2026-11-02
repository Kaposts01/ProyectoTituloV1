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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def is_registered(db: Session, sha256: str) -> bool:
    return db.scalar(select(TchFileLoad.file_sha256).where(TchFileLoad.file_sha256 == sha256)) is not None


def register(db: Session, sha256: str, filename: str, size_bytes: int, rows_loaded: int | None = None) -> None:
    """Registra el reporte; idempotente por sha256. Guarda solo nombre, tamano y conteo, no su contenido."""
    statement = insert(TchFileLoad).values(
        file_sha256=sha256, file_name=filename[:255], size_bytes=size_bytes, rows_loaded=rows_loaded
    )
    db.execute(statement.on_conflict_do_nothing(index_elements=[TchFileLoad.file_sha256]))
    db.flush()


def clear(db: Session) -> None:
    db.execute(delete(TchFileLoad))
    db.flush()


def last_loaded_at(db: Session) -> datetime | None:
    """Instante de la carga de reporte mas reciente (salud por recurso de TCH)."""
    return db.scalar(select(func.max(TchFileLoad.loaded_at)))


def consolidation_snapshot(db: Session) -> dict:
    """Foto del registro: sha256 de los reportes cargados y el instante del mas reciente (ISO o None)."""
    rows = db.execute(select(TchFileLoad.file_sha256, TchFileLoad.loaded_at)).all()
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
