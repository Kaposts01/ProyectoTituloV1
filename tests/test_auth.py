import uuid

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Role, User
from app.services.rbac import seed_permissions


def test_login_sets_session_and_requires_csrf_for_logout(monkeypatch) -> None:
    username = f"auth-{uuid.uuid4().hex[:12]}"
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    db = SessionLocal()
    try:
        seed_permissions(db)
        role = Role(name=f"role-{uuid.uuid4().hex[:12]}")
        db.add(role)
        db.flush()
        seed_permissions(db)
        db.add(User(username=username, password_hash=hash_password("correct-password"), roles=[role]))
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    login = client.post("/api/v1/auth/login", json={"username": username, "password": "correct-password"})

    assert login.status_code == 200
    csrf_token = login.json()["csrf_token"]
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf_token}).status_code == 200
