"""Remove payment credentials before any provider payload reaches central storage.

Las claves se normalizan antes de comparar (d212): se pliegan tildes y diacriticos (`Número Cuenta` ->
`numero_cuenta`), se pasan a minusculas y espacios, guiones, guiones bajos y otros separadores son equivalentes. Ademas
se compara la forma compacta sin separadores, asi `NumeroCuenta`, `numero-cuenta` y `numerocuenta` caen igual.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

_SENSITIVE = {
    "account_number", "api_key", "authorization", "auth_code", "bank_account_number", "bin", "card_number", "card_pan",
    "card_token", "cavv", "cvc", "cvv", "mac", "pan", "password",
    "private_token", "secret", "secret_key", "security_code", "sign",
    "numero_cuenta", "signature", "token", "verification_key",
    # d212: variantes del numero de cuenta bancaria de los informes TCH (mismo dato que `numero_cuenta`).
    "numero_de_cuenta", "nro_cuenta", "num_cuenta", "n_cuenta", "no_cuenta", "cuenta_bancaria",
    "numero_cuenta_bancaria",
}
_SENSITIVE_COMPACT = {key.replace("_", "") for key in _SENSITIVE}


def _key(value: str) -> str:
    """Clave normalizada: sin tildes, minusculas, cualquier separador -> `_`."""
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", folded.lower()).strip("_")


def is_sensitive_key(key: Any) -> bool:
    """¿La clave nombra una credencial de pago o un numero de cuenta? (tolerante a tildes, mayusculas y separadores)."""
    norm = _key(str(key))
    return norm in _SENSITIVE or norm.replace("_", "") in _SENSITIVE_COMPACT


def sanitize_payload(value: Any) -> Any:
    """Recursively retain useful provider data without payment credentials."""
    if isinstance(value, dict):
        return {
            key: sanitize_payload(nested)
            for key, nested in value.items()
            if not is_sensitive_key(key)
        }
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    return value
