"""REP-02: POST /api/v1/scheduler/reports/test (solo administrador). SMTP simulado; destinatario ficticio."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.main import app
from app.models.auth import Role, User
from app.models.report_dispatch import ReportDispatch
from app.services import alerts
from tests.test_scheduled_reports import FakeSMTP
from tests.test_tch_import import _admin_client

URL = "/api/v1/scheduler/reports/test"
TO = "persona@ejemplo.org"


@pytest.fixture(autouse=True)
def _smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.messages, FakeSMTP.fail_with = [], [], None
    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(alerts.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(settings, "alert_smtp_host", "smtp.ejemplo.test")
    monkeypatch.setattr(settings, "alert_smtp_port", 587)
    monkeypatch.setattr(settings, "alert_smtp_user", "")
    monkeypatch.setattr(settings, "alert_smtp_password", "")
    monkeypatch.setattr(settings, "report_email_to", TO)
    monkeypatch.setattr(settings, "reports_weekly_enabled", False)  # la prueba ignora las banderas
    monkeypatch.setattr(settings, "reports_monthly_enabled", False)
    yield
    db = SessionLocal()
    try:
        db.execute(delete(ReportDispatch).where(ReportDispatch.period_key.like("test:%")))
        db.commit()
    finally:
        db.close()


def test_anonymous_gets_401() -> None:
    client = TestClient(app, base_url="https://testserver")
    assert client.post(URL, json={"kind": "weekly"}).status_code == 401
    assert FakeSMTP.messages == []


def test_non_admin_gets_403_and_nothing_is_sent(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    username = f"rep-user-{uuid.uuid4().hex[:12]}"
    db = SessionLocal()
    try:
        role = Role(name=f"role-{uuid.uuid4().hex[:12]}")
        db.add(role)
        db.flush()
        db.add(User(username=username, password_hash=hash_password("correct-password"), roles=[role]))
        db.commit()
    finally:
        db.close()
    client = TestClient(app, base_url="https://testserver")
    login = client.post("/api/v1/auth/login", json={"username": username, "password": "correct-password"})
    response = client.post(URL, json={"kind": "weekly"}, headers={"X-CSRF-Token": login.json()["csrf_token"]})
    assert response.status_code == 403
    assert FakeSMTP.messages == [] and FakeSMTP.instances == []


def test_admin_without_csrf_gets_403(monkeypatch) -> None:
    client, _csrf = _admin_client(monkeypatch)
    assert client.post(URL, json={"kind": "weekly"}).status_code == 403
    assert FakeSMTP.messages == []


@pytest.mark.parametrize("kind", ["weekly", "monthly"])
def test_admin_sends_a_test_report_without_exposing_addresses(monkeypatch, kind) -> None:
    client, csrf = _admin_client(monkeypatch)
    response = client.post(URL, json={"kind": kind}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "sent" and body["kind"] == kind and body["recipients"] == 1
    assert body["period_key"].startswith("test:")
    assert TO not in response.text
    assert len(FakeSMTP.messages) == 1
    assert FakeSMTP.messages[0]["To"] == TO and "[SynkmetriX ·" in FakeSMTP.messages[0]["Subject"]


def test_invalid_kind_is_rejected(monkeypatch) -> None:
    client, csrf = _admin_client(monkeypatch)
    assert client.post(URL, json={"kind": "daily"}, headers={"X-CSRF-Token": csrf}).status_code == 422
    assert FakeSMTP.messages == []


def test_missing_recipient_returns_409_and_sends_nothing(monkeypatch) -> None:
    monkeypatch.setattr(settings, "report_email_to", "")
    client, csrf = _admin_client(monkeypatch)
    response = client.post(URL, json={"kind": "weekly"}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "no_recipient"
    assert FakeSMTP.instances == []


def test_smtp_failure_returns_502_with_class_name_only(monkeypatch) -> None:
    FakeSMTP.fail_with = OSError(f"caido {TO}")
    client, csrf = _admin_client(monkeypatch)
    response = client.post(URL, json={"kind": "weekly"}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 502
    assert response.json()["detail"]["error_class"] == "OSError"
    assert TO not in response.text
