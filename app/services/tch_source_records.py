"""SYNC-D-16: trazabilidad ``source_record_id`` para TCH.

Los conectores de API (VirtualPOS, Toku, Payku) guardan cada recurso en ``source_records`` y la consolidacion
(`channel_consolidation._link_source_records`) enlaza la fila centralizada con su registro de origen por
``(source, resource_type, external_id)``. TCH llega por Excel y no escribia ``source_records``: ``source_record_id``
quedaba NULL en el 100 % de sus filas centralizadas.

Este modulo registra un ``source_record`` por cada fila de las tablas ``tch_*`` con las MISMAS claves que usa la
consolidacion TCH:

==============  ======================  ===============================  =========================
resource_type   tabla                   external_id                      fila centralizada
==============  ======================  ===============================  =========================
``client``      ``tch_clientes``        ``rut`` (llave del canal)        ``clients``
``subscription`` ``tch_suscripciones``  ``numero_ficha``                 ``subscriptions``
``transaction`` ``tch_transacciones``   ``dedupe_key`` (ficha|mes|cuota) ``charges``
==============  ======================  ===============================  =========================

El payload es minimo y SIN datos personales (solo la tabla de origen): el detalle ya vive en ``tch_*.raw_payload`` y
copiarlo duplicaria PII. Es una sola sentencia ``INSERT .. SELECT`` por tipo, idempotente (``NOT EXISTS`` + ``ON
CONFLICT DO NOTHING``): sirve tanto para cada carga como para el backfill de lo ya cargado. Un registro existente no
se toca, asi su ``id`` (al que apunta ``source_record_id``) es estable entre recargas completas.

No hace commit.
"""

from __future__ import annotations

import json

from sqlalchemy import String, cast, exists, func, literal, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Session

from app.models.source_record import SourceRecord
from app.models.tch import TchClient, TchSubscription, TchTransaction

SOURCE = "tch"


def _payload(table: str):
    return cast(literal(json.dumps({"tabla": table})), JSONB)


def _register(db: Session, resource_type: str, table: str, key_column) -> int:
    key = cast(key_column, String) if key_column.type.python_type is not str else key_column
    already = exists().where(
        SourceRecord.source == SOURCE,
        SourceRecord.resource_type == resource_type,
        SourceRecord.external_id == key,
    )
    rows = select(
        func.gen_random_uuid(),
        literal(SOURCE),
        literal(resource_type),
        key,
        _payload(table),
    ).where(key_column.isnot(None), ~already)
    statement = insert(SourceRecord).from_select(
        ["id", "source", "resource_type", "external_id", "payload"], rows
    ).on_conflict_do_nothing(constraint="uq_source_record")
    # SQLAlchemy 2 solo conserva el rowcount de un INSERT si se pide (preserve_rowcount).
    return db.execute(statement.execution_options(preserve_rowcount=True)).rowcount or 0


def sync_tch_source_records(db: Session) -> dict[str, int]:
    """Registra en ``source_records`` las filas ``tch_*`` que aun no lo estan. Devuelve cuantas se crearon por tipo."""
    return {
        "client": _register(db, "client", "tch_clientes", TchClient.rut),
        "subscription": _register(
            db, "subscription", "tch_suscripciones", TchSubscription.file_number
        ),
        "transaction": _register(
            db, "transaction", "tch_transacciones", TchTransaction.dedupe_key
        ),
    }


def missing_tch_source_records(db: Session) -> dict[str, int]:
    """Cuantas filas ``tch_*`` no tienen ``source_record`` (0 en los tres tipos tras el backfill). Solo lectura."""

    def _missing(resource_type: str, key_column) -> int:
        key = cast(key_column, String) if key_column.type.python_type is not str else key_column
        already = exists().where(
            SourceRecord.source == SOURCE,
            SourceRecord.resource_type == resource_type,
            SourceRecord.external_id == key,
        )
        return db.scalar(select(func.count()).where(key_column.isnot(None), ~already)) or 0

    return {
        "client": _missing("client", TchClient.rut),
        "subscription": _missing("subscription", TchSubscription.file_number),
        "transaction": _missing("transaction", TchTransaction.dedupe_key),
    }
