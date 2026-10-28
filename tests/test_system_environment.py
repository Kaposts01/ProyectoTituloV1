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
    executive_permission_codes,
    seed_default_roles,
    seed_permissions,
    support_permission_codes,
)

# Soporte hereda `virtualpos.billing_changes.view` por incluir todos los `.view` (decisión intencional).
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
    assert set(body) == {"app_env", "label", "is_production", "access_cookie_name", "enabled_channels"}
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


def _set_creds(monkeypatch, *, vp: bool, toku: bool, payku: bool) -> None:
    for name, on, fields in (
        ("virtualpos", vp, ("base_url", "api_key", "secret_key")),
        ("toku", toku, ("base_url", "api_key")),
        ("payku", payku, ("base_url", "api_key", "secret_key")),
    ):
        for f in fields:
            monkeypatch.setattr(settings, f"{name}_{f}", "x" if on else "")


def _enabled() -> list[str]:
    res = TestClient(app).get("/api/v1/system/environment")
    assert res.status_code == 200
    return res.json()["enabled_channels"]


def test_enabled_channels_production(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    assert _enabled() == ["virtualpos1", "virtualpos2", "toku", "payku", "tch"]


def test_enabled_channels_sandbox_only_vp1_and_toku(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "sandbox")
    _set_creds(monkeypatch, vp=True, toku=True, payku=False)
    assert _enabled() == ["virtualpos1", "toku", "tch"]


def test_enabled_channels_sandbox_channel_without_credentials(monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_env", "sandbox")
    _set_creds(monkeypatch, vp=True, toku=False, payku=False)
    assert _enabled() == ["virtualpos1", "tch"]
    assert "virtualpos2" not in _enabled()


def test_scheduler_trigger_disabled_channels(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.api.v1.routes import scheduler as sched_routes

    monkeypatch.setattr(settings, "app_env", "sandbox")
    _set_creds(monkeypatch, vp=True, toku=False, payku=False)
    ran: list = []

    async def fake_sync(run_id, channels):
        ran.append(channels)

    monkeypatch.setattr(sched_routes, "sync_all_channels", fake_sync)
    monkeypatch.setattr(sched_routes, "get_scheduler", lambda: SimpleNamespace(get_job=lambda _id: object()))
    client = _login(monkeypatch, ["sync.run"])
    url = "/api/v1/scheduler/jobs/sync_all_channels/run"

    res = client.post(url, json={"channels": ["payku", "virtualpos2"]})
    assert res.status_code == 409
    assert "deshabilitado" in res.json()["detail"]
    assert ran == []

    res = client.post(url, json={"channels": ["virtualpos1", "payku"]})
    assert res.status_code == 202
    assert res.json()["skipped_channels"] == ["payku"]
    assert ran == [["virtualpos1"]]


NEW_BILLING_PERMISSIONS = {
    "virtualpos.billing_changes.request",
    "virtualpos.billing_changes.approve",
    "virtualpos.billing_changes.view",
    "virtualpos.billing_policy.manage",
}
BILLING_WRITE_PERMISSIONS = {
    "virtualpos.billing_changes.request",
    "virtualpos.billing_changes.approve",
    "virtualpos.billing_policy.manage",
}


def test_billing_permissions_in_catalog() -> None:
    assert NEW_BILLING_PERMISSIONS <= set(PERMISSIONS)


def test_billing_permissions_assigned_to_admin(db) -> None:
    seed_permissions(db)
    admin = db.scalar(select(Role).where(Role.name == "admin"))
    assert admin is not None
    assert NEW_BILLING_PERMISSIONS <= {p.code for p in admin.permissions}


def test_executive_permissions_view_only_and_no_dangerous() -> None:
    codes = executive_permission_codes()
    assert codes and all(c.endswith(".view") for c in codes)
    for forbidden in ("export", "create", "cancel", "update", "delete", "manage", "merge", "run", "retry", "switch"):
        assert not any(f".{forbidden}" in c for c in codes), forbidden
    assert not codes & BILLING_WRITE_PERMISSIONS
    assert "virtualpos.recovery.export" not in codes
    assert "virtualpos.billing_changes.view" in codes


def test_support_has_no_billing_write_permissions() -> None:
    assert not support_permission_codes() & BILLING_WRITE_PERMISSIONS


def test_seed_executive_role_idempotent_and_additive(db) -> None:
    seed_default_roles(db)
    role = db.scalar(select(Role).where(Role.name == "ejecutivo"))
    assert role is not None and role.description
    assert {p.code for p in role.permissions} == executive_permission_codes()

    extra = db.scalar(select(Permission).where(Permission.code == "users.manage"))
    role.permissions.append(extra)
    db.flush()
    first = seed_default_roles(db)
    second = seed_default_roles(db)
    assert first == second
    role = db.scalar(select(Role).where(Role.name == "ejecutivo"))
    assert "users.manage" in {p.code for p in role.permissions}  # nunca quita
    assert db.query(Role).filter(Role.name == "ejecutivo").count() == 1
