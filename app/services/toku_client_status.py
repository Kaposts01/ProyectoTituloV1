"""Estado de cliente de Toku desde el reporte de Clientes (TK-PAR-07, d126 opcion a).

La API de Toku no trae estado de cliente (`clients.status` queda NULL). El reporte de Clientes (`tk_report_customers`)
si sabe si el cliente fue eliminado. Regla: **manda la API; el reporte solo completa lo vacio**.

* Cliente con `Fecha de Eliminacion` en el reporte -> `deleted`; sin ella -> `active`. «Silenciado hasta» no cambia el
  estado (solo silencia avisos).
* Solo se escribe en filas `clients` de Toku cuyo `status` este vacio (NULL o solo espacios). Un estado que traiga la
  API nunca se pisa.
* Dos puntos de entrada con la MISMA regla:
  - `project_report_status(db)`: UPDATE en SQL tras cargar un reporte de Clientes (`toku_report_import`).
  - `report_statuses(db, ids)`: lectura para la consolidacion de la API (`channel_consolidation`), para que una
    sincronizacion que vuelva a escribir `status = NULL` no borre lo que el reporte completo.
Sin datos personales: solo IDs `cus_` y fechas.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.toku_report import TkReportCustomer

REPORT_DELETED = "deleted"
REPORT_ACTIVE = "active"


def report_status(deleted_at_source: datetime | None) -> str:
    return REPORT_DELETED if deleted_at_source is not None else REPORT_ACTIVE


def is_blank(status: Any) -> bool:
    return status is None or str(status).strip() == ""


def report_statuses(db: Session, external_ids: Iterable[str] | None = None) -> dict[str, str]:
    """{cus_: estado del reporte}. Con `external_ids` solo esos (los que la API dejo sin estado)."""
    stmt = select(TkReportCustomer.customer_external_id, TkReportCustomer.deleted_at_source)
    if external_ids is not None:
        ids = sorted({str(x) for x in external_ids if x})
        if not ids:
            return {}
        stmt = stmt.where(TkReportCustomer.customer_external_id.in_(ids))
    return {ext: report_status(deleted) for ext, deleted in db.execute(stmt)}


def fill_blank_status(row: dict[str, Any], statuses: dict[str, str]) -> dict[str, Any]:
    """Completa `row['status']` con el del reporte solo si la API lo dejo vacio."""
    if is_blank(row.get("status")):
        reported = statuses.get(str(row.get("external_id")))
        if reported is not None:
            row["status"] = reported
    return row


_PROJECT_SQL = text(
    """
    UPDATE clients c
    SET status = CASE WHEN r.deleted_at_source IS NOT NULL THEN :deleted ELSE :active END,
        updated_at = now()
    FROM tk_report_customers r
    WHERE c.source = 'toku'
      AND c.external_id = r.customer_external_id
      AND NULLIF(TRIM(c.status), '') IS NULL
    """
)


def project_report_status(db: Session) -> int:
    """Completa `clients.status` vacios de Toku con el estado del reporte. Idempotente; no hace commit."""
    result = db.execute(_PROJECT_SQL, {"deleted": REPORT_DELETED, "active": REPORT_ACTIVE})
    return result.rowcount or 0

