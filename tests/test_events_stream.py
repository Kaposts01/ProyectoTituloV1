"""RT-11: SSE de cambios de estado (`GET /api/v1/events/stream`). Datos sinteticos; sin red ni proveedores."""

import json
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1.routes import events
from app.api.v1.routes.crm import get_db as crm_get_db
from app.core.config import settings
from app.core.security import ACCESS_COOKIE, create_access_token
from app.core.security import get_db as security_get_db
from app.db.session import engine
from app.main import app
from app.models.auth import Permission, Role, User
from app.models.status_change import StatusChangeEvent
from app.scheduler import event_bus
from app.services.rbac import seed_permissions

URL = "/api/v1/events/stream"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    monkeypatch.setattr(settings, "events_stream_poll_seconds", 0.2)
    monkeypatch.setattr(settings, "events_stream_max_seconds", 0.8)
    yield
    app.dependency_overrides.pop(crm_get_db, None)
    app.dependency_overrides.pop(security_get_db, None)


@pytest.fixture
def db_session(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    @contextmanager
    def _same_session():
        yield session

    monkeypatch.setattr(events, "_open_session", _same_session)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _client(db: Session, codes: set[str]) -> TestClient:
    seed_permissions(db)
    perms = {p.code: p for p in db.query(Permission)}
    role = Role(name=f"r-{uuid.uuid4().hex[:8]}")
    role.permissions = [perms[c] for c in sorted(codes)]
    user = User(username=f"u-{uuid.uuid4().hex[:10]}", password_hash="x", is_active=True, roles=[role])
    db.add_all([role, user])
    db.flush()
    token, _csrf = create_access_token(user)
    app.dependency_overrides[crm_get_db] = lambda: db
    app.dependency_overrides[security_get_db] = lambda: db
    client = TestClient(app, base_url="https://testserver")
    client.cookies.set(ACCESS_COOKIE, token)
    return client


def _ev(db: Session, *, at: datetime, kind="status_changed", field="status", frm="ACTIVE", to="CANCELLED",
        ext="sub_1", source="toku", baseline=False, entity="subscription") -> StatusChangeEvent:
    row = StatusChangeEvent(
        entity_type=entity, source=source, external_id=ext, subscription_external_id=ext, event_kind=kind, field=field,
        from_value=frm, to_value=to, detected_at=at, is_baseline=baseline, dedupe_key=uuid.uuid4().hex + uuid.uuid4().hex)
    db.add(row)
    db.flush()
    return row


def _parse_sse(text: str) -> list[dict]:
    out = []
    for block in text.split("\n\n"):
        item: dict = {}
        for line in block.splitlines():
            if line.startswith(":"):
                continue
            key, _, value = line.partition(": ")
            item[key] = value
        if "event" in item:
            item["data"] = json.loads(item.get("data") or "null")
            out.append(item)
    return out


# ----------------------------- unidades -----------------------------


def test_cursor_roundtrip_and_invalid_values() -> None:
    at = datetime(2026, 11, 2, 12, 0, 0, 123456, tzinfo=UTC)
    eid = uuid.uuid4()
    assert events.parse_cursor(events.make_cursor(at, eid)) == (at, eid)
    assert events.parse_cursor(f"{int(at.timestamp() * 1_000_000)}.") == (at, None)
    for bad in (None, "", "abc", "12.not-a-uuid", "9" * 40 + ".x"):
        assert events.parse_cursor(bad) is None


def test_public_change_has_no_free_text_and_only_safe_fields(db_session) -> None:
    now = datetime.now(UTC)
    status = events.public_change(_ev(db_session, at=now))
    assert set(status) == {"entity", "source", "external_id", "subscription_external_id", "kind", "field", "from", "to",
                           "at"}
    assert (status["from"], status["to"]) == ("ACTIVE", "CANCELLED")
    glosa = events.public_change(_ev(db_session, at=now, kind="reason_changed", field="rejection_reason", frm=None,
                                     to="Texto libre del banco", entity="charge"))
    assert glosa["to"] is None and glosa["from"] is None


def test_cursor_poll_skips_baseline_never_repeats_and_catches_late_rows(db_session) -> None:
    now = datetime.now(UTC)
    cursor = events.ChangeCursor(now - timedelta(seconds=1))
    _ev(db_session, at=now - timedelta(seconds=10), ext="baseline", baseline=True)
    a = _ev(db_session, at=now, ext="a")
    b = _ev(db_session, at=now + timedelta(milliseconds=5), ext="b")
    assert [r.id for r in cursor.poll(db_session)] == [a.id, b.id]
    assert cursor.poll(db_session) == []  # sin repetir
    late = _ev(db_session, at=now - timedelta(seconds=30), ext="late")  # confirmada tarde, dentro del margen
    assert [r.id for r in cursor.poll(db_session)] == [late.id]
    assert cursor.poll(db_session) == []


def test_start_resets_on_old_or_invalid_cursor() -> None:
    now = datetime.now(UTC)
    assert events._start(None, now)[1] is False
    assert events._start("basura", now)[1] is True
    old = events.make_cursor(now - events.MAX_REPLAY - timedelta(minutes=1), uuid.uuid4())
    assert events._start(old, now)[1] is True
    recent_id = uuid.uuid4()
    cursor, reset = events._start(events.make_cursor(now - timedelta(minutes=5), recent_id), now)
    assert reset is False and recent_id in cursor.seen


def test_notify_status_changes_bumps_the_sequence() -> None:
    before = event_bus.status_change_seq()
    event_bus.notify_status_changes()
    assert event_bus.status_change_seq() != before


# ----------------------------- endpoint -----------------------------


def test_stream_requires_session_and_permission(db_session) -> None:
    anonymous = TestClient(app, base_url="https://testserver")
    assert anonymous.get(URL).status_code == 401
    assert _client(db_session, {"toku.dashboard.view"}).get(URL).status_code == 403


def test_stream_replays_from_last_event_id_without_pii(db_session) -> None:
    now = datetime.now(UTC)
    first = _ev(db_session, at=now - timedelta(minutes=10), ext="sub_old")
    second = _ev(db_session, at=now - timedelta(minutes=5), ext="sub_new", frm="ACTIVE", to="PAUSED")
    _ev(db_session, at=now - timedelta(minutes=4), ext="sub_base", baseline=True)
    client = _client(db_session, {"dashboard.view"})
    response = client.get(URL, headers={"Last-Event-ID": events.make_cursor(first.detected_at, first.id)})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "retry: " in response.text
    parsed = _parse_sse(response.text)
    assert parsed[0]["event"] == "ready" and parsed[0]["id"]
    changes = [p for p in parsed if p["event"] == "change"]
    assert [c["data"]["external_id"] for c in changes] == ["sub_new"]  # sin el ya visto ni el baseline
    assert changes[0]["id"] == events.make_cursor(second.detected_at, second.id)
    assert changes[0]["data"]["to"] == "PAUSED"


def test_stream_accepts_query_cursor_and_emits_reset_when_expired(db_session) -> None:
    client = _client(db_session, {"dashboard.view"})
    old = events.make_cursor(datetime.now(UTC) - timedelta(days=3), uuid.uuid4())
    parsed = _parse_sse(client.get(URL, params={"last_event_id": old}).text)
    assert [p["event"] for p in parsed][:2] == ["reset", "ready"]


def test_stream_without_cursor_starts_now_and_sends_new_rows(db_session) -> None:
    _ev(db_session, at=datetime.now(UTC) - timedelta(hours=2), ext="history")  # historia: no se reenvia
    _ev(db_session, at=datetime.now(UTC) + timedelta(seconds=1), ext="live")
    parsed = _parse_sse(_client(db_session, {"dashboard.view"}).get(URL).text)
    assert [p["data"]["external_id"] for p in parsed if p["event"] == "change"] == ["live"]
