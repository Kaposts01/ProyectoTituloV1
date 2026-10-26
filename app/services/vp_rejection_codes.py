"""Catálogo de códigos de rechazo VirtualPOS con etiquetas legibles.

Fuente: docs/integrations/virtualpos/resources/errors.md (catálogo oficial). Un código que no esté
aquí se muestra tal cual; nunca se inventan códigos.
"""

from __future__ import annotations

VP_REJECTION_LABELS: dict[str, str] = {
    "-1": "Tarjeta inválida (error en número de tarjeta)",
    "-2": "Error de conexión",
    "-3": "Rechazado por el banco emisor: excede el monto máximo permitido",
    "-4": "Tarjeta inválida (error en fecha de expiración)",
    "-5": "Error de autenticación del cliente en su banco emisor",
    "-6": "Rechazo general",
    "-7": "Tarjeta bloqueada",
    "-8": "Tarjeta expirada",
    "-9": "Tarjeta no soportada por el adquirente",
    "-10": "Problema general en la transacción",
    "-11": "El pagador excedió el límite de rechazos de la marca",
    "-1001": "El comercio no tiene habilitado Quick Checkout",
    "-1002": "La transacción no está en estado pendiente",
    "-1003": "El monto supera el máximo permitido para el comercio",
    "-1004": "Pago desde navegador en modo incógnito",
    "-1005": "Posible transacción ejecutada por un bot",
    "-1006": "No se pudo determinar el identificador del sistema del pagador",
    "-1007": "Pago desde un país no permitido",
    "-1009": "El comercio superó el monto máximo de ventas diarias",
    "-1010": "El comercio superó la cantidad máxima de transacciones diarias",
    "-1011": "Cliente o dispositivo restringido para realizar pagos",
    "-1013": "El comercio no tiene habilitadas las tarjetas extranjeras",
    "-1014": "El comercio superó el máximo diario de intentos fallidos",
    "-1015": "El comercio superó el máximo diario de transacciones por una misma tarjeta",
    "-1016": "Tarjeta no habilitada para Quick Checkout",
    "-1017": "No se pudo completar la validación de seguridad del pagador",
    "-1018": "Transacción rechazada por botón volver",
}

NOT_REPORTED = "No informado por VirtualPOS"


def format_rejection_reason(code: str | None, reason: str | None) -> str:
    """Motivo legible: etiqueta del catálogo, si no el texto del proveedor, si no el código tal cual."""
    code = str(code).strip() if code is not None and str(code).strip() else None
    reason = str(reason).strip() if reason is not None and str(reason).strip() else None
    if code and code in VP_REJECTION_LABELS:
        return VP_REJECTION_LABELS[code]
    return reason or code or NOT_REPORTED
