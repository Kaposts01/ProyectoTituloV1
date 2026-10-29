"""Motivo de rechazo legible por canal (VirtualPOS, Toku, Payku).

`format_rejection_reason(source, code, reason)` elige el catálogo del canal. Regla común: el texto del
catálogo manda cuando el código está; si no, el texto crudo del proveedor; si no, el código tal cual;
si no, «No informado por <canal>». Nunca se inventan códigos ni textos.

Los códigos y textos crudos se guardan siempre en `core_*`; esta función es solo de presentación.
"""

from __future__ import annotations

from app.services.payku_rejection_codes import (
    PAYKU_CATEGORY_LABELS,
    payku_rejection_category,
)
from app.services.toku_rejection_codes import (
    lookup_toku_code,
    normalize_processor_message,
)
from app.services.vp_rejection_codes import VP_REJECTION_LABELS

_CHANNEL_LABEL = {"virtualpos": "VirtualPOS", "toku": "Toku", "payku": "Payku"}


def channel_of_source(source: str | None) -> str | None:
    """`virtualpos1`/`virtualpos2` -> `virtualpos`; `toku`; `payku`; otro -> None."""
    text = str(source or "").strip().casefold()
    if text.startswith("virtualpos"):
        return "virtualpos"
    return text if text in ("toku", "payku") else None


def not_reported_label(source: str | None) -> str:
    channel = channel_of_source(source)
    return f"No informado por {_CHANNEL_LABEL[channel]}" if channel else "No informado"


def _clean(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def format_rejection_reason(source: str | None, code: str | None, reason: str | None) -> str:
    """Motivo legible para el canal de `source` (ver el docstring del módulo)."""
    channel = channel_of_source(source)
    code_s, reason_s = _clean(code), _clean(reason)

    if channel == "virtualpos":
        if code_s and code_s in VP_REJECTION_LABELS:
            return VP_REJECTION_LABELS[code_s]
    elif channel == "toku":
        entry = lookup_toku_code(code_s)
        if entry is not None:
            return entry.message
        processor_message = normalize_processor_message(reason_s)
        if processor_message is not None and processor_message.text:
            return processor_message.text
    elif channel == "payku":
        category = payku_rejection_category(reason_s) or (code_s if code_s in PAYKU_CATEGORY_LABELS else None)
        if category:
            return PAYKU_CATEGORY_LABELS[category]

    return reason_s or code_s or not_reported_label(source)
