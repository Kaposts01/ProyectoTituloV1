"""AUTH-04: piezas del inicio de sesion con Google (OpenID Connect, flujo de codigo con PKCE).

Todo lo de red y de criptografia vive aqui para que las rutas queden delgadas y las pruebas lo sustituyan sin red real.
Nada de lo que se registre incluye el correo, el codigo, el token ni el `client_secret`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientError

from app.core.config import settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ["https://accounts.google.com", "accounts.google.com"]
TX_COOKIE_BASE = "crm_oauth_tx"
TX_COOKIE_PATH = "/api/v1/auth/google"
TX_TTL_SECONDS = 600
HTTP_TIMEOUT_SECONDS = 10.0
CLOCK_LEEWAY_SECONDS = 30


class GoogleLoginError(Exception):
    """Fallo del flujo. `reason` es un codigo corto para la bitacora; nunca se muestra al usuario."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Transaction:
    state: str
    nonce: str
    verifier: str


def tx_cookie_name() -> str:
    """Produccion y sandbox comparten host (127.0.0.1) con puertos distintos: la cookie lleva sufijo por ambiente."""
    mode = settings.env_mode
    return TX_COOKIE_BASE if mode == "production" else f"{TX_COOKIE_BASE}_{mode}"


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def new_transaction() -> Transaction:
    return Transaction(state=token_urlsafe(32), nonce=token_urlsafe(32), verifier=token_urlsafe(64))


def encode_transaction(tx: Transaction) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "typ": "oauth_tx",
            "st": tx.state,
            "nc": tx.nonce,
            "cv": tx.verifier,
            "iat": now,
            "exp": now + timedelta(seconds=TX_TTL_SECONDS),
        },
        settings.auth_jwt_secret,
        algorithm="HS256",
    )


def decode_transaction(value: str | None) -> Transaction:
    if not value:
        raise GoogleLoginError("no_tx_cookie")
    try:
        payload = jwt.decode(value, settings.auth_jwt_secret, algorithms=["HS256"], options={"require": ["exp", "iat"]})
    except InvalidTokenError as exc:
        raise GoogleLoginError("bad_tx_cookie") from exc
    if payload.get("typ") != "oauth_tx" or not all(isinstance(payload.get(k), str) for k in ("st", "nc", "cv")):
        raise GoogleLoginError("bad_tx_cookie")
    return Transaction(state=payload["st"], nonce=payload["nc"], verifier=payload["cv"])


def authorization_url(tx: Transaction) -> str:
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": "openid email",
        "state": tx.state,
        "nonce": tx.nonce,
        "code_challenge": pkce_challenge(tx.verifier),
        "code_challenge_method": "S256",
        "hd": settings.google_oauth_allowed_domain.strip().lower(),  # solo ayuda de interfaz; se verifica en el token
        "prompt": "select_account",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def state_matches(expected: str, received: str | None) -> bool:
    return bool(received) and hmac.compare_digest(expected.encode("utf-8"), received.encode("utf-8"))


def exchange_code(code: str, verifier: str) -> str:
    """Cambia el codigo por tokens y devuelve el `id_token`. Falla cerrado ante cualquier problema de red o respuesta."""
    try:
        response = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "redirect_uri": settings.google_oauth_redirect_uri,
            },
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise GoogleLoginError("token_endpoint_unreachable") from exc
    if response.status_code != 200:
        raise GoogleLoginError("token_exchange_rejected")
    try:
        id_token = response.json().get("id_token")
    except ValueError as exc:
        raise GoogleLoginError("token_response_invalid") from exc
    if not isinstance(id_token, str) or not id_token:
        raise GoogleLoginError("token_response_invalid")
    return id_token


_jwks_client: PyJWKClient | None = None


def signing_key(id_token: str):
    """Clave publica de Google que firmo el token (PyJWKClient con cache). Se sustituye en las pruebas."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(JWKS_URL, cache_keys=True, timeout=HTTP_TIMEOUT_SECONDS)
    return _jwks_client.get_signing_key_from_jwt(id_token).key


def verify_id_token(id_token: str, nonce: str) -> str:
    """Valida el `id_token` y devuelve el correo (en minusculas). RS256 fijo; cualquier desvio es GoogleLoginError."""
    try:
        key = signing_key(id_token)
    except (PyJWKClientError, InvalidTokenError, OSError) as exc:
        raise GoogleLoginError("jwks_unavailable_or_unknown_key") from exc
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=settings.google_oauth_client_id,
            issuer=ISSUERS,
            leeway=CLOCK_LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except InvalidTokenError as exc:
        raise GoogleLoginError(f"id_token_{type(exc).__name__}") from exc
    token_nonce = claims.get("nonce")
    if not isinstance(token_nonce, str) or not hmac.compare_digest(token_nonce.encode("utf-8"), nonce.encode("utf-8")):
        raise GoogleLoginError("nonce_mismatch")
    if claims.get("email_verified") is not True:
        raise GoogleLoginError("email_not_verified")
    domain = settings.google_oauth_allowed_domain.strip().lower()
    hosted = claims.get("hd")
    if not isinstance(hosted, str) or hosted.strip().lower() != domain:
        raise GoogleLoginError("hd_mismatch")
    email = claims.get("email")
    if not isinstance(email, str) or not email.strip():
        raise GoogleLoginError("email_missing")
    email = email.strip().lower()
    if not email.endswith(f"@{domain}") or email.count("@") != 1:
        raise GoogleLoginError("email_domain_mismatch")
    return email
