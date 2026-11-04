"""Filtro de logs: oculta el token `?k=` de Payku (y similares) en el access log de uvicorn (RT-08).

Payku autentica con `?k=<secreto>` en la URL; uvicorn imprime la ruta completa en cada peticion, lo que filtraria el
token al log. El filtro reemplaza el valor por `[redacted]` en los argumentos del registro.
"""

from __future__ import annotations

import logging
import re

_TOKEN_RE = re.compile(r"([?&](?:k|token|key|secret)=)[^&\s\"']+", re.IGNORECASE)


def redact_query_secrets(text: str) -> str:
    return _TOKEN_RE.sub(r"\1[redacted]", text)


class RedactQuerySecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(redact_query_secrets(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: redact_query_secrets(v) if isinstance(v, str) else v for k, v in record.args.items()}
        if isinstance(record.msg, str):
            record.msg = redact_query_secrets(record.msg)
        return True


def install_access_log_redaction() -> None:
    """Idempotente: agrega el filtro a los loggers de acceso de uvicorn."""
    for name in ("uvicorn.access", "uvicorn.error", "uvicorn"):
        target = logging.getLogger(name)
        if not any(isinstance(f, RedactQuerySecretsFilter) for f in target.filters):
            target.addFilter(RedactQuerySecretsFilter())
