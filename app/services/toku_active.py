"""«Suscripcion activa efectiva» de Toku (DEC-18, TK-13): la UNICA base de MRR, ARPU y suscriptores activos de Toku.

Criterio (en este orden; regla vigente desde d118 opcion c, 2026-11-02):

0. **Pausadas y sin estado fuera**: una suscripcion con estado de la API `PAUSED` o vacio (`NULL`/`''`) NO es activa
   efectiva, haya o no senal del reporte (el reporte no conoce las pausas, y un estado vacio no prueba que este viva).
1. **Senal del reporte** (`core_subscription_signals`, TK-20; solo con `TOKU_REPORT_SIGNALS_ENABLED=true`): si la
   suscripcion tiene fila, manda
   `is_effectively_active` (= no eliminada en el reporte **y** medio de pago `chargeable`). El reporte gana para estado y
   medio de pago (DEC-23).
2. **Sin senal, la API**: no eliminada (estado distinto de las bajas de Toku: `cancelled`, `canceled`, `cancelada`,
   `deleted`, `ended`, `deleted_at_source`) **y** con un medio de pago `chargeable` de la API que la lista en
   `subscription_ids`.

Historia: antes de TK-13 se exigia `status == 'active'` y se ignoraban las senales; la primera version de TK-13 contaba
`PAUSED` y el estado vacio como activas; d118 (opcion c) las vuelve a excluir.
"""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.crm import PaymentMethod as CPaymentMethod
from app.models.toku_report import CoreSubscriptionSignal
from app.services.status_history import CANCELLATION_STATES

TOKU_DELETED_STATES = frozenset(CANCELLATION_STATES["toku"] | {"deleted_at_source"})
# d118 (opcion c): estados que nunca cuentan como activa efectiva (el vacio se representa con "").
TOKU_NOT_ACTIVE_STATES = frozenset({"paused", ""})
CRITERION_LABEL = (
    "suscripción activa efectiva: no eliminada, no pausada, con estado y con medio de pago cobrable "
    "(DEC-18, d118; el reporte de Toku manda cuando existe)"
)


def payment_method_subscription_ids(payload: dict[str, Any] | None) -> list[str]:
    """IDs de suscripcion que lista un medio de pago de Toku (`subscription_ids`, en raiz o en `payment_method`)."""
    payload = payload or {}
    values = payload.get("subscription_ids")
    if not isinstance(values, list):
        method = payload.get("payment_method")
        values = method.get("subscription_ids") if isinstance(method, dict) else []
    return [str(value) for value in values if value is not None] if isinstance(values, list) else []


def api_chargeable_subscription_ids(db: Session) -> set[str]:
    """Suscripciones con un medio de pago `chargeable` segun la API (tabla centralizada `payment_methods`)."""
    return {
        sub_id
        for payload in db.scalars(
            select(CPaymentMethod.raw_payload).where(
                CPaymentMethod.source == "toku", func.lower(CPaymentMethod.status) == "chargeable"
            )
        )
        for sub_id in payment_method_subscription_ids(payload)
    }


def report_signals(db: Session) -> dict[str, bool]:
    """{external_id: is_effectively_active} de las senales del reporte.

    Vacio si `TOKU_REPORT_SIGNALS_ENABLED` esta apagada (la misma bandera que las calcula en el ETL core): con la bandera
    apagada no se leen senales viejas y manda la API.
    """
    if not settings.toku_report_signals_enabled:
        return {}
    return {
        ext: bool(flag)
        for ext, flag in db.execute(
            select(CoreSubscriptionSignal.external_id, CoreSubscriptionSignal.is_effectively_active).where(
                CoreSubscriptionSignal.source == "toku"
            )
        )
    }


def is_effectively_active(
    external_id: str, status: Any, chargeable_ids: set[str], signals: dict[str, bool]
) -> bool:
    """Regla pura (ver el docstring del modulo)."""
    normalized = str(status or "").strip().lower()
    if normalized in TOKU_NOT_ACTIVE_STATES:
        return False
    if external_id in signals:
        return signals[external_id]
    if normalized in TOKU_DELETED_STATES:
        return False
    return external_id in chargeable_ids


class EffectiveActive:
    """Contexto cargado una vez por request: chargeable de la API + senales del reporte."""

    def __init__(self, db: Session):
        self.chargeable_ids = api_chargeable_subscription_ids(db)
        self.signals = report_signals(db)

    def __call__(self, external_id: str, status: Any) -> bool:
        return is_effectively_active(external_id, status, self.chargeable_ids, self.signals)

    def filter(self, rows: Iterable[Any], *, ext: str = "external_id", status: str = "status") -> list[Any]:
        return [row for row in rows if self(getattr(row, ext), getattr(row, status))]
