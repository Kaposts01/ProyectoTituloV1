"""Errores de configuracion de canales: deterministas, no se reintentan y nunca incluyen valores."""

import re

CONFIG_ERROR_PREFIX = "Configuracion incompleta"


class ChannelConfigError(RuntimeError):
    """Canal sin las variables de entorno necesarias (credencial o URL vacia).

    Hereda de RuntimeError por compatibilidad. El mensaje siempre empieza por
    ``CONFIG_ERROR_PREFIX`` para que el reintento diario lo reconozca leyendo ``sync_runs``.
    """

    def __init__(self, detail: str, missing: tuple[str, ...] = ()) -> None:
        names = f" (faltan: {', '.join(missing)})" if missing else ""
        super().__init__(f"{CONFIG_ERROR_PREFIX}: {detail}{names}")
        self.missing = missing


# SYNC-D-08 / d139a: fallos de configuracion o credencial (deterministas). Se reconocen por el texto ya saneado de
# `sync_runs.error_message`; solo se usa para clasificar (nunca se copia el texto a una alerta ni a un log).
_CONFIG_OR_CREDENTIAL_MARKERS = (
    CONFIG_ERROR_PREFIX.lower(),
    "not configured",
    "no configurad",
    "illegal header value",
    "bearer '",
    'bearer "',
    "unauthorized",
    "forbidden",
    "invalid api key",
    "invalid token",
)
# 401/403 solo en contexto HTTP («HTTP 401», «status 403», «error 401»): un «401 registros» no cuenta.
_HTTP_AUTH_STATUS = re.compile(r"(?:http|status|error|code|c[oó]digo)\D{0,12}(?<!\d)(?:401|403)(?!\d)")


def is_config_or_credential_error(message: str | None) -> bool:
    """True si el error es de configuracion o credencial: variable vacia, «not configured», 401/403 o Bearer vacio."""
    if not message:
        return False
    text = message.lower()
    if any(marker in text for marker in _CONFIG_OR_CREDENTIAL_MARKERS):
        return True
    return _HTTP_AUTH_STATUS.search(text) is not None
