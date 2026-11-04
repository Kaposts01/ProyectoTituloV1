"""VP-PAR-02 (parte 4): POST /api/v1/imports/virtualpos-reports. Autenticacion real (JWT + cookie + CSRF), CSV sinteticos."""

import importlib.util
import logging
import uuid
from pathlib import Path

import pytest
from billing_requests_support import client_for, make_role, make_user
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from vp_reports_support import (
    PEPPER,
    PII_SENTINELS,
    payment_row,
    rejected_payment_row,
    subscription_row,
    write_report,
)

from app.api.v1.routes import imports as imports_route
from app.api.v1.routes.crm import get_db as crm_get_db
from app.core.config import settings
from app.core.security import get_db as security_get_db
from app.db.session import engine
from app.main import app
from app.models.auth import Permission, Role
from app.models.vp import VpCharge
from app.models.vp_report import VpReportFile, VpReportPayment
from app.models.write_run import WriteRun
from app.services import vp_report_import as imp
from app.services.rbac import (
    PERMISSIONS,
    executive_permission_codes,
    seed_permissions,
    support_permission_codes,
)

URL = "/api/v1/imports/virtualpos-reports"
PERMISSION = "virtualpos.reports.import"
ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "alembic" / "versions" / "20261029_0046_seed_vp_reports_import_permission.py"


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
    monkeypatch.setattr(settings, "vp_report_hash_pepper", PEPPER)
    yield
    app.dependency_overrides.pop(crm_get_db, None)
    app.dependency_overrides.pop(security_get_db, None)


class World:
    def __init__(self, db: Session):
        self.db = db
        seed_permissions(db)
        self.admin_role = make_role(db, "admin", set(PERMISSIONS))
        self.admin = make_user(db, self.admin_role)
        self.soporte = make_user(db, make_role(db, "soporte", support_permission_codes()))
        self.ejecutivo = make_user(db, make_role(db, "ejecutivo", executive_permission_codes()))
        self.jefatura = make_user(db, make_role(db, "jefatura", {"virtualpos.charges.view", "export.pii"}))
        self.coordinador = make_user(db, make_role(db, "coordinador", {"virtualpos.charges.view"}))

    def post(self, who, path: Path, *, csrf=True, name=None, content=None, content_type="text/csv"):
        client, headers = client_for(self.db, getattr(self, who))
        data = path.read_bytes() if content is None else content
        return client.post(
            URL, files={"report": (name or path.name, data, content_type)}, headers=headers if csrf else {}
        )


@pytest.fixture
def world(db_session):
    return World(db_session)


def _csv(tmp_path, rows=None, kind="transacciones", name="TransaccionesPAT-VirtualPOS-1792546479.csv"):
    return write_report(tmp_path / name, kind, rows)


def _runs(db):
    return list(db.scalars(select(WriteRun).where(WriteRun.operation == "import_report")))


def _all_text(db) -> str:
    parts = []
    for table in ("vp_report_files", "vp_report_payments", "vp_report_subscriptions", "payment_rejection_details", "write_runs"):
        parts += [r[0] for r in db.execute(text(f"SELECT to_jsonb(t)::text FROM {table} t"))]
    return "\n".join(parts)


def test_admin_uploads_a_report_and_gets_a_summary_without_pii(world, tmp_path, caplog):
    world.db.add(VpCharge(platform="virtualpos1", external_id="cid_T00002.9", subscription_external_id="S00002xyz", status="rechazado"))
    world.db.flush()
    path = _csv(tmp_path, [payment_row(1), rejected_payment_row(2)])
    with caplog.at_level(logging.DEBUG):
        r = world.post("admin", path)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report_type"] == "transacciones" and body["status"] == "completed" and not body["already_loaded"]
    assert (body["rows_total"], body["rows_new"], body["rows_skipped"]) == (2, 2, 0)
    assert body["platforms"]["resolved"] == 1 and body["rejections"]["inserted"] == 1
    assert world.db.scalar(select(func.count()).select_from(VpReportPayment)) == 2
    assert not any(s in r.text for s in PII_SENTINELS) and not any(s in caplog.text for s in PII_SENTINELS)
    assert not any(s in _all_text(world.db) for s in PII_SENTINELS)


def test_upload_is_audited_in_write_runs_without_content(world, tmp_path):
    path = _csv(tmp_path, [payment_row(1)])
    assert world.post("admin", path).status_code == 200
    (run,) = _runs(world.db)
    assert (run.source, run.resource_type, run.status) == ("virtualpos", "report_import", "completed")
    assert run.requested_by_user_id == world.admin.id and run.finished_at is not None
    payload = run.request_payload
    assert payload["report_type"] == "transacciones" and payload["filename"] == path.name
    assert len(payload["sha256"]) == 64 and payload["rows_total"] == 1
    assert "cid_" not in str(payload) and not any(s in str(payload) for s in PII_SENTINELS)


def test_suscriptores_report_is_accepted(world, tmp_path):
    path = _csv(tmp_path, [subscription_row(1)], kind="suscriptores", name="SuscriptoresPAT-VirtualPOS-1792546479.csv")
    r = world.post("admin", path)
    assert r.status_code == 200 and r.json()["report_type"] == "suscriptores"


@pytest.mark.parametrize("who", ["soporte", "ejecutivo", "jefatura", "coordinador"])
def test_other_roles_are_forbidden_and_nothing_is_written(world, tmp_path, who):
    r = world.post(who, _csv(tmp_path))
    assert r.status_code == 403
    assert world.db.scalar(select(func.count()).select_from(VpReportFile)) == 0 and not _runs(world.db)


def test_csrf_and_authentication_are_required(world, tmp_path):
    path = _csv(tmp_path)
    assert world.post("admin", path, csrf=False).status_code == 403
    anonymous = TestClient(app, base_url="https://testserver")
    app.dependency_overrides[crm_get_db] = lambda: world.db
    app.dependency_overrides[security_get_db] = lambda: world.db
    assert anonymous.post(URL, files={"report": (path.name, path.read_bytes(), "text/csv")}).status_code == 401
    assert world.db.scalar(select(func.count()).select_from(VpReportFile)) == 0


def test_same_file_twice_is_409_and_does_not_duplicate(world, tmp_path):
    path = _csv(tmp_path)
    assert world.post("admin", path).status_code == 200
    r = world.post("admin", path, name="renombrado.csv")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_loaded"
    assert world.db.scalar(select(func.count()).select_from(VpReportFile)) == 1
    assert world.db.scalar(select(func.count()).select_from(VpReportPayment)) == 3
    assert [x.status for x in _runs(world.db)] == ["completed", "already_loaded"]


def test_invalid_uploads_are_rejected_without_echoing_content(world, tmp_path):
    bad = tmp_path / "x.csv"
    bad.write_text("a,b,c\nSENTINELA-NOMBRE,2,3\n", encoding="utf-8")
    r = world.post("admin", bad)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_format"
    assert "SENTINELA" not in r.text
    assert world.post("admin", bad, name="datos.xlsx").status_code == 422  # extension
    assert world.post("admin", bad, name="vacio.csv", content=b"").status_code == 422
    assert world.db.scalar(select(func.count()).select_from(VpReportFile)) == 0
    assert all(x.status == "rejected" for x in _runs(world.db))


def test_oversized_upload_is_413(world, tmp_path, monkeypatch):
    monkeypatch.setattr(imports_route, "MAX_REPORT_BYTES", 100)
    r = world.post("admin", _csv(tmp_path))
    assert r.status_code == 413
    assert world.db.scalar(select(func.count()).select_from(VpReportFile)) == 0


def test_import_failure_is_500_with_a_label_only(world, tmp_path, monkeypatch, caplog):
    def boom(*_a, **_k):
        raise RuntimeError("SENTINELA-NOMBRE 00.000.001-K")

    monkeypatch.setattr(imp, "_apply_rejection_details", boom)
    with caplog.at_level(logging.DEBUG):
        r = world.post("admin", _csv(tmp_path, [rejected_payment_row(1)]))
    assert r.status_code == 500 and r.json()["detail"]["code"] == "import_failed"
    assert r.json()["detail"]["label"] == "rejections:RuntimeError"
    assert "SENTINELA" not in r.text and "SENTINELA" not in caplog.text
    (run,) = _runs(world.db)
    assert run.status == "failed" and "SENTINELA" not in str(run.request_payload) + str(run.error_message)
    assert world.db.scalar(select(func.count()).select_from(VpReportPayment)) == 0


def test_temporary_upload_is_removed(world, tmp_path, monkeypatch):
    seen: list[Path] = []
    original = imp.import_report

    def spy(db, path, **kw):
        seen.append(Path(path))
        assert Path(path).exists()
        return original(db, path, **kw)

    monkeypatch.setattr(imports_route.vp_report_import, "import_report", spy)
    assert world.post("admin", _csv(tmp_path)).status_code == 200
    assert seen and not seen[0].exists()


def test_route_is_registered_in_openapi():
    assert URL in app.openapi()["paths"]


# ---- permiso y migracion 0046 -----------------------------------------------------------------------------


def test_permission_is_admin_only(db_session):
    assert PERMISSION in PERMISSIONS and not PERMISSION.endswith(".view")
    assert PERMISSION not in support_permission_codes() and PERMISSION not in executive_permission_codes()
    seed_permissions(db_session)
    perm = db_session.scalar(select(Permission).where(Permission.code == PERMISSION))
    assert perm is not None and "VirtualPOS" in perm.description
    admin = db_session.scalar(select(Role).where(Role.name == "admin"))
    if admin is not None:
        assert PERMISSION in {p.code for p in admin.permissions}


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0046", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0046_chain_and_seeded_in_test_database():
    module = _load_migration()
    assert module.revision == "20261029_0046" and module.down_revision == "20261029_0045"
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from permissions where code = :c"), {"c": PERMISSION}).scalar() == 1


def test_migration_0046_grants_only_admin_and_is_idempotent():
    module = _load_migration()
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code = :c)"), {"c": PERMISSION})
            if not conn.execute(text("select 1 from roles where name='soporte'")).scalar():
                conn.execute(text("INSERT INTO roles (id, name, description) VALUES (:i, 'soporte', 't')"), {"i": uuid.uuid4()})
            if not conn.execute(text("select 1 from roles where name='admin'")).scalar():
                conn.execute(text("INSERT INTO roles (id, name, description) VALUES (:i, 'admin', 't')"), {"i": uuid.uuid4()})
            module.grant(conn)
            module.grant(conn)
            holders = {
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT roles.name FROM roles JOIN role_permissions rp ON rp.role_id = roles.id "
                        "JOIN permissions p ON p.id = rp.permission_id WHERE p.code = :c"
                    ),
                    {"c": PERMISSION},
                )
            }
            assert holders == {"admin"}
        finally:
            trans.rollback()
