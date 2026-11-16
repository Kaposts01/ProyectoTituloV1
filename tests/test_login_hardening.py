"""CRM-16A: login endurecido (bloqueo progresivo, respuesta generica, revocacion de sesion, politica de claves,
registro sin datos personales, flags de cookie). Datos sinteticos en la base *_test."""

import logging
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.v1.routes import auth as auth_routes
from app.core import security
from app.core.config import settings
from app.core.security import ACCESS_COOKIE, hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Role, User

SECRET = "test-jwt-secret-with-at-least-32-chars"
PASSWORD = "clave-sintetica-larga-1"


@pytest.fixture(autouse=True)
def _auth_settings(monkeypatch):
    monkeypatch.setattr(settings, "auth_jwt_secret", SECRET)
    monkeypatch.setattr(settings, "auth_login_max_failures_per_user", 3)
    monkeypatch.setattr(settings, "auth_login_max_failures_per_ip", 6)
    monkeypatch.setattr(settings, "auth_login_lockout_base_seconds", 60)


def _make_user(password: str = PASSWORD, *, active: bool = True) -> str:
    username = f"login-{uuid.uuid4().hex[:12]}"
    db = SessionLocal()
    try:
        role = Role(name=f"role-{uuid.uuid4().hex[:12]}")
        db.add(role)
        db.flush()
        db.add(User(username=username, password_hash=hash_password(password), is_active=active, roles=[role]))
        db.commit()
    finally:
        db.close()
    return username


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def _login(client: TestClient, username: str, password: str = PASSWORD):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_unknown_user_inactive_user_and_bad_password_get_the_same_answer(monkeypatch) -> None:
    calls: list[int] = []
    real_burn = security.burn_password_check
    monkeypatch.setattr(auth_routes, "burn_password_check", lambda pw: (calls.append(1), real_burn(pw)))
    client = _client()
    known = _make_user()
    inactive = _make_user(active=False)

    answers = [
        _login(client, f"nadie-{uuid.uuid4().hex[:8]}", "algo-cualquiera-123"),
        _login(client, inactive),
        _login(client, known, "otra-clave-equivocada"),
    ]
    assert {r.status_code for r in answers} == {401}
    assert {r.json()["detail"] for r in answers} == {"Invalid username or password"}
    assert calls == [1, 1]  # usuario inexistente e inactivo pagan el mismo hash que una clave real


def test_user_is_locked_after_failures_even_with_correct_password_and_unlocks_later(monkeypatch) -> None:
    clock = {"t": 1000.0}
    monkeypatch.setattr("app.core.rate_limit.now", lambda: clock["t"])
    client = _client()
    username = _make_user()

    codes = [_login(client, username, "equivocada-123456").status_code for _ in range(3)]
    assert codes == [401, 401, 401]
    blocked = _login(client, username)  # clave correcta, pero bloqueado
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"
    assert "Demasiados intentos" in blocked.json()["detail"]

    # Otro usuario desde la misma IP no queda bloqueado por el contador del primero.
    other = _make_user()
    assert _login(client, other).status_code == 200

    clock["t"] += 61
    assert _login(client, username).status_code == 200


def test_unknown_usernames_are_locked_too_so_lock_state_does_not_reveal_existence(monkeypatch) -> None:
    client = _client()
    ghost = f"fantasma-{uuid.uuid4().hex[:8]}"
    for _ in range(3):
        assert _login(client, ghost, "equivocada-123456").status_code == 401
    assert _login(client, ghost, "equivocada-123456").status_code == 429


def test_ip_is_locked_after_failures_across_usernames() -> None:
    client = _client()
    for i in range(6):
        assert _login(client, f"rociado-{i}-{uuid.uuid4().hex[:6]}", "equivocada-123456").status_code == 401
    username = _make_user()
    response = _login(client, username)
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0


def test_successful_login_resets_user_failures() -> None:
    client = _client()
    username = _make_user()
    for _ in range(2):
        _login(client, username, "equivocada-123456")
    assert _login(client, username).status_code == 200
    for _ in range(2):
        assert _login(client, username, "equivocada-123456").status_code == 401
    assert _login(client, username).status_code == 200


def test_session_cookie_flags_and_token_claims(monkeypatch) -> None:
    monkeypatch.setattr(settings, "debug", False)
    client = _client()
    response = _login(client, _make_user())
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie

    payload = jwt.decode(client.cookies[ACCESS_COOKIE], SECRET, algorithms=["HS256"])
    assert {"sub", "csrf", "exp", "iat", "jti", "tv"} <= payload.keys()
    assert payload["exp"] - payload["iat"] == settings.auth_access_token_minutes * 60

    monkeypatch.setattr(settings, "auth_cookie_samesite", "strict")
    assert "samesite=strict" in _login(_client(), _make_user()).headers["set-cookie"].lower()


def test_secure_cookie_is_forced_in_production_even_with_debug(monkeypatch) -> None:
    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setattr(settings, "app_env", "production")
    assert security.cookie_secure() is True
    monkeypatch.setattr(settings, "app_env", "sandbox")
    assert security.cookie_secure() is False


def test_logout_revokes_the_token_server_side() -> None:
    client = _client()
    username = _make_user()
    login = _login(client, username)
    stolen = client.cookies[ACCESS_COOKIE]
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": login.json()["csrf_token"]}).status_code == 200

    replay = _client()
    replay.cookies.set(ACCESS_COOKIE, stolen)
    response = replay.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_or_expired_session"
    # Un login nuevo vuelve a funcionar.
    assert _login(_client(), username).status_code == 200


def test_tokens_issued_before_the_migration_without_tv_claim_stay_valid() -> None:
    client = _client()
    username = _make_user()
    _login(client, username)
    payload = jwt.decode(client.cookies[ACCESS_COOKIE], SECRET, algorithms=["HS256"])
    legacy = jwt.encode({"sub": payload["sub"], "csrf": "x", "exp": payload["exp"]}, SECRET, algorithm="HS256")
    other = _client()
    other.cookies.set(ACCESS_COOKIE, legacy)
    assert other.get("/api/v1/auth/me").status_code == 200


def test_password_change_enforces_policy_and_revokes_other_sessions() -> None:
    username = _make_user()
    browser_a, browser_b = _client(), _client()
    csrf_a = _login(browser_a, username).json()["csrf_token"]
    _login(browser_b, username)

    weak = browser_a.patch(
        "/api/v1/auth/me",
        headers={"X-CSRF-Token": csrf_a},
        json={"current_password": PASSWORD, "new_password": "corta123", "confirm_password": "corta123"},
    )
    assert weak.status_code == 400
    assert "al menos 12" in weak.json()["detail"]
    common = browser_a.patch(
        "/api/v1/auth/me",
        headers={"X-CSRF-Token": csrf_a},
        json={"current_password": PASSWORD, "new_password": "password1234", "confirm_password": "password1234"},
    )
    assert common.status_code == 400

    new_password = "marea-lenta-azul-47"
    ok = browser_a.patch(
        "/api/v1/auth/me",
        headers={"X-CSRF-Token": csrf_a},
        json={"current_password": PASSWORD, "new_password": new_password, "confirm_password": new_password},
    )
    assert ok.status_code == 200
    new_csrf = ok.json()["csrf_token"]
    assert browser_a.get("/api/v1/auth/me").status_code == 200  # esta sesion sigue con la cookie nueva
    assert browser_a.get("/api/v1/auth/me").json()["csrf_token"] == new_csrf
    assert browser_b.get("/api/v1/auth/me").status_code == 401  # la otra sesion queda revocada
    assert _login(_client(), username, new_password).status_code == 200


def test_wrong_current_password_on_profile_counts_towards_lock() -> None:
    username = _make_user()
    client = _client()
    csrf = _login(client, username).json()["csrf_token"]
    body = {"current_password": "no-es-la-clave-1", "new_username": username}
    codes = [client.patch("/api/v1/auth/me", headers={"X-CSRF-Token": csrf}, json=body).status_code for _ in range(4)]
    assert codes == [400, 400, 400, 429]


def test_auth_log_has_no_username_password_or_full_ip(caplog) -> None:
    username = _make_user()
    client = _client()
    with caplog.at_level(logging.INFO, logger="crm.auth.audit"):
        _login(client, username, "equivocada-123456")
        _login(client, username)
    text = "\n".join(r.getMessage() for r in caplog.records if r.name == "crm.auth.audit")
    assert "event=login_failed" in text and "event=login_success" in text
    assert "user_ref=" in text and "user_id=" in text
    assert username not in text
    assert PASSWORD not in text and "equivocada" not in text
    assert "ip=unknown" in text  # TestClient no tiene IP valida; una real saldria truncada (/24, /48)


def test_csrf_comparison_rejects_missing_and_wrong_tokens() -> None:
    client = _client()
    _login(client, _make_user())
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "x" * 43}).status_code == 403
