"""Registro de reportes TCH ya cargados, identificados por el sha256 de su contenido.

No usa tablas nuevas: guarda una fila en ``source_records`` con ``source='tch_report'`` (distinto de
``tch`` para no mezclarse con los registros de clientes, suscripciones y cargos),
``resource_type='file'`` y ``external_id=<sha256>``. Una carga completa reinicia el registro.

SYNC-O-03: ademas guarda una marca de "ultima consolidacion TCH exitosa" (``resource_type='consolidation_mark'``) para
que la corrida nocturna consolide TCH solo si llego algun reporte nuevo desde entonces. La marca es una foto del
registro tomada ANTES de consolidar: un reporte que llega mientras se consolida no se pierde (queda fuera de la foto
y dispara la siguiente consolidacion).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.source_record import SourceRecord

SOURCE = "tch_report"
RESOURCE_TYPE = "file"
MARK_RESOURCE_TYPE = "consolidation_mark"
MARK_EXTERNAL_ID = "tch"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def is_registered(db: Session, sha256: str) -> bool:
    return (
        db.scalar(
            select(SourceRecord.id).where(
                SourceRecord.source == SOURCE,
                SourceRecord.resource_type == RESOURCE_TYPE,
                SourceRecord.external_id == sha256,
            )
        )
        is not None
    )


def register(db: Session, sha256: str, filename: str, size_bytes: int) -> None:
    """Registra el reporte; idempotente por sha256. Guarda solo el nombre y el tamano, no su contenido."""
    statement = insert(SourceRecord).values(
        source=SOURCE,
        resource_type=RESOURCE_TYPE,
        external_id=sha256,
        payload={"filename": filename[:255], "size_bytes": size_bytes},
    )
    db.execute(statement.on_conflict_do_nothing(constraint="uq_source_record"))
    db.flush()


def clear(db: Session) -> None:
    db.execute(delete(SourceRecord).where(SourceRecord.source == SOURCE, SourceRecord.resource_type == RESOURCE_TYPE))
    db.flush()


def consolidation_snapshot(db: Session) -> dict:
    """Foto del registro: sha256 de los reportes cargados y el instante del mas reciente (ISO o None)."""
    rows = db.execute(
        select(SourceRecord.external_id, SourceRecord.first_seen_at).where(
            SourceRecord.source == SOURCE, SourceRecord.resource_type == RESOURCE_TYPE
        )
    ).all()
    latest = max((row.first_seen_at for row in rows if row.first_seen_at is not None), default=None)
    return {"sha256s": sorted(row.external_id for row in rows), "latest_load_at": latest.isoformat() if latest else None}


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
    """Guarda la foto como "ultima consolidacion TCH exitosa". Idempotente. No hace commit."""
    statement = insert(SourceRecord).values(
        source=SOURCE,
        resource_type=MARK_RESOURCE_TYPE,
        external_id=MARK_EXTERNAL_ID,
        payload=snapshot,
    )
    db.execute(statement.on_conflict_do_update(constraint="uq_source_record", set_={"payload": statement.excluded.payload}))
    db.flush()
