"""L7-IMPORT (d151): panel unificado «Importar reportes de plataformas».

* `POST /api/v1/imports/payku-reports` (permiso nuevo `payku.reports.import`, migracion 0071): RBAC, CSRF, archivo
  valido, encabezados invalidos, archivo duplicado (sha256) y sin datos personales en respuesta, logs ni auditoria.
* `GET /api/v1/imports/status`: ultima carga por canal y tipo (fecha, nombre, filas, resultado) y aviso de mas de 7 dias,
  solo de los canales que el usuario puede cargar.
* VirtualPOS: aviso `data_older_than_max_age` en la respuesta del POST existente.

Solo fixtures SINTETICAS (Excel/CSV generados en el test). Autenticacion real (JWT + cookie + CSRF).
"""

import importlib.util
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from billing_requests_support import client_for, make_role, make_user
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from vp_reports_support import PEPPER, payment_row, write_report

from app.api.v1.routes.crm import get_db as crm_get_db
from app.core.config import settings
from app.core.security import get_db as security_get_db
from app.db.session import engine
from app.main import app
from app.models.auth import Permission
from app.models.payku_report import PkReportFile, PkReportTransaction
from app.models.tch import TchFileLoad
from app.models.write_run import WriteRun
from app.services.rbac import (
    PERMISSIONS,
    executive_permission_codes,
    seed_permissions,
    support_permission_codes,
)
from tests.test_payku_report_import import DATA_TX, PII, data_tx_row, write_data_tx

PAYKU_URL = "/api/v1/imports/payku-reports"
VP_URL = "/api/v1/imports/virtualpos-reports"
STATUS_URL = "/api/v1/imports/status"
PERMISSION = "payku.reports.import"
ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "alembic" / "versions" / "20261104_0071_seed_payku_reports_import_permission.py"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
        self.admin = make_user(db, make_role(db, "admin", set(PERMISSIONS)))
        self.soporte = make_user(db, make_role(db, "soporte", support_permission_codes()))
        self.ejecutivo = make_user(db, make_role(db, "ejecutivo", executive_permission_codes()))
        self.payku_only = make_user(db, make_role(db, "carga_payku", {PERMISSION}))

    def post(self, who, url, path: Path, *, csrf=True, name=None, content=None, content_type=XLSX):
        client, headers = client_for(self.db, getattr(self, who))
        data = path.read_bytes() if content is None else content
        return client.post(url, files={"report": (name or path.name, data, content_type)}, headers=headers if csrf else {})

    def get(self, who, url):
        client, _ = client_for(self.db, getattr(self, who))
        return client.get(url)


@pytest.fixture
def world(db_session):
    return World(db_session)


def _runs(db, source="payku"):
    return list(db.scalars(select(WriteRun).where(WriteRun.operation == "import_report", WriteRun.source == source)))


def _files(db) -> int:
    return db.scalar(select(func.count()).select_from(PkReportFile))


def _all_text(db) -> str:
    parts = []
    for table in ("p_report_files", "p_report_transactions", "write_runs"):
        parts += [r[0] for r in db.execute(text(f"SELECT to_jsonb(t)::text FROM {table} t"))]
    return "\n".join(parts)


# ---- Payku: POST /api/v1/imports/payku-reports -------------------------------------------------------------------


def test_payku_valid_report_returns_a_summary_without_personal_data(world, tmp_path, caplog):
    path = write_data_tx(tmp_path / "Payku_dataTransacciones.xlsx")
    with caplog.at_level(logging.DEBUG):
        r = world.post("admin", PAYKU_URL, path)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["report_type"], body["status"], body["already_loaded"]) == ("transacciones", "completed", False)
    assert (body["rows_total"], body["rows_new"], body["rows_skipped"]) == (2, 2, 0)
    assert body["sheets"] == ["data_transacciones"]
    assert world.db.scalar(select(func.count()).select_from(PkReportTransaction)) == 2
    assert not any(s in r.text for s in PII) and not any(s in caplog.text for s in PII)
    assert not any(s in _all_text(world.db) for s in PII)
    (run,) = _runs(world.db)
    assert (run.status, run.resource_type) == ("completed", "report_import")
    assert run.request_payload["filename"] == path.name and len(run.request_payload["sha256"]) == 64


def test_payku_invalid_headers_are_rejected_naming_only_the_columns(world, tmp_path):
    header = [h for h in DATA_TX if h != "Comisión"]  # falta una columna obligatoria de la firma
    path = write_data_tx(tmp_path / "Payku_dataTransacciones.xlsx", [data_tx_row(1)], header=header)
    r = world.post("admin", PAYKU_URL, path)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "invalid_format" and "comision" in detail["message"]
    assert not any(s in r.text for s in PII) and "tzp" not in r.text
    assert _files(world.db) == 0 and [x.status for x in _runs(world.db)] == ["rejected"]


def test_payku_unknown_sheet_extension_and_corrupt_files_are_422(world, tmp_path):
    unknown = write_data_tx(tmp_path / "otro.xlsx", [{"a": 1}], header=["Columna A", "Columna B"])
    assert world.post("admin", PAYKU_URL, unknown).json()["detail"]["code"] == "invalid_format"
    csv = tmp_path / "datos.csv"
    csv.write_text("a,b\n1,2\n", encoding="utf-8")
    assert world.post("admin", PAYKU_URL, csv).status_code == 422
    assert world.post("admin", PAYKU_URL, csv, name="roto.xlsx").status_code == 422  # no es un libro real
    assert world.post("admin", PAYKU_URL, csv, name="vacio.xlsx", content=b"").status_code == 422
    assert _files(world.db) == 0
    assert all(x.status == "rejected" for x in _runs(world.db))


def test_payku_duplicate_file_is_409_even_if_renamed(world, tmp_path):
    path = write_data_tx(tmp_path / "Payku_dataTransacciones.xlsx")
    assert world.post("admin", PAYKU_URL, path).status_code == 200
    r = world.post("admin", PAYKU_URL, path, name="renombrado.xlsx")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_loaded"
    assert _files(world.db) == 1
    assert [x.status for x in _runs(world.db)] == ["completed", "already_loaded"]


@pytest.mark.parametrize("who", ["soporte", "ejecutivo"])
def test_payku_other_roles_are_forbidden_and_nothing_is_written(world, tmp_path, who):
    r = world.post(who, PAYKU_URL, write_data_tx(tmp_path / "p.xlsx"))
    assert r.status_code == 403
    assert _files(world.db) == 0 and not _runs(world.db)


def test_payku_permission_alone_is_enough_and_csrf_and_auth_are_required(world, tmp_path):
    path = write_data_tx(tmp_path / "p.xlsx")
    assert world.post("payku_only", PAYKU_URL, path, csrf=False).status_code == 403
    anonymous = TestClient(app, base_url="https://testserver")
    assert anonymous.post(PAYKU_URL, files={"report": (path.name, path.read_bytes(), XLSX)}).status_code == 401
    assert _files(world.db) == 0
    assert world.post("payku_only", PAYKU_URL, path).status_code == 200


# ---- GET /api/v1/imports/status ----------------------------------------------------------------------------------


def _channel(body, name):
    return next(c for c in body["channels"] if c["channel"] == name)


def test_status_lists_every_channel_for_admin_with_expected_types(world):
    r = world.get("admin", STATUS_URL)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["max_age_days"] == 7
    assert [c["channel"] for c in body["channels"]] == ["toku", "virtualpos", "payku", "tch"]
    toku = [x["report_type"] for x in _channel(body, "toku")["reports"]]
    assert toku[:6] == ["productos", "intentos", "deudas", "clientes", "pagos", "liquidaciones"]
    assert [x["report_type"] for x in _channel(body, "virtualpos")["reports"]][:2] == ["transacciones", "suscriptores"]


def test_status_is_filtered_by_permission_and_forbidden_without_any(world):
    body = world.get("payku_only", STATUS_URL).json()
    assert [c["channel"] for c in body["channels"]] == ["payku"]
    r = world.get("soporte", STATUS_URL)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "permission_denied"
    assert TestClient(app, base_url="https://testserver").get(STATUS_URL).status_code == 401


def test_status_shows_the_last_load_with_name_rows_and_result(world, tmp_path):
    path = write_data_tx(tmp_path / "Payku_dataTransacciones.xlsx")
    assert world.post("admin", PAYKU_URL, path).status_code == 200
    world.db.add(TchFileLoad(file_sha256="f" * 64, file_name="reporte_tch.xlsx", rows_loaded=12, result="fallido",
                             loaded_at=datetime.now(UTC)))
    world.db.add(TchFileLoad(file_sha256="e" * 64, file_name="reporte_ok.xlsx", rows_loaded=10, result="cargado",
                             loaded_at=datetime.now(UTC) - timedelta(days=10)))
    world.db.flush()
    body = world.get("admin", STATUS_URL).json()
    payku = {x["report_type"]: x for x in _channel(body, "payku")["reports"]}
    tx = payku["transacciones"]
    assert (tx["filename"], tx["rows_total"], tx["result"], tx["is_stale"]) == (path.name, 2, "completed", False)
    assert tx["loaded_at"] and tx["age_days"] == 0
    assert payku["liquidaciones"]["result"] is None  # tipo esperado sin cargas
    (tch,) = _channel(body, "tch")["reports"]
    # ultima carga intentada (fallida) y frescura de la ultima carga buena (10 dias: aviso)
    assert (tch["filename"], tch["rows_total"], tch["result"]) == ("reporte_tch.xlsx", 12, "fallido")
    assert tch["is_stale"] is True and _channel(body, "tch")["stale_types"] == ["reporte"]
    assert "f" * 64 not in str(body) and str(world.admin.id) not in str(body)


def test_status_and_vp_upload_warn_when_the_data_is_older_than_7_days(world, tmp_path):
    old_epoch = int((datetime.now(UTC) - timedelta(days=20)).timestamp())
    path = write_report(tmp_path / f"TransaccionesPAT-VirtualPOS-{old_epoch}.csv", "transacciones", [payment_row(1)])
    r = world.post("admin", VP_URL, path, content_type="text/csv")
    assert r.status_code == 200, r.text
    assert "data_older_than_max_age" in r.json()["warnings"] and r.json()["data_age_days"] >= 19
    vp = _channel(world.get("admin", STATUS_URL).json(), "virtualpos")
    tx = next(x for x in vp["reports"] if x["report_type"] == "transacciones")
    assert tx["is_stale"] is True and tx["filename"] == path.name and vp["stale_types"] == ["transacciones"]


# ---- permiso y migracion 0071 ------------------------------------------------------------------------------------


def test_permission_is_admin_only(db_session):
    assert PERMISSION in PERMISSIONS and not PERMISSION.endswith(".view")
    assert PERMISSION not in support_permission_codes() and PERMISSION not in executive_permission_codes()
    seed_permissions(db_session)
    perm = db_session.scalar(select(Permission).where(Permission.code == PERMISSION))
    assert perm is not None and "Payku" in perm.description


def _load_migration():
    spec = importlib.util.spec_from_file_location("mig_0071", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0071_chain_grants_only_admin_and_is_reversible():
    module = _load_migration()
    assert (module.revision, module.down_revision) == ("20261104_0071", "20261103_0068")
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            for role in ("admin", "soporte"):
                if not conn.execute(text("select 1 from roles where name = :n"), {"n": role}).scalar():
                    conn.execute(text("INSERT INTO roles (id, name, description) VALUES (:i, :n, 't')"),
                                 {"i": uuid.uuid4(), "n": role})
            module.revoke(conn)
            assert conn.execute(text("select count(*) from permissions where code = :c"), {"c": PERMISSION}).scalar() == 0
            module.grant(conn)
            module.grant(conn)  # idempotente
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
            module.revoke(conn)
            assert conn.execute(text("select count(*) from permissions where code = :c"), {"c": PERMISSION}).scalar() == 0
        finally:
            trans.rollback()
