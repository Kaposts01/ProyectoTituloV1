"""RT-14: panel de salud de webhooks y reproceso manual. Datos sinteticos; sin red ni proveedores."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.v1.routes.crm import get_db as crm_get_db
from app.core.config import settings
from app.core.security import ACCESS_COOKIE, CSRF_HEADER, create_access_token
from app.core.security import get_db as security_get_db
from app.db.session import engine
from app.main import app
from app.models.auth import Permission, Role, User
from app.models.webhook_event import WebhookEvent
from app.services import rbac
from app.services.webhook_health import queue_health
from app.services.webhook_processor import requeue_events

BASE = "/api/v1/admin/webhooks"
PII_RUT = "12.345.678-5"
PII_MAIL = "juan.perez@example.com"


@pytest.fixture(autouse=True)
def _jwt(monkeypatch):
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    yield
    app.dependency_overrides.pop(crm_get_db, None)
    app.dependency_overrides.pop(security_get_db, None)


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    session.execute(delete(WebhookEvent))  # filas confirmadas por otras pruebas no cuentan (se revierte al final)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _client(db: Session, codes: set[str]) -> tuple[TestClient, str]:
    rbac.seed_permissions(db)
    perms = {p.code: p for p in db.query(Permission)}
    role = Role(name=f"r-{uuid.uuid4().hex[:8]}")
    role.permissions = [perms[c] for c in sorted(codes)]
    user = User(username=f"u-{uuid.uuid4().hex[:10]}", password_hash="x", is_active=True, roles=[role])
    db.add_all([role, user])
    db.flush()
    token, csrf = create_access_token(user)
    app.dependency_overrides[crm_get_db] = lambda: db
    app.dependency_overrides[security_get_db] = lambda: db
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(ACCESS_COOKIE, token)
    return client, csrf


def _ev(db: Session, source="toku", status="failed", minutes_ago=10, code="UNEXPECTED", processed=True) -> WebhookEvent:
    now = datetime.now(UTC)
    row = WebhookEvent(
        source=source, event_type="subscription.updated", resource_type="subscription",
        resource_external_id=PII_RUT, subscription_external_id=PII_RUT, payload_masked={"email": PII_MAIL},
        dedupe_key=uuid.uuid4().hex + uuid.uuid4().hex, status=status, attempts=5 if status == "failed" else 1,
        last_error_code=code, received_at=now - timedelta(minutes=minutes_ago), next_attempt_at=now,
        processed_at=(now - timedelta(minutes=minutes_ago) + timedelta(seconds=30)) if processed else None)
    db.add(row)
    db.flush()
    return row


def test_permission_is_admin_only() -> None:
    assert rbac.WEBHOOKS_MANAGE in rbac.PERMISSIONS
    assert rbac.WEBHOOKS_MANAGE not in rbac.support_permission_codes()
    assert rbac.WEBHOOKS_MANAGE not in rbac.executive_permission_codes()


def test_endpoints_require_session_and_permission(db_session) -> None:
    assert TestClient(app, base_url="https://testserver").get(f"{BASE}/health").status_code == 401
    client, csrf = _client(db_session, {"sync_runs.view", "dashboard.view"})
    assert client.get(f"{BASE}/health").status_code == 403
    assert client.get(f"{BASE}/events").status_code == 403
    assert client.post(f"{BASE}/requeue", json={"all_failed": True}, headers={CSRF_HEADER: csrf}).status_code == 403


def test_health_counts_lag_and_last_event_without_pii(db_session) -> None:
    _ev(db_session, "toku", "failed")
    _ev(db_session, "toku", "done", minutes_ago=5, code=None)
    _ev(db_session, "toku", "pending", minutes_ago=45, code=None, processed=False)
    _ev(db_session, "payku", "ignored", code="NO_RESOURCE")
    client, _ = _client(db_session, {rbac.WEBHOOKS_MANAGE})
    response = client.get(f"{BASE}/health")
    assert response.status_code == 200
    body = response.json()
    assert PII_RUT not in response.text and PII_MAIL not in response.text
    by_source = {s["source"]: s for s in body["sources"]}
    assert set(by_source) == {"toku", "virtualpos", "payku"}
    toku = by_source["toku"]
    assert (toku["counts"]["failed"], toku["counts"]["done"], toku["counts"]["pending"]) == (1, 1, 1)
    assert 44 <= toku["pending_lag_minutes"] <= 46
    assert toku["done_last_24h"] == 1 and toku["avg_processing_seconds_24h"] == pytest.approx(30, abs=1)
    assert by_source["virtualpos"]["last_received_at"] is None
    assert {c["code"] for c in body["error_codes_24h"]} == {"UNEXPECTED", "NO_RESOURCE"}
    assert body["processor_enabled"] is settings.webhook_processor_enabled


def test_events_list_filters_and_hides_payload_and_resource_ids(db_session) -> None:
    failed = _ev(db_session, "toku", "failed")
    _ev(db_session, "payku", "failed")
    _ev(db_session, "toku", "done", code=None)
    client, _ = _client(db_session, {rbac.WEBHOOKS_MANAGE})
    response = client.get(f"{BASE}/events", params={"source": "toku"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["id"] for i in items] == [str(failed.id)]
    assert "payload_masked" not in items[0] and "resource_external_id" not in items[0]
    assert PII_RUT not in response.text and PII_MAIL not in response.text
    assert client.get(f"{BASE}/events", params={"status": "raro"}).status_code == 422
    assert client.get(f"{BASE}/events", params={"source": "otro"}).status_code == 422
    assert len(client.get(f"{BASE}/events", params={"status": "done"}).json()["items"]) == 1


def test_requeue_by_id_needs_csrf_and_only_moves_failed_or_ignored(db_session) -> None:
    failed = _ev(db_session, "toku", "failed")
    ignored = _ev(db_session, "payku", "ignored", code="NO_RESOURCE")
    done = _ev(db_session, "toku", "done", code=None)
    client, csrf = _client(db_session, {rbac.WEBHOOKS_MANAGE})
    ids = [str(failed.id), str(ignored.id), str(done.id)]
    assert client.post(f"{BASE}/requeue", json={"ids": ids}).status_code == 403  # sin CSRF
    response = client.post(f"{BASE}/requeue", json={"ids": ids}, headers={CSRF_HEADER: csrf})
    assert response.status_code == 200 and response.json()["requeued"] == 2
    db_session.expire_all()
    for row in (failed, ignored):
        got = db_session.get(WebhookEvent, row.id)
        assert (got.status, got.attempts, got.last_error_code, got.processed_at) == ("pending", 0, None, None)
    assert db_session.get(WebhookEvent, done.id).status == "done"


def test_requeue_all_failed_by_source_and_bad_requests(db_session) -> None:
    toku = _ev(db_session, "toku", "failed")
    payku = _ev(db_session, "payku", "failed")
    ignored = _ev(db_session, "toku", "ignored", code="NO_RESOURCE")
    client, csrf = _client(db_session, {rbac.WEBHOOKS_MANAGE})
    headers = {CSRF_HEADER: csrf}
    assert client.post(f"{BASE}/requeue", json={}, headers=headers).status_code == 422
    assert client.post(f"{BASE}/requeue", json={"ids": ["no-uuid"]}, headers=headers).status_code == 422
    assert client.post(f"{BASE}/requeue", json={"ids": []}, headers=headers).status_code == 422
    assert client.post(f"{BASE}/requeue", json={"all_failed": True, "source": "x"}, headers=headers).status_code == 422
    response = client.post(f"{BASE}/requeue", json={"all_failed": True, "source": "toku"}, headers=headers)
    assert response.json()["requeued"] == 1
    db_session.expire_all()
    assert db_session.get(WebhookEvent, toku.id).status == "pending"
    assert db_session.get(WebhookEvent, payku.id).status == "failed"
    assert db_session.get(WebhookEvent, ignored.id).status == "ignored"  # los ignorados solo se reencolan por id


def test_requeue_service_with_empty_ids_is_a_noop(db_session) -> None:
    assert requeue_events(db_session, []) == 0


def test_queue_health_of_an_empty_queue(db_session) -> None:
    health = queue_health(db_session)
    assert all(sum(s["counts"].values()) == 0 for s in health["sources"])
    assert health["error_codes_24h"] == []
