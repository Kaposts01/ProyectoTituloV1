"""SYNC-O-16 / PK-PAR-02 / TK-PAR-08: el ETL Core de Toku, Payku y VirtualPOS corre dentro del flujo de sync.

Corre despues de la consolidacion de cada canal que tuvo exito (nunca de un canal fallido), su resultado queda
en el run, y `/sync-runs/health` marca `degraded` si el ETL Core queda mas de 24 h detras del ultimo sync exitoso.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.v1.routes import sync_runs
from app.core.config import settings
from app.db.session import engine
from app.models.core import CoreCharge
from app.models.etl_run import EtlRun
from app.models.sync_run import SyncRun
from app.scheduler.jobs import sync_all
from app.services import core_etl_mark

NOW = datetime(2099, 6, 1, 12, 0, tzinfo=timezone.utc)


# --- orquestador ----------------------------------------------------------------------------------


def _patch(monkeypatch, *, failing_sync: tuple[str, ...] = (), consolidation_failures: list[str] | None = None,
           core_fails: tuple[str, ...] = (), core_etl_enabled: bool = True):
    monkeypatch.setattr(settings, "sync_core_etl_enabled", core_etl_enabled)
    events: list[tuple] = []
    run = EtlRun(status="running")
    run.id = uuid.uuid4()

    class FakeDb:
        def scalar(self, *_a, **_k):
            return None

        def add(self, *_a):
            pass

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

        def get(self, *_a):
            return run

    monkeypatch.setattr(sync_all, "SessionLocal", FakeDb)
    monkeypatch.setattr(sync_all, "start_exclusive_run", lambda _db, **_f: run)
    monkeypatch.setattr(sync_all, "skip_disabled_channel", lambda _c: False)

    async def vp(_db, platform, _cb=None, **_k):
        events.append(("sync", platform))
        if platform in failing_sync:
            raise RuntimeError("boom")
        return SimpleNamespace(id=uuid.uuid4(), records_processed=1)

    def named(name):
        async def fn(_db, _cb=None):
            events.append(("sync", name))
            if name in failing_sync:
                raise RuntimeError("boom")
            return SimpleNamespace(id=uuid.uuid4(), records_processed=1)

        return fn

    def consolidate(_db, sources, failures=None, **_k):
        events.append(("consolidate", tuple(sources)))
        failures.extend(consolidation_failures or [])
        return 0

    def core(channel):
        def fn(_db):
            events.append(("core", channel))
            if channel in core_fails:
                raise RuntimeError("core boom")
            return {"rows": 7}

        return fn

    monkeypatch.setattr(sync_all, "sync_virtualpos", vp)
    monkeypatch.setattr(sync_all, "sync_toku", named("toku"))
    monkeypatch.setattr(sync_all, "sync_payku", named("payku"))
    monkeypatch.setattr(sync_all, "consolidate_to_centralized", consolidate)
    monkeypatch.setattr(sync_all, "reconcile_charge_recoveries", lambda *_a, **_k: None)
    monkeypatch.setattr(sync_all, "_CORE_ETL_RUNNERS", {c: core(c) for c in ("virtualpos", "toku", "payku")})
    monkeypatch.setattr(sync_all.core_etl_mark, "record", lambda _db, channel, result: events.append(("mark", channel)))
    monkeypatch.setattr(sync_all.tch_registry, "consolidation_snapshot", lambda _db: {"sha256s": [], "latest_load_at": None})
    monkeypatch.setattr(sync_all.tch_registry, "needs_consolidation", lambda _db, _s: False)
    return events, run


def _core_events(events):
    return [e[1] for e in events if e[0] == "core"]


def test_core_etl_runs_after_the_consolidation_for_every_successful_channel(monkeypatch) -> None:
    events, run = _patch(monkeypatch)
    asyncio.run(sync_all.sync_all_channels())
    assert _core_events(events) == ["virtualpos", "toku", "payku"]
    last_consolidation = max(i for i, e in enumerate(events) if e[0] == "consolidate")
    assert all(i > last_consolidation for i, e in enumerate(events) if e[0] == "core")
    assert [e for e in events if e[0] == "mark"] == [("mark", "virtualpos"), ("mark", "toku"), ("mark", "payku")]
    assert run.status == "completed"


def test_core_etl_is_not_run_for_a_failed_channel(monkeypatch) -> None:
    events, run = _patch(monkeypatch, failing_sync=("toku",))
    asyncio.run(sync_all.sync_all_channels())
    assert _core_events(events) == ["virtualpos", "payku"]
    assert run.channels_failed == ["toku"]


def test_core_etl_for_virtualpos_needs_at_least_one_account_ok(monkeypatch) -> None:
    events, _ = _patch(monkeypatch, failing_sync=("virtualpos1", "virtualpos2"))
    asyncio.run(sync_all.sync_all_channels())
    assert "virtualpos" not in _core_events(events)
    events, _ = _patch(monkeypatch, failing_sync=("virtualpos2",))
    asyncio.run(sync_all.sync_all_channels())
    assert "virtualpos" in _core_events(events)


def test_core_etl_is_not_run_for_a_channel_whose_consolidation_failed(monkeypatch) -> None:
    events, _ = _patch(monkeypatch, consolidation_failures=["payku.transactions"])
    asyncio.run(sync_all.sync_all_channels())
    assert _core_events(events) == ["virtualpos", "toku"]


def test_a_core_etl_failure_marks_the_run_partial_and_does_not_stop_the_others(monkeypatch) -> None:
    events, run = _patch(monkeypatch, core_fails=("toku",))
    asyncio.run(sync_all.sync_all_channels())
    assert _core_events(events) == ["virtualpos", "toku", "payku"]
    assert ("mark", "toku") not in events
    assert run.status == "partial"
    assert "ETL Core" in run.error_message and "toku" in run.error_message
    assert "boom" not in run.error_message  # el texto de la excepcion no se vuelca al run
    assert not run.channels_failed  # el canal sincronizo bien: no se reintenta el sync por un fallo del core


def test_explicit_channels_only_run_their_own_core_etl(monkeypatch) -> None:
    events, _ = _patch(monkeypatch)
    asyncio.run(sync_all.sync_all_channels(channels=["toku"]))
    assert _core_events(events) == ["toku"]


def test_the_core_etl_can_be_turned_off_by_setting(monkeypatch) -> None:
    events, _ = _patch(monkeypatch, core_etl_enabled=False)
    asyncio.run(sync_all.sync_all_channels())
    assert _core_events(events) == []


def test_the_core_etl_is_off_by_default() -> None:
    """Producción no debe encender el ETL Core por sorpresa: lo activa el usuario tras una primera corrida manual."""
    assert type(settings).model_fields["sync_core_etl_enabled"].default is False


# --- marca y salud ---------------------------------------------------------------------------------


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


def _sync(db, source, hours_ago, status="completed"):
    at = NOW - timedelta(hours=hours_ago)
    db.add(SyncRun(source=source, status=status, started_at=at, finished_at=at))
    db.flush()


def _health(db):
    return {item["channel"]: item for item in sync_runs._compute_health(db, NOW)}


def test_mark_roundtrip(db_session) -> None:
    assert core_etl_mark.last_finished_at(db_session, "toku") is None
    core_etl_mark.record(db_session, "toku", {"charges_upserted": 3}, finished_at=NOW)
    assert core_etl_mark.last_finished_at(db_session, "toku") == NOW
    core_etl_mark.record(db_session, "toku", {"charges_upserted": 0}, finished_at=NOW + timedelta(hours=1))
    assert core_etl_mark.last_finished_at(db_session, "toku") == NOW + timedelta(hours=1)


def test_health_is_degraded_when_core_etl_lags_the_sync_by_more_than_24h(db_session) -> None:
    _sync(db_session, "toku", 1)
    core_etl_mark.record(db_session, "toku", {}, finished_at=NOW - timedelta(hours=30))
    item = _health(db_session)["toku"]
    assert item["status"] == "degraded"
    assert item["level"] in ("warn", "error")
    assert item["core_lag_hours"] == pytest.approx(29, abs=0.2)


def test_health_stays_ok_when_core_is_within_24h(db_session) -> None:
    _sync(db_session, "toku", 1)
    core_etl_mark.record(db_session, "toku", {}, finished_at=NOW - timedelta(hours=10))
    item = _health(db_session)["toku"]
    assert item["status"] == "ok" and item["level"] == "ok"
    assert item["core_lag_hours"] == pytest.approx(9, abs=0.2)


def test_health_uses_the_last_core_row_when_there_is_no_mark(db_session) -> None:
    _sync(db_session, "payku", 1)
    db_session.add(CoreCharge(source="payku", external_id="hc-1", updated_at=NOW - timedelta(days=8)))
    db_session.flush()
    item = _health(db_session)["payku"]
    assert item["status"] == "degraded" and item["core_lag_hours"] > 24


def test_health_without_any_core_signal_is_unchanged(db_session) -> None:
    _sync(db_session, "toku", 1)
    item = _health(db_session)["toku"]
    assert item["status"] == "ok" and "core_lag_hours" not in item


def test_health_virtualpos_takes_the_best_core_mark_against_the_latest_sync(db_session) -> None:
    _sync(db_session, "virtualpos1", 1)
    _sync(db_session, "virtualpos2", 2)
    core_etl_mark.record(db_session, "virtualpos", {}, finished_at=NOW - timedelta(hours=40))
    assert _health(db_session)["virtualpos"]["status"] == "degraded"


def test_a_failed_sync_does_not_make_core_look_late(db_session) -> None:
    """El atraso se mide contra el ultimo sync EXITOSO: si el sync mismo falla, eso ya lo dice el estado del canal."""
    _sync(db_session, "toku", 200)  # el ultimo sync exitoso es antiguo
    _sync(db_session, "toku", 1, status="failed")
    core_etl_mark.record(db_session, "toku", {}, finished_at=NOW - timedelta(hours=199))
    assert "core_lag_hours" in _health(db_session)["toku"]
    assert _health(db_session)["toku"]["core_lag_hours"] <= 24


# --- RJ-06: captura de glosas de VirtualPOS dentro del flujo ----------------------------------------------------------


def _capture_spy(monkeypatch, events, *, fails: tuple[str, ...] = ()):
    async def fake(platform, run_id):
        events.append(("capture", platform))
        if platform in fails:
            raise RuntimeError("capture boom")
        return {"details_new": 3, "subscriptions_failed": 0, "subscriptions_pending": 3, "aborted": None}

    monkeypatch.setattr(sync_all, "_capture_vp_rejections", fake)


def test_vp_rejection_capture_is_off_by_default_and_does_not_run(monkeypatch) -> None:
    assert settings.vp_rejection_capture_enabled is False
    events, _ = _patch(monkeypatch)
    _capture_spy(monkeypatch, events)
    asyncio.run(sync_all.sync_all_channels())
    assert [e for e in events if e[0] == "capture"] == []


def test_vp_rejection_capture_runs_between_the_syncs_and_the_consolidation(monkeypatch) -> None:
    monkeypatch.setattr(settings, "vp_rejection_capture_enabled", True)
    events, run = _patch(monkeypatch)
    _capture_spy(monkeypatch, events)
    asyncio.run(sync_all.sync_all_channels())
    kinds = [e[0] for e in events]
    captures = [e for e in events if e[0] == "capture"]
    assert captures == [("capture", "virtualpos1"), ("capture", "virtualpos2")]
    assert max(i for i, k in enumerate(kinds) if k == "capture") < kinds.index("consolidate")
    assert min(i for i, k in enumerate(kinds) if k == "capture") > max(i for i, k in enumerate(kinds) if k == "sync")
    assert run.status == "completed"


def test_vp_rejection_capture_skips_failed_accounts_and_its_failure_does_not_fail_the_run(monkeypatch) -> None:
    monkeypatch.setattr(settings, "vp_rejection_capture_enabled", True)
    events, run = _patch(monkeypatch, failing_sync=("virtualpos2",))
    _capture_spy(monkeypatch, events, fails=("virtualpos1",))
    asyncio.run(sync_all.sync_all_channels())
    assert [e for e in events if e[0] == "capture"] == [("capture", "virtualpos1")]  # la cuenta caida no se captura
    assert run.status == "partial"  # por virtualpos2; la captura fallida no agrego nada
    assert "capture" not in (run.error_message or "")
    assert any(e[0] == "consolidate" for e in events)  # la consolidacion siguio


def test_vp_rejection_capture_is_not_run_for_explicit_channels_without_virtualpos(monkeypatch) -> None:
    monkeypatch.setattr(settings, "vp_rejection_capture_enabled", True)
    events, _ = _patch(monkeypatch)
    _capture_spy(monkeypatch, events)
    asyncio.run(sync_all.sync_all_channels(channels=["toku"]))
    assert [e for e in events if e[0] == "capture"] == []
