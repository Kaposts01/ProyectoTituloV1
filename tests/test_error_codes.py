"""D35: los `detail` de HTTPException de writes, staging, security y scheduler son `{code, message}`.

- El `code` es un identificador estable en inglés (snake_case) y el `message` va en español.
- Todo codigo del codigo fuente esta documentado en `docs/data/error-codes.md`.
- Algunos codigos y estados HTTP concretos se fijan con llamadas reales.
"""

import ast
import re
from pathlib import Path

import pytest
from billing_requests_support import PERMISSIONS, client_for, make_role, make_user
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.v1.routes import staging
from app.core.config import settings
from app.db.session import engine
from app.main import app

ROOT = Path(__file__).resolve().parent.parent
FILES = ("app/api/v1/routes/writes.py", "app/api/v1/routes/staging.py", "app/core/security.py", "app/api/v1/routes/scheduler.py")
CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
LEGACY_UPPERCASE = {"INVOICE_IN_PROGRESS"}  # codigo preexistente que consume el frontend


def _http_exceptions():
    for rel in FILES:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "HTTPException":
                detail = next((k.value for k in node.keywords if k.arg == "detail"), None)
                yield rel, node.lineno, detail


def test_every_detail_is_a_code_and_message_object() -> None:
    seen = 0
    for rel, line, detail in _http_exceptions():
        seen += 1
        assert isinstance(detail, ast.Dict), f"{rel}:{line} detail no estructurado"
        keys = [k.value for k in detail.keys if isinstance(k, ast.Constant)]
        assert keys == ["code", "message"], f"{rel}:{line} {keys}"
        code = detail.values[0]
        assert isinstance(code, ast.Constant) and CODE_RE.match(code.value), f"{rel}:{line} codigo no estatico"
        if code.value not in LEGACY_UPPERCASE:
            assert code.value == code.value.lower(), f"{rel}:{line} {code.value}"
    assert seen >= 150


def test_every_code_is_documented() -> None:
    doc = (ROOT / "docs" / "data" / "error-codes.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| `([a-z_]+)` \|", doc, flags=re.M))
    in_code = {d.values[0].value for _, _, d in _http_exceptions() if d.values[0].value not in LEGACY_UPPERCASE}
    assert in_code <= documented, sorted(in_code - documented)
    assert documented <= in_code, sorted(documented - in_code)


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        app.dependency_overrides.clear()


def test_security_codes_and_status(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    from fastapi.testclient import TestClient

    anonymous = TestClient(app).get("/api/v1/staging/summary")
    assert anonymous.status_code == 401
    assert anonymous.json()["detail"] == {"code": "authentication_required", "message": "Debes iniciar sesión para continuar."}

    nobody = make_user(db_session, make_role(db_session, "sin-permisos-ec", set()))
    client, _ = client_for(db_session, nobody)
    denied = client.get("/api/v1/staging/summary")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "permission_denied"

    admin = make_user(db_session, make_role(db_session, "admin-ec", set(PERMISSIONS)))
    client, _csrf = client_for(db_session, admin)
    bad_csrf = client.put("/api/v1/writes/virtualpos/clients/x", json={"first_name": "a"}, headers={"X-CSRF-Token": "otro"})
    assert bad_csrf.status_code == 403
    assert bad_csrf.json()["detail"]["code"] == "invalid_csrf_token"
    client, csrf = client_for(db_session, admin)
    empty = client.put("/api/v1/writes/virtualpos/clients/x", json={}, headers=csrf)
    assert empty.status_code == 422
    assert empty.json()["detail"] == {"code": "at_least_one_field_required", "message": "Se requiere al menos un campo."}


def test_staging_codes_keep_their_http_status(db_session) -> None:
    with pytest.raises(HTTPException) as unknown_channel:
        staging.centralized_channel_dashboard("no-existe", db=db_session)
    assert unknown_channel.value.status_code == 404
    assert unknown_channel.value.detail["code"] == "unknown_channel"
    assert "Canal desconocido" in unknown_channel.value.detail["message"]

    with pytest.raises(HTTPException) as client_missing:
        staging.general_client_detail("00000000-0", db=db_session)
    assert client_missing.value.status_code == 404
    assert client_missing.value.detail["code"] == "client_not_found"
