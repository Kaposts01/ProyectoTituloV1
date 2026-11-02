"""BILL-22: el barrido `billing_sweep_applying` deja su «latido» en el tablero del scheduler, detras de una bandera.

Sin VirtualPOS ni correo: el barrido es solo local y se sustituye por un doble que devuelve lo que se le pide.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.models.sync_run import SyncRun
from app.scheduler.jobs import billing_jobs
from app.services import billing_apply

SOURCE = billing_jobs.JOB_BILLING_SWEEP


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    session.execute(delete(SyncRun).where(SyncRun.source == SOURCE))
    session.flush()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def sweep(db_session, monkeypatch):
    monkeypatch.setattr(billing_jobs, "SessionLocal",
                        lambda: Session(bind=db_session.get_bind(), join_transaction_mode="create_savepoint"))
    result: list[uuid.UUID] = []
    monkeypatch.setattr(billing_apply, "sweep_stuck_applying", lambda db, older_than_minutes: list(result))
    return result


def _rows(db) -> list[SyncRun]:
    db.expire_all()
    return list(db.scalars(select(SyncRun).where(SyncRun.source == SOURCE).order_by(SyncRun.started_at)))


def test_heartbeat_flag_is_off_by_default():
    assert type(settings).model_fields["billing_sweep_heartbeat_enabled"].default is False


def test_without_flag_an_empty_scheduled_sweep_leaves_no_row(db_session, sweep, monkeypatch):
    monkeypatch.setattr(settings, "billing_sweep_heartbeat_enabled", False)
    asyncio.run(billing_jobs.billing_sweep_applying())
    assert _rows(db_session) == []


def test_with_flag_the_dashboard_keeps_a_single_heartbeat_and_every_real_sweep(db_session, sweep, monkeypatch):
    monkeypatch.setattr(settings, "billing_sweep_heartbeat_enabled", True)
    asyncio.run(billing_jobs.billing_sweep_applying())
    first = _rows(db_session)
    assert [(r.status, r.records_processed) for r in first] == [("completed", 0)]
    assert first[0].finished_at is not None
    first_id = first[0].id

    sweep.append(uuid.uuid4())  # una corrida que si barre queda siempre
    asyncio.run(billing_jobs.billing_sweep_applying())
    sweep.clear()
    asyncio.run(billing_jobs.billing_sweep_applying())
    asyncio.run(billing_jobs.billing_sweep_applying())

    rows = _rows(db_session)
    assert sorted(r.records_processed for r in rows) == [0, 1]  # un solo latido vacio (el ultimo) y el barrido real
    heartbeat = next(r for r in rows if r.records_processed == 0)
    assert heartbeat.id != first_id


def test_with_flag_a_failed_sweep_is_never_pruned(db_session, sweep, monkeypatch):
    monkeypatch.setattr(settings, "billing_sweep_heartbeat_enabled", True)

    def boom(db, older_than_minutes):
        raise RuntimeError("caido")

    monkeypatch.setattr(billing_apply, "sweep_stuck_applying", boom)
    asyncio.run(billing_jobs.billing_sweep_applying())
    monkeypatch.setattr(billing_apply, "sweep_stuck_applying", lambda db, older_than_minutes: [])
    asyncio.run(billing_jobs.billing_sweep_applying())
    assert sorted(r.status for r in _rows(db_session)) == ["completed", "failed"]
