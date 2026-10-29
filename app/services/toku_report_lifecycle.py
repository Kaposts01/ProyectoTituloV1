"""Fechas de alta y baja de las suscripciones de Toku segun el reporte de Productos (TK-PAR-05).

La API de Toku no entrega la fecha de alta (`recurring.anchor` es el proximo cobro) ni lista las suscripciones
eliminadas. El reporte de Productos trae `Fecha de Creacion` (alta real) y `Fecha de Eliminacion` (baja) por `sub_`.
Este modulo solo lee `tk_report_products`; quien escribe en core y en la tabla centralizada son el ETL core y la
consolidacion. Sin datos personales: solo IDs, fechas y monto.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.toku_report import TkReportProduct

CHILE_TZ = ZoneInfo("America/Santiago")


@dataclass(frozen=True)
class ReportProductDates:
    subscription_external_id: str
    customer_external_id: str
    amount: Decimal | None
    created_at: datetime | None
    deleted_at: datetime | None


def chile_date(value: datetime | None) -> date | None:
    """Fecha calendario en hora de Chile (los reportes se generan en hora local; la base guarda UTC)."""
    return value.astimezone(CHILE_TZ).date() if value is not None else None


def chile_date_iso(value: datetime | None) -> str | None:
    d = chile_date(value)
    return d.isoformat() if d else None


def report_product_dates(db: Session, external_ids: set[str] | None = None) -> dict[str, ReportProductDates]:
    stmt = select(
        TkReportProduct.subscription_external_id,
        TkReportProduct.customer_external_id,
        TkReportProduct.amount,
        TkReportProduct.created_at_source,
        TkReportProduct.deleted_at_source,
    )
    if external_ids is not None:
        if not external_ids:
            return {}
        stmt = stmt.where(TkReportProduct.subscription_external_id.in_(external_ids))
    return {
        r.subscription_external_id: ReportProductDates(
            r.subscription_external_id, r.customer_external_id, r.amount, r.created_at_source, r.deleted_at_source
        )
        for r in db.execute(stmt)
    }
