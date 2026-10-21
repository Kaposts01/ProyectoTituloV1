"""Tests para retry_failed_channels (VP-13)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.etl_run import EtlRun
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
