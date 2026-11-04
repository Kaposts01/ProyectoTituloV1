"""TK-19: POST /api/v1/imports/toku-reports. Autenticacion real (JWT + cookie + CSRF), .xlsx SINTETICOS."""

import logging
from pathlib import Path

import pytest
from billing_requests_support import client_for, make_role, make_user
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from toku_reports_support import PEPPER, PII_SENTINELS, default_row, write_report

from app.api.v1.routes import imports as imports_route
from app.api.v1.routes.crm import get_db as crm_get_db
from app.core.config import settings
from app.core.security import get_db as security_get_db
from app.db.session import engine
from app.main import app
from app.models.toku_report import TkReportFile, TkReportProduct
from app.models.write_run import WriteRun
from app.services import toku_report_import as imp
from app.services.rbac import (
    PERMISSIONS,
    executive_permission_codes,
    seed_permissions,
    support_permission_codes,
)

URL = "/api/v1/imports/toku-reports"
PERMISSION = "toku.reports.import"


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


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    monkeypatch.setattr(settings, "toku_report_hash_pepper", PEPPER)
    yield
    app.dependency_overrides.pop(crm_get_db, None)
    app.dependency_overrides.pop(security_get_db, None)


class World:
    def __init__(self, db: Session):
        self.db = db
        seed_permissions(db)
        self.admin = make_user(db, make_role(db, "admin", set(PERMISSIONS)))
        self.soporte = make_user(db, make_role(db, "soporte", support_permission_codes()))
        self.ejecutivo = make_user(db, make_role(db, "ejecutivo", executive_permission_codes()))
        self.jefatura = make_user(db, make_role(db, "jefatura", {"toku.subscriptions.view", "export.pii"}))
        self.coordinador = make_user(db, make_role(db, "coordinador", {"toku.subscriptions.view"}))

    def post(self, who, path: Path, *, csrf=True, name=None, content=None):
        client, headers = client_for(self.db, getattr(self, who))
        data = path.read_bytes() if content is None else content
        return client.post(URL, files={"report": (name or path.name, data, "application/octet-stream")}, headers=headers if csrf else {})


@pytest.fixture
def world(db_session):
    return World(db_session)


def _xlsx(tmp_path, kind="productos", name="Productos.xlsx", **kw):
    return write_report(tmp_path / name, kind, **kw)


def _runs(db):
    return list(db.scalars(select(WriteRun).where(WriteRun.operation == "import_report", WriteRun.source == "toku")))


def _all_text(db) -> str:
    parts = []
    for table in ("tk_report_files", "tk_report_products", "tk_report_attempts", "tk_report_response_codes", "write_runs"):
        parts += [r[0] for r in db.execute(text(f"SELECT to_jsonb(t)::text FROM {table} t"))]
    return "\n".join(parts)


def test_admin_uploads_and_gets_a_summary_without_pii(world, tmp_path, caplog):
    with caplog.at_level(logging.DEBUG):
        r = world.post("admin", _xlsx(tmp_path))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report_type"] == "productos" and body["status"] == "completed" and not body["already_loaded"]
    assert (body["rows_total"], body["rows_new"], body["rows_skipped"]) == (3, 3, 0)
    assert world.db.scalar(select(func.count()).select_from(TkReportProduct)) == 3
    assert not any(s in r.text for s in PII_SENTINELS) and not any(s in caplog.text for s in PII_SENTINELS)
    assert not any(s in _all_text(world.db) for s in PII_SENTINELS)
    assert "Donación" not in r.text and "product_key" not in r.text


def test_upload_is_audited_in_write_runs_without_content(world, tmp_path):
    path = _xlsx(tmp_path)
    assert world.post("admin", path).status_code == 200
    (run,) = _runs(world.db)
    assert (run.source, run.resource_type, run.status) == ("toku", "report_import", "completed")
    assert run.requested_by_user_id == world.admin.id and run.finished_at is not None
    payload = run.request_payload
    assert payload["report_type"] == "productos" and payload["filename"] == path.name
    assert len(payload["sha256"]) == 64 and payload["rows_total"] == 3
    assert "sub_T" not in str(payload) and not any(s in str(payload) for s in PII_SENTINELS)


def test_attempts_report_with_catalog_is_accepted(world, tmp_path):
    r = world.post("admin", _xlsx(tmp_path, "intentos", "Intentos.xlsx"))
    assert r.status_code == 200 and r.json()["report_type"] == "intentos" and r.json()["catalog_codes"] == 4


@pytest.mark.parametrize("who", ["soporte", "ejecutivo", "jefatura", "coordinador"])
def test_other_roles_are_forbidden_and_nothing_is_written(world, tmp_path, who):
    assert world.post(who, _xlsx(tmp_path)).status_code == 403
    assert world.db.scalar(select(func.count()).select_from(TkReportFile)) == 0 and not _runs(world.db)


def test_csrf_and_authentication_are_required(world, tmp_path):
    path = _xlsx(tmp_path)
    assert world.post("admin", path, csrf=False).status_code == 403
    anonymous = TestClient(app, base_url="https://testserver")
    app.dependency_overrides[crm_get_db] = lambda: world.db
    app.dependency_overrides[security_get_db] = lambda: world.db
    assert anonymous.post(URL, files={"report": (path.name, path.read_bytes(), "application/octet-stream")}).status_code == 401
    assert world.db.scalar(select(func.count()).select_from(TkReportFile)) == 0


def test_same_file_twice_is_409_even_if_renamed_and_does_not_duplicate(world, tmp_path):
    path = _xlsx(tmp_path)
    assert world.post("admin", path).status_code == 200
    r = world.post("admin", path, name="renombrado.xlsx")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_loaded"
    assert world.db.scalar(select(func.count()).select_from(TkReportFile)) == 1
    assert world.db.scalar(select(func.count()).select_from(TkReportProduct)) == 3
    assert [x.status for x in _runs(world.db)] == ["completed", "already_loaded"]


def test_missing_pepper_refuses_with_a_fixed_code_and_writes_nothing(world, tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(settings, "toku_report_hash_pepper", "")
    with caplog.at_level(logging.DEBUG):
        r = world.post("admin", _xlsx(tmp_path))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "pepper_not_configured"
    assert "TOKU_REPORT_HASH_PEPPER" in r.json()["detail"]["message"]
    assert not any(s in r.text for s in PII_SENTINELS) and not any(s in caplog.text for s in PII_SENTINELS)
    assert world.db.scalar(select(func.count()).select_from(TkReportFile)) == 0
    assert world.db.scalar(select(func.count()).select_from(TkReportProduct)) == 0
    (run,) = _runs(world.db)
    assert run.status == "rejected" and run.error_message == "pepper_not_configured"


def test_invalid_uploads_are_rejected_without_echoing_content(world, tmp_path):
    bad = tmp_path / "x.xlsx"
    bad.write_bytes(b"SENTINELA-NOMBRE no es un xlsx")
    r = world.post("admin", bad)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_format"
    assert "SENTINELA" not in r.text
    assert world.post("admin", bad, name="datos.csv").status_code == 422  # extension
    assert world.post("admin", bad, name="vacio.xlsx", content=b"").status_code == 422
    assert world.db.scalar(select(func.count()).select_from(TkReportFile)) == 0
    assert all(x.status == "rejected" for x in _runs(world.db))


def test_unsupported_report_type_is_422(world, tmp_path):
    from toku_reports_support import write_unsupported

    r = world.post("admin", write_unsupported(tmp_path / "Clientes.xlsx"))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_format"
    assert "SENTINELA" not in r.text


def test_oversized_upload_is_413(world, tmp_path, monkeypatch):
    monkeypatch.setattr(imports_route, "MAX_TOKU_REPORT_BYTES", 100)
    r = world.post("admin", _xlsx(tmp_path))
    assert r.status_code == 413
    assert world.db.scalar(select(func.count()).select_from(TkReportFile)) == 0


def test_older_report_does_not_overwrite_newer_data_and_flags_stale_rows(world, tmp_path):
    new = _xlsx(
        tmp_path, name="nuevo.xlsx", generated="2026-10-20 10:00:00",
        rows=[default_row("productos", 1, Estado="permanent_failed")],
    )
    old = _xlsx(
        tmp_path, name="viejo.xlsx", generated="2026-08-09 10:00:00",
        rows=[default_row("productos", 1, Estado="chargeable")],
    )
    assert world.post("admin", new).status_code == 200
    r = world.post("admin", old)
    assert r.status_code == 200 and r.json()["rows_stale"] == 1 and "stale_report" in r.json()["warnings"]
    row = world.db.scalar(select(TkReportProduct))
    assert row.payment_method_status == "permanent_failed"


def test_import_failure_is_500_with_a_label_only(world, tmp_path, monkeypatch, caplog):
    def boom(*_a, **_k):
        raise RuntimeError("SENTINELA-NOMBRE 00.000.001-K")

    monkeypatch.setattr(imp, "_upsert_rows", boom)
    with caplog.at_level(logging.DEBUG):
        r = world.post("admin", _xlsx(tmp_path))
    assert r.status_code == 500 and r.json()["detail"]["code"] == "import_failed"
    assert r.json()["detail"]["label"] == "load:RuntimeError"
    assert "SENTINELA" not in r.text and "SENTINELA" not in caplog.text
    (run,) = _runs(world.db)
    assert run.status == "failed" and "SENTINELA" not in str(run.request_payload) + str(run.error_message)


def test_temporary_upload_is_removed(world, tmp_path, monkeypatch):
    seen: list[Path] = []
    original = imp.import_report

    def spy(db, path, **kw):
        seen.append(Path(path))
        assert Path(path).exists()
        return original(db, path, **kw)

    monkeypatch.setattr(imports_route.toku_report_import, "import_report", spy)
    assert world.post("admin", _xlsx(tmp_path)).status_code == 200
    assert seen and not seen[0].exists()


def test_route_is_registered_and_permission_is_admin_only(db_session):
    assert URL in app.openapi()["paths"]
    assert PERMISSION in PERMISSIONS and not PERMISSION.endswith(".view")
    assert PERMISSION not in support_permission_codes() and PERMISSION not in executive_permission_codes()
