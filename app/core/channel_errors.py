"""Errores de configuracion de canales: deterministas, no se reintentan y nunca incluyen valores."""

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
