import uuid
import zipfile
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.v1.routes import tch
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Role, User
from app.services.rbac import seed_permissions


class _ImportDb:
    def __init__(self, active_run=None) -> None:
        self.active_run = active_run
        self.added = []

    def scalar(self, _statement):
        return self.active_run

    def add(self, value) -> None:
        self.added.append(value)

    def commit(self) -> None:
        pass

    def refresh(self, _value) -> None:
        pass

    def close(self) -> None:
        pass


def _admin_client(monkeypatch) -> tuple[TestClient, str]:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    username = f"tch-admin-{uuid.uuid4().hex[:12]}"
    db = SessionLocal()
    try:
        # Aislamiento: el rol `admin` no puede darse por creado por otro test (corrido solo, no existe).
        admin = db.scalar(select(Role).where(Role.name == "admin"))
        if admin is None:
            admin = Role(name="admin")
            db.add(admin)
            db.flush()
        seed_permissions(db)  # con el rol ya creado, le asigna todos los permisos
        db.add(User(username=username, password_hash=hash_password("correct-password"), roles=[admin]))
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    login = client.post("/api/v1/auth/login", json={"username": username, "password": "correct-password"})
    assert login.status_code == 200
    return client, login.json()["csrf_token"]


def _xlsx_payload() -> bytes:
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    return stream.getvalue()


def test_tch_report_import_accepts_xlsx_for_admin(monkeypatch) -> None:
    client, csrf_token = _admin_client(monkeypatch)
    monkeypatch.setattr(tch, "_get_db", lambda: _ImportDb())
    captured: list[Path] = []

    def fake_import(_run_id: str, report_path: str) -> None:
        path = Path(report_path)
        captured.append(path)
        assert path.suffix == ".xlsx"
        assert path.exists()
        path.unlink()

    monkeypatch.setattr(tch, "_import_report_background", fake_import)
    response = client.post(
        "/api/v1/tch/import-report",
        headers={"X-CSRF-Token": csrf_token},
        files={"report": ("septiembre.xlsx", _xlsx_payload(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert len(captured) == 1


def test_tch_report_import_rejects_an_invalid_xlsx(monkeypatch) -> None:
    client, csrf_token = _admin_client(monkeypatch)
    monkeypatch.setattr(tch, "_get_db", lambda: _ImportDb())

    response = client.post(
        "/api/v1/tch/import-report",
        headers={"X-CSRF-Token": csrf_token},
        files={"report": ("septiembre.xlsx", b"not an xlsx")},
    )

    assert response.status_code == 422


def test_tch_report_import_rejects_when_another_run_is_active(monkeypatch) -> None:
    client, csrf_token = _admin_client(monkeypatch)
    active_run = type("ActiveRun", (), {"id": uuid.uuid4()})()
    monkeypatch.setattr(tch, "_get_db", lambda: _ImportDb(active_run))

    response = client.post(
        "/api/v1/tch/import-report",
        headers={"X-CSRF-Token": csrf_token},
        files={"report": ("septiembre.xlsx", _xlsx_payload())},
    )

    assert response.status_code == 409


def test_tch_report_import_requires_admin_role(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    username = f"tch-user-{uuid.uuid4().hex[:12]}"
    db = SessionLocal()
    try:
        role = Role(name=f"role-{uuid.uuid4().hex[:12]}")
        db.add(role)
        db.flush()
        db.add(User(username=username, password_hash=hash_password("correct-password"), roles=[role]))
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    login = client.post("/api/v1/auth/login", json={"username": username, "password": "correct-password"})
    csrf_token = login.json()["csrf_token"]
    response = client.post(
        "/api/v1/tch/import-report",
        headers={"X-CSRF-Token": csrf_token},
        files={"report": ("septiembre.xlsx", _xlsx_payload())},
    )

    assert response.status_code == 403


class _DuplicateReportDb(_ImportDb):
    """Sin corrida activa (1.a consulta) y con el sha256 ya registrado (2.a consulta)."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def scalar(self, _statement):
        self.calls += 1
        return None if self.calls == 1 else uuid.uuid4()


def test_tch_report_import_rejects_a_report_already_loaded_by_sha256(monkeypatch) -> None:
    client, csrf_token = _admin_client(monkeypatch)
    db = _DuplicateReportDb()
    monkeypatch.setattr(tch, "_get_db", lambda: db)
    launched: list[str] = []
    monkeypatch.setattr(tch, "_import_report_background", lambda run_id, path: launched.append(path))

    response = client.post(
        "/api/v1/tch/import-report",
        headers={"X-CSRF-Token": csrf_token},
        files={"report": ("20260101 TCH IG DICIEMBRE 2025.xlsx", _xlsx_payload())},
    )

    assert response.status_code == 409
    assert "ya fue cargado" in response.json()["detail"].lower()
    assert launched == []
    assert db.added == []  # no se crea corrida ETL para un duplicado
