"""Reintentos de lectura HTTP comunes a los clientes de proveedores (SYNC-D-10).

Solo para peticiones IDEMPOTENTES (GET de lectura). Un GET con efectos (p. ej. `/v3/charge/{id}/retry` de VirtualPOS)
o cualquier POST/PUT/DELETE no pasa por aqui: tras un timeout el primer intento pudo ejecutarse.

Se reintenta:
- errores de red (`ReadTimeout`, `ReadError`, `ConnectError`), con backoff 2^n;
- respuestas 429 y 5xx transitorias (500, 502, 503, 504), respetando `Retry-After` (segundos o fecha HTTP) si viene.

Tope: `retries` reintentos (ademas del primer intento) y ninguna espera supera `HTTP_RETRY_MAX_DELAY_SECONDS`. Si el
proveedor pide esperar MAS que ese tope, no se reintenta (otro intento antes de tiempo solo daria otro 429): se devuelve
la respuesta tal cual y el llamador decide (normalmente `raise_for_status`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.core.config import settings

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
NETWORK_ERRORS: tuple[type[Exception], ...] = (httpx.ReadTimeout, httpx.ReadError, httpx.ConnectError)


def retry_after_seconds(response: httpx.Response, *, now: datetime | None = None) -> float | None:
    """Segundos que pide esperar el encabezado `Retry-After`; None si falta o no se entiende."""
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - (now or datetime.now(timezone.utc))).total_seconds())


def _max_delay() -> float:
    return max(0.0, float(settings.http_retry_max_delay_seconds))


async def send_with_retries(send: Callable[[], Awaitable[httpx.Response]], *, retries: int) -> httpx.Response:
    """Ejecuta `send` con hasta `retries` reintentos ante red caida, 429 o 5xx transitorio. Devuelve la ultima respuesta."""
    retries = max(0, int(retries))
    cap = _max_delay()
    for attempt in range(retries + 1):
        last = attempt == retries
        try:
            response = await send()
        except NETWORK_ERRORS:
            if last:
                raise
            await asyncio.sleep(min(2**attempt, cap))
            continue
        if last or response.status_code not in RETRYABLE_STATUS:
            return response
        wait = retry_after_seconds(response)
        if wait is None:
            wait = float(2**attempt)
        elif wait > cap:
            return response  # el proveedor pide esperar mas que el tope: no se insiste
        await asyncio.sleep(min(wait, cap))
    raise AssertionError("inalcanzable")  # pragma: no cover
