from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.security import (
    ACCESS_COOKIE,
    create_access_token,
    get_csrf_token,
    get_current_user,
    get_db,
    hash_password,
    require_csrf,
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
    new_password: str | None = Field(default=None, min_length=6, max_length=256)
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


@router.post("/login", tags=["Authentication"])
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict:  # noqa: B008
    user = _login_user(db, body.username)
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    try:
        access_token, csrf_token = create_access_token(user)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Authentication is not configured") from exc
    response.set_cookie(
        key=ACCESS_COOKIE,
        value=access_token,
        max_age=settings.auth_access_token_minutes * 60,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        path="/",
    )
    return {"user": serialize_user(user), "csrf_token": csrf_token}


@router.post("/logout", tags=["Authentication"])
def logout(
    response: Response,
    _: Annotated[User, Depends(get_current_user)],
    __: Annotated[None, Depends(require_csrf)],
) -> dict:
    response.delete_cookie(ACCESS_COOKIE, path="/")
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
    current_user: Annotated[User, Depends(get_current_user)],
    _: Annotated[None, Depends(require_csrf)],
    db: Session = Depends(get_db),  # noqa: B008
) -> dict:
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Contraseña actual incorrecta")

    if body.new_username is not None and body.new_username != current_user.username:
        existing = db.scalar(select(User).where(User.username == body.new_username))
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El nombre de usuario ya está en uso")
        current_user.username = body.new_username

    if body.new_password is not None:
        current_user.password_hash = hash_password(body.new_password)

    db.commit()
    db.refresh(current_user)
    return {"user": serialize_user(current_user)}
