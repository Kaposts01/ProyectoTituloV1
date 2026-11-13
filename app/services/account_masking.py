"""Enmascarado del numero de cuenta bancaria al LEER (d199, R1 del inventario SEC-01).

`tch_suscripciones.numero_cuenta` guarda la cuenta bancaria del mandato TCH en claro y la base no se cambia (sin
migraciones). Ademas, el saneador de payloads (`payload_sanitization`) normaliza las claves sin plegar tildes, asi que
un encabezado del Excel como «Número Cuenta» (-> `n_mero_cuenta`) no se quitaba y la cuenta podia quedar en
`tch_suscripciones.raw_payload` y en su copia consolidada (`subscriptions.raw_payload`, fuente `tch`).

Regla: ninguna vista, respuesta de la API ni exportacion muestra la cuenta completa; a lo mas los ultimos 4 digitos
(`••••1234`). No existe un permiso para verla completa, asi que no hay excepcion.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

MASK = "••••"
_KEYS = {"account_number", "bank_account_number", "accountnumber", "numero_cuenta", "numerocuenta", "cuenta_bancaria",
         "numero_cuenta_bancaria", "nro_cuenta", "num_cuenta", "n_cuenta", "no_cuenta", "numero_de_cuenta", "n_de_cuenta"}
_NUMBER_TOKENS = {"numero", "num", "nro", "n", "no", "nr"}


def _norm_key(key: str) -> str:
    folded = unicodedata.normalize("NFKD", key).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", folded.lower()).strip("_")


def is_account_number_key(key: Any) -> bool:
    """¿La clave nombra un numero de cuenta bancaria? (`Número Cuenta`, `N° Cuenta`, `numero_cuenta`, ...).

    `tipo_cuenta`, `cuenta` (cuenta VirtualPOS 1/2) y similares NO cuentan: solo con un token de numero o en ingles."""
    norm = _norm_key(str(key))
    if norm in _KEYS:
        return True
    tokens = norm.split("_")
    return "cuenta" in tokens and bool(_NUMBER_TOKENS & set(tokens)) and "tipo" not in tokens


def mask_account_number(value: Any) -> str | None:
    """Ultimos 4 digitos con prefijo `••••`; None si no hay valor. Nunca devuelve mas de 4 digitos."""
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if not digits and not str(value).strip():
        return None
    return MASK + digits[-4:] if len(digits) > 4 else MASK


def mask_account_fields(value: Any) -> Any:
    """Copia de `value` (dict/list anidados) con toda clave de numero de cuenta enmascarada a los ultimos 4 digitos."""
    if isinstance(value, dict):
        return {
            key: mask_account_number(nested) if is_account_number_key(key) and not isinstance(nested, (dict, list))
            else mask_account_fields(nested)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [mask_account_fields(item) for item in value]
    return value
