import hmac
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.auth import User
from app.services.rbac import get_user, permission_codes

_BASE_ACCESS_COOKIE = "crm_access_token"


def access_cookie_name(env_mode: str) -> str:
    """Produccion conserva el nombre historico; sandbox/qa llevan sufijo para no chocar en localhost."""
    return _BASE_ACCESS_COOKIE if env_mode == "production" else f"{_BASE_ACCESS_COOKIE}_{env_mode}"


ACCESS_COOKIE = access_cookie_name(settings.env_mode)
CSRF_HEADER = "X-CSRF-Token"
_password_hash = PasswordHash.recommended()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


_dummy_hash: str | None = None


def burn_password_check(password: str) -> None:
    """Verifica contra un hash ficticio para que un usuario inexistente o inactivo tarde lo mismo (CRM-16A)."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _password_hash.hash(token_urlsafe(24))
    _password_hash.verify(password, _dummy_hash)


def create_access_token(user: User) -> tuple[str, str]:
    if len(settings.auth_jwt_secret) < 32:
        raise RuntimeError("AUTH_JWT_SECRET must contain at least 32 characters")
    csrf_token = token_urlsafe(32)
    issued_at = datetime.now(UTC)
    expires_at = issued_at + timedelta(minutes=settings.auth_access_token_minutes)
    token = jwt.encode(
        {
            "sub": str(user.id),
            "csrf": csrf_token,
            "iat": issued_at,
            "exp": expires_at,
            "jti": token_urlsafe(16),
            "tv": int(user.token_version or 0),
        },
        settings.auth_jwt_secret,
        algorithm="HS256",
    )
    return token, csrf_token


def cookie_secure() -> bool:
    """Secure siempre en produccion; fuera de produccion solo sin DEBUG (http://localhost en desarrollo)."""
    return settings.is_production or not settings.debug


def cookie_samesite() -> str:
    value = settings.auth_cookie_samesite.strip().lower()
    return value if value in {"lax", "strict"} else "lax"


def set_session_cookie(response: Response, access_token: str) -> None:
    response.set_cookie(
        key=ACCESS_COOKIE,
        value=access_token,
        max_age=settings.auth_access_token_minutes * 60,
        httponly=True,
        secure=cookie_secure(),
        samesite=cookie_samesite(),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/", httponly=True, secure=cookie_secure(), samesite=cookie_samesite())


def revoke_sessions(user: User) -> None:
    """Invalida todas las sesiones emitidas del usuario (el llamador hace commit)."""
    user.token_version = int(user.token_version or 0) + 1


def token_subject(token: str) -> str | None:
    """`sub` de un JWT valido o None. Sin BD; lo usa el rate limit para contar por usuario."""
    if len(settings.auth_jwt_secret) < 32:
        return None
    try:
        sub = jwt.decode(token, settings.auth_jwt_secret, algorithms=["HS256"]).get("sub")
    except InvalidTokenError:
        return None
    return sub if isinstance(sub, str) else None


def _decode_token(token: str) -> dict:
    if len(settings.auth_jwt_secret) < 32:
        raise HTTPException(status_code=503, detail={"code": "authentication_not_configured", "message": "La autenticación no está configurada en este servidor."})
    try:
        return jwt.decode(token, settings.auth_jwt_secret, algorithms=["HS256"])
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_or_expired_session", "message": "Sesión inválida o expirada. Vuelve a iniciar sesión."},
        ) from exc


def get_current_user(
    access_token: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None,
    db: Session = Depends(get_db),  # noqa: B008
) -> User:
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "authentication_required", "message": "Debes iniciar sesión para continuar."})
    payload = _decode_token(access_token)
    user_id = payload.get("sub")
    user = get_user(db, user_id) if isinstance(user_id, str) else None
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "authentication_required", "message": "Debes iniciar sesión para continuar."})
    # CRM-16A: sesion revocada (logout, cambio o reseteo de clave). Tokens previos sin `tv` cuentan como version 0.
    token_version = payload.get("tv", 0)
    if not isinstance(token_version, int) or token_version != int(user.token_version or 0):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_or_expired_session", "message": "Sesión inválida o expirada. Vuelve a iniciar sesión."},
        )
    return user


def get_csrf_token(access_token: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None) -> str:
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "authentication_required", "message": "Debes iniciar sesión para continuar."})
    csrf_token = _decode_token(access_token).get("csrf")
    if not isinstance(csrf_token, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "invalid_session", "message": "Sesión inválida. Vuelve a iniciar sesión."})
    return csrf_token


def require_csrf(request: Request, csrf_token: Annotated[str, Depends(get_csrf_token)]) -> None:
    sent = request.headers.get(CSRF_HEADER) or ""
    if not hmac.compare_digest(sent.encode("utf-8"), csrf_token.encode("utf-8")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "invalid_csrf_token", "message": "Sesión desactualizada. Recarga la página e inténtalo de nuevo."})


def require_permissions(*required: str):
    def dependency(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if not set(required).issubset(permission_codes(current_user)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "permission_denied", "message": "No tienes permiso para realizar esta acción."})
        return current_user

    return dependency


def require_role(role_name: str):
    def dependency(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if not any(role.name == role_name for role in current_user.roles):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "permission_denied", "message": "No tienes permiso para realizar esta acción."})
        return current_user

    return dependency


def require_any_permission(*required: str):
    def dependency(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if not set(required).intersection(permission_codes(current_user)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "permission_denied", "message": "No tienes permiso para realizar esta acción."})
        return current_user

    return dependency
