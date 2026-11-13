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
from app.models.sync_cursor import SyncCursor
from app.models.sync_run import SyncRun
from app.models.tch import TchFileLoad

NOW = datetime(2099, 6, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    session.execute(delete(SyncRun))
    session.execute(delete(EtlRun))
    session.execute(delete(SyncCursor))
    session.execute(delete(TchFileLoad))
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


@pytest.mark.parametrize("hours,level,state", [
    (1, "ok", "ok"), (23.9, "ok", "ok"), (24, "warn", "stale"), (71, "warn", "stale"),
    (72, "warn", "stale"), (200, "warn", "stale"),  # 13B: la antiguedad sola nunca es «error»
])
def test_level_by_age(db_session, hours, level, state) -> None:
    _run(db_session, "toku", "completed", hours)
    item = _by_channel(db_session)["toku"]
    assert item["level"] == level
    assert item["state"] == state
    assert item["age_hours"] == round(hours, 1)
    assert item["last_finished_at"] is not None


def test_no_runs_is_unknown(db_session) -> None:
    items = _by_channel(db_session)
    assert set(items) == {"virtualpos", "toku", "payku", "tch"}
    for item in items.values():
        assert item == {
            "channel": item["channel"], "level": "unknown", "last_finished_at": None, "age_hours": None,
            "status": "unknown", "consecutive_failures": 0, "days_without_success": None, "state": "unknown",
        }


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


def test_qa05_virtualpos_account_without_runs_does_not_hide_the_one_that_syncs(db_session) -> None:
    """QA-05: la cuenta 2 sin corridas no deja a VirtualPOS en «Sin datos»; el estado sale de la cuenta 1."""
    _run(db_session, "virtualpos1", "completed", 1)
    item = _by_channel(db_session)["virtualpos"]
    assert item["level"] == "ok" and item["status"] == "ok" and item["last_finished_at"] is not None
    _run(db_session, "virtualpos1", "completed", 30)  # mas vieja: no cambia la ultima
    assert _by_channel(db_session)["virtualpos"]["level"] == "ok"


def test_qa05_account_without_runs_does_not_hide_a_failing_account(db_session) -> None:
    _run(db_session, "virtualpos1", "failed", 1)
    assert _by_channel(db_session)["virtualpos"]["level"] == "error"


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
    return TestClient(app, base_url="https://testserver")


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
        assert all(set(i) == {"channel", "level", "last_finished_at", "age_hours", "status", "consecutive_failures", "days_without_success", "state"} for i in first.json())
        assert {i["channel"]: i["level"] for i in first.json()}["toku"] == "error"

        db_session.execute(delete(SyncRun))
        db_session.flush()
        assert client.get("/api/v1/sync-runs/health").json() == first.json()  # cache 5 min
        sync_runs.clear_sync_health_cache()
        assert {i["channel"]: i["level"] for i in client.get("/api/v1/sync-runs/health").json()}["toku"] == "unknown"
    finally:
        _cleanup()


# --- channel_failing_days: estado degraded/failing (SYNC-D-09) ---------------------------------------


def test_status_ok_when_recent_success(db_session) -> None:
    _run(db_session, "toku", "completed", 2)
    item = _by_channel(db_session)["toku"]
    assert (item["status"], item["consecutive_failures"], item["days_without_success"]) == ("ok", 0, 0)


def test_one_failure_after_recent_success_is_ok_status_but_level_error(db_session) -> None:
    _run(db_session, "toku", "completed", 5)
    _run(db_session, "toku", "failed", 1)
    item = _by_channel(db_session)["toku"]
    assert item["status"] == "ok"
    assert item["consecutive_failures"] == 1
    assert item["level"] == "error"


def test_two_consecutive_failures_same_day_is_degraded_and_raises_level(db_session) -> None:
    _run(db_session, "payku", "completed", 10)
    _run(db_session, "payku", "failed", 3)
    _run(db_session, "payku", "failed", 1)
    item = _by_channel(db_session)["payku"]
    assert item["status"] == "degraded"
    assert item["consecutive_failures"] == 2
    assert item["level"] == "error"


def test_failures_and_more_than_a_day_without_success_is_failing(db_session) -> None:
    _run(db_session, "virtualpos2", "completed", 80)
    _run(db_session, "virtualpos2", "failed", 50)
    _run(db_session, "virtualpos2", "failed", 26)
    _run(db_session, "virtualpos1", "completed", 1)
    item = _by_channel(db_session)["virtualpos"]
    assert item["status"] == "failing"
    assert item["consecutive_failures"] == 2
    assert item["days_without_success"] == 3
    assert item["level"] == "error"


def test_day_without_success_without_failures_is_degraded(db_session) -> None:
    _run(db_session, "toku", "completed", 30)
    item = _by_channel(db_session)["toku"]
    assert item["status"] == "degraded"
    assert item["days_without_success"] == 1
    assert item["level"] == "warn"


def test_never_succeeded_with_failures_is_failing(db_session) -> None:
    _run(db_session, "payku", "failed", 30)
    _run(db_session, "payku", "failed", 6)
    item = _by_channel(db_session)["payku"]
    assert item["status"] == "failing"
    assert item["days_without_success"] is None


def test_partial_etl_run_counts_as_success_for_tch(db_session) -> None:
    started = NOW - timedelta(hours=2)
    db_session.add(EtlRun(status="partial", channels_processed=["tch"], started_at=started, finished_at=started))
    db_session.flush()
    item = _by_channel(db_session)["tch"]
    assert item["status"] == "ok"
    assert item["level"] == "ok"


# --- 13B: «al dia», «atrasada», «fallo» y «en curso» -------------------------------------------------------------


def test_13b_four_days_without_runs_is_stale_not_error(db_session) -> None:
    """Backend apagado 4 dias: ninguna corrida fallo, todos los canales quedan «atrasados» (antes «error»)."""
    for source in ("virtualpos1", "virtualpos2", "toku", "payku"):
        _run(db_session, source, "completed", 96)
    started = NOW - timedelta(hours=96)
    db_session.add(EtlRun(status="completed", channels_processed=["tch"], started_at=started, finished_at=started))
    db_session.flush()
    for item in _by_channel(db_session).values():
        assert (item["level"], item["state"], item["age_hours"]) == ("warn", "stale", 96.0), item["channel"]
        assert item["days_without_success"] == 4


def test_13b_last_run_failed_is_failed(db_session) -> None:
    _run(db_session, "toku", "completed", 30)
    _run(db_session, "toku", "failed", 2)
    item = _by_channel(db_session)["toku"]
    assert (item["level"], item["state"]) == ("error", "failed")


def test_13b_run_closed_by_server_restart_is_not_a_failure(db_session) -> None:
    """El arranque cierra como `failed` lo que quedo `running`; eso no es un fallo del canal."""
    from app.scheduler.run_lock import RESTART_MESSAGE

    _run(db_session, "payku", "completed", 96)
    _run(db_session, "payku", "failed", 95, error=RESTART_MESSAGE)
    item = _by_channel(db_session)["payku"]
    assert (item["level"], item["state"], item["consecutive_failures"]) == ("warn", "stale", 0)
    _run(db_session, "payku", "failed", 1, error="timeout del proveedor")
    assert _by_channel(db_session)["payku"]["state"] == "failed"


def test_13b_recent_running_is_running_and_hung_is_failed(db_session) -> None:
    _run(db_session, "toku", "completed", 30)
    _run(db_session, "toku", "running", 0.2, finished=False)
    _run(db_session, "payku", "completed", 2)
    _run(db_session, "payku", "running", 100, finished=False)
    items = _by_channel(db_session)
    assert items["toku"]["state"] == "running"
    assert items["payku"]["state"] == "failed"


def test_13b_virtualpos_running_account_wins_and_never_ran_is_unknown(db_session) -> None:
    _run(db_session, "virtualpos1", "completed", 1)
    _run(db_session, "virtualpos2", "running", 0.1, finished=False)
    items = _by_channel(db_session)
    assert items["virtualpos"]["state"] == "running"
    assert items["toku"]["state"] == "unknown"
