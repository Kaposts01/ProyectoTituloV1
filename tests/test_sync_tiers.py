"""SYNC-O-09: niveles caliente / tibio / frio (D10), detras de SYNC_TIERS_ENABLED (apagada). Sin proveedores reales."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models.etl_run import EtlRun
from app.scheduler.jobs import sync_all, sync_tiers
from app.services import sync_cursors, sync_window
from app.services import tch_report_registry as registry


def _patch_orchestrator(monkeypatch):
    seen: dict = {"forced": [], "consolidate": [], "capture": 0}
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

    async def channel(*_a, **_k):
        seen["forced"].append(sync_window.full_reads_forced())
        return SimpleNamespace(id=uuid.uuid4(), records_processed=1)

    def consolidate(_db, sources, failures=None, **kwargs):
        seen["consolidate"].append((tuple(sources), kwargs.get("differential", "default")))
        return 0

    async def capture(*_a, **_k):
        seen["capture"] += 1
        return {}

    monkeypatch.setattr(sync_all, "SessionLocal", FakeDb)
    monkeypatch.setattr(sync_all, "start_exclusive_run", lambda _db, **_f: run)
    monkeypatch.setattr(sync_all, "skip_disabled_channel", lambda _c: False)
    monkeypatch.setattr(sync_all, "sync_virtualpos", channel)
    monkeypatch.setattr(sync_all, "sync_toku", channel)
    monkeypatch.setattr(sync_all, "sync_payku", channel)
    monkeypatch.setattr(sync_all, "consolidate_to_centralized", consolidate)
    monkeypatch.setattr(sync_all, "reconcile_charge_recoveries", lambda *_a, **_k: None)
    monkeypatch.setattr(sync_all, "_capture_vp_rejections", capture)
    monkeypatch.setattr(sync_all, "_CORE_ETL_RUNNERS", {})
    monkeypatch.setattr(registry, "consolidation_snapshot", lambda _db: {"sha256s": [], "latest_load_at": None})
    monkeypatch.setattr(registry, "needs_consolidation", lambda _db, _snap: False)  # sin carga TCH nueva
    monkeypatch.setattr(registry, "mark_consolidated", lambda _db, _snap: None)
    return seen, run


def test_tier_flag_is_off_by_default() -> None:
    assert type(settings).model_fields["sync_tiers_enabled"].default is False


def test_jobs_do_nothing_with_the_flag_off(monkeypatch) -> None:
    monkeypatch.setattr(settings, "sync_tiers_enabled", False)
    monkeypatch.setattr(settings, "sync_windowed_reads_enabled", True)

    async def boom(**_k):
        pytest.fail("no debe sincronizar con la bandera apagada")

    monkeypatch.setattr(sync_tiers, "sync_all_channels", boom)
    asyncio.run(sync_tiers.sync_hot())
    asyncio.run(sync_tiers.sync_cold())


def test_hot_requires_windowed_reads(monkeypatch) -> None:
    monkeypatch.setattr(settings, "sync_tiers_enabled", True)
    monkeypatch.setattr(settings, "sync_windowed_reads_enabled", False)
    calls: list = []

    async def fake(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(sync_tiers, "sync_all_channels", fake)
    asyncio.run(sync_tiers.sync_hot())
    assert calls == []

    monkeypatch.setattr(settings, "sync_windowed_reads_enabled", True)
    asyncio.run(sync_tiers.sync_hot())
    asyncio.run(sync_tiers.sync_cold())
    assert calls == [
        {"channels": ["virtualpos1", "virtualpos2", "toku", "payku"], "tier": "hot"},
        {"tier": "cold"},
    ]


def test_hot_tier_api_channels_only_without_rejection_capture(monkeypatch) -> None:
    monkeypatch.setattr(settings, "vp_rejection_capture_enabled", True)
    seen, run = _patch_orchestrator(monkeypatch)
    asyncio.run(sync_all.sync_all_channels(channels=list(sync_tiers.HOT_CHANNELS), tier=sync_all.TIER_HOT))
    assert seen["forced"] == [False, False, False, False]  # por ventana (si la bandera de ventanas lo permite)
    assert seen["consolidate"] == [(("virtualpos", "toku", "payku"), "default")]
    assert seen["capture"] == 0
    assert run.status == "completed"


def test_cold_tier_forces_full_reads_full_consolidation_and_tch(monkeypatch) -> None:
    seen, run = _patch_orchestrator(monkeypatch)
    asyncio.run(sync_all.sync_all_channels(tier=sync_all.TIER_COLD))
    assert seen["forced"] == [True, True, True, True]
    assert seen["consolidate"] == [(("virtualpos", "toku", "payku", "tch"), False)]  # TCH aunque no haya carga
    assert sync_window.full_reads_forced() is False  # se restablece al terminar
    assert run.status == "completed"


def test_warm_tier_is_the_usual_run(monkeypatch) -> None:
    seen, _ = _patch_orchestrator(monkeypatch)
    asyncio.run(sync_all.sync_all_channels())
    assert seen["forced"] == [False, False, False, False]
    assert seen["consolidate"] == [(("virtualpos", "toku", "payku"), "default")]  # TCH omitida sin carga nueva


def test_forced_full_reads_disable_windows(monkeypatch) -> None:
    monkeypatch.setattr(settings, "sync_windowed_reads_enabled", True)
    now = datetime.now(UTC)
    mark = SimpleNamespace(last_success_at=now - timedelta(hours=1), records_seen=10)
    monkeypatch.setattr(sync_cursors, "get", lambda *_a, **_k: mark)
    monkeypatch.setattr(sync_cursors, "last_success", lambda *_a, **_k: now - timedelta(hours=1))
    assert sync_window.plan_window(None, "toku", "transaction", now) is not None
    with sync_window.force_full_reads():
        assert sync_window.plan_window(None, "toku", "transaction", now) is None
    assert sync_window.plan_window(None, "toku", "transaction", now) is not None


def test_jobs_registered_with_d10_schedule_and_idempotent() -> None:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from app.scheduler import engine as sched_engine

    sched = AsyncIOScheduler(timezone="America/Santiago")
    sched_engine.register_jobs(sched)
    jobs = {j.id: j for j in sched.get_jobs()}
    hot = str(jobs[sync_tiers.JOB_SYNC_HOT].trigger)
    cold = str(jobs[sync_tiers.JOB_SYNC_COLD].trigger)
    assert "hour='7,10,13,16,19,22'" in hot and "minute='30'" in hot
    assert "day_of_week='sun'" in cold and "hour='1'" in cold
    assert sched_engine.JOB_SYNC_ALL in jobs  # la tibia sigue siendo la de las 02:00
    n_jobs = len(jobs)
    sched_engine.register_jobs(sched)
    assert len(sched.get_jobs()) == n_jobs
