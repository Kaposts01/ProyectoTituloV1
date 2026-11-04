"""Motivo de rechazo legible por canal (VirtualPOS, Toku, Payku).

`format_rejection_reason(source, code, reason)` elige el catálogo del canal. Regla común: el texto del
catálogo manda cuando el código está; si no, el texto crudo del proveedor; si no, el código tal cual;
si no, «No informado por <canal>». Nunca se inventan códigos ni textos.

Los códigos y textos crudos se guardan siempre en `core_*`; esta función es solo de presentación.
"""

from __future__ import annotations

from app.services.payku_rejection_codes import (
    PAYKU_CATEGORY_LABELS,
    PAYKU_SUBSCRIPTION_REJECTION_LABELS,
    payku_rejection_category,
    payku_subscription_rejection_status,
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
        subscription_status = payku_subscription_rejection_status(reason_s)  # respaldo PK-PAR-06
        if subscription_status:
            return PAYKU_SUBSCRIPTION_REJECTION_LABELS[subscription_status]

    return reason_s or code_s or not_reported_label(source)


def format_rejection_with_code(source: str | None, code: str | None, reason: str | None) -> str:
    """Motivo legible seguido del código del proveedor (VP-PAR-03): «Tarjeta expirada (código -8)».

    El código va tal como lo guarda `core_*` (p. ej. `-2119`, `TEPSP1008`, `ISO:51`) para que se pueda buscar en
    la documentación del proveedor. Sin código, o si el motivo ya es el código, devuelve solo el motivo.
    """
    text = format_rejection_reason(source, code, reason)
    code_s = _clean(code)
    if code_s is None or text == code_s:
        return text
    return f"{text} (código {code_s})"


# ----------------------------------------------------------------------------- motivo en texto (d143, L6-GLOSAS)

NOT_REPORTED_TEXT = "Motivo no informado"


def _legible(text: str | None) -> str | None:
    """Texto del proveedor presentable: sin espacios de mas y, si viene TODO en mayusculas, en tipo oracion.

    Solo cambia mayusculas/minusculas: nunca agrega ni quita palabras (no se inventan glosas, d120).
    """
    clean = " ".join(str(text).split()) if text is not None else ""
    if not clean:
        return None
    letters = [ch for ch in clean if ch.isalpha()]
    if letters and all(ch.isupper() for ch in letters):
        clean = clean[0].upper() + clean[1:].lower()
    return clean


def _catalog_text(channel: str | None, code: str | None, api_reason: str | None) -> str | None:
    """Traduccion con el catalogo del canal; None si el codigo (o el mensaje) no esta documentado."""
    if channel == "virtualpos":
        return VP_REJECTION_LABELS.get(code) if code else None
    if channel == "toku":
        entry = lookup_toku_code(code)
        return entry.message if entry is not None else None
    if channel == "payku":
        category = payku_rejection_category(api_reason) or (code if code in PAYKU_CATEGORY_LABELS else None)
        if category:
            return PAYKU_CATEGORY_LABELS[category]
        status = payku_subscription_rejection_status(api_reason)
        return PAYKU_SUBSCRIPTION_REJECTION_LABELS[status] if status else None
    return None


def rejection_text(
    source: str | None,
    code: str | None,
    *,
    report_reason: str | None = None,
    api_reason: str | None = None,
    rejected: bool = True,
) -> str | None:
    """Motivo de rechazo SIEMPRE en texto legible, con el codigo entre parentesis cuando existe (d143).

    Prioridad de fuentes:
    1. glosa del reporte de la plataforma: «Motivo» del PAT de VirtualPOS (`vp_report_payments.response_text`),
       la hoja oficial de codigos del reporte «Intentos de pago» de Toku (`toku_rejection_codes`, el reporte trae
       solo el codigo y esa hoja es su glosa) y la «razon de rechazo» del Excel de TCH;
    2. glosa de la API (`core_*.latest_rejection_reason`: `rejected_object` de VirtualPOS, glosa del procesador de
       Toku sin fecha ni ISO, mensaje del gateway o `last_status_current_payment` de Payku);
    3. traduccion del codigo con el catalogo del canal (Payku: el mensaje conocido del gateway);
    4. «Motivo no informado (código X)», o «Motivo no informado» sin codigo.

    Nunca inventa glosas para codigos no documentados (d120): un codigo fuera del catalogo y sin glosa cae en (4).
    Con `rejected=False` y sin ningun dato devuelve None (el cobro no es un rechazo: la celda queda vacia).
    """
    channel = channel_of_source(source)
    code_s = _clean(code)
    report_s = _legible(report_reason)
    api_s = _clean(api_reason)

    text: str | None = report_s
    if text is None and channel == "toku":
        text = _catalog_text(channel, code_s, None)  # glosa del reporte de Intentos (hoja oficial de codigos)
    if text is None and api_s is not None:
        if channel == "payku":
            # El mensaje del gateway y el estado de la suscripcion tienen forma documentada: se muestran legibles.
            text = _catalog_text(channel, code_s, api_s) or _legible(api_s)
        elif channel == "toku":
            glosa = normalize_processor_message(api_s)
            text = _legible(glosa.text) if glosa is not None and glosa.text else None
        else:
            text = _legible(api_s)
        if text is not None and code_s is not None and text.casefold() == code_s.casefold():
            text = None  # la «glosa» es el codigo repetido: no es texto
    if text is None:
        text = _catalog_text(channel, code_s, None)

    if text is None:
        if code_s is None and not rejected:
            return None
        return f"{NOT_REPORTED_TEXT} (código {code_s})" if code_s else NOT_REPORTED_TEXT
    return f"{text} (código {code_s})" if code_s else text
