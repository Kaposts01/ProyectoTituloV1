import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.admin import _is_active_admin
from app.core.config import settings
from app.core.security import get_db, hash_password
from app.db.session import SessionLocal, engine
from app.main import app
from app.models.auth import Permission, Role, User
from app.services.rbac import seed_permissions


@pytest.fixture
def isolated_db():
    """Savepoint-backed session that rolls back all changes on teardown; safe for HTTP tests via dependency override."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


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


def _setup_single_admin_session(monkeypatch, suffix: str) -> tuple[str, str, TestClient, dict]:
    """Create exactly one active admin user and return (admin_id, admin_role_id, client, headers)."""
    admin_username = f"solo-adm-{suffix}"
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")

    db = SessionLocal()
    try:
        # Ensure admin role exists before seeding so seed_permissions assigns all perms to it
        admin_role = db.scalar(select(Role).where(Role.name == "admin"))
        if admin_role is None:
            admin_role = Role(name="admin")
            db.add(admin_role)
            db.flush()
        seed_permissions(db)
        admin_user = User(username=admin_username, password_hash=hash_password("Admin-pw-12345"), is_active=True, roles=[admin_role])
        db.add(admin_user)
        db.commit()
        admin_id = str(admin_user.id)
        admin_role_id = str(admin_role.id)
    finally:
        db.close()

    client = TestClient(app)
    login = client.post("/api/v1/auth/login", json={"username": admin_username, "password": "Admin-pw-12345"})
    assert login.status_code == 200
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}
    return admin_id, admin_role_id, client, headers


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


def test_cannot_deactivate_last_active_admin(monkeypatch, isolated_db) -> None:
    # T4: Regression SEC-3 — deactivating the only active admin must return 422
    # Uses dependency_overrides to inject an isolated savepoint session with exactly one active admin.
    # Found by /review on 2026-10-20
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")

    # Deactivate all pre-existing active admins so exactly one will exist after we create ours
    pre_existing = isolated_db.scalars(
        select(User).join(User.roles).where(Role.name == "admin", User.is_active.is_(True))
    ).all()
    for u in pre_existing:
        u.is_active = False
    isolated_db.flush()

    admin_role = isolated_db.scalar(select(Role).where(Role.name == "admin"))
    if admin_role is None:
        admin_role = Role(name="admin")
        isolated_db.add(admin_role)
        isolated_db.flush()
    seed_permissions(isolated_db)
    admin_user = User(username="last-only-admin", password_hash=hash_password("Admin-pw-12345"), is_active=True, roles=[admin_role])
    isolated_db.add(admin_user)
    isolated_db.flush()
    admin_id = str(admin_user.id)

    def _override():
        yield isolated_db

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app)
        login = client.post("/api/v1/auth/login", json={"username": "last-only-admin", "password": "Admin-pw-12345"})
        assert login.status_code == 200
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}

        resp = client.put(f"/api/v1/admin/users/{admin_id}", headers=headers, json={"is_active": False})
        assert resp.status_code == 422
    finally:
        del app.dependency_overrides[get_db]


def test_cannot_remove_admin_role_from_last_active_admin(monkeypatch, isolated_db) -> None:
    # T5: Regression SEC-3 — removing the admin role from the only active admin must return 422
    # Found by /review on 2026-10-20
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")

    pre_existing = isolated_db.scalars(
        select(User).join(User.roles).where(Role.name == "admin", User.is_active.is_(True))
    ).all()
    for u in pre_existing:
        u.is_active = False
    isolated_db.flush()

    admin_role = isolated_db.scalar(select(Role).where(Role.name == "admin"))
    if admin_role is None:
        admin_role = Role(name="admin")
        isolated_db.add(admin_role)
        isolated_db.flush()
    seed_permissions(isolated_db)
    viewer_role = Role(name="viewer-t5")
    admin_user = User(username="last-only-admin-t5", password_hash=hash_password("Admin-pw-12345"), is_active=True, roles=[admin_role])
    isolated_db.add_all([viewer_role, admin_user])
    isolated_db.flush()
    admin_id = str(admin_user.id)
    viewer_role_id = str(viewer_role.id)

    def _override():
        yield isolated_db

    app.dependency_overrides[get_db] = _override
    try:
        client = TestClient(app)
        login = client.post("/api/v1/auth/login", json={"username": "last-only-admin-t5", "password": "Admin-pw-12345"})
        assert login.status_code == 200
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}

        resp = client.put(f"/api/v1/admin/users/{admin_id}", headers=headers, json={"role_ids": [viewer_role_id]})
        assert resp.status_code == 422
    finally:
        del app.dependency_overrides[get_db]


def test_admin_can_delete_role_with_no_users(monkeypatch) -> None:
    # T7: delete_role success path — role with no users must return 200
    # Found by /review on 2026-10-20
    suffix = uuid.uuid4().hex[:12]
    _admin_id, _role_id, client, headers = _setup_single_admin_session(monkeypatch, suffix)

    db = SessionLocal()
    try:
        seed_permissions(db)
        empty_role = Role(name=f"empty-{suffix}")
        db.add(empty_role)
        db.commit()
        empty_role_id = str(empty_role.id)
    finally:
        db.close()

    resp = client.delete(f"/api/v1/admin/roles/{empty_role_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_cannot_delete_admin_role(monkeypatch) -> None:
    # T8: delete_role must return 422 when trying to delete the "admin" role
    # Found by /review on 2026-10-20
    suffix = uuid.uuid4().hex[:12]
    _admin_id, admin_role_id, client, headers = _setup_single_admin_session(monkeypatch, suffix)

    resp = client.delete(f"/api/v1/admin/roles/{admin_role_id}", headers=headers)
    assert resp.status_code == 422


def test_reset_password_returns_404_for_unknown_user(monkeypatch) -> None:
    # T9: reset_user_password must return 404 when the target user UUID does not exist
    # Found by /review on 2026-10-20
    suffix = uuid.uuid4().hex[:12]
    _admin_id, _role_id, client, headers = _setup_single_admin_session(monkeypatch, suffix)

    nonexistent_id = str(uuid.uuid4())
    resp = client.patch(f"/api/v1/admin/users/{nonexistent_id}/password", headers=headers, json={"new_password": "New-password-123"})
    assert resp.status_code == 404
