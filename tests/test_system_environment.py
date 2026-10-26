import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.main as main_module
from app.core.config import settings
from app.core.security import access_cookie_name, hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Permission, Role, User
from app.services.rbac import (
    PERMISSIONS,
    seed_default_roles,
    seed_permissions,
    support_permission_codes,
)

EXPECTED_SUPPORT = {c for c in PERMISSIONS if c.endswith(".view")} | {
    "virtualpos.charges.retry",
    "system.environment.switch",
}


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_permission_declared() -> None:
    assert "system.environment.switch" in PERMISSIONS


def test_support_permissions_exact_and_no_dangerous() -> None:
    codes = support_permission_codes()
    assert codes == EXPECTED_SUPPORT
    for forbidden in ("export", "create", "cancel", "update", "delete", "manage", "merge", "run"):
        assert not any(f".{forbidden}" in c for c in codes), forbidden
    assert "virtualpos.recovery.export" not in codes


def test_seed_default_roles_idempotent_and_additive(db) -> None:
    seed_default_roles(db)
    role = db.scalar(select(Role).where(Role.name == "soporte"))
    assert role is not None and role.description
    assert {p.code for p in role.permissions} == EXPECTED_SUPPORT

    extra = db.scalar(select(Permission).where(Permission.code == "users.manage"))
    role.permissions.append(extra)
    db.flush()
    first = seed_default_roles(db)
    second = seed_default_roles(db)
    assert first == second
    role = db.scalar(select(Role).where(Role.name == "soporte"))
    assert "users.manage" in {p.code for p in role.permissions}  # nunca quita
    assert db.query(Role).filter(Role.name == "soporte").count() == 1


def test_seed_default_roles_restores_missing(db) -> None:
    seed_default_roles(db)
    role = db.scalar(select(Role).where(Role.name == "soporte"))
    role.permissions = [p for p in role.permissions if p.code != "system.environment.switch"]
    db.flush()
    seed_default_roles(db)
    role = db.scalar(select(Role).where(Role.name == "soporte"))
    assert "system.environment.switch" in {p.code for p in role.permissions}


def test_public_environment_no_auth_no_sensitive(monkeypatch) -> None:
    monkeypatch.setattr(settings, "sandbox_app_url", "https://sandbox.example.test")
    res = TestClient(app).get("/api/v1/system/environment")
    assert res.status_code == 200
    body = res.json()
    assert body["app_env"] in {"production", "sandbox", "qa"}
    assert set(body) == {"app_env", "label", "is_production", "access_cookie_name"}
    assert "example.test" not in res.text
    assert settings.database_url not in res.text


def _make_user(permission_codes: list[str]) -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:10]
    username = f"env-{suffix}"
    db = SessionLocal()
    try:
        seed_permissions(db)
        perms = db.scalars(select(Permission).where(Permission.code.in_(permission_codes))).all()
        role = Role(name=f"env-role-{suffix}", permissions=list(perms))
        db.add_all([role, User(username=username, password_hash=hash_password("pw-env-test"), roles=[role])])
        db.commit()
    finally:
        db.close()
    return username, "pw-env-test"


def _login(monkeypatch, permission_codes: list[str]) -> TestClient:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    username, password = _make_user(permission_codes)
    client = TestClient(app)
    assert client.post("/api/v1/auth/login", json={"username": username, "password": password}).status_code == 200
    return client


def test_switch_requires_auth_and_permission(monkeypatch) -> None:
    assert TestClient(app).get("/api/v1/system/environment/switch").status_code == 401
    client = _login(monkeypatch, ["dashboard.view"])
    assert client.get("/api/v1/system/environment/switch").status_code == 403


def test_switch_from_production(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "sandbox_app_url", "https://sandbox.example.test:8001")
    client = _login(monkeypatch, ["system.environment.switch"])
    res = client.get("/api/v1/system/environment/switch")
    assert res.status_code == 200
    assert res.json() == {
        "target_env": "sandbox",
        "target_label": "Sandbox",
        "url": "https://sandbox.example.test:8001",
    }


def test_switch_from_sandbox_targets_production(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "sandbox")
    monkeypatch.setattr(settings, "production_app_url", "http://localhost:8000")
    client = _login(monkeypatch, ["system.environment.switch"])
    body = client.get("/api/v1/system/environment/switch").json()
    assert body == {"target_env": "production", "target_label": "Producción", "url": "http://localhost:8000"}


@pytest.mark.parametrize("raw", ["", "   ", "javascript:alert(1)", "ftp://x.test", "//evil.test", "no-scheme.test"])
def test_switch_url_null_when_missing_or_invalid(monkeypatch, raw) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "sandbox_app_url", raw)
    client = _login(monkeypatch, ["system.environment.switch"])
    assert client.get("/api/v1/system/environment/switch").json()["url"] is None


def test_cookie_names_per_environment() -> None:
    assert access_cookie_name("production") == "crm_access_token"
    assert access_cookie_name("sandbox") == "crm_access_token_sandbox"
    assert access_cookie_name("qa") == "crm_access_token_qa"


@pytest.mark.parametrize(
    ("env", "flag", "expected"),
    [
        ("production", False, True),
        ("sandbox", False, False),
        ("qa", False, False),
        ("sandbox", True, True),
    ],
)
def test_scheduler_start_policy(monkeypatch, env, flag, expected) -> None:
    monkeypatch.setattr(settings, "app_env", env)
    monkeypatch.setattr(settings, "sandbox_scheduler_enabled", flag)
    assert main_module.scheduler_should_start() is expected
