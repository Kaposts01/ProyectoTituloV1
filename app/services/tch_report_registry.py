"""Registro de reportes TCH ya cargados, identificados por el sha256 de su contenido.

No usa tablas nuevas: guarda una fila en ``source_records`` con ``source='tch_report'`` (distinto de
``tch`` para no mezclarse con los registros de clientes, suscripciones y cargos),
``resource_type='file'`` y ``external_id=<sha256>``. Una carga completa reinicia el registro.
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
