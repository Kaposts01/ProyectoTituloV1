"""Clasificación de los mensajes de rechazo de Payku (`gateway_response.message`).

Payku no entrega códigos, solo texto. Fuente: docs/integrations/payku/resources/errors.md §4 (siete
mensajes de rechazo y uno de éxito). El texto crudo se guarda siempre; la categoría es solo para
agrupar y presentar. Un mensaje que no esté aquí no tiene categoría y se muestra tal cual.
"""

from __future__ import annotations

import unicodedata

# Categoría -> etiqueta legible.
PAYKU_CATEGORY_LABELS: dict[str, str] = {
    "REJECT": "Rechazo de la transacción",
    "RETRY": "La transacción debe reintentarse",
    "ERROR": "Error en la transacción",
    "RATE": "Rechazo por error de tasa",
    "MONTHLY_LIMIT": "Excede el cupo máximo mensual",
    "DAILY_LIMIT": "Excede el límite diario por transacción",
    "MCC": "Rubro no autorizado",
}


def _key(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(folded.casefold().replace(".", " ").split())


_MESSAGE_TO_CATEGORY: dict[str, str] = {
    _key("Rechazo de transacción."): "REJECT",
    _key("Transacción debe reintentarse."): "RETRY",
    _key("Error en transacción."): "ERROR",
    _key("Rechazo por error de tasa."): "RATE",
    _key("Excede cupo máximo mensual."): "MONTHLY_LIMIT",
    _key("Excede límite diario por transacción."): "DAILY_LIMIT",
    _key("Rubro no autorizado."): "MCC",
}


# Respaldo por suscripcion (PK-PAR-06 / RJ-10): `last_status_current_payment` de `GET /api/sususcription` (V1).
# Valores de la «Lista A» de estados de cobro clasificados como RECHAZADO en docs/integrations/payku/resources/statuses.md
# (§2 y §12; `rejected` es de la Lista B y no aparece en este campo). Textos segun el significado de ese documento.
# No es la glosa del cobro (esa solo existe en `GET /api/transaction/{id}`, PK-PAR-05): es el ultimo estado de cobro
# de la suscripcion, y por eso solo se aplica al rechazo mas reciente de la suscripcion.
PAYKU_SUBSCRIPTION_REJECTION_LABELS: dict[str, str] = {
    "maximum attempt limit": "Se agotaron los reintentos de cobro",
    "first payment rejected": "Falló el primer cobro",
    "payment consumes failed": "Falló el cobro del plan de consumo",
}


def payku_subscription_rejection_status(value: str | None) -> str | None:
    """Clave normalizada de `last_status_current_payment` si es un estado de rechazo documentado; si no, None."""
    if value is None:
        return None
    key = " ".join(str(value).casefold().split())
    return key if key in PAYKU_SUBSCRIPTION_REJECTION_LABELS else None


def payku_rejection_category(message: str | None) -> str | None:
    """Categoría de un mensaje de rechazo de Payku, o None si es de éxito o desconocido."""
    if message is None or not str(message).strip():
        return None
    return _MESSAGE_TO_CATEGORY.get(_key(str(message)))
