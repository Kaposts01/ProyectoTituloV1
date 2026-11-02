"""RUT en el canal TCH (TCH-PAR-14, ADR-001).

El reporte TCH no trae otro identificador del socio que el RUT, asi que dentro del canal el RUT normalizado es el ID
de proveedor (``tch_clientes.rut`` = ``external_identities.external_id`` con ``source='tch'``). ADR-001 prohibe usarlo
como clave transversal; ademas, un RUT solo aporta evidencia de identidad si su digito verificador es correcto.

Reglas:

* Un valor con forma de RUT (cuerpo numerico y digito verificador 0-9/K) se guarda con el formato del canal
  ``12.345.678-5``, sea o no correcto su verificador: es la llave natural del proveedor y cambiarla exigiria migrar.
* Un valor que NO tiene forma de RUT (pasaporte, documento extranjero, texto) se AISLA con el prefijo ``EXT-`` y sus
  caracteres alfanumericos. Antes se le quitaban las letras y documentos distintos colapsaban en un mismo "RUT".
* Solo un RUT con verificador correcto sale del canal como senal de identidad: atributo ``rut`` en
  ``core_client_attributes`` (lo usa el detector de candidatos) y ``social_id`` en las tablas centralizadas.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

ISOLATED_PREFIX = "EXT-"
_MAX_KEY = 20  # tch_clientes.rut y tch_suscripciones.cliente_rut son String(20)
_RUT_SHAPE = re.compile(r"(\d{1,9})([\dK])")


def _compact(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().strip().upper()
    return re.sub(r"[\s.\-]", "", text)


def check_digit(body: str) -> str:
    """Digito verificador (modulo 11) de un cuerpo numerico."""
    total = sum(int(digit) * (2 + i % 6) for i, digit in enumerate(reversed(body)))
    remainder = 11 - total % 11
    return "K" if remainder == 10 else "0" if remainder == 11 else str(remainder)


def normalize_tch_rut(value: Any) -> str | None:
    """Llave del cliente TCH: ``12.345.678-5`` si tiene forma de RUT; ``EXT-<alfanumerico>`` si no; None si vacio."""
    if value is None or (isinstance(value, float) and value != value):
        return None
    compact = _compact(value)
    if not compact:
        return None
    shape = _RUT_SHAPE.fullmatch(compact)
    if shape:
        body, dv = shape.groups()
        return f"{int(body):,}".replace(",", ".") + f"-{dv}"
    alnum = re.sub(r"[^0-9A-Z]", "", compact)
    if not alnum:
        return None
    return (ISOLATED_PREFIX + alnum)[:_MAX_KEY]


def is_isolated(rut: str | None) -> bool:
    return bool(rut) and str(rut).startswith(ISOLATED_PREFIX)


def is_valid_rut(value: Any) -> bool:
    """True solo si el valor tiene forma de RUT, cuerpo de 6 a 9 digitos y verificador correcto."""
    if value is None or is_isolated(str(value)):
        return False
    shape = _RUT_SHAPE.fullmatch(_compact(value))
    if not shape:
        return False
    body, dv = shape.groups()
    body = body.lstrip("0")
    return 6 <= len(body) <= 9 and check_digit(body) == dv


def identity_rut(value: Any) -> str | None:
    """El valor tal cual si es un RUT valido (sirve como senal de identidad); None si no."""
    return value if is_valid_rut(value) else None
