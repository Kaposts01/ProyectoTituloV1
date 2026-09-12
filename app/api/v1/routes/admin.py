import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.security import (
    get_db,
    hash_password,
    require_any_permission,
    require_csrf,
    require_permissions,
)
from app.models.auth import Permission, Role, User
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


class UserUpdate(BaseModel):
    is_active: bool | None = None
    role_ids: set[uuid.UUID] | None = Field(default=None, min_length=1)


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
    role.name = body.name
    role.description = body.description
    role.permissions = _permissions(db, body.permission_codes)
    db.commit()
    return {"id": str(role.id), "name": role.name}


@router.get("/users", dependencies=[Depends(require_permissions("users.manage"))], tags=["Administration"])
def list_users(db: Session = Depends(get_db)) -> list[dict]:  # noqa: B008
    users = db.scalars(select(User).options(selectinload(User.roles).selectinload(Role.permissions)).order_by(User.username)).all()
    return [serialize_user(user) for user in users]


@router.post("/users", dependencies=[Depends(require_permissions("users.manage")), Depends(require_csrf)], tags=["Administration"])
def create_user(body: UserInput, db: Session = Depends(get_db)) -> dict:  # noqa: B008
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status_code=409, detail="Username already exists")
    user = User(username=body.username, password_hash=hash_password(body.password), roles=_roles(db, body.role_ids))
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": str(user.id), "username": user.username}


@router.put("/users/{user_id}", dependencies=[Depends(require_permissions("users.manage")), Depends(require_csrf)], tags=["Administration"])
def update_user(user_id: uuid.UUID, body: UserUpdate, db: Session = Depends(get_db)) -> dict:  # noqa: B008
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.role_ids is not None:
        user.roles = _roles(db, body.role_ids)
    db.commit()
    return {"id": str(user.id), "username": user.username, "is_active": user.is_active}
