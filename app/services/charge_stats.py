"""Definicion UNICA de 'rechazo' y 'pendiente' para los dashboards (universo = CARGOS).

Universo de rechazo: cargos con fecha de cobro <= hoy (hora Chile), SIN cancelados / expirados /
anulados. `rate = rechazados / (pagados + rechazados)`; `None` si el denominador es 0.
La normalizacion de estados reutiliza `billing_plan.norm_state` y sus conjuntos.
"""
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import date
from typing import Any

from app.services.billing_plan import CANCELLED_STATES, PENDING_STATES, norm_state

PAID_STATES = frozenset({"pagado", "pago", "aceptado", "accepted", "paid", "success", "aprobada", "aceptada"})
REJECTED_STATES = frozenset({"rechazado", "rechazada", "rejected", "failed", "failure", "declined", "error"})
# Cargos que nunca ocurrieron / se dieron de baja: fuera de pagados, rechazados y pendientes.
EXCLUDED_STATES = CANCELLED_STATES | frozenset({
    "expirado", "expirada", "expired", "anulado", "anulada", "voided", "void",
})
# 'procesando' es un cargo en curso (aun sin resultado): es pendiente de resolver.
PENDING_DASHBOARD_STATES = PENDING_STATES | frozenset({"procesando", "processing"})

_DATE = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?")


def charge_outcome(status: Any) -> str:
    """'paid' | 'rejected' | 'pending' | 'excluded' | 'other' segun el estado normalizado."""
    state = norm_state(status)
    if state in PAID_STATES:
        return "paid"
    if state in REJECTED_STATES:
        return "rejected"
    if state in EXCLUDED_STATES:
        return "excluded"
    if state in PENDING_DASHBOARD_STATES:
        return "pending"
    return "other"


def parse_charge_date(value: Any) -> date | None:
    """'YYYY-MM' (dia 1) o 'YYYY-MM-DD...' -> date; None si no es parseable."""
    match = _DATE.match(str(value or ""))
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3) or 1))
    except ValueError:
        return None


def charge_rejection_stats(
    rows: Iterable[dict[str, Any]], today: date, *, since: date | None = None
) -> dict[str, Any]:
    """Estadistica de rechazo sobre filas {date, status, count?}.

    Solo cuentan cargos con `since <= fecha <= today`; solo pagados y rechazados (el resto,
    incluidos cancelados/expirados/anulados y pendientes, queda fuera). `rate` es None sin denominador.
    """
    paid = rejected = 0
    for row in rows:
        day = parse_charge_date(row.get("date"))
        if day is None or day > today or (since is not None and day < since):
            continue
        outcome = charge_outcome(row.get("status"))
        count = int(row.get("count", 1) or 0)
        if outcome == "paid":
            paid += count
        elif outcome == "rejected":
            rejected += count
    evaluable = paid + rejected
    return {
        "paid": paid,
        "rejected": rejected,
        "evaluable": evaluable,
        "rate": round(100 * rejected / evaluable, 1) if evaluable else None,
    }


def rejection_stats_by(
    rows: Iterable[dict[str, Any]], today: date, key: Callable[[dict[str, Any]], Any]
) -> dict[Any, dict[str, Any]]:
    """`charge_rejection_stats` por grupo (p. ej. (canal, 'YYYY-MM')); grupos sin cargos evaluables se omiten."""
    groups: defaultdict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    out = {k: charge_rejection_stats(v, today) for k, v in groups.items()}
    return {k: v for k, v in out.items() if v["evaluable"] > 0}


def fmt_pct(rate: float | None) -> str:
    """Porcentaje con coma decimal y un decimal ('98,0%'); '—' si no hay denominador."""
    return "—" if rate is None else f"{rate:.1f}".replace(".", ",") + "%"
