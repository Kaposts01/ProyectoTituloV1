from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.auth_audit import log_auth_event
from app.core.config import settings
from app.core.password_policy import PasswordPolicyError, validate_new_password
from app.core.rate_limit import client_ip_from, login_throttle, username_ref
from app.core.security import (
    burn_password_check,
    clear_session_cookie,
    create_access_token,
    get_csrf_token,
    get_current_user,
    get_db,
    hash_password,
    require_csrf,
    revoke_sessions,
    set_session_cookie,
    verify_password,
)
from app.models.auth import Role, User
from app.services.rbac import serialize_user

router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class ProfileUpdate(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_username: str | None = Field(default=None, min_length=3, max_length=100)
    new_password: str | None = Field(default=None, min_length=1, max_length=256)  # politica en validate_new_password
    confirm_password: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def check_passwords_match(self) -> "ProfileUpdate":
        if self.new_password is not None and self.new_password != self.confirm_password:
            raise ValueError("Las contraseñas no coinciden")
        return self


def _login_user(db: Session, username: str) -> User | None:
    return db.scalar(
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.username == username)
    )


# Mensajes genericos: no revelan si el usuario existe ni si esta bloqueado por usuario o por IP.
INVALID_CREDENTIALS = "Invalid username or password"
TOO_MANY_ATTEMPTS = "Demasiados intentos de inicio de sesión. Espera unos minutos e inténtalo de nuevo."


def _request_ip(request: Request) -> str:
    return client_ip_from(request.client.host if request.client else None, request.headers.get("x-forwarded-for"))


@router.post("/login", tags=["Authentication"])
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:  # noqa: B008
    ip = _request_ip(request)
    user_key = ("user", username_ref(body.username))
    ip_key = ("ip", ip)
    retry_after = login_throttle.retry_after([user_key, ip_key])
    if retry_after:
        log_auth_event("login_blocked", ip=ip, username=body.username)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=TOO_MANY_ATTEMPTS, headers={"Retry-After": str(retry_after)}
        )

    user = _login_user(db, body.username)
    if user is None or not user.is_active:
        burn_password_check(body.password)  # mismo costo que una clave real: el tiempo no delata al usuario
        valid = False
    else:
        valid = verify_password(body.password, user.password_hash)
    if not valid:
        locked = login_throttle.register_failure(user_key, settings.auth_login_max_failures_per_user)
        locked = login_throttle.register_failure(ip_key, settings.auth_login_max_failures_per_ip) or locked
        reason = "unknown_or_inactive" if user is None or not user.is_active else "bad_password"
        log_auth_event("login_failed", ip=ip, username=body.username, detail=reason)
        if locked:
            log_auth_event("login_lockout", ip=ip, username=body.username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS)

    try:
        access_token, csrf_token = create_access_token(user)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Authentication is not configured") from exc
    login_throttle.clear(user_key)
    set_session_cookie(response, access_token)
    log_auth_event("login_success", ip=ip, user_id=user.id)
    return {"user": serialize_user(user), "csrf_token": csrf_token}


@router.post("/logout", tags=["Authentication"])
def logout(
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
    __: Annotated[None, Depends(require_csrf)],
    db: Session = Depends(get_db),  # noqa: B008
) -> dict:
    # Invalida el token en el servidor (y las otras sesiones del mismo usuario), no solo la cookie del navegador.
    user = db.get(User, current_user.id)
    if user is not None:
        revoke_sessions(user)
        db.commit()
    clear_session_cookie(response)
    log_auth_event("logout", ip=_request_ip(request), user_id=current_user.id)
    return {"status": "ok"}


@router.get("/me", tags=["Authentication"])
def me(
    current_user: Annotated[User, Depends(get_current_user)],
    csrf_token: Annotated[str, Depends(get_csrf_token)],
) -> dict:
    return {"user": serialize_user(current_user), "csrf_token": csrf_token}


@router.patch("/me", tags=["Authentication"])
def update_profile(
    body: ProfileUpdate,
    request: Request,
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
    _: Annotated[None, Depends(require_csrf)],
    db: Session = Depends(get_db),  # noqa: B008
) -> dict:
    ip = _request_ip(request)
    user_key = ("user", username_ref(current_user.username))
    retry_after = login_throttle.retry_after([user_key])
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=TOO_MANY_ATTEMPTS, headers={"Retry-After": str(retry_after)}
        )
    if not verify_password(body.current_password, current_user.password_hash):
        # Cuenta como fallo de login: adivinar la clave actual con una sesion robada tambien se frena.
        login_throttle.register_failure(user_key, settings.auth_login_max_failures_per_user)
        log_auth_event("password_change_failed", ip=ip, user_id=current_user.id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Contraseña actual incorrecta")

    if body.new_username is not None and body.new_username != current_user.username:
        existing = db.scalar(select(User).where(User.username == body.new_username))
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El nombre de usuario ya está en uso")
        current_user.username = body.new_username

    if body.new_password is not None:
        try:
            validate_new_password(body.new_password, body.new_username or current_user.username)
        except PasswordPolicyError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        current_user.password_hash = hash_password(body.new_password)
        revoke_sessions(current_user)  # las otras sesiones abiertas quedan invalidas

    db.commit()
    db.refresh(current_user)
    result: dict = {"user": serialize_user(current_user)}
    if body.new_password is not None:
        # Esta sesion sigue: nueva cookie con la version vigente y nuevo token CSRF.
        access_token, csrf_token = create_access_token(current_user)
        set_session_cookie(response, access_token)
        result["csrf_token"] = csrf_token
        log_auth_event("password_changed", ip=ip, user_id=current_user.id)
    return result
