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


def payku_rejection_category(message: str | None) -> str | None:
    """Categoría de un mensaje de rechazo de Payku, o None si es de éxito o desconocido."""
    if message is None or not str(message).strip():
        return None
    return _MESSAGE_TO_CATEGORY.get(_key(str(message)))
