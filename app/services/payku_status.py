"""Taxonomia comun de estados Payku (PK-PAR-07, PK-06). Funciones puras, sin dependencias de la app.

Vive en su propio modulo para que la usen tanto los extractores de `channel_store` (que escriben `p_*` durante la
sincronizacion) como el ETL Core (`core_payku_etl`, que reexporta estos nombres), sin importaciones circulares.

* Suscripcion: mapeo de docs/integrations/payku/resources/statuses.md §12 con los nombres del plan
  (`active`/`suspended`/`cancelled`/`pending_enrollment`). `suspended_awaits_change_plan` cuenta como vigente.
* Cobro (PK-06): Listas A y B de statuses.md §2 -> `paid`/`pending`/`retrying`/`rejected`/`refunded`/`cancelled`.
  La lista de `paid[].status` de V3 no esta documentada (Q-05): se asume que comparte valores con A y B y se valida
  en sandbox cuando exista (DEC-10).

Cualquier otro valor es `unknown` (nunca rompe el ETL). El estado crudo de Payku se sigue guardando tal cual; el
normalizado va en columnas `status_normalized` aparte (migracion 20261102_0055).
"""

from __future__ import annotations

import unicodedata

COMMON_STATUS_UNKNOWN = "unknown"

PAYKU_COMMON_STATUS: dict[str, str] = {
    "register": "pending_enrollment",
    "active": "active",
    "suspended_awaits_change_plan": "active",
    "suspended": "suspended",
    "cancel": "cancelled",
    "delete": "cancelled",
    "finish": "cancelled",
}

PAYKU_CHARGE_STATUS: dict[str, str] = {
    "success": "paid",
    "pending": "pending",
    "retry": "retrying",
    "rejected": "rejected",
    "first payment rejected": "rejected",
    "maximum attempt limit": "rejected",
    "payment consumes failed": "rejected",
    "refunded": "refunded",
    "refunded partial": "refunded",
    "canceled by customer": "cancelled",
    "canceled by paymaster": "cancelled",
    "canceled by payku": "cancelled",
}


def _fold(value: str | None) -> str:
    """Minusculas, sin tildes (`paymáster` -> `paymaster`) y espacios simples."""
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(text.strip().lower().split())


def normalize_payku_status(status: str | None) -> str:
    """Estado de suscripcion Payku crudo -> taxonomia comun."""
    return PAYKU_COMMON_STATUS.get((status or "").strip().lower(), COMMON_STATUS_UNKNOWN)


def normalize_payku_charge_status(status: str | None) -> str:
    """Estado de cobro/ciclo Payku crudo -> taxonomia comun de cobros."""
    return PAYKU_CHARGE_STATUS.get(_fold(status), COMMON_STATUS_UNKNOWN)
