"""SYNC-O-02 / SYNC-O-05: lectura por ventana de fecha con solapamiento y respaldo completo.

Detras de `SYNC_WINDOWED_READS_ENABLED` (APAGADA por defecto). Con la bandera apagada todo se lee completo, como
siempre. Con la bandera encendida, un recurso se lee por ventana SOLO si:
  * hay una lectura completa exitosa (`sync_cursors`, modo `full`) mas nueva que `SYNC_WINDOW_FULL_REFRESH_DAYS`
    (por defecto 7): si no, toca la relectura completa (la "fria" semanal, que tambien cubre los cambios de estado
    de registros viejos que una ventana por fecha de creacion no ve);
  * la ventana empieza en el ultimo exito del recurso (cualquier modo) menos `SYNC_WINDOW_OVERLAP_HOURS` (48 h):
    cubre la ambiguedad de DEC-03 (Toku: fecha de transaccion vs de inicializacion) y los `INITIALIZED` que pasan a
    un estado final despues.

Guardas (si el proveedor IGNORA el filtro, la lectura se abandona y se hace el respaldo completo):
  * un registro cuyas fechas conocidas son TODAS anteriores al inicio de la ventana (menos 1 dia de tolerancia por
    zona horaria) delata un filtro ignorado;
  * si la respuesta trae un total y es >= al total visto en la ultima lectura completa (con un minimo de registros
    para no confundir una cuenta chica), el filtro no recorto nada.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import sync_cursors

logger = logging.getLogger(__name__)

_DATE_TOLERANCE = timedelta(days=1)
# Con menos registros que esto en la lectura completa, la guarda por total no decide (una cuenta chica puede tener
# todo dentro de la ventana).
MIN_TOTAL_FOR_GUARD = 200


class WindowFilterIgnored(Exception):
    """El proveedor devolvio registros fuera de la ventana pedida: hay que leer completo."""


@dataclass(frozen=True)
class ReadWindow:
    start: datetime
    end: datetime
    full_total: int | None = None  # registros vistos en la ultima lectura completa (guarda por total)

    @property
    def start_date(self) -> str:
        return self.start.date().isoformat()

    @property
    def end_date(self) -> str:
        # Fecha inclusive: se pide hasta mañana para no perder el dia en curso por la zona horaria.
        return (self.end.date() + timedelta(days=1)).isoformat()


def plan_window(db: Session, source: str, resource: str, now: datetime | None = None) -> ReadWindow | None:
    """Ventana a leer, o None si toca lectura completa (bandera apagada, sin marca o relectura vencida)."""
    if not settings.sync_windowed_reads_enabled:
        return None
    now = now or datetime.now(UTC)
    full = sync_cursors.get(db, source, resource, sync_cursors.MODE_FULL)
    last_full = full.last_success_at if full is not None else None
    if last_full is None:
        return None
    if last_full.tzinfo is None:
        last_full = last_full.replace(tzinfo=UTC)
    if now - last_full >= timedelta(days=settings.sync_window_full_refresh_days):
        return None
    last_any = sync_cursors.last_success(db, source, resource) or last_full
    start = min(last_any, now) - timedelta(hours=settings.sync_window_overlap_hours)
    return ReadWindow(start=start, end=now, full_total=full.records_seen if full is not None else None)


def _value_at(record: dict[str, Any], path: str) -> Any:
    value: Any = record
    for key in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day, tzinfo=UTC)
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text[:10])
            except ValueError:
                return None
    else:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def records_outside(records: Iterable[dict[str, Any]], window: ReadWindow, date_fields: Sequence[str]) -> int:
    """Registros cuyas fechas conocidas son todas anteriores a la ventana (sin fechas legibles no cuentan)."""
    limit = window.start - _DATE_TOLERANCE
    outside = 0
    for record in records:
        dates = [d for d in (_parse(_value_at(record, field)) for field in date_fields) if d is not None]
        if dates and max(dates) < limit:
            outside += 1
    return outside


def response_total(response: Any) -> int | None:
    """Total de registros que declara la respuesta (`pagination.total`, `meta.total` o `total` en la raiz)."""
    if not isinstance(response, dict):
        return None
    for key in ("pagination", "meta"):
        metadata = response.get(key)
        if isinstance(metadata, dict):
            total = metadata.get("total", metadata.get("total_records"))
            if isinstance(total, int) and total >= 0:
                return total
    total = response.get("total")
    return total if isinstance(total, int) and total >= 0 else None


def check_page(
    response: Any, records: Sequence[dict[str, Any]], window: ReadWindow, date_fields: Sequence[str], *, label: str
) -> None:
    """Lanza `WindowFilterIgnored` si la pagina muestra que el proveedor ignoro el filtro de fecha."""
    outside = records_outside(records, window, date_fields)
    if outside:
        logger.warning("%s: %d registros fuera de la ventana %s..%s; respaldo completo.", label, outside,
                       window.start_date, window.end_date)
        raise WindowFilterIgnored(label)
    total = response_total(response)
    full_total = window.full_total
    if total is not None and full_total and full_total >= MIN_TOTAL_FOR_GUARD and total >= full_total:
        logger.warning("%s: la ventana declara %d registros (lectura completa: %d); respaldo completo.", label, total,
                       full_total)
        raise WindowFilterIgnored(label)
