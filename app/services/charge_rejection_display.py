"""Motivo de rechazo legible de UN cobro para las fichas de detalle (d143, L6-GLOSAS).

Misma regla que la vista unificada de Cobros y su exportacion (`export_queries._charges_post`): glosa del reporte
de la plataforma (PAT de VirtualPOS) > glosa de la API (`core_charges.latest_rejection_reason`) > catalogo >
«Motivo no informado (código X)». Solo lectura.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import CoreCharge
from app.models.vp_report import VpReportPayment
from app.services.charge_stats import charge_outcome
from app.services.rejection_format import channel_of_source, rejection_text

DETAIL_FIELD = "motivo_rechazo"


def charge_rejection_text(db: Session, source: str, external_id: str, status: str | None) -> str | None:
    """Texto del motivo para el cobro (`source`, `external_id`); None si no es un rechazo y no hay dato."""
    core = db.execute(
        select(CoreCharge.latest_rejection_code, CoreCharge.latest_rejection_reason)
        .where(CoreCharge.source == source, CoreCharge.external_id == external_id)
    ).first()
    code, api = (core.latest_rejection_code, core.latest_rejection_reason) if core is not None else (None, None)
    report = report_code = None
    if channel_of_source(source) == "virtualpos":
        row = db.execute(
            select(VpReportPayment.response_code, VpReportPayment.response_text).where(
                VpReportPayment.charge_external_id == external_id, VpReportPayment.platform == source,
                VpReportPayment.platform_status == "resolved", VpReportPayment.charge_status == "rechazado",
            )
        ).first()
        if row is not None:
            report_code, report = (row.response_code or None), row.response_text
    chosen = (report_code or code) if report else (code or report_code)
    return rejection_text(source, chosen, report_reason=report, api_reason=api,
                          rejected=charge_outcome(status) == "rejected")
