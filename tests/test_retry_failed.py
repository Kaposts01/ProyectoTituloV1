"""Tests para retry_failed_channels (VP-13)."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.models.etl_run import EtlRun
from app.models.sync_run import SyncRun
from app.scheduler.jobs import retry_failed


def _mock_db(scalar_side_effect):
    db = MagicMock()
    db.scalar.side_effect = scalar_side_effect
    return db


def test_skips_when_run_active():
    """Si hay un EtlRun activo, no se inicia reintento."""
    active_run = EtlRun(status="running")
    mock_db = _mock_db([active_run])

    with patch.object(retry_failed, "SessionLocal", return_value=mock_db):
        with patch.object(retry_failed, "_defer_retry"):
            with patch("app.scheduler.jobs.sync_all.sync_all_channels", AsyncMock()) as mock_sync:
                asyncio.run(retry_failed.retry_failed_channels())

    mock_sync.assert_not_called()
    mock_db.close.assert_called_once()


def test_skips_when_no_failed_channels():
    """Si el último run no tiene canales fallidos, no se inicia reintento."""
    last_run = EtlRun(status="completed")
    last_run.channels_failed = None
    mock_db = _mock_db([None, last_run])

    with patch.object(retry_failed, "SessionLocal", return_value=mock_db):
        with patch("app.scheduler.jobs.sync_all.sync_all_channels", AsyncMock()) as mock_sync:
            asyncio.run(retry_failed.retry_failed_channels())

    mock_sync.assert_not_called()


def test_skips_when_failed_channels_empty_list():
    """channels_failed=[] (lista vacía) también omite el reintento."""
    last_run = EtlRun(status="completed")
    last_run.channels_failed = []
    mock_db = _mock_db([None, last_run])

    with patch.object(retry_failed, "SessionLocal", return_value=mock_db):
        with patch("app.scheduler.jobs.sync_all.sync_all_channels", AsyncMock()) as mock_sync:
            asyncio.run(retry_failed.retry_failed_channels())

    mock_sync.assert_not_called()


def test_retries_failed_channels():
    """Si el último run tiene canales fallidos y no hay run activo, los reintenta."""
    last_run = EtlRun(status="completed")
    last_run.channels_failed = ["toku"]
    mock_db = _mock_db([None, last_run])

    with patch.object(retry_failed, "SessionLocal", return_value=mock_db):
        with patch("app.scheduler.jobs.sync_all.sync_all_channels", AsyncMock()) as mock_sync:
            asyncio.run(retry_failed.retry_failed_channels())

    mock_sync.assert_called_once_with(channels=["toku"])
    mock_db.close.assert_called_once()


# --- SYNC-D-10: desacople de la ventana y tope de fallos ----------------------------------------------------------


def test_active_run_defers_instead_of_dropping_the_retry():
    """Con la sync principal aun corriendo, el reintento se pospone (no se pierde)."""
    mock_db = _mock_db([EtlRun(status="running")])

    with patch.object(retry_failed, "SessionLocal", return_value=mock_db):
        with patch.object(retry_failed, "_defer_retry") as defer:
            with patch("app.scheduler.jobs.sync_all.sync_all_channels", AsyncMock()) as mock_sync:
                asyncio.run(retry_failed.retry_failed_channels(deferrals=2))

    defer.assert_called_once_with(2)
    mock_sync.assert_not_called()


def test_defer_schedules_a_one_off_job_with_the_next_deferral(monkeypatch):
    scheduler = MagicMock(running=True)
    monkeypatch.setattr(settings, "sync_retry_max_deferrals", 3)
    monkeypatch.setattr(settings, "sync_retry_defer_minutes", 30)
    with patch("app.scheduler.engine.get_scheduler", return_value=scheduler):
        assert retry_failed._defer_retry(1) is True
    kwargs = scheduler.add_job.call_args.kwargs
    assert kwargs["trigger"] == "date"
    assert kwargs["kwargs"] == {"deferrals": 2}
    assert kwargs["id"] == retry_failed.JOB_SYNC_RETRY_DEFERRED
    assert kwargs["replace_existing"] is True


def test_defer_gives_up_after_the_max_deferrals(monkeypatch):
    scheduler = MagicMock(running=True)
    monkeypatch.setattr(settings, "sync_retry_max_deferrals", 3)
    with patch("app.scheduler.engine.get_scheduler", return_value=scheduler):
        assert retry_failed._defer_retry(3) is False
    scheduler.add_job.assert_not_called()


def test_defer_does_nothing_without_a_running_scheduler():
    scheduler = MagicMock(running=False)
    with patch("app.scheduler.engine.get_scheduler", return_value=scheduler):
        assert retry_failed._defer_retry(0) is False
    scheduler.add_job.assert_not_called()


def test_channels_over_the_daily_failure_cap_are_not_retried():
    last_run = EtlRun(status="partial")
    last_run.channels_failed = ["toku", "payku"]
    mock_db = _mock_db([None, last_run])

    with patch.object(retry_failed, "SessionLocal", return_value=mock_db):
        with patch.object(retry_failed, "_config_failed_sources", return_value=set()):
            with patch.object(retry_failed, "_exhausted_sources", return_value={"payku"}):
                with patch("app.scheduler.jobs.sync_all.sync_all_channels", AsyncMock()) as mock_sync:
                    asyncio.run(retry_failed.retry_failed_channels())

    mock_sync.assert_called_once_with(channels=["toku"])


def test_all_channels_exhausted_means_no_retry():
    last_run = EtlRun(status="failed")
    last_run.channels_failed = ["toku"]
    mock_db = _mock_db([None, last_run])

    with patch.object(retry_failed, "SessionLocal", return_value=mock_db):
        with patch.object(retry_failed, "_exhausted_sources", return_value={"toku"}):
            with patch("app.scheduler.jobs.sync_all.sync_all_channels", AsyncMock()) as mock_sync:
                asyncio.run(retry_failed.retry_failed_channels())

    mock_sync.assert_not_called()


def test_exhausted_sources_counts_todays_failures_in_the_database(monkeypatch):
    """Base de test: cuenta solo fallos de HOY (dia de Chile) y del canal pedido."""
    monkeypatch.setattr(settings, "sync_retry_max_failures_per_day", 2)
    src_hit, src_ok = f"tst-{uuid.uuid4().hex[:8]}", f"tst-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    connection = engine.connect()
    transaction = connection.begin()
    db = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        db.add_all([
            SyncRun(source=src_hit, status="failed", started_at=now),
            SyncRun(source=src_hit, status="failed", started_at=now),
            SyncRun(source=src_ok, status="failed", started_at=now),
            SyncRun(source=src_ok, status="completed", started_at=now),
            SyncRun(source=src_ok, status="failed", started_at=now - timedelta(days=3)),  # otro dia: no cuenta
        ])
        db.flush()
        assert retry_failed._exhausted_sources(db, [src_hit, src_ok]) == {src_hit}
    finally:
        db.close()
        transaction.rollback()
        connection.close()
