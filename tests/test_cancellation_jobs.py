# ruff: noqa: F811  (fixtures importadas de cancellation_support: db_session)
"""Jobs de bajas en el scheduler: expiracion de solicitudes pendientes y barredor de `applying` atascadas.

Registran su corrida en `sync_runs` con el prefijo propio `cancellation_`, que los KPI y listados de canales excluyen
(igual que el prefijo `billing_` de la Opcion A). Ninguna llamada de red.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from cancellation_support import (
    NOW,
    db_session,  # noqa: F401 - fixture
    make_roles,
    make_user,
    params,
    seed_vp,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes import staging, sync_runs
from app.models.sync_run import SyncRun
from app.scheduler import engine as sched_engine
from app.scheduler.jobs import billing_jobs, cancellation_jobs
from app.services import cancellation_apply as ca
from app.services import cancellation_requests as cr


def _factory(db):
    return lambda: Session(bind=db.get_bind(), join_transaction_mode="create_savepoint")


def _patch_sessions(monkeypatch, db):
    """El job y los helpers de filas (`billing_jobs._start_run/_finish_run`) abren su propia sesion: ambas, a la de la prueba."""
    monkeypatch.setattr(cancellation_jobs, "SessionLocal", _factory(db))
    monkeypatch.setattr(billing_jobs, "SessionLocal", _factory(db))


def _runs(db, source):
    db.expire_all()
    return list(db.scalars(select(SyncRun).where(SyncRun.source == source)))


def test_ids_use_their_own_excluded_prefix():
    from app.models.sync_run import CANCELLATION_JOB_PREFIX

    assert cancellation_jobs.CANCELLATION_JOB_IDS == (
        cancellation_jobs.JOB_CANCELLATION_EXPIRE, cancellation_jobs.JOB_CANCELLATION_SWEEP)
    assert all(j.startswith(CANCELLATION_JOB_PREFIX) for j in cancellation_jobs.CANCELLATION_JOB_IDS)


def test_jobs_registered_with_expected_schedule_and_idempotent():
    sched = AsyncIOScheduler(timezone="America/Santiago")
    sched_engine.register_jobs(sched)
    jobs = {j.id: j for j in sched.get_jobs()}
    assert {"cancellation_expire_requests", "cancellation_sweep_applying"} <= set(jobs)
    assert "minute='25'" in str(jobs["cancellation_expire_requests"].trigger)
    assert "minute='8,23,38,53'" in str(jobs["cancellation_sweep_applying"].trigger)
    assert str(jobs["cancellation_sweep_applying"].trigger.timezone) == "America/Santiago"
    n_jobs = len(sched.get_jobs())
    sched_engine.register_jobs(sched)
    assert len(sched.get_jobs()) == n_jobs


def test_channel_kpis_and_listing_exclude_the_cancellation_prefix(db_session):
    db_session.add_all([
        SyncRun(source="toku", status="completed", finished_at=datetime.now(UTC)),
        SyncRun(source="cancellation_sweep_applying", status="failed", finished_at=datetime.now(UTC)),
        SyncRun(source="cancellation_expire_requests", status="completed", finished_at=datetime.now(UTC)),
    ])
    db_session.flush()
    listed = {r["source"] for r in sync_runs.list_sync_runs(db=db_session)}
    assert not any(s.startswith("cancellation_") for s in listed) and "toku" in listed
    rows = db_session.scalars(select(SyncRun.source).where(SyncRun.is_channel_source())).all()
    assert not any(s.startswith(("cancellation_", "billing_")) for s in rows)
    assert staging  # los KPI de staging usan la misma condicion `is_channel_source()` (ver test_billing_tanda2)


def test_expire_job_expires_pending_requests_and_records_a_run(db_session, monkeypatch):
    _patch_sessions(monkeypatch, db_session)
    roles = make_roles(db_session)
    solicitante = make_user(db_session, roles["solicitante"])
    seed_vp(db_session, "sub-j1")
    req = cr.create_request(db_session, solicitante, params(sub="sub-j1"), now=NOW)
    req.expires_at = datetime.now(UTC) - timedelta(days=1)
    db_session.commit()
    asyncio.run(cancellation_jobs.cancellation_expire_requests())
    assert cr.get_request(db_session, req.id).status == "expired"
    runs = _runs(db_session, "cancellation_expire_requests")
    assert len(runs) == 1 and runs[0].status == "completed" and runs[0].records_processed == 1


def test_scheduled_runs_that_do_nothing_leave_no_row(db_session, monkeypatch):
    _patch_sessions(monkeypatch, db_session)
    monkeypatch.setattr(cr, "expire_pending_cancellation_requests", lambda db: [])
    monkeypatch.setattr(ca, "sweep_stuck_applying", lambda db, **kw: [])
    asyncio.run(cancellation_jobs.cancellation_expire_requests())
    asyncio.run(cancellation_jobs.cancellation_sweep_applying())
    assert _runs(db_session, "cancellation_expire_requests") == []
    assert _runs(db_session, "cancellation_sweep_applying") == []


def test_sweep_job_moves_stuck_applying_to_reconciliation_and_records_a_run(db_session, monkeypatch):
    _patch_sessions(monkeypatch, db_session)
    roles = make_roles(db_session)
    jefa = make_user(db_session, roles["jefatura"])
    seed_vp(db_session, "sub-j2")
    req = cr.create_request(db_session, jefa, params(sub="sub-j2"), now=NOW)
    req.status = "applying"
    db_session.commit()
    seen = {}
    real = ca.sweep_stuck_applying

    def _later(db, **kw):  # el job usa la hora real: se adelanta para que la solicitud cuente como atascada
        seen.update(kw)
        return real(db, now=datetime.now(UTC) + timedelta(days=1), **kw)

    monkeypatch.setattr(ca, "sweep_stuck_applying", _later)
    asyncio.run(cancellation_jobs.cancellation_sweep_applying())
    assert seen["older_than_minutes"] == cancellation_jobs.SWEEP_OLDER_THAN_MINUTES == 30
    assert cr.get_request(db_session, req.id).status == "requires_reconciliation"
    runs = _runs(db_session, "cancellation_sweep_applying")
    assert len(runs) == 1 and runs[0].status == "completed" and runs[0].records_processed == 1


@pytest.mark.parametrize(("job", "target", "source"), [
    ("cancellation_expire_requests", "expire_pending_cancellation_requests", "cancellation_expire_requests"),
    ("cancellation_sweep_applying", "sweep_stuck_applying", "cancellation_sweep_applying"),
])
def test_a_failing_job_records_a_failed_run_without_the_error_text(db_session, monkeypatch, job, target, source):
    _patch_sessions(monkeypatch, db_session)
    module = cr if target.startswith("expire") else ca

    def boom(*a, **k):
        raise RuntimeError("detalle con juan.perez@example.com")

    monkeypatch.setattr(module, target, boom)
    asyncio.run(getattr(cancellation_jobs, job)())  # no propaga
    runs = _runs(db_session, source)
    assert len(runs) == 1 and runs[0].status == "failed" and runs[0].error_message == "RuntimeError"
