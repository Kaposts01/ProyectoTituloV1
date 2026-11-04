"""Catálogo de códigos de rechazo de Toku y normalización de las glosas del procesador.

Fuente del catálogo: hoja «Códigos de Error Toku» del reporte «Intentos de pago» del Backoffice de
Toku (24 códigos de detalle; sin datos personales). El `response_code` de la API tiene el formato
`GRAVEDAD(2) + FUENTE(3) + DETALLE(4)` (p. ej. `TEPSP1008`); el catálogo se indexa por el DETALLE.

Huecos conocidos (no se inventan): las reglas de negocio DEC-16 a DEC-25 usan los detalles 1051, 2043
y 2044, que NO están en la hoja oficial. Mientras Toku no entregue su texto, `lookup_toku_code`
devuelve `None` para ellos y la presentación cae al texto crudo del procesador.

La «glosa» (`original_response_message`) es el texto libre del procesador. Suele traer un número ISO
8583 entre corchetes (`[51]`, `[05]`, `[9G]`) y, en los reintentos, fecha y hora incrustadas
(`REINTENTAR EL 01-10-2025 A LAS 07:33`). `normalize_processor_message` separa el ISO como
`processor_code` y quita la fecha/hora para poder agrupar las ~450 variantes en pocas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TokuRejectionCode:
    detail: str
    severity: str  # SU éxito, TE temporal, PE permanente, UE desconocido
    message: str
    description: str


def _c(detail: str, severity: str, message: str, description: str) -> tuple[str, TokuRejectionCode]:
    return detail, TokuRejectionCode(detail, severity, message, description)


TOKU_REJECTION_CODES: dict[str, TokuRejectionCode] = dict(
    [
        _c("0000", "SU", "Transacción exitosa", "La transacción se ha completado exitosamente."),
        _c("1001", "TE", "Fondos insuficientes", "El cliente no tiene saldo suficiente para pagar."),
        _c("1002", "PE", "Cuenta cerrada", "La cuenta del cliente figura como cerrada, debe contactar a su banco para solucionarlo."),
        _c("1007", "PE", "Verificación fallida", "La verificación de la cuenta falló."),
        _c("1008", "TE", "Tarjeta rechazada", "La tarjeta del cliente fue rechazada, debe comunicarse con el banco para solucionarlo."),
        _c("1010", "PE", "Tarjeta expirada", "La tarjeta del cliente está expirada, debe comunicarse con el banco para solucionarlo."),
        _c("1011", "PE", "Tarjeta rechazada", "Esta tarjeta ha sido identificada como robada."),
        _c("1017", "PE", "Tarjeta inválida", "Esta tarjeta es inválida."),
        _c("1019", "PE", "Tarjeta bloqueada", "Esta tarjeta ha sido identificada como bloqueada."),
        _c("1059", "TE", "Cuenta temporalmente bloqueada", "La cuenta del cliente se encuentra temporalmente bloqueada."),
        _c("1062", "TE", "Fecha de expiración inválida", "La fecha de expiración ingresada no es válida. Puede que la fecha ingresada sea incorrecta o que la tarjeta expiró."),
        _c("1073", "TE", "Tarjeta temporalmente bloqueada", "La tarjeta del cliente se encuentra temporalmente bloqueada."),
        _c("2005", "PE", "PAC eliminado", "El servicio ingresado fue eliminado."),
        _c("2006", "TE", "CVC inválido", "El CVC de la tarjeta es inválido."),
        _c("2008", "TE", "Error al procesar", "Error de procesamiento con el medio de pago."),
        _c("2009", "TE", "Error de validación", "Ocurrió un error de validación de parámetros."),
        _c("2028", "TE", "Transacción rechazada", "El banco ha rechazado la transacción."),
        _c("2035", "TE", "Transacción rechazada", "Este tipo de transacción no está soportada."),
        _c("2063", "PE", "Tarjeta expirada", "La tarjeta está expirada por lo que no se volverá a intentar con esa."),
        _c("2070", "TE", "Excede límite de reintentos", "Se excedió el límite de reintentos de rechazo en el mes."),
        _c("2106", "PE", "Transacción rechazada", "El banco emisor es desconocido."),
        _c("4007", "TE", "Error general de Klap", "Error general adquirente."),
        _c("5408", "TE", "Error al procesar", "Hay un problema con el procesador de pago externo."),
        _c("9999", "UE", "Problema inesperado", "Problema inesperado"),
    ]
)

_LONG_CODE_RE = re.compile(r"^(SU|TE|PE|UE)([A-Z]{3})(\d{4})$")
_SHORT_CODE_RE = re.compile(r"^\d{4}$")


@dataclass(frozen=True)
class ParsedResponseCode:
    severity: str
    source: str
    detail: str


def parse_toku_response_code(code: str | None) -> ParsedResponseCode | None:
    """`TEPSP1008` -> (TE, PSP, 1008). None si no calza con el formato largo."""
    if code is None:
        return None
    m = _LONG_CODE_RE.match(str(code).strip().upper())
    return ParsedResponseCode(m.group(1), m.group(2), m.group(3)) if m else None


def lookup_toku_code(code: str | None) -> TokuRejectionCode | None:
    """Entrada del catálogo para un código largo (`TEPSP1008`) o corto (`1008`); None si no existe."""
    if code is None:
        return None
    text = str(code).strip().upper()
    parsed = parse_toku_response_code(text)
    detail = parsed.detail if parsed else (text if _SHORT_CODE_RE.match(text) else None)
    return TOKU_REJECTION_CODES.get(detail) if detail else None


# ---- glosas del procesador ----------------------------------------------------------------------

_MAX_TEXT = 200
_BRACKET_RE = re.compile(r"^\s*\[([^\]]{0,3})\]\s*")
# Fecha dd-mm-aaaa (o con «/»), hora hh:mm(:ss) y los restos «--» y «:» que deja una fecha vacía.
_DATETIME_TAIL_RE = re.compile(
    r"\s+(?:EL|el)\s+(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|--)\s+(?:A LAS|a las)\s+(?:\d{1,2}:\d{2}(?::\d{2})?|:)\s*$"
)
_DATE_RE = re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
_TAG_RE = re.compile(r"<[^>]*>")
_SPACES_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class NormalizedGlosa:
    text: str
    processor_code: str | None


def normalize_processor_message(raw: str | None) -> NormalizedGlosa | None:
    """Glosa del procesador sin fecha/hora y con el número ISO entre corchetes como `processor_code`.

    - `[51] RECHAZADA- REINTENTAR EL 01-10-2025 A LAS 07:33` -> texto `RECHAZADA- REINTENTAR`, código `51`.
    - Corchetes vacíos (`[]`) no producen código. Un cuerpo HTML se reduce a su texto visible.
    - None si la glosa viene vacía.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.startswith("<"):
        text = _TAG_RE.sub(" ", text)
    processor_code: str | None = None
    m = _BRACKET_RE.match(text)
    if m:
        processor_code = m.group(1).strip() or None
        text = text[m.end():]
    text = _SPACES_RE.sub(" ", text).strip()
    text = _DATETIME_TAIL_RE.sub("", text)
    text = _DATE_RE.sub("", text)
    text = _TIME_RE.sub("", text)
    text = _SPACES_RE.sub(" ", text).strip()
    if not text:
        return None if processor_code is None else NormalizedGlosa("", processor_code)
    return NormalizedGlosa(text[:_MAX_TEXT], processor_code)
