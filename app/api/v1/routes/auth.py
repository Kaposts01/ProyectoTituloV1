from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.security import (
    ACCESS_COOKIE,
    create_access_token,
    get_csrf_token,
    get_current_user,
    get_db,
    require_csrf,
    verify_password,
)
from app.models.auth import Role, User
from app.services.rbac import serialize_user

router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=1, max_length=256)


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
