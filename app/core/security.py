from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, HTTPException, Request, status
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.auth import User
from app.services.rbac import get_user, permission_codes

ACCESS_COOKIE = "crm_access_token"
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


def create_access_token(user: User) -> tuple[str, str]:
    if len(settings.auth_jwt_secret) < 32:
        raise RuntimeError("AUTH_JWT_SECRET must contain at least 32 characters")
    csrf_token = token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.auth_access_token_minutes)
    token = jwt.encode(
        {"sub": str(user.id), "csrf": csrf_token, "exp": expires_at},
        settings.auth_jwt_secret,
        algorithm="HS256",
    )
    return token, csrf_token


def _decode_token(token: str) -> dict:
    if len(settings.auth_jwt_secret) < 32:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    try:
        return jwt.decode(token, settings.auth_jwt_secret, algorithms=["HS256"])
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        ) from exc


def get_current_user(
    access_token: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None,
    db: Session = Depends(get_db),  # noqa: B008
) -> User:
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    payload = _decode_token(access_token)
    user_id = payload.get("sub")
    user = get_user(db, user_id) if isinstance(user_id, str) else None
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user


def get_csrf_token(access_token: Annotated[str | None, Cookie(alias=ACCESS_COOKIE)] = None) -> str:
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    csrf_token = _decode_token(access_token).get("csrf")
    if not isinstance(csrf_token, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    return csrf_token


def require_csrf(request: Request, csrf_token: Annotated[str, Depends(get_csrf_token)]) -> None:
    if request.headers.get(CSRF_HEADER) != csrf_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


def require_permissions(*required: str):
    def dependency(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if not set(required).issubset(permission_codes(current_user)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
        return current_user

    return dependency


def require_any_permission(*required: str):
    def dependency(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if not set(required).intersection(permission_codes(current_user)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")
        return current_user

    return dependency
