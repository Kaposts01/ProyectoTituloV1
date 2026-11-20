import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.auth_audit import log_auth_event
from app.core.config import settings
from app.core.password_policy import PasswordPolicyError, validate_new_password
from app.core.rate_limit import client_ip_from
from app.core.security import (
    get_db,
    hash_password,
    require_any_permission,
    require_csrf,
    require_permissions,
    revoke_sessions,
)
from app.models.auth import Permission, Role, User
from app.services.billing_requests import policy_effective_approvers
from app.services.rbac import PERMISSIONS, serialize_user

router = APIRouter()


class RoleInput(BaseModel):
    name: str = Field(min_length=3, max_length=100, pattern=r"^[a-z0-9_-]+$")
    description: str | None = Field(default=None, max_length=1000)
    permission_codes: set[str]


class UserInput(BaseModel):
    username: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)
    role_ids: set[uuid.UUID] = Field(min_length=1)
    google_email: str | None = Field(default=None, max_length=255)  # AUTH-04


class UserUpdate(BaseModel):
    is_active: bool | None = None
    role_ids: set[uuid.UUID] | None = Field(default=None, min_length=1)
    # AUTH-04: ausente = sin cambio; null o vacio = quitar el correo de Google.
    google_email: str | None = Field(default=None, max_length=255)


def _normalize_google_email(raw: str | None) -> str | None:
    """AUTH-04: minusculas, sin espacios y del dominio permitido (422 si no). Vacio o None = sin correo."""
    value = (raw or "").strip().lower()
    if not value:
        return None
    domain = settings.google_oauth_allowed_domain.strip().lower()
    local, _, host = value.partition("@")
    if not domain or not local or host != domain or not re.fullmatch(r"[a-z0-9._%+-]+", local):
        raise HTTPException(status_code=422, detail=f"El correo de Google debe ser de la forma usuario@{domain}")
    return value


def _ensure_google_email_free(db: Session, email: str, exclude_user_id: uuid.UUID | None = None) -> None:
    query = select(User.id).where(func.lower(User.google_email) == email)
    if exclude_user_id is not None:
        query = query.where(User.id != exclude_user_id)
    if db.scalar(query) is not None:
        raise HTTPException(status_code=409, detail="Ese correo de Google ya está asignado a otro usuario")


def _admin_ip(request: Request) -> str:
    return client_ip_from(request.client.host if request.client else None, request.headers.get("x-forwarded-for"))


def _check_password_policy(password: str, username: str) -> None:
    """CRM-16A: politica de claves nuevas (largo y lista de comunes). 422 con mensaje apto para el usuario."""
    try:
        validate_new_password(password, username)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _roles(db: Session, role_ids: set[uuid.UUID]) -> list[Role]:
    roles = db.scalars(select(Role).where(Role.id.in_(role_ids))).all()
    if len(roles) != len(role_ids):
        raise HTTPException(status_code=422, detail="Unknown role")
    return roles


def _permissions(db: Session, codes: set[str]) -> list[Permission]:
    if not codes.issubset(PERMISSIONS):
        raise HTTPException(status_code=422, detail="Unknown permission")
    permissions = db.scalars(select(Permission).where(Permission.code.in_(codes))).all()
    if len(permissions) != len(codes):
        raise HTTPException(status_code=503, detail="Permissions are not initialized")
    return permissions


def _is_active_admin(user: User, roles: list[Role] | None = None, is_active: bool | None = None) -> bool:
    assigned_roles = roles if roles is not None else user.roles
    active = user.is_active if is_active is None else is_active
    return active and any(role.name == "admin" for role in assigned_roles)



def _guard_billing_approvers(db: Session, before: set[uuid.UUID] | None) -> None:
    """Extiende la guarda del ultimo admin: tras aplicar (sin confirmar) el cambio pendiente en la sesion, la politica
    de aprobadores de cambios de cobro no puede quedar SIN aprobadores efectivos si antes tenia. 409 y rollback."""
    if not before:
        return
    db.flush()
    after = policy_effective_approvers(db)
    if after is not None and not after:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Este cambio dejaría la política de cambios de cobro VirtualPOS sin ningún aprobador efectivo "
                   "(usuario activo con el permiso 'approve'). Agregue otro aprobador a la política primero.",
        )


@router.get("/permissions", dependencies=[Depends(require_permissions("roles.manage"))], tags=["Administration"])
def list_permissions() -> list[dict[str, str]]:
    return [{"code": code, "description": description} for code, description in sorted(PERMISSIONS.items())]


@router.get("/roles", dependencies=[Depends(require_any_permission("roles.manage", "users.manage"))], tags=["Administration"])
def list_roles(db: Session = Depends(get_db)) -> list[dict]:  # noqa: B008
    roles = db.scalars(select(Role).options(selectinload(Role.permissions)).order_by(Role.name)).all()
    return [
        {
            "id": str(role.id),
            "name": role.name,
            "description": role.description,
            "permission_codes": sorted(permission.code for permission in role.permissions),
        }
        for role in roles
    ]


@router.post("/roles", dependencies=[Depends(require_permissions("roles.manage")), Depends(require_csrf)], tags=["Administration"])
def create_role(body: RoleInput, db: Session = Depends(get_db)) -> dict:  # noqa: B008
    if db.scalar(select(Role).where(Role.name == body.name)):
        raise HTTPException(status_code=409, detail="Role already exists")
    role = Role(name=body.name, description=body.description, permissions=_permissions(db, body.permission_codes))
    db.add(role)
    db.commit()
    return {"id": str(role.id), "name": role.name}


@router.put("/roles/{role_id}", dependencies=[Depends(require_permissions("roles.manage")), Depends(require_csrf)], tags=["Administration"])
def update_role(role_id: uuid.UUID, body: RoleInput, db: Session = Depends(get_db)) -> dict:  # noqa: B008
    role = db.get(Role, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.name == "admin" and body.name != "admin":
        raise HTTPException(status_code=422, detail="The admin role cannot be renamed")
    permissions = _permissions(db, body.permission_codes)
    approvers_before = policy_effective_approvers(db)
    role.name = body.name
    role.description = body.description
    role.permissions = permissions
    _guard_billing_approvers(db, approvers_before)  # quitar `approve` o renombrar un rol listado en la politica
    db.commit()
    return {"id": str(role.id), "name": role.name}


@router.get("/users", dependencies=[Depends(require_permissions("users.manage"))], tags=["Administration"])
def list_users(db: Session = Depends(get_db)) -> list[dict]:  # noqa: B008
    users = db.scalars(select(User).options(selectinload(User.roles).selectinload(Role.permissions)).order_by(User.username)).all()
    return [{**serialize_user(user), "google_email": user.google_email} for user in users]


@router.post("/users", dependencies=[Depends(require_csrf)], tags=["Administration"])
def create_user(body: UserInput, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_permissions("users.manage"))) -> dict:  # noqa: B008
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status_code=409, detail="Username already exists")
    new_roles = _roles(db, body.role_ids)
    # SEC-4: only an admin can create an admin account
    if any(role.name == "admin" for role in new_roles) and not any(role.name == "admin" for role in current_user.roles):
        raise HTTPException(status_code=403, detail="Only an admin can create an admin account")
    _check_password_policy(body.password, body.username)
    google_email = _normalize_google_email(body.google_email)
    if google_email is not None:
        _ensure_google_email_free(db, google_email)
    user = User(username=body.username, password_hash=hash_password(body.password), roles=new_roles, google_email=google_email)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ese correo de Google ya está asignado a otro usuario") from exc
    db.refresh(user)
    if google_email is not None:
        log_auth_event("google_email_set", ip=_admin_ip(request), user_id=user.id)
    return {"id": str(user.id), "username": user.username}


@router.put("/users/{user_id}", dependencies=[Depends(require_csrf)], tags=["Administration"])
def update_user(user_id: uuid.UUID, body: UserUpdate, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_permissions("users.manage"))) -> dict:  # noqa: B008
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    # SEC-2: only an admin can modify another admin account
    if _is_active_admin(user) and not any(role.name == "admin" for role in current_user.roles):
        raise HTTPException(status_code=403, detail="Only an admin can modify another admin account")
    next_roles = _roles(db, body.role_ids) if body.role_ids is not None else user.roles
    next_active = body.is_active if body.is_active is not None else user.is_active
    if _is_active_admin(user) and not _is_active_admin(user, next_roles, next_active):
        # SEC-3: lock active admin rows before counting to eliminate TOCTOU race
        admin_user_sq = select(User.id).join(User.roles).where(Role.name == "admin")
        locked_ids = db.scalars(
            select(User.id)
            .where(User.is_active.is_(True), User.id.in_(admin_user_sq))
            .with_for_update()
        ).all()
        if len(locked_ids) == 1:
            raise HTTPException(status_code=422, detail="Cannot deactivate or remove the last active admin")
    google_changed = False
    if "google_email" in body.model_fields_set:
        new_google_email = _normalize_google_email(body.google_email)
        if new_google_email is not None:
            _ensure_google_email_free(db, new_google_email, exclude_user_id=user.id)
        google_changed = new_google_email != (user.google_email or None)
    approvers_before = policy_effective_approvers(db)
    if google_changed:
        user.google_email = new_google_email
        revoke_sessions(user)  # cambiar o quitar el correo cierra las sesiones abiertas del usuario
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.role_ids is not None:
        user.roles = next_roles
    _guard_billing_approvers(db, approvers_before)  # desactivar / quitar rol al ultimo aprobador efectivo
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ese correo de Google ya está asignado a otro usuario") from exc
    if google_changed:
        log_auth_event("google_email_changed", ip=_admin_ip(request), user_id=user.id, detail="set" if user.google_email else "cleared")
    return {"id": str(user.id), "username": user.username, "is_active": user.is_active}


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=12, max_length=256)


@router.patch("/users/{user_id}/password", dependencies=[Depends(require_csrf)], tags=["Administration"])
def reset_user_password(user_id: uuid.UUID, body: PasswordReset, db: Session = Depends(get_db), current_user: User = Depends(require_permissions("users.manage"))) -> dict:  # noqa: B008
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    # SEC-1: only an admin can reset another admin's password
    if _is_active_admin(user) and not any(role.name == "admin" for role in current_user.roles):
        raise HTTPException(status_code=403, detail="Only an admin can reset another admin's password")
    _check_password_policy(body.new_password, user.username)
    user.password_hash = hash_password(body.new_password)
    revoke_sessions(user)  # CRM-16A: las sesiones abiertas del usuario reseteado dejan de valer
    db.commit()
    return {"id": str(user.id), "username": user.username}


@router.delete("/roles/{role_id}", dependencies=[Depends(require_permissions("roles.manage")), Depends(require_csrf)], tags=["Administration"])
def delete_role(role_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:  # noqa: B008
    role = db.scalar(select(Role).options(selectinload(Role.users)).where(Role.id == role_id))
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.name == "admin":
        raise HTTPException(status_code=422, detail="The admin role cannot be deleted")
    if role.users:
        raise HTTPException(status_code=409, detail="Cannot delete a role that has users assigned")
    db.delete(role)
    db.commit()
    return {"id": str(role_id), "deleted": True}
