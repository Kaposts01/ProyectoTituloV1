"""CRM-16C: la sesion se verifica ANTES de leer el cuerpo de la peticion.

FastAPI lee y decodifica el cuerpo (JSON o multipart) antes de resolver las dependencias de la ruta. Sin este guardia,
una peticion SIN sesion a una ruta protegida recibia 422 (JSON invalido) en vez de 401, y un multipart se volcaba
completo a disco (SpooledTemporaryFile de Starlette, sin tope) antes de que `get_current_user` lo rechazara.

Este middleware ASGI corta con 401 cualquier peticion a `/api/v1/...` que no sea publica y no traiga una cookie de
sesion con un JWT valido (firma y expiracion), sin tocar el cuerpo ni la base. La verificacion completa (usuario
activo, permisos, CSRF) sigue en las dependencias de cada ruta; esto es solo la primera barrera.

Rutas publicas (excepciones explicitas, ver `tests/test_authz_route_matrix.py`):
  - POST /api/v1/auth/login: inicio de sesion.
  - GET  /api/v1/system/environment: ambiente y canales, la pantalla de login lo necesita sin sesion.
  - /api/v1/health/...: latido para el monitor externo, sin datos personales (d139c).
  - /api/v1/webhooks/...: receptores de proveedores, autenticados por firma HMAC (Toku, payout VirtualPOS) o token
    secreto (Payku) dentro de la propia ruta.

Se apaga con AUTH_SESSION_FIRST_ENABLED=false (vuelta atras sin desplegar codigo).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, MutableMapping
from http.cookies import CookieError, SimpleCookie
from typing import Any

import jwt
from jwt.exceptions import InvalidTokenError

from app.core.config import settings
from app.core.security import ACCESS_COOKIE, get_current_user

API_PREFIX = "/api/v1/"
PUBLIC_API_PATHS: frozenset[str] = frozenset({"/api/v1/auth/login", "/api/v1/system/environment"})
PUBLIC_API_PREFIXES: tuple[str, ...] = ("/api/v1/health/", "/api/v1/webhooks/")

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_MISSING = {"code": "authentication_required", "message": "Debes iniciar sesión para continuar."}
_INVALID = {"code": "invalid_or_expired_session", "message": "Sesión inválida o expirada. Vuelve a iniciar sesión."}


def is_public_api_path(path: str) -> bool:
    return path in PUBLIC_API_PATHS or path.startswith(PUBLIC_API_PREFIXES)


def _session_cookie(scope: Scope) -> str | None:
    raw = b"; ".join(value for name, value in scope.get("headers", []) if name == b"cookie")
    if not raw:
        return None
    jar = SimpleCookie()
    try:
        jar.load(raw.decode("latin-1"))
    except CookieError:
        return None
    morsel = jar.get(ACCESS_COOKIE)
    return morsel.value if morsel is not None and morsel.value else None


def _token_rejection(token: str | None) -> dict[str, str] | None:
    """None si el token pasa la primera barrera; si no, el detalle del 401."""
    if not token:
        return _MISSING
    secret = settings.auth_jwt_secret
    if len(secret) < 32:
        return None  # sin llave configurada la dependencia responde 503 authentication_not_configured
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except InvalidTokenError:
        return _INVALID
    return None if isinstance(payload.get("sub"), str) else _INVALID


class SessionFirstMiddleware:
    def __init__(self, app: ASGIApp, overrides_provider: Any = None) -> None:
        self.app = app
        self.overrides_provider = overrides_provider

    def _auth_overridden(self) -> bool:
        # Solo los tests sobreescriben get_current_user; en ese caso decide la dependencia sobreescrita.
        overrides = getattr(self.overrides_provider, "dependency_overrides", None) or {}
        return get_current_user in overrides

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or not settings.auth_session_first_enabled
            or not scope.get("path", "").startswith(API_PREFIX)
            or is_public_api_path(scope["path"])
            or self._auth_overridden()
        ):
            await self.app(scope, receive, send)
            return
        rejection = _token_rejection(_session_cookie(scope))
        if rejection is None:
            await self.app(scope, receive, send)
            return
        body = json.dumps({"detail": rejection}, ensure_ascii=False).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
