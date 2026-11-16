"""Rate limit general de la API (CRM-16D) como middleware ASGI propio, sin dependencias nuevas.

- Solo rutas `/api/...`; el frontend estatico y los prefijos de `API_RATE_LIMIT_EXEMPT_PATHS` (por defecto `/health`
  y `/api/v1/health`) no cuentan.
- Webhooks (`/api/v1/webhooks/...`): un contador por IP de origen para todas las rutas de webhooks juntas
  (`API_RATE_LIMIT_WEBHOOK_IP_PER_MINUTE`). Se suma al limite por (ruta, IP) que ya aplica cada receptor.
- Resto: un contador por IP (`API_RATE_LIMIT_IP_PER_MINUTE`) y, si la cookie de sesion trae un JWT valido, otro por
  usuario (`API_RATE_LIMIT_USER_PER_MINUTE`). El usuario se toma del `sub` del JWT sin ir a la base.
- Al superar un limite: 429 con `Retry-After` (segundos hasta que se abre la ventana) y `detail` {code, message}.
"""

from __future__ import annotations

import json
from http.cookies import CookieError, SimpleCookie

from app.core.config import settings
from app.core.rate_limit import api_limiter, client_ip_from
from app.core.security import ACCESS_COOKIE, token_subject

WEBHOOK_PREFIX = "/api/v1/webhooks/"
RATE_LIMITED_MESSAGE = "Demasiadas solicitudes. Espera un momento e inténtalo de nuevo."


def _exempt(path: str) -> bool:
    for raw in settings.api_rate_limit_exempt_paths.split(","):
        prefix = raw.strip().rstrip("/")
        if prefix and (path == prefix or path.startswith(prefix + "/")):
            return True
    return False


def _header(scope: dict, name: bytes) -> str | None:
    for key, value in scope.get("headers") or ():
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _session_subject(scope: dict) -> str | None:
    raw = _header(scope, b"cookie")
    if not raw:
        return None
    try:
        jar = SimpleCookie()
        jar.load(raw)
    except CookieError:
        return None
    morsel = jar.get(ACCESS_COOKIE)
    return token_subject(morsel.value) if morsel is not None else None


def rate_limit_checks(scope: dict) -> list[tuple[tuple[str, str], int]]:
    """Claves y limites que aplican a la solicitud (vacio = no se limita)."""
    path = scope.get("path") or ""
    if not path.startswith("/api/") or _exempt(path):
        return []
    client = scope.get("client")
    ip = client_ip_from(client[0] if client else None, _header(scope, b"x-forwarded-for"))
    if path.startswith(WEBHOOK_PREFIX):
        return [(("webhook-ip", ip), settings.api_rate_limit_webhook_ip_per_minute)]
    checks = [(("ip", ip), settings.api_rate_limit_ip_per_minute)]
    subject = _session_subject(scope)
    if subject:
        checks.append((("user", subject), settings.api_rate_limit_user_per_minute))
    return checks


class ApiRateLimitMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not settings.api_rate_limit_enabled:
            await self.app(scope, receive, send)
            return
        for key, limit in rate_limit_checks(scope):
            retry_after = api_limiter.hit(key, limit)
            if retry_after:
                await _send_429(send, retry_after)
                return
        await self.app(scope, receive, send)


async def _send_429(send, retry_after: int) -> None:
    body = json.dumps({"detail": {"code": "rate_limited", "message": RATE_LIMITED_MESSAGE}}, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"retry-after", str(retry_after).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
