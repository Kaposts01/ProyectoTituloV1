import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.v1.routes.admin import _is_active_admin
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Permission, Role, User
from app.services.rbac import seed_permissions


def test_active_admin_requires_active_user_with_admin_role() -> None:
    admin_role = Role(name="admin")
    user = User(username="admin-user", password_hash="unused", is_active=True, roles=[admin_role])

    assert _is_active_admin(user)
    assert not _is_active_admin(user, is_active=False)
    assert not _is_active_admin(user, roles=[Role(name="viewer")])


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


def _setup_admin_and_manager(monkeypatch, suffix: str) -> tuple[str, TestClient, dict]:
    """Create an admin user and a non-admin manager with users.manage; return admin_id, logged-in client, headers."""
    admin_username = f"adm-{suffix}"
    manager_username = f"mgr-{suffix}"
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")

    db = SessionLocal()
    try:
        seed_permissions(db)
        admin_role = db.scalar(select(Role).where(Role.name == "admin"))
        if admin_role is None:
            admin_role = Role(name="admin")
            db.add(admin_role)
            db.flush()
        manage_perms = db.scalars(select(Permission).where(Permission.code == "users.manage")).all()
        manager_role = Role(name=f"mgr-role-{suffix}", permissions=manage_perms)
        admin_user = User(username=admin_username, password_hash=hash_password("Admin-pw-12345"), is_active=True, roles=[admin_role])
        manager_user = User(username=manager_username, password_hash=hash_password("Mgr-pw-12345"), is_active=True, roles=[manager_role])
        db.add_all([manager_role, admin_user, manager_user])
        db.commit()
        admin_id = str(admin_user.id)
    finally:
        db.close()

    client = TestClient(app)
    login = client.post("/api/v1/auth/login", json={"username": manager_username, "password": "Mgr-pw-12345"})
    assert login.status_code == 200
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}
    return admin_id, client, headers


def test_non_admin_cannot_reset_admin_password(monkeypatch) -> None:
    # Regression: SEC-1 — non-admin with users.manage must receive 403 when resetting admin password
    # Found by /qa on 2026-10-20
    suffix = uuid.uuid4().hex[:12]
    admin_id, client, headers = _setup_admin_and_manager(monkeypatch, suffix)

    resp = client.patch(f"/api/v1/admin/users/{admin_id}/password", headers=headers, json={"new_password": "New-password-123"})
    assert resp.status_code == 403


def test_non_admin_cannot_modify_admin_account(monkeypatch) -> None:
    # Regression: SEC-2 — non-admin with users.manage must receive 403 when modifying admin account
    # Found by /qa on 2026-10-20
    suffix = uuid.uuid4().hex[:12]
    admin_id, client, headers = _setup_admin_and_manager(monkeypatch, suffix)

    resp = client.put(f"/api/v1/admin/users/{admin_id}", headers=headers, json={"is_active": False})
    assert resp.status_code == 403


def test_non_admin_cannot_create_admin_account(monkeypatch) -> None:
    # Regression: SEC-4 — non-admin with users.manage must receive 403 when creating a user with admin role
    # Found by /review on 2026-10-20
    suffix = uuid.uuid4().hex[:12]
    _admin_id, client, headers = _setup_admin_and_manager(monkeypatch, suffix)

    db = SessionLocal()
    try:
        admin_role = db.scalar(select(Role).where(Role.name == "admin"))
        admin_role_id = str(admin_role.id)
    finally:
        db.close()

    resp = client.post(
        "/api/v1/admin/users",
        headers=headers,
        json={"username": f"new-admin-{suffix}", "password": "New-password-123", "role_ids": [admin_role_id]},
    )
    assert resp.status_code == 403
