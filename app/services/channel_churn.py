"""Churn unificado de los dashboards de canal (DEC-37, misma definicion que D31 del resumen).

Antes cada canal media algo distinto: VirtualPOS promediaba 3 meses, Toku y Payku usaban el acumulado historico y TCH
el promedio mensual historico. Ahora el KPI `churn_rate` de los cuatro canales es el del resumen general:
bajas del mes calendario en curso (hora de Chile) / socios al cierre del mes anterior, en porcentaje.

La serie mensual `churn_rate_monthly` de cada canal ya seguia esa definicion (bajas del mes / activas al inicio del
mes); el KPI se toma del punto del mes en curso de esa serie. Un mes sin punto (sin altas ni bajas) es 0 % si hay base.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from app.services import rejected_month
from app.services.dashboard_general import CHURN_WINDOW_LABEL

__all__ = ["CHURN_WINDOW_LABEL", "unified_churn_rate"]


def unified_churn_rate(
    rate_series: Iterable[dict[str, Any]], *, has_base: bool, today: date | None = None
) -> float | None:
    """KPI de churn del mes en curso (Chile) desde la serie mensual del canal.

    `None` sin base (el canal no tiene ninguna suscripcion); `0.0` con base y sin punto en el mes en curso.
    """
    if not has_base:
        return None
    current = today or rejected_month.now_chile().date()
    for entry in rate_series:
        if (int(entry["year"]), int(entry["month"])) == (current.year, current.month):
            rate = entry.get("rate")
            return float(rate) if rate is not None else 0.0
    return 0.0
