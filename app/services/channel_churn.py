"""Churn unificado de los dashboards de canal (DEC-37, misma definicion que D31 del resumen).

Antes cada canal media algo distinto: VirtualPOS promediaba 3 meses, Toku y Payku usaban el acumulado historico y TCH
el promedio mensual historico. Ahora el KPI `churn_rate` de los cuatro canales usa la definicion del resumen general:
bajas del mes / socios al cierre del mes anterior, en porcentaje.

L6-DASH (ficha d142): el KPI ya no toma el mes calendario EN CURSO, que los primeros dias casi siempre da 0 % (aun no hay
bajas registradas) y escondia las bajas reales del mes anterior. Toma el ULTIMO MES CERRADO CON DATO (hora de Chile):
el punto mas reciente de la serie mensual `churn_rate_monthly` anterior al mes en curso. La serie tiene un punto por cada
mes con altas o bajas; el rotulo dice que mes se uso (`churn_window_label`).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from app.services import rejected_month

CLOSED_MONTH_WINDOW = "último mes cerrado con dato (hora de Chile)"
CHURN_DEFINITION_TAIL = "bajas del mes ÷ socios al cierre del mes anterior"
# Rotulo sin mes concreto (canal sin base o sin ningun mes cerrado con dato).
CHURN_WINDOW_LABEL = f"{CLOSED_MONTH_WINDOW}: {CHURN_DEFINITION_TAIL}"

__all__ = ["CHURN_WINDOW_LABEL", "churn_window_label", "closed_month_churn", "unified_churn_rate"]


def churn_window_label(period: str | None) -> str:
    """Rotulo del KPI: nombra el mes usado (`YYYY-MM`) cuando lo hay."""
    if not period:
        return CHURN_WINDOW_LABEL
    return f"{CLOSED_MONTH_WINDOW}, {period}: {CHURN_DEFINITION_TAIL}"


def closed_month_churn(
    rate_series: Iterable[dict[str, Any]], *, has_base: bool, today: date | None = None
) -> tuple[float | None, str | None, str]:
    """(churn, mes `YYYY-MM`, rotulo) del ultimo mes cerrado con dato de la serie mensual del canal.

    `None` sin base (el canal no tiene ninguna suscripcion) o sin ningun mes cerrado en la serie (toda la actividad
    es del mes en curso): no hay un mes completo que medir, y un 0 seria inventado.
    """
    if not has_base:
        return None, None, CHURN_WINDOW_LABEL
    current = today or rejected_month.now_chile().date()
    best: tuple[tuple[int, int], Any] | None = None
    for entry in rate_series:
        key = (int(entry["year"]), int(entry["month"]))
        if key >= (current.year, current.month):
            continue
        if best is None or key > best[0]:
            best = (key, entry.get("rate"))
    if best is None:
        return None, None, CHURN_WINDOW_LABEL
    (year, month), rate = best
    period = f"{year:04d}-{month:02d}"
    return (float(rate) if rate is not None else 0.0), period, churn_window_label(period)


def unified_churn_rate(
    rate_series: Iterable[dict[str, Any]], *, has_base: bool, today: date | None = None
) -> float | None:
    """Solo el valor de `closed_month_churn` (compatibilidad con los llamadores que no usan el rotulo)."""
    return closed_month_churn(rate_series, has_base=has_base, today=today)[0]
