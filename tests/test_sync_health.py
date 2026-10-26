import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.v1.routes import sync_runs
from app.core.security import get_current_user
from app.db.session import engine
from app.main import app
from app.models.etl_run import EtlRun
from app.models.sync_run import SyncRun

NOW = datetime(2099, 6, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    session.execute(delete(SyncRun))
    session.execute(delete(EtlRun))
    session.flush()
    sync_runs.clear_sync_health_cache()
    try:
        yield session
    finally:
        sync_runs.clear_sync_health_cache()
        session.close()
        transaction.rollback()
        connection.close()


def _run(db, source, status, hours_ago, finished=True, error=None):
    started = NOW - timedelta(hours=hours_ago)
    db.add(SyncRun(source=source, status=status, started_at=started,
                   finished_at=started if finished else None, error_message=error))
    db.flush()


def _by_channel(db):
    return {item["channel"]: item for item in sync_runs._compute_health(db, NOW)}


@pytest.mark.parametrize("hours,level", [(1, "ok"), (23.9, "ok"), (24, "warn"), (71, "warn"), (72, "error"), (200, "error")])
def test_level_by_age(db_session, hours, level) -> None:
    _run(db_session, "toku", "completed", hours)
    item = _by_channel(db_session)["toku"]
    assert item["level"] == level
    assert item["age_hours"] == round(hours, 1)
    assert item["last_finished_at"] is not None


def test_no_runs_is_unknown(db_session) -> None:
    items = _by_channel(db_session)
    assert set(items) == {"virtualpos", "toku", "payku", "tch"}
    for item in items.values():
        assert item == {"channel": item["channel"], "level": "unknown", "last_finished_at": None, "age_hours": None}


def test_failed_last_run_is_error(db_session) -> None:
    _run(db_session, "payku", "completed", 30)
    _run(db_session, "payku", "failed", 1)
    assert _by_channel(db_session)["payku"]["level"] == "error"


def test_recovered_after_failure_is_ok(db_session) -> None:
    _run(db_session, "payku", "failed", 5)
    _run(db_session, "payku", "completed", 1)
    assert _by_channel(db_session)["payku"]["level"] == "ok"


def test_hung_running_over_72h_is_error_but_recent_running_is_not(db_session) -> None:
    _run(db_session, "toku", "completed", 2)
    _run(db_session, "toku", "running", 100, finished=False)
    _run(db_session, "payku", "completed", 2)
    _run(db_session, "payku", "running", 1, finished=False)
    items = _by_channel(db_session)
    assert items["toku"]["level"] == "error"
    assert items["payku"]["level"] == "ok"


def test_virtualpos_takes_worst_of_vp1_vp2(db_session) -> None:
    _run(db_session, "virtualpos1", "completed", 1)
    _run(db_session, "virtualpos2", "completed", 30)
    assert _by_channel(db_session)["virtualpos"]["level"] == "warn"
    _run(db_session, "virtualpos2", "failed", 0.5)
    assert _by_channel(db_session)["virtualpos"]["level"] == "error"


def test_virtualpos_one_side_unknown_is_worse_than_ok(db_session) -> None:
    _run(db_session, "virtualpos1", "completed", 1)
    assert _by_channel(db_session)["virtualpos"]["level"] == "unknown"


def test_tch_uses_etl_runs(db_session) -> None:
    started = NOW - timedelta(hours=30)
    db_session.add(EtlRun(status="completed", channels_processed=["tch"], started_at=started, finished_at=started))
    db_session.add(EtlRun(status="failed", channels_processed=["toku"], started_at=NOW, finished_at=NOW))
    db_session.flush()
    item = _by_channel(db_session)["tch"]
    assert item["level"] == "warn"
    assert item["age_hours"] == 30.0


def _client(permissions, db_session):
    user = SimpleNamespace(
        id=uuid.uuid4(), is_active=True,
        roles=[SimpleNamespace(name="r", permissions=[SimpleNamespace(code=c) for c in permissions])],
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[sync_runs.get_db] = lambda: db_session
    return TestClient(app)


def _cleanup():
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(sync_runs.get_db, None)


def test_endpoint_requires_dashboard_view(db_session) -> None:
    try:
        assert _client([], db_session).get("/api/v1/sync-runs/health").status_code == 403
        assert _client(["sync_runs.view"], db_session).get("/api/v1/sync-runs/health").status_code == 403
        assert _client(["dashboard.view"], db_session).get("/api/v1/sync-runs/health").status_code == 200
    finally:
        _cleanup()


def test_endpoint_does_not_leak_error_message_and_is_cached(db_session) -> None:
    now = datetime.now(timezone.utc)
    db_session.add(SyncRun(source="toku", status="failed", started_at=now, finished_at=now,
                           error_message="SECRET-DETAIL rut 11.111.111-1"))
    db_session.flush()
    try:
        client = _client(["dashboard.view"], db_session)
        first = client.get("/api/v1/sync-runs/health")
        assert first.status_code == 200
        assert "SECRET-DETAIL" not in first.text and "error_message" not in first.text
        assert all(set(i) == {"channel", "level", "last_finished_at", "age_hours"} for i in first.json())
        assert {i["channel"]: i["level"] for i in first.json()}["toku"] == "error"

        db_session.execute(delete(SyncRun))
        db_session.flush()
        assert client.get("/api/v1/sync-runs/health").json() == first.json()  # cache 5 min
        sync_runs.clear_sync_health_cache()
        assert {i["channel"]: i["level"] for i in client.get("/api/v1/sync-runs/health").json()}["toku"] == "unknown"
    finally:
        _cleanup()
