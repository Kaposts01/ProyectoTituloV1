"""Servicio comun de exportacion CSV (EXP-01).

- CSV en STREAMING: `csv_stream` es un generador que consume una fuente de filas perezosa (cursor del lado del
  servidor con `yield_per`) y entrega bytes por trozos; nunca arma el archivo completo en memoria.
- UTF-8 con BOM (abre bien en Excel) y neutralizacion de inyeccion de formulas (`csv_safe`).
- Columnas con datos personales (`ExportColumn.pii`): se excluyen salvo que el llamador pase `include_pii=True`.
- Auditoria en `write_runs` (quien, cuando, endpoint, filtros, filas, si incluyo PII). NUNCA el contenido.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.write_run import WriteRun

BOM = b"\xef\xbb\xbf"
CSV_MEDIA_TYPE = "text/csv; charset=utf-8"
DEFAULT_CHUNK_ROWS = 1000


@dataclass(frozen=True)
class ExportColumn:
    key: str  # clave en el dict de la fila
    header: str  # encabezado en el CSV
    pii: bool = False  # dato personal: solo con permiso `export.pii`


def csv_safe(value: Any) -> Any:
    """Neutraliza la inyeccion de formulas en celdas de texto (primer caracter = + - @, tab o CR)."""
    if isinstance(value, str) and value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


_RUT_SHAPE = re.compile(r"^\d{1,9}[0-9K]$")


def format_rut(value: Any) -> Any:
    """Formato unico del RUT en los CSV (QA-08): `12.345.678-9`, igual que en la interfaz.

    Lo que no tiene forma de RUT (otro documento, dato sintetico invalido) se deja tal cual; no se inventa un formato.
    """
    if not isinstance(value, str) or not value.strip():
        return value
    compact = re.sub(r"[.\-\s]", "", value.strip().upper())
    if not _RUT_SHAPE.match(compact):
        return value
    body = compact[:-1].lstrip("0") or "0"
    return f"{int(body):,}".replace(",", ".") + "-" + compact[-1]


def _cell(key: str, value: Any) -> Any:
    return csv_safe(format_rut(value) if key == "rut" else value)


def visible_columns(columns: Sequence[ExportColumn], include_pii: bool) -> list[ExportColumn]:
    return [c for c in columns if include_pii or not c.pii]


def csv_stream(
    columns: Sequence[ExportColumn],
    include_pii: bool,
    rows: Iterable[Mapping[str, Any]],
    *,
    chunk_rows: int = DEFAULT_CHUNK_ROWS,
    on_finish: Callable[[int, bool], None] | None = None,
) -> Iterator[bytes]:
    """Genera el CSV por trozos. `on_finish(filas, completo)` corre siempre al terminar o si se corta el stream."""
    cols = visible_columns(columns, include_pii)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow([c.header for c in cols])
    count = 0
    completed = False
    try:
        pending = BOM + buffer.getvalue().encode("utf-8")
        buffer.seek(0)
        buffer.truncate()
        for row in rows:
            writer.writerow([_cell(c.key, row.get(c.key)) for c in cols])
            count += 1
            if count % chunk_rows == 0:
                yield pending + buffer.getvalue().encode("utf-8")
                pending = b""
                buffer.seek(0)
                buffer.truncate()
        yield pending + buffer.getvalue().encode("utf-8")
        completed = True
    finally:
        close = getattr(rows, "close", None)
        if callable(close):
            close()
        if on_finish is not None:
            on_finish(count, completed)


def audit_payload(user: Any, endpoint: str, filters: dict, row_count: int, include_pii: bool) -> dict[str, Any]:
    """Cuerpo de auditoria: quien, endpoint, filtros, cantidad de filas y si incluyo PII. Sin contenido."""
    return {
        "user_id": str(user.id), "username": user.username, "endpoint": endpoint,
        "filters": filters, "rows": row_count, "pii_included": include_pii,
    }


def record_export_audit(
    db: Session,
    user: Any,
    endpoint: str,
    filters: dict,
    row_count: int,
    include_pii: bool,
    *,
    source: str = "export",
    resource_type: str = "export",
    status: str = "completed",
) -> None:
    now = datetime.now().astimezone()
    db.add(WriteRun(
        source=source, resource_type=resource_type, external_id=endpoint, operation="export_csv", status=status,
        request_payload=audit_payload(user, endpoint, filters, row_count, include_pii),
        finished_at=now, requested_by_user_id=user.id,
    ))
    db.commit()
