from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.auth_audit import log_auth_event
from app.core.config import settings
from app.core.password_policy import PasswordPolicyError, validate_new_password
from app.core.rate_limit import client_ip_from, login_throttle, username_ref
from app.core.security import (
    burn_password_check,
    clear_session_cookie,
    cookie_samesite,
    cookie_secure,
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
from app.services import google_oauth
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


GOOGLE_LOGIN_ERROR_URL = "/?login_error=google"


def _require_google_enabled() -> None:
    if not settings.google_login_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


def _tx_cookie_kwargs() -> dict:
    return {"path": google_oauth.TX_COOKIE_PATH, "httponly": True, "secure": cookie_secure(), "samesite": cookie_samesite()}


@router.get("/google/start", tags=["Authentication"], include_in_schema=False)
def google_start() -> RedirectResponse:
    """AUTH-04: genera state, nonce y PKCE, los guarda en una cookie temporal firmada y redirige a Google."""
    _require_google_enabled()
    if len(settings.auth_jwt_secret) < 32:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    tx = google_oauth.new_transaction()
    response = RedirectResponse(google_oauth.authorization_url(tx), status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=google_oauth.tx_cookie_name(),
        value=google_oauth.encode_transaction(tx),
        max_age=google_oauth.TX_TTL_SECONDS,
        **_tx_cookie_kwargs(),
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _google_failure(ip: str, reason: str, *, count: bool = False) -> RedirectResponse:
    # M1: solo cuentan los fallos con una transaccion valida (state ya comprobado) y con clave propia, para que
    # un GET anonimo al callback no pueda bloquear el login con contrasena de la IP compartida.
    if count:
        login_throttle.register_failure(("google_ip", ip), settings.auth_login_max_failures_per_ip)
    log_auth_event("google_login_failed", ip=ip, detail=reason)
    return _google_redirect(GOOGLE_LOGIN_ERROR_URL)


def _google_redirect(url: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(google_oauth.tx_cookie_name(), **_tx_cookie_kwargs())  # un solo uso
    return response


@router.get("/google/callback", tags=["Authentication"], include_in_schema=False)
def google_callback(
    request: Request,
    db: Session = Depends(get_db),  # noqa: B008
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """AUTH-04: verifica state, intercambia el codigo, valida el id_token y abre la misma sesion que /login.

    Todo fallo redirige a `/?login_error=google` sin detalle; el motivo va solo a la bitacora (sin correo ni token).
    """
    _require_google_enabled()
    ip = _request_ip(request)
    retry_after = login_throttle.retry_after([("google_ip", ip)])
    if retry_after:
        log_auth_event("login_blocked", ip=ip)
        return _google_redirect(GOOGLE_LOGIN_ERROR_URL)
    try:
        tx = google_oauth.decode_transaction(request.cookies.get(google_oauth.tx_cookie_name()))
        if error:
            raise google_oauth.GoogleLoginError("google_returned_error")
        if not google_oauth.state_matches(tx.state, state):
            raise google_oauth.GoogleLoginError("state_mismatch")
    except google_oauth.GoogleLoginError as exc:
        return _google_failure(ip, exc.reason)  # sin transaccion valida: solo bitacora
    try:
        if not code:
            raise google_oauth.GoogleLoginError("code_missing")
        email = google_oauth.verify_id_token(google_oauth.exchange_code(code, tx.verifier), tx.nonce)
    except google_oauth.GoogleLoginError as exc:
        return _google_failure(ip, exc.reason, count=True)

    user = db.scalar(
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(func.lower(User.google_email) == email)
    )
    if user is None or not user.is_active:
        return _google_failure(ip, "unknown_or_inactive", count=True)  # mismo resultado para no registrado e inactivo
    try:
        access_token, _csrf = create_access_token(user)
    except RuntimeError:
        return _google_failure(ip, "auth_not_configured", count=True)
    response = _google_redirect("/")
    set_session_cookie(response, access_token)
    log_auth_event("google_login_success", ip=ip, user_id=user.id)
    return response


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
