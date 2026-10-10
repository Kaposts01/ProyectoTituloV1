import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Permission, Role, User
from app.services.rbac import seed_permissions


def test_admin_can_manage_users_roles_and_passwords(monkeypatch) -> None:
    suffix = uuid.uuid4().hex[:12]
    manager_username = f"manager-{suffix}"
    member_username = f"member-{suffix}"
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")

    db = SessionLocal()
    try:
        seed_permissions(db)
        permissions = db.scalars(
            select(Permission).where(Permission.code.in_({"users.manage", "roles.manage"}))
        ).all()
        manager_role = Role(name=f"manager-{suffix}", permissions=permissions)
        db.add_all([
            manager_role,
            User(
                username=manager_username,
                password_hash=hash_password("manager-password"),
                roles=[manager_role],
            ),
        ])
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    login = client.post(
        "/api/v1/auth/login",
        json={"username": manager_username, "password": "manager-password"},
    )
    assert login.status_code == 200
    csrf_token = login.json()["csrf_token"]
    headers = {"X-CSRF-Token": csrf_token}

    role = client.post(
        "/api/v1/admin/roles",
        headers=headers,
        json={
            "name": f"viewer-{suffix}",
            "description": "Test role",
            "permission_codes": ["dashboard.view"],
        },
    )
    assert role.status_code == 200
    role_id = role.json()["id"]

    user = client.post(
        "/api/v1/admin/users",
        headers=headers,
        json={"username": member_username, "password": "member-password", "role_ids": [role_id]},
    )
    assert user.status_code == 200
    user_id = user.json()["id"]

    reset = client.patch(
        f"/api/v1/admin/users/{user_id}/password",
        headers=headers,
        json={"new_password": "changed-password"},
    )
    assert reset.status_code == 200

    member_client = TestClient(app)
    assert member_client.post(
        "/api/v1/auth/login",
        json={"username": member_username, "password": "changed-password"},
    ).status_code == 200

    assert client.delete(f"/api/v1/admin/roles/{role_id}", headers=headers).status_code == 409
    assert client.put(
        f"/api/v1/admin/users/{user_id}",
        headers=headers,
        json={"is_active": False},
    ).status_code == 200
    assert TestClient(app).post(
        "/api/v1/auth/login",
        json={"username": member_username, "password": "changed-password"},
    ).status_code == 401
