"""RT-06: reconciliacion dirigida por ventana de riesgo (sin webhooks). Fakes: nada de red ni de proveedores."""

import asyncio
import uuid
from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.models.crm import Charge, Subscription
from app.models.etl_run import EtlRun
from app.services import targeted_reconcile as tr
from app.services.subscription_refresh import RefreshError

TODAY = date(2026, 10, 29)


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def _no_active_sync(monkeypatch):
    """Corridas `running` confirmadas por otros tests no deben afectar: por defecto no hay sync activa."""
    monkeypatch.setattr(tr, "find_active_run", lambda db: None)


def _sub(db, source, sid, status="ACTIVA"):
    db.add(Subscription(source=source, external_id=sid, status=status, raw_payload={}))


def _charge(db, source, sid, cid, status, charge_date):
    db.add(Charge(source=source, external_id=cid, subscription_external_id=sid, status=status,
                  charge_date=charge_date, raw_payload={}))


def _mine(selected):
    return [s for s in selected if s[1].startswith("rc-")]


class Recorder:
    def __init__(self, fail: dict | None = None) -> None:
        self.calls: list[tuple[str, str, uuid.UUID]] = []
        self.fail = fail or {}

    async def __call__(self, db, source, external_id, *, run_id=None):
        self.calls.append((source, external_id, run_id))
        if (source, external_id) in self.fail:
            raise self.fail[(source, external_id)]


async def _nosleep(_seconds):
    return None


def _seed_window(db):
    _sub(db, "virtualpos1", "rc-due")
    _charge(db, "virtualpos1", "rc-due", "rc-due-c", "pagado", "2026-10-26")            # cobro de hace 3 dias
    _sub(db, "toku", "rc-rej")
    _charge(db, "toku", "rc-rej", "rc-rej-c", "REJECTED", "2026-10-15")                 # rechazo de hace 14 dias
    _sub(db, "payku", "rc-pend")
    _charge(db, "payku", "rc-pend", "rc-pend-c", "pending", "2026-10-20")               # pendiente vencido
    _sub(db, "virtualpos2", "rc-old")
    _charge(db, "virtualpos2", "rc-old", "rc-old-c", "pagado", "2026-09-01")            # fuera de la ventana
    _sub(db, "virtualpos1", "rc-future")
    _charge(db, "virtualpos1", "rc-future", "rc-future-c", "pendiente", "2026-11-05")   # pendiente futuro: no es riesgo
    _sub(db, "virtualpos1", "rc-cancel", status="CANCELADA")
    _charge(db, "virtualpos1", "rc-cancel", "rc-cancel-c", "rechazado", "2026-10-27")    # ya cancelada
    _sub(db, "tch", "rc-tch")
    _charge(db, "tch", "rc-tch", "rc-tch-c", "rechazado", "2026-10-27")                  # canal sin refresh
    db.flush()


def test_window_selects_due_rejected_and_pending_but_not_the_rest(db_session) -> None:
    _seed_window(db_session)
    selected = _mine(tr.select_risk_subscriptions(db_session, limit=100, today=TODAY))
    assert {s[1] for s in selected} == {"rc-due", "rc-rej", "rc-pend"}
    assert ("tch", "rc-tch") not in selected


def test_priority_orders_rejections_first_then_due_then_pending(db_session) -> None:
    _seed_window(db_session)
    selected = _mine(tr.select_risk_subscriptions(db_session, limit=100, today=TODAY))
    assert [s[1] for s in selected] == ["rc-rej", "rc-due", "rc-pend"]


def test_window_boundaries_are_inclusive_of_five_days(db_session) -> None:
    _sub(db_session, "toku", "rc-edge5")
    _charge(db_session, "toku", "rc-edge5", "rc-edge5-c", "PAID", "2026-10-24")   # hoy - 5 dias
    _sub(db_session, "toku", "rc-edge6")
    _charge(db_session, "toku", "rc-edge6", "rc-edge6-c", "PAID", "2026-10-23")   # hoy - 6 dias
    db_session.flush()
    selected = {s[1] for s in _mine(tr.select_risk_subscriptions(db_session, limit=100, today=TODAY))}
    assert selected == {"rc-edge5"}


def test_limit_caps_the_selection(db_session) -> None:
    for i in range(6):
        _sub(db_session, "toku", f"rc-n{i}")
        _charge(db_session, "toku", f"rc-n{i}", f"rc-n{i}-c", "PAID", "2026-10-28")
    db_session.flush()
    assert len(tr.select_risk_subscriptions(db_session, limit=4, today=TODAY)) == 4


def test_each_subscription_is_selected_once(db_session) -> None:
    _sub(db_session, "toku", "rc-multi")
    for i, st in enumerate(("REJECTED", "PAID", "UNPAID")):
        _charge(db_session, "toku", "rc-multi", f"rc-multi-c{i}", st, "2026-10-27")
    db_session.flush()
    assert [s for s in tr.select_risk_subscriptions(db_session, limit=100, today=TODAY) if s[1] == "rc-multi"] == [
        ("toku", "rc-multi")]


def test_run_refreshes_selected_with_own_run_id_and_pauses_between(db_session, monkeypatch) -> None:
    _seed_window(db_session)
    monkeypatch.setattr(tr, "select_risk_subscriptions",
                        lambda db, limit, today=None: [("toku", "rc-rej"), ("virtualpos1", "rc-due")])
    rec, pauses = Recorder(), []

    async def sleep(seconds):
        pauses.append(seconds)

    summary = asyncio.run(tr.run_targeted_reconcile(
        db_session, limit=10, pause_seconds=0.5, refresh=rec, sleep=sleep, today=TODAY))
    assert [(c[0], c[1]) for c in rec.calls] == [("toku", "rc-rej"), ("virtualpos1", "rc-due")]
    assert len({c[2] for c in rec.calls}) == 2 and None not in {c[2] for c in rec.calls}
    assert pauses == [0.5]  # entre peticiones, no despues de la ultima
    assert (summary.selected, summary.refreshed, summary.failed, summary.skipped_reason) == (2, 2, 0, None)


def test_run_applies_default_limit_from_settings(db_session, monkeypatch) -> None:
    seen = {}

    def fake_select(db, limit, today=None):
        seen["limit"] = limit
        return []

    monkeypatch.setattr(tr, "select_risk_subscriptions", fake_select)
    monkeypatch.setattr(settings, "targeted_reconcile_max_per_run", 7)
    asyncio.run(tr.run_targeted_reconcile(db_session, refresh=Recorder(), sleep=_nosleep))
    assert seen["limit"] == 7
    assert settings.targeted_reconcile_enabled is False
    assert type(settings).model_fields["targeted_reconcile_max_per_run"].default == 200


def test_partial_failures_do_not_stop_the_run(db_session, monkeypatch) -> None:
    monkeypatch.setattr(tr, "select_risk_subscriptions",
                        lambda db, limit, today=None: [("toku", "rc-a"), ("toku", "rc-b"), ("toku", "rc-c")])
    rec = Recorder(fail={("toku", "rc-b"): RefreshError("PROVIDER_READ_FAILED")})
    summary = asyncio.run(tr.run_targeted_reconcile(db_session, refresh=rec, sleep=_nosleep))
    assert (summary.refreshed, summary.failed) == (2, 1) and len(rec.calls) == 3
    assert summary.codes == {"PROVIDER_READ_FAILED": 1}


def test_run_aborts_after_consecutive_failures(db_session, monkeypatch) -> None:
    ids = [("toku", f"rc-{i}") for i in range(12)]
    monkeypatch.setattr(tr, "select_risk_subscriptions", lambda db, limit, today=None: ids)
    rec = Recorder(fail=dict.fromkeys(ids, RefreshError("PROVIDER_READ_FAILED")))
    summary = asyncio.run(tr.run_targeted_reconcile(db_session, refresh=rec, sleep=_nosleep))
    assert summary.skipped_reason == "provider_failing" and len(rec.calls) == tr.MAX_CONSECUTIVE_FAILURES


def test_skips_when_a_sync_is_running(db_session, monkeypatch) -> None:
    monkeypatch.setattr(tr, "find_active_run", lambda db: EtlRun(status="running", records_upserted=0))
    monkeypatch.setattr(tr, "select_risk_subscriptions", lambda db, limit, today=None: [("toku", "rc-a")])
    rec = Recorder()
    summary = asyncio.run(tr.run_targeted_reconcile(db_session, refresh=rec, sleep=_nosleep))
    assert summary.skipped_reason == "sync_active" and rec.calls == []


# ----------------------------- job y bandera -----------------------------


def test_job_does_nothing_while_flag_is_off(monkeypatch) -> None:
    from app.scheduler.jobs import reconcile_targeted as job

    called = []

    async def fake_run(*a, **k):
        called.append(1)

    monkeypatch.setattr(job, "run_targeted_reconcile", fake_run)
    monkeypatch.setattr(settings, "targeted_reconcile_enabled", False)
    asyncio.run(job.reconcile_targeted())
    assert called == []
    monkeypatch.setattr(settings, "targeted_reconcile_enabled", True)
    asyncio.run(job.reconcile_targeted())
    assert called == [1]


def test_job_registered_every_three_hours_from_07_to_22() -> None:
    from app.scheduler.engine import JOB_TARGETED_RECONCILE, register_jobs

    class FakeScheduler:
        def __init__(self) -> None:
            self.jobs: dict[str, dict] = {}

        def get_job(self, _id):
            return None

        def add_job(self, func, **kw):
            self.jobs[kw["id"]] = {"func": func, **kw}

    sched = FakeScheduler()
    register_jobs(sched)
    job = sched.jobs[JOB_TARGETED_RECONCILE]
    assert job["trigger"] == "cron" and job["hour"] == "7,10,13,16,19,22" and job["minute"] == 0
    assert job["func"].__name__ == "reconcile_targeted"
