"""d139d (L5-ALERTAS): alertas de negocio de severidad «alta» por correo. Ver docs/data/alerts.md.

Reutiliza las alertas que YA calcula el panel (`app/api/v1/routes/staging.py`): no repite ningun calculo, solo toma las
de severidad `alta` de los mismos tableros (general, VirtualPOS, Toku y Payku) y las convierte en condiciones con un
`kind` por tipo:

- `business_rejection_rate:<canal>[:<YYYY-MM>]`: «Tasa de rechazo global elevada» (canal `consolidado`) y «Alta tasa de
  rechazo» por canal y mes. De las de canal y mes solo cuentan el mes actual y el anterior (hora de Chile): el panel
  lista toda la historia y un mes viejo no es accionable.
- `business_churn:<canal>`: «Churn rate elevado».
- `business_rejection_streak:<canal>`: «Racha de rechazos».
- `business_no_recent_charge:<canal>`: «Sin cobro reciente».

Detras de `ALERT_BUSINESS_ENABLED` (apagada por defecto, d138). Los tableros son pesados: el resultado se reutiliza
durante `ALERT_BUSINESS_EVAL_MINUTES` (60) en vez de recalcularse en cada chequeo de 15 min. Si un tablero falla, se
conservan sus ultimas condiciones conocidas (un fallo de calculo no se confunde con «Recuperado»). Sin datos
personales: el detalle del panel solo trae canal, periodo, porcentajes y conteos.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import alerts

logger = logging.getLogger(__name__)

DASHBOARD_LINK = "/central/resumen"
SEVERITY = "alta"

# tipo del panel -> (kind, sujeto del aviso)
TYPE_KINDS: dict[str, tuple[str, str]] = {
    "Tasa de rechazo global elevada": ("business_rejection_rate", "tasa de rechazo elevada"),
    "Alta tasa de rechazo": ("business_rejection_rate", "tasa de rechazo elevada"),
    "Churn rate elevado": ("business_churn", "churn elevado"),
    "Racha de rechazos": ("business_rejection_streak", "racha de rechazos"),
    "Sin cobro reciente": ("business_no_recent_charge", "suscripciones sin cobro reciente"),
}
KINDS: tuple[str, ...] = tuple(dict.fromkeys(kind for kind, _ in TYPE_KINDS.values()))
_SUBJECTS = {kind: subject for kind, subject in TYPE_KINDS.values()}

_cache: dict[str, Any] = {"at": None, "by_board": {}}


def reset_cache() -> None:
    _cache["at"] = None
    _cache["by_board"] = {}


def _boards() -> dict[str, Callable[[Session], dict[str, Any]]]:
    from app.api.v1.routes import staging  # import local: modulo de rutas pesado

    return {
        "general": staging._general_dashboard,
        "virtualpos": lambda db: staging._vp_centralized_dashboard("virtualpos", db),
        "toku": staging._toku_centralized_dashboard,
        "payku": staging._payku_centralized_dashboard,
    }


def _slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", plain).strip("_") or "canal"


def _recent_periods(now: datetime) -> set[str]:
    """Mes actual y anterior en hora de Chile (YYYY-MM)."""
    today = now.astimezone(ZoneInfo("America/Santiago")).date()
    first = today.replace(day=1)
    previous = (first - timedelta(days=1)).replace(day=1)
    return {first.strftime("%Y-%m"), previous.strftime("%Y-%m")}


def to_condition(alert: dict[str, Any], now: datetime) -> alerts.Condition | None:
    """Alerta del panel -> condicion. None si no es de severidad alta, no es de un tipo enviado o es de un mes viejo."""
    if alert.get("sev") != SEVERITY:
        return None
    kind_subject = TYPE_KINDS.get(str(alert.get("tipo") or ""))
    if kind_subject is None:
        return None
    kind, subject = kind_subject
    channel = str(alert.get("canal") or "Consolidado")
    period = alert.get("periodo")
    detail = _slug(channel)
    if period:
        if str(period) not in _recent_periods(now):
            return None
        detail = f"{detail}:{period}"
    return alerts.Condition(
        key=f"{kind}:{detail}", channel=channel, title=f"{subject} ({channel}{' ' + str(period) if period else ''})",
        text=f"{alert['tipo']} (severidad alta).", details=(str(alert.get("detalle") or ""),), link=DASHBOARD_LINK)


def _board_alerts(db: Session, name: str, build: Callable[[Session], dict[str, Any]]) -> list[dict[str, Any]] | None:
    try:
        with db.begin_nested():
            return list((build(db) or {}).get("alerts") or [])
    except Exception as exc:  # noqa: BLE001 - un tablero roto no debe tumbar el chequeo ni dar nada por recuperado
        logger.warning("Alertas de negocio: el tablero %s no se pudo calcular (%s).", name, type(exc).__name__)
        return None


def evaluate(db: Session, now: datetime) -> list[alerts.Condition]:
    every = timedelta(minutes=max(0, int(settings.alert_business_eval_minutes)))
    last = _cache["at"]
    if last is None or now - last >= every or now < last:
        by_board: dict[str, list[dict[str, Any]]] = dict(_cache["by_board"])
        for name, build in _boards().items():
            fresh = _board_alerts(db, name, build)
            if fresh is not None:
                by_board[name] = fresh
        _cache["by_board"] = by_board
        _cache["at"] = now
    found: dict[str, alerts.Condition] = {}
    for board_alerts in _cache["by_board"].values():
        for alert in board_alerts:
            condition = to_condition(alert, now)
            if condition is not None and condition.key not in found:
                found[condition.key] = condition
    return list(found.values())


def _describe(kind: str) -> Callable[[str], tuple[str, str]]:
    def describe(detail: str) -> tuple[str, str]:
        channel = detail.split(":", 1)[0].replace("_", " ").title() if detail else "Negocio"
        return channel, _SUBJECTS[kind]

    return describe


def _none(_db: Session, _now: datetime) -> list[alerts.Condition]:
    return []


def register() -> None:
    enabled = lambda: bool(settings.alert_business_enabled)  # noqa: E731
    # Un solo tablero alimenta todos los kinds: el primero evalua (con cache) y los demas solo describen.
    alerts.register_condition_provider(KINDS[0], evaluate, _describe(KINDS[0]), enabled)
    for kind in KINDS[1:]:
        alerts.register_condition_provider(kind, _none, _describe(kind), enabled)


register()
