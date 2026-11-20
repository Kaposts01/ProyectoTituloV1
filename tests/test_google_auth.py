"""AUTH-04: entrar con Google. Sin red real: `httpx.post` simulado y una clave RSA generada en la prueba."""

import logging
import time
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Permission, Role, User
from app.services import google_oauth
from app.services.rbac import seed_permissions

CLIENT_ID = "test-client-id.apps.example"
CLIENT_SECRET = "test-client-secret-value-xyz"
REDIRECT = "http://127.0.0.1:5173/api/v1/auth/google/callback"
JWT_SECRET = "test-jwt-secret-with-at-least-32-chars"
ERROR_URL = "/?login_error=google"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setattr(settings, "auth_jwt_secret", JWT_SECRET)
    monkeypatch.setattr(settings, "google_oauth_enabled", True)
    monkeypatch.setattr(settings, "google_oauth_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "google_oauth_client_secret", CLIENT_SECRET)
    monkeypatch.setattr(settings, "google_oauth_allowed_domain", "techo.org")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", REDIRECT)
    monkeypatch.setattr(google_oauth, "signing_key", lambda _token: _KEY.public_key())
    calls: list[dict] = []
    state = {"id_token": None, "status": 200}

    def fake_post(url, data=None, timeout=None, **_kw):
        calls.append({"url": url, "data": dict(data or {})})
        if state["status"] == -1:
            raise httpx.ConnectError("sin red")
        body = {"id_token": state["id_token"]} if state["id_token"] else {}
        return httpx.Response(state["status"], json=body)

    monkeypatch.setattr(google_oauth.httpx, "post", fake_post)
    return {"calls": calls, "state": state}


def _make_user(email: str | None, *, active: bool = True) -> str:
    db = SessionLocal()
    try:
        role = Role(name=f"g-role-{uuid.uuid4().hex[:10]}")
        db.add(role)
        db.flush()
        user = User(
            username=f"g-{uuid.uuid4().hex[:12]}",
            password_hash=hash_password("unused-password-123"),
            is_active=active,
            roles=[role],
            google_email=email,
        )
        db.add(user)
        db.commit()
        return str(user.id)
    finally:
        db.close()


def _email() -> str:
    return f"g{uuid.uuid4().hex[:10]}@techo.org"


def _id_token(_nonce: str, _email_: str, **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234567890",
        "email": _email_,
        "email_verified": True,
        "hd": "techo.org",
        "nonce": _nonce,
        "iat": now,
        "exp": now + 600,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, _KEY, algorithm="RS256", headers={"kid": "test"})


def _start(client: TestClient) -> tuple[str, str, str]:
    resp = client.get("/api/v1/auth/google/start", follow_redirects=False)
    assert resp.status_code == 302
    query = parse_qs(urlparse(resp.headers["location"]).query)
    return query["state"][0], query["nonce"][0], resp.headers["location"]


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def _callback(client: TestClient, state: str | None, code: str | None = "auth-code"):
    params = {k: v for k, v in (("state", state), ("code", code)) if v is not None}
    return client.get("/api/v1/auth/google/callback", params=params, follow_redirects=False)


def _full_login(google, mail: str, client: TestClient | None = None, **overrides):
    client = client or _client()
    state, nonce, _ = _start(client)
    google["state"]["id_token"] = _id_token(nonce, mail, **overrides)
    return client, _callback(client, state)


def _failed(resp) -> bool:
    return resp.status_code == 303 and resp.headers["location"] == ERROR_URL


def test_start_redirects_to_google_with_pkce_and_temporary_cookie(google) -> None:
    client = _client()
    resp = client.get("/api/v1/auth/google/start", follow_redirects=False)
    assert resp.status_code == 302
    location = urlparse(resp.headers["location"])
    assert location.netloc == "accounts.google.com"
    q = {k: v[0] for k, v in parse_qs(location.query).items()}
    assert q["client_id"] == CLIENT_ID and q["redirect_uri"] == REDIRECT
    assert q["code_challenge_method"] == "S256" and q["scope"] == "openid email"
    assert q["hd"] == "techo.org" and q["prompt"] == "select_account" and q["response_type"] == "code"
    assert "client_secret" not in q
    cookie = resp.headers["set-cookie"].lower()
    assert google_oauth.tx_cookie_name() in cookie
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/api/v1/auth/google" in cookie
    tx = google_oauth.decode_transaction(client.cookies.get(google_oauth.tx_cookie_name()))
    assert tx.state == q["state"] and tx.nonce == q["nonce"]
    assert google_oauth.pkce_challenge(tx.verifier) == q["code_challenge"]


def test_happy_path_opens_same_session_as_login_and_sends_pkce(google, caplog) -> None:
    email = _email()
    user_id = _make_user(email)
    caplog.set_level(logging.INFO, logger="crm.auth.audit")
    client, resp = _full_login(google, email.upper())  # el correo del token se compara en minusculas
    assert resp.status_code == 303 and resp.headers["location"] == "/"
    sent = google["calls"][0]["data"]
    assert sent["grant_type"] == "authorization_code" and sent["redirect_uri"] == REDIRECT
    assert sent["client_secret"] == CLIENT_SECRET and sent["code"] == "auth-code"
    assert google_oauth.pkce_challenge(sent["code_verifier"])
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["user"]["id"] == user_id
    assert client.cookies.get(google_oauth.tx_cookie_name()) is None  # la cookie temporal se borra
    log = caplog.text
    assert "event=google_login_success" in log and f"user_id={user_id}" in log
    assert email not in log and CLIENT_SECRET not in log and "id_token" not in log


def test_registered_email_is_matched_case_insensitively(google) -> None:
    email = _email()
    _make_user(email.upper())
    _, resp = _full_login(google, email)
    assert resp.headers["location"] == "/"


@pytest.mark.parametrize("variant", ["missing_state", "wrong_state", "no_cookie", "no_code", "google_error", "tampered_cookie"])
def test_state_and_transaction_failures_redirect_without_detail(google, variant, caplog) -> None:
    email = _email()
    _make_user(email)
    client = _client()
    state, nonce, _ = _start(client)
    google["state"]["id_token"] = _id_token(nonce, email)
    if variant == "missing_state":
        resp = _callback(client, None)
    elif variant == "wrong_state":
        resp = _callback(client, state + "x")
    elif variant == "no_cookie":
        client.cookies.clear()
        resp = _callback(client, state)
    elif variant == "no_code":
        resp = _callback(client, state, code=None)
    elif variant == "google_error":
        resp = client.get("/api/v1/auth/google/callback", params={"error": "access_denied", "state": state}, follow_redirects=False)
    else:
        client.cookies.set(google_oauth.tx_cookie_name(), "no-es-un-jwt", path="/api/v1/auth/google")
        resp = _callback(client, state)
    assert _failed(resp)
    assert not google["calls"]  # ni siquiera se intenta el intercambio
    assert client.get("/api/v1/auth/me").status_code == 401
    assert "event=google_login_failed" in caplog.text


def test_transaction_cookie_is_single_use(google) -> None:
    email = _email()
    _make_user(email)
    client = _client()
    state, nonce, _ = _start(client)
    google["state"]["id_token"] = _id_token(nonce, email)
    assert _callback(client, state).headers["location"] == "/"
    assert client.cookies.get(google_oauth.tx_cookie_name()) is None  # el navegador la descarta tras el primer uso
    # Repetir el callback (mismo state, sin la cookie) falla y no vuelve a intercambiar el codigo.
    assert _failed(_callback(client, state))
    assert len(google["calls"]) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"nonce": "otro"},
        {"aud": "otro-cliente"},
        {"iss": "https://evil.example"},
        {"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200},
        {"iat": int(time.time()) + 7200, "exp": int(time.time()) + 9000},
        {"hd": None},
        {"hd": "otro.org"},
        {"email_verified": False},
        {"email_verified": "true"},
        {"email": "alguien@otro.org"},
    ],
    ids=["nonce", "aud", "iss", "exp", "iat_futuro", "hd_ausente", "hd_distinto", "no_verificado", "verificado_texto", "dominio"],
)
def test_invalid_id_token_claims_are_rejected(google, overrides) -> None:
    email = _email()
    _make_user(email)
    use_email = overrides.get("email", email)
    if "email" in overrides:
        _make_user(use_email)
    client, resp = _full_login(google, use_email, **overrides)
    assert _failed(resp)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_token_signed_with_foreign_key_is_rejected(google) -> None:
    email = _email()
    _make_user(email)
    client = _client()
    state, nonce, _ = _start(client)
    now = int(time.time())
    google["state"]["id_token"] = jwt.encode(
        {"iss": "accounts.google.com", "aud": CLIENT_ID, "sub": "1", "email": email, "email_verified": True,
         "hd": "techo.org", "nonce": nonce, "iat": now, "exp": now + 600},
        _OTHER_KEY, algorithm="RS256",
    )
    assert _failed(_callback(client, state))


@pytest.mark.parametrize("alg", ["none", "HS256"])
def test_unsigned_and_hmac_tokens_are_rejected(google, alg) -> None:
    email = _email()
    _make_user(email)
    client = _client()
    state, nonce, _ = _start(client)
    now = int(time.time())
    claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": "1", "email": email, "email_verified": True,
              "hd": "techo.org", "nonce": nonce, "iat": now, "exp": now + 600}
    if alg == "none":
        google["state"]["id_token"] = jwt.encode(claims, None, algorithm="none")
    else:
        google["state"]["id_token"] = jwt.encode(claims, "x" * 40, algorithm="HS256")
    assert _failed(_callback(client, state))


def test_unregistered_and_inactive_users_get_the_same_result(google, caplog) -> None:
    inactive = _email()
    _make_user(inactive, active=False)
    _, resp_inactive = _full_login(google, inactive)
    _, resp_unknown = _full_login(google, _email())
    assert _failed(resp_inactive) and _failed(resp_unknown)
    assert resp_inactive.headers["location"] == resp_unknown.headers["location"]
    db = SessionLocal()
    try:
        assert db.scalar(select(User).where(User.google_email == inactive)).is_active is False
    finally:
        db.close()
    assert "unknown_or_inactive" in caplog.text


def test_unknown_email_never_creates_a_user(google) -> None:
    email = _email()
    _, resp = _full_login(google, email)
    assert _failed(resp)
    db = SessionLocal()
    try:
        assert db.scalar(select(User).where(User.google_email == email)) is None
    finally:
        db.close()


@pytest.mark.parametrize("mode", ["rejected", "network"])
def test_token_endpoint_failure_fails_closed(google, mode) -> None:
    email = _email()
    _make_user(email)
    client = _client()
    state, nonce, _ = _start(client)
    google["state"]["id_token"] = _id_token(nonce, email)
    google["state"]["status"] = 400 if mode == "rejected" else -1
    assert _failed(_callback(client, state))


def test_jwks_unavailable_fails_closed(google, monkeypatch) -> None:
    from jwt.exceptions import PyJWKClientError

    def boom(_token):
        raise PyJWKClientError("sin claves")

    monkeypatch.setattr(google_oauth, "signing_key", boom)
    email = _email()
    _make_user(email)
    _, resp = _full_login(google, email)
    assert _failed(resp)


def test_disabled_returns_404(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_jwt_secret", JWT_SECRET)
    monkeypatch.setattr(settings, "google_oauth_enabled", False)
    client = _client()
    assert client.get("/api/v1/auth/google/start", follow_redirects=False).status_code == 404
    assert client.get("/api/v1/auth/google/callback?code=a&state=b", follow_redirects=False).status_code == 404
    assert client.get("/api/v1/system/environment").json()["google_login_enabled"] is False


def test_incomplete_configuration_keeps_it_disabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "google_oauth_enabled", True)
    monkeypatch.setattr(settings, "google_oauth_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "google_oauth_client_secret", "")
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", REDIRECT)
    assert settings.google_login_active is False
    assert _client().get("/api/v1/auth/google/start", follow_redirects=False).status_code == 404


def test_environment_reports_google_login_enabled(google) -> None:
    assert _client().get("/api/v1/system/environment").json()["google_login_enabled"] is True


def test_settings_validator_disables_and_warns_without_values(monkeypatch, caplog) -> None:
    from app.core.config import Settings

    caplog.set_level(logging.WARNING, logger="app.core.config")
    cfg = Settings(
        google_oauth_enabled=True, google_oauth_client_id="id-visible-no", google_oauth_client_secret="", google_oauth_redirect_uri=""
    )
    assert cfg.google_oauth_enabled is False
    assert "GOOGLE_OAUTH_CLIENT_SECRET" in caplog.text
    assert "id-visible-no" not in caplog.text


def test_sandbox_uses_its_own_redirect_uri_and_same_client(monkeypatch) -> None:
    from app.core.config import Settings

    cfg = Settings(
        app_env="sandbox",
        sandbox_database_url="postgresql+psycopg://u:p@127.0.0.1:5433/crm_sandbox",
        database_url="postgresql+psycopg://u:p@127.0.0.1:5433/crm",
        sandbox_auth_jwt_secret="s" * 40,
        auth_jwt_secret="p" * 40,
        google_oauth_enabled=True,
        google_oauth_client_id="cid",
        google_oauth_client_secret="sec",
        google_oauth_redirect_uri="http://127.0.0.1:5173/api/v1/auth/google/callback",
        sandbox_google_oauth_redirect_uri="http://127.0.0.1:5174/api/v1/auth/google/callback",
    )
    assert cfg.google_oauth_redirect_uri.endswith(":5174/api/v1/auth/google/callback")
    assert cfg.google_oauth_client_id == "cid" and cfg.google_login_active


def _password_user() -> str:
    username = f"pw-{uuid.uuid4().hex[:10]}"
    db = SessionLocal()
    try:
        seed_permissions(db)
        role = Role(name=f"pw-role-{uuid.uuid4().hex[:8]}")
        db.add(role)
        db.flush()
        db.add(User(username=username, password_hash=hash_password("correct-password"), roles=[role]))
        db.commit()
    finally:
        db.close()
    return username


def test_failures_with_valid_transaction_block_google_but_not_password_login(google, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_login_max_failures_per_ip", 3)
    username = _password_user()
    client = _client()
    for _ in range(3):  # transaccion valida, usuario no registrado: cuenta
        _, resp = _full_login(google, _email())
        assert _failed(resp)
    email = _email()
    _make_user(email)
    calls_before = len(google["calls"])
    _, resp = _full_login(google, email)  # bloqueada: ni con un token valido entra
    assert _failed(resp)
    assert len(google["calls"]) == calls_before
    # clave propia: el login con contrasena de la misma IP sigue funcionando
    assert client.post("/api/v1/auth/login", json={"username": username, "password": "correct-password"}).status_code == 200


def test_successful_google_login_clears_the_google_ip_counter(google, monkeypatch) -> None:
    # O1: todos llegan desde 127.0.0.1 por el proxy; un ingreso correcto limpia los fallos acumulados de la IP.
    monkeypatch.setattr(settings, "auth_login_max_failures_per_ip", 3)
    for _ in range(2):  # dos fallos que cuentan, sin llegar al umbral
        _, resp = _full_login(google, _email())
        assert _failed(resp)
    email = _email()
    _make_user(email)
    _, resp = _full_login(google, email)
    assert resp.headers["location"] == "/"
    for _ in range(2):  # sin la limpieza, el tercer fallo bloquearia; con ella el contador parte de cero
        _, resp = _full_login(google, _email())
        assert _failed(resp)
    _, resp = _full_login(google, email)
    assert resp.headers["location"] == "/"


def test_callback_failures_without_transaction_do_not_count(google, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_login_max_failures_per_ip", 3)
    username = _password_user()
    client = _client()
    for _ in range(20):
        assert _failed(_callback(client, "x"))  # sin cookie
    anon = _client()
    state, _nonce, _ = _start(anon)
    for _ in range(5):
        assert _failed(_callback(anon, state + "x"))  # state distinto (la cookie se borra, da igual)
        anon.cookies.clear()
        state, _nonce, _ = _start(anon)
        assert _failed(anon.get("/api/v1/auth/google/callback", params={"error": "access_denied", "state": state}, follow_redirects=False))
        state, _nonce, _ = _start(anon)
    assert client.post("/api/v1/auth/login", json={"username": username, "password": "correct-password"}).status_code == 200
    email = _email()
    _make_user(email)
    _, resp = _full_login(google, email)  # y Google tampoco quedo bloqueado
    assert resp.headers["location"] == "/"


def test_login_with_password_is_unaffected(google) -> None:
    username = f"pw-{uuid.uuid4().hex[:10]}"
    db = SessionLocal()
    try:
        seed_permissions(db)
        role = Role(name=f"pw-role-{uuid.uuid4().hex[:8]}")
        db.add(role)
        db.flush()
        db.add(User(username=username, password_hash=hash_password("correct-password"), roles=[role]))
        db.commit()
    finally:
        db.close()
    assert _client().post("/api/v1/auth/login", json={"username": username, "password": "correct-password"}).status_code == 200


# ── Administracion ────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def manager(monkeypatch):
    """Usuario con `users.manage` (no admin) con sesion abierta; devuelve (client, headers, role_id)."""
    monkeypatch.setattr(settings, "auth_jwt_secret", JWT_SECRET)
    monkeypatch.setattr(settings, "google_oauth_allowed_domain", "techo.org")
    suffix = uuid.uuid4().hex[:10]
    db = SessionLocal()
    try:
        seed_permissions(db)
        perms = db.scalars(select(Permission).where(Permission.code == "users.manage")).all()
        mgr_role = Role(name=f"gm-{suffix}", permissions=perms)
        plain_role = Role(name=f"gp-{suffix}")
        db.add_all([mgr_role, plain_role, User(username=f"gm-{suffix}", password_hash=hash_password("Mgr-pw-12345"), roles=[mgr_role])])
        db.commit()
        plain_role_id = str(plain_role.id)
    finally:
        db.close()
    client = _client()
    login = client.post("/api/v1/auth/login", json={"username": f"gm-{suffix}", "password": "Mgr-pw-12345"})
    assert login.status_code == 200
    return client, {"X-CSRF-Token": login.json()["csrf_token"]}, plain_role_id


def _create(client, headers, role_id, google_email=None):
    body = {"username": f"u-{uuid.uuid4().hex[:10]}", "password": "Member-pw-12345", "role_ids": [role_id]}
    if google_email is not None:
        body["google_email"] = google_email
    return client.post("/api/v1/admin/users", headers=headers, json=body)


def test_admin_creates_user_with_normalized_google_email_and_lists_it(manager, caplog) -> None:
    client, headers, role_id = manager
    caplog.set_level(logging.INFO, logger="crm.auth.audit")
    email = _email()
    resp = _create(client, headers, role_id, f"  {email.upper()} ")
    assert resp.status_code == 200
    listed = {u["id"]: u for u in client.get("/api/v1/admin/users").json()}
    assert listed[resp.json()["id"]]["google_email"] == email
    assert "event=google_email_set" in caplog.text and email not in caplog.text


def test_admin_rejects_wrong_domain_and_duplicates(manager) -> None:
    client, headers, role_id = manager
    assert _create(client, headers, role_id, "alguien@gmail.com").status_code == 422
    assert _create(client, headers, role_id, "alguien@techo.org.evil.com").status_code == 422
    assert _create(client, headers, role_id, "sin-arroba").status_code == 422
    email = _email()
    assert _create(client, headers, role_id, email).status_code == 200
    assert _create(client, headers, role_id, email.upper()).status_code == 409
    other = _create(client, headers, role_id).json()["id"]
    assert client.put(f"/api/v1/admin/users/{other}", headers=headers, json={"google_email": email}).status_code == 409
    assert client.put(f"/api/v1/admin/users/{other}", headers=headers, json={"google_email": "x@otro.org"}).status_code == 422


def test_changing_or_removing_google_email_revokes_sessions_and_hides_email_in_audit(manager, google, caplog) -> None:
    client, headers, role_id = manager
    caplog.set_level(logging.INFO, logger="crm.auth.audit")
    email = _email()
    user_id = _create(client, headers, role_id, email).json()["id"]
    member, resp = _full_login(google, email)
    assert resp.headers["location"] == "/" and member.get("/api/v1/auth/me").status_code == 200

    # Un PUT sin google_email no toca el correo ni las sesiones.
    assert client.put(f"/api/v1/admin/users/{user_id}", headers=headers, json={"is_active": True}).status_code == 200
    assert member.get("/api/v1/auth/me").status_code == 200

    new_email = _email()
    assert client.put(f"/api/v1/admin/users/{user_id}", headers=headers, json={"google_email": new_email}).status_code == 200
    assert member.get("/api/v1/auth/me").status_code == 401
    assert "event=google_email_changed" in caplog.text and new_email not in caplog.text and email not in caplog.text

    member2, _ = _full_login(google, new_email)
    assert member2.get("/api/v1/auth/me").status_code == 200
    assert client.put(f"/api/v1/admin/users/{user_id}", headers=headers, json={"google_email": None}).status_code == 200
    assert member2.get("/api/v1/auth/me").status_code == 401
    _, resp3 = _full_login(google, new_email)
    assert _failed(resp3)


def test_google_email_admin_permissions(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_jwt_secret", JWT_SECRET)
    client = _client()
    assert client.get("/api/v1/admin/users").status_code == 401
    suffix = uuid.uuid4().hex[:10]
    db = SessionLocal()
    try:
        seed_permissions(db)
        role = Role(name=f"np-{suffix}")
        db.add_all([role, User(username=f"np-{suffix}", password_hash=hash_password("Plain-pw-12345"), roles=[role])])
        db.commit()
    finally:
        db.close()
    login = client.post("/api/v1/auth/login", json={"username": f"np-{suffix}", "password": "Plain-pw-12345"})
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}
    assert client.get("/api/v1/admin/users").status_code == 403
    assert client.post("/api/v1/admin/users", headers=headers, json={"username": "zzz-user", "password": "Member-pw-12345", "role_ids": [str(uuid.uuid4())], "google_email": _email()}).status_code == 403


# ── Migracion ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_migration_adds_nullable_column_and_partial_unique_index() -> None:
    from sqlalchemy import text

    from app.db.session import engine

    with engine.connect() as conn:
        cols = {r[0]: r[1] for r in conn.execute(text(
            "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name='users'"))}
        assert cols["google_email"] == "YES"
        idx = conn.execute(text("SELECT indexdef FROM pg_indexes WHERE indexname='uq_users_google_email_lower'")).scalar_one()
        assert "UNIQUE" in idx and "lower" in idx and "google_email IS NOT NULL" in idx


def test_migration_downgrade_and_upgrade_are_symmetric(monkeypatch) -> None:
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect, text

    from app.db.session import engine

    config = Config("alembic.ini")
    config.set_main_option("path_separator", "os")
    script = ScriptDirectory.from_config(config)
    migration = script.get_revision("20261119_0084").module
    assert migration.down_revision == "20261118_0083"
    connection = engine.connect()
    transaction = connection.begin()  # el DDL de PostgreSQL es transaccional: todo vuelve atras al final
    try:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.downgrade()
        assert "google_email" not in {c["name"] for c in inspect(connection).get_columns("users")}
        assert connection.execute(text("SELECT 1 FROM pg_indexes WHERE indexname='uq_users_google_email_lower'")).first() is None
        migration.upgrade()
        assert "google_email" in {c["name"] for c in inspect(connection).get_columns("users")}
        connection.execute(text("INSERT INTO users (id, username, password_hash, google_email) VALUES (gen_random_uuid(), 'mig-a', 'x', 'A@techo.org')"))
        with pytest.raises(Exception, match="uq_users_google_email_lower"):
            connection.execute(text("INSERT INTO users (id, username, password_hash, google_email) VALUES (gen_random_uuid(), 'mig-b', 'x', 'a@techo.org')"))
    finally:
        transaction.rollback()
        connection.close()
