"""CRM-16D: rate limit general de la API (por IP y por usuario) y de webhooks (por IP de origen); /health exento."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.api_rate_limit import rate_limit_checks
from app.core.config import settings
from app.core.security import ACCESS_COOKIE, hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Role, User

SECRET = "test-jwt-secret-with-at-least-32-chars"


@pytest.fixture(autouse=True)
def _limits(monkeypatch):
    monkeypatch.setattr(settings, "auth_jwt_secret", SECRET)
    monkeypatch.setattr(settings, "api_rate_limit_enabled", True)
    monkeypatch.setattr(settings, "api_rate_limit_ip_per_minute", 1000)
    monkeypatch.setattr(settings, "api_rate_limit_user_per_minute", 1000)
    monkeypatch.setattr(settings, "api_rate_limit_webhook_ip_per_minute", 1000)


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def test_ip_limit_returns_429_with_retry_after_and_json_detail(monkeypatch) -> None:
    monkeypatch.setattr(settings, "api_rate_limit_ip_per_minute", 3)
    client = _client()
    codes = [client.get("/api/v1/auth/me").status_code for _ in range(3)]
    assert codes == [401, 401, 401]
    limited = client.get("/api/v1/auth/me")
    assert limited.status_code == 429
    assert 1 <= int(limited.headers["Retry-After"]) <= 60
    assert limited.json()["detail"]["code"] == "rate_limited"


def test_health_endpoints_are_exempt(monkeypatch) -> None:
    monkeypatch.setattr(settings, "api_rate_limit_ip_per_minute", 1)
    client = _client()
    assert all(client.get("/health").status_code == 200 for _ in range(5))
    assert all(client.get("/api/v1/health/heartbeat").status_code != 429 for _ in range(5))
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 429


def test_authenticated_user_has_its_own_limit(monkeypatch) -> None:
    username = f"rl-{uuid.uuid4().hex[:12]}"
    password = "clave-sintetica-larga-1"
    db = SessionLocal()
    try:
        role = Role(name=f"role-{uuid.uuid4().hex[:12]}")
        db.add(role)
        db.flush()
        db.add(User(username=username, password_hash=hash_password(password), roles=[role]))
        db.commit()
    finally:
        db.close()
    client = _client()
    assert client.post("/api/v1/auth/login", json={"username": username, "password": password}).status_code == 200
    monkeypatch.setattr(settings, "api_rate_limit_user_per_minute", 2)
    assert [client.get("/api/v1/auth/me").status_code for _ in range(2)] == [200, 200]
    assert client.get("/api/v1/auth/me").status_code == 429
    # Sin cookie (mismo IP) solo cuenta el limite por IP, que sigue holgado.
    anonymous = _client()
    assert anonymous.get("/api/v1/auth/me").status_code == 401


def test_webhooks_are_limited_per_source_ip_across_routes(monkeypatch) -> None:
    monkeypatch.setattr(settings, "api_rate_limit_webhook_ip_per_minute", 2)
    client = _client()
    first = client.post("/api/v1/webhooks/toku", content=b"{}")
    second = client.post("/api/v1/webhooks/payku/subscription", content=b"{}")
    assert first.status_code != 429 and second.status_code != 429
    third = client.post("/api/v1/webhooks/virtualpos/payment", content=b"{}")
    assert third.status_code == 429
    assert "Retry-After" in third.headers
    # El limite de webhooks no consume el de la API general.
    monkeypatch.setattr(settings, "api_rate_limit_ip_per_minute", 1)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_disabled_flag_and_zero_limits_turn_it_off(monkeypatch) -> None:
    monkeypatch.setattr(settings, "api_rate_limit_ip_per_minute", 1)
    monkeypatch.setattr(settings, "api_rate_limit_enabled", False)
    client = _client()
    assert all(client.get("/api/v1/auth/me").status_code == 401 for _ in range(4))
    monkeypatch.setattr(settings, "api_rate_limit_enabled", True)
    monkeypatch.setattr(settings, "api_rate_limit_ip_per_minute", 0)
    assert all(client.get("/api/v1/auth/me").status_code == 401 for _ in range(4))


def test_rate_limit_checks_classify_paths() -> None:
    base = {"type": "http", "client": ("203.0.113.5", 1234), "headers": []}
    assert rate_limit_checks({**base, "path": "/assets/app.js"}) == []
    assert rate_limit_checks({**base, "path": "/health"}) == []
    assert rate_limit_checks({**base, "path": "/api/v1/healthz"})[0][0] == ("ip", "203.0.113.5")
    assert rate_limit_checks({**base, "path": "/api/v1/webhooks/toku"})[0][0] == ("webhook-ip", "203.0.113.5")
    bad_cookie = {**base, "path": "/api/v1/crm/x", "headers": [(b"cookie", f"{ACCESS_COOKIE}=no-es-jwt".encode())]}
    assert [key for key, _ in rate_limit_checks(bad_cookie)] == [("ip", "203.0.113.5")]
