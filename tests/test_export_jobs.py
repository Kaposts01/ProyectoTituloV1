"""EXP-06 (d114 b): exportacion en segundo plano con umbral, estado, descarga y caducidad. Datos SINTETICOS.

El job corre en linea (se reemplaza `export_jobs._submit`) para que la prueba sea determinista.
"""

import csv
import io
import logging
import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Permission, Role, User
from app.models.crm import Charge, Client, Subscription
from app.models.export_job import ExportJob
from app.models.write_run import WriteRun
from app.services import export_jobs
from app.services.rbac import seed_permissions

_TAG = "zx[0-9a-f]{8}"
SECRET_RUT = "77777777-7"


def _sfx() -> str:
    return "zx" + "".join(random.choice("0123456789abcdef") for _ in range(8))


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    monkeypatch.setattr(settings, "export_job_dir", str(tmp_path / "jobs"))
    monkeypatch.setattr(settings, "export_background_threshold_rows", 1)
    monkeypatch.setattr(export_jobs, "_submit", lambda fn, *args: fn(*args))
    yield
    db = SessionLocal()
    try:
        params = {"tag": _TAG}
        for stmt in (
            "DELETE FROM write_runs WHERE request_payload->>'username' ~ ('^xj-' || :tag)",
            "DELETE FROM export_jobs WHERE requested_by_user_id IN (SELECT id FROM users WHERE username ~ ('^xj-' || :tag))",
            "DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username ~ ('^xj-' || :tag))",
            "DELETE FROM users WHERE username ~ ('^xj-' || :tag)",
            "DELETE FROM roles WHERE name ~ ('^xj-' || :tag)",
            "DELETE FROM charges WHERE external_id ~ :tag",
            "DELETE FROM subscriptions WHERE external_id ~ :tag",
            "DELETE FROM clients WHERE external_id ~ :tag",
        ):
            db.execute(text(stmt), params)
        db.commit()
    finally:
        db.close()


def _login(suffix: str, perms: list[str]) -> tuple[TestClient, dict[str, str]]:
    db = SessionLocal()
    try:
        seed_permissions(db)
        plist = [db.scalar(select(Permission).where(Permission.code == p)) for p in perms]
        role = Role(name=f"xj-{suffix}", permissions=plist)
        db.add_all([role, User(username=f"xj-{suffix}", password_hash=hash_password("Pw-xj-12345"), is_active=True, roles=[role])])
        db.commit()
    finally:
        db.close()
    client = TestClient(app, base_url="https://testserver")
    resp = client.post("/api/v1/auth/login", json={"username": f"xj-{suffix}", "password": "Pw-xj-12345"})
    assert resp.status_code == 200
    return client, {"X-CSRF-Token": resp.json()["csrf_token"]}


def _seed(sfx: str) -> None:
    db = SessionLocal()
    try:
        db.add_all([
            Client(source="virtualpos1", external_id=f"cl-{sfx}", first_name="Ana", last_name="Prueba", social_id=SECRET_RUT),
            Subscription(source="virtualpos1", external_id=f"sub-{sfx}", client_external_id=f"cl-{sfx}", status="activa"),
            Charge(source="virtualpos1", external_id=f"c1-{sfx}", subscription_external_id=f"sub-{sfx}", status="pagado",
                   charge_date="2012-03-02", amount="1000", currency="CLP"),
            Charge(source="virtualpos1", external_id=f"c2-{sfx}", subscription_external_id=f"sub-{sfx}", status="rechazado",
                   charge_date="2012-03-03", amount="1000", currency="CLP"),
        ])
        db.commit()
    finally:
        db.close()


PARAMS = {"date_from": "2012-03-01", "date_to": "2012-03-31", "canal": "virtualpos1"}


def test_count_reports_background_and_job_runs_downloads_and_audits(caplog) -> None:
    sfx = _sfx()
    _seed(sfx)
    client, csrf = _login(sfx, ["virtualpos.charges.view", "export.pii"])
    count = client.get("/api/v1/export/cobros/count", params=PARAMS).json()
    assert count["rows"] == 2 and count["background"] is True and count["background_threshold"] == 1

    assert client.post("/api/v1/export/cobros/jobs", params=PARAMS).status_code == 403  # sin CSRF
    caplog.set_level(logging.INFO)
    resp = client.post("/api/v1/export/cobros/jobs", params={**PARAMS, "query": SECRET_RUT, "filter_field": "all"},
                       headers=csrf)
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "completed" and job["rows_written"] == 0  # el RUT no es campo de busqueda de cobros
    job = client.post("/api/v1/export/cobros/jobs", params=PARAMS, headers=csrf).json()
    assert job["status"] == "completed" and job["rows_estimated"] == 2 and job["rows_written"] == 2
    assert job["include_pii"] is True and job["download_url"].endswith("/download")

    status = client.get(f"/api/v1/export/jobs/{job['id']}").json()
    assert status["status"] == "completed"
    listed = client.get("/api/v1/export/jobs").json()["items"]
    assert {item["id"] for item in listed} >= {job["id"]}

    download = client.get(job["download_url"])
    assert download.status_code == 200 and "attachment" in download.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(download.content.decode("utf-8-sig"))))
    assert [r["ID de cobro"] for r in rows] == [f"c1-{sfx}", f"c2-{sfx}"]
    assert rows[0]["RUT del cliente"] == "77.777.777-7"  # con export.pii el archivo lleva PII (formato es-CL, QA-08)

    # nada personal en la tabla de jobs ni en los logs
    db = SessionLocal()
    try:
        stored = db.scalars(select(ExportJob).where(ExportJob.id.in_([uuid.UUID(job["id"])]))).all()
        all_jobs = db.scalars(select(ExportJob).where(ExportJob.requested_by_user_id == stored[0].requested_by_user_id)).all()
        assert all(SECRET_RUT not in repr(j.filters) for j in all_jobs)
        audits = db.scalars(select(WriteRun).where(WriteRun.request_payload["username"].astext == f"xj-{sfx}")).all()
        endpoints = [a.request_payload["endpoint"] for a in audits]
        assert "export/cobros/jobs" in endpoints and "export/cobros/jobs/download" in endpoints
        assert all(SECRET_RUT not in repr(a.request_payload) for a in audits)
    finally:
        db.close()
    # logs de la app (el cliente HTTP de prueba registra su propia URL, que no es un log del backend)
    app_logs = " ".join(r.getMessage() for r in caplog.records if r.name.startswith("app."))
    assert "Exportacion en segundo plano" in app_logs and SECRET_RUT not in app_logs


def test_job_without_pii_permission_omits_personal_columns() -> None:
    sfx = _sfx()
    _seed(sfx)
    client, csrf = _login(sfx, ["virtualpos.charges.view"])
    job = client.post("/api/v1/export/cobros/jobs", params=PARAMS, headers=csrf).json()
    assert job["include_pii"] is False
    content = client.get(job["download_url"]).content.decode("utf-8-sig")
    assert "RUT del cliente" not in content and SECRET_RUT not in content and "77.777.777-7" not in content


def test_permissions_owner_only_and_limits() -> None:
    sfx = _sfx()
    _seed(sfx)
    owner, csrf = _login(sfx, ["virtualpos.charges.view"])
    other, _other_csrf = _login(_sfx(), ["virtualpos.charges.view"])
    nobody, nobody_csrf = _login(_sfx(), ["dashboard.view"])
    assert nobody.post("/api/v1/export/cobros/jobs", params=PARAMS, headers=nobody_csrf).status_code == 403
    job = owner.post("/api/v1/export/cobros/jobs", params=PARAMS, headers=csrf).json()
    assert other.get(f"/api/v1/export/jobs/{job['id']}").status_code == 404
    assert other.get(f"/api/v1/export/jobs/{job['id']}/download").status_code == 404
    assert owner.get(f"/api/v1/export/jobs/{uuid.uuid4()}").status_code == 404


def test_too_many_active_jobs_is_429(monkeypatch) -> None:
    sfx = _sfx()
    _seed(sfx)
    monkeypatch.setattr(export_jobs, "_submit", lambda fn, *args: None)  # quedan en cola
    monkeypatch.setattr(settings, "export_job_max_active_per_user", 1)
    client, csrf = _login(sfx, ["virtualpos.charges.view"])
    first = client.post("/api/v1/export/cobros/jobs", params=PARAMS, headers=csrf).json()
    assert first["status"] == "queued" and first["download_url"] is None
    assert client.get(f"/api/v1/export/jobs/{first['id']}/download").status_code == 409
    second = client.post("/api/v1/export/cobros/jobs", params=PARAMS, headers=csrf)
    assert second.status_code == 429 and second.json()["detail"]["code"] == "too_many_export_jobs"


def test_expired_job_deletes_file_and_returns_410() -> None:
    sfx = _sfx()
    _seed(sfx)
    client, csrf = _login(sfx, ["virtualpos.charges.view"])
    job = client.post("/api/v1/export/cobros/jobs", params=PARAMS, headers=csrf).json()
    db = SessionLocal()
    try:
        row = db.get(ExportJob, uuid.UUID(job["id"]))
        path = row.file_path
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()
    resp = client.get(job["download_url"])
    assert resp.status_code == 410 and resp.json()["detail"]["code"] == "export_job_expired"
    import os

    assert not os.path.exists(path)
    assert client.get(f"/api/v1/export/jobs/{job['id']}").json()["status"] == "expired"


def test_failed_job_is_labelled_without_pii(monkeypatch) -> None:
    sfx = _sfx()
    _seed(sfx)
    client, csrf = _login(sfx, ["virtualpos.charges.view"])

    def boom(*_args, **_kwargs):
        raise RuntimeError(f"fallo con {SECRET_RUT}")

    monkeypatch.setattr(export_jobs, "iter_rows", boom)
    job = client.post("/api/v1/export/cobros/jobs", params=PARAMS, headers=csrf).json()
    assert job["status"] == "failed" and job["error_label"] == "run:RuntimeError"


def test_threshold_rule() -> None:
    assert export_jobs.needs_background(2) is True
    assert export_jobs.needs_background(1) is False
