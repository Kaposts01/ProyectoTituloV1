"""SYNC-O-08: marcas de agua en `sync_cursors`, registro TCH en `tch_file_loads` y `last_success_at` por recurso."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.v1.routes import sync_runs
from app.db.session import engine
from app.models.sync_cursor import SyncCursor
from app.models.tch import TchFileLoad
from app.services import sync_cursors
from app.services import tch_report_registry as registry


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    session.execute(delete(SyncCursor))
    session.flush()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_record_success_is_one_row_per_mode_and_advances(db_session) -> None:
    t1 = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)
    t2 = t1 + timedelta(days=1)
    sync_cursors.record_success(db_session, "toku", "transaction", "full", started_at=t1, records_seen=10, requests_made=1)
    sync_cursors.record_success(db_session, "toku", "transaction", "full", started_at=t2, records_seen=12, requests_made=2)
    rows = db_session.scalars(select(SyncCursor).where(SyncCursor.source == "toku")).all()
    assert len(rows) == 1  # NULLS NOT DISTINCT: una sola marca por modo
    assert rows[0].records_seen == 12 and rows[0].requests_made == 2 and rows[0].status == "done"
    assert sync_cursors.last_success(db_session, "toku", "transaction", "full") == t2


def test_last_success_without_mode_takes_the_newest_of_any_mode(db_session) -> None:
    t1 = datetime(2026, 10, 1, tzinfo=UTC)
    sync_cursors.record_success(db_session, "virtualpos1", "payment", "full", started_at=t1)
    sync_cursors.record_success(db_session, "virtualpos1", "payment", "window", started_at=t1 + timedelta(hours=5))
    assert sync_cursors.last_success(db_session, "virtualpos1", "payment") == t1 + timedelta(hours=5)
    assert sync_cursors.last_success(db_session, "virtualpos1", "payment", "full") == t1
    assert sync_cursors.last_success(db_session, "virtualpos1", "client") is None


def test_health_exposes_last_success_at_per_resource(db_session) -> None:
    t1 = datetime(2026, 10, 1, tzinfo=UTC)
    sync_cursors.record_success(db_session, "virtualpos2", "payment", "full", started_at=t1)
    sync_cursors.record_success(db_session, "toku", "invoice", "full", started_at=t1)
    items = {item["channel"]: item for item in sync_runs._compute_health(db_session, t1 + timedelta(hours=1))}
    assert items["virtualpos"]["resources"] == [
        {"source": "virtualpos2", "resource": "payment", "mode": "full", "last_success_at": t1.isoformat()}
    ]
    assert items["toku"]["resources"][0]["resource"] == "invoice"
    assert "resources" not in items["payku"]  # sin marcas no se agrega la clave


def test_tch_health_resource_is_the_last_report_load(db_session) -> None:
    registry.clear(db_session)
    items = {item["channel"]: item for item in sync_runs._compute_health(db_session, datetime.now(UTC))}
    assert "resources" not in items["tch"]
    registry.register(db_session, uuid.uuid4().hex * 2, "a.xlsx", 10, rows_loaded=5)
    items = {item["channel"]: item for item in sync_runs._compute_health(db_session, datetime.now(UTC))}
    assert items["tch"]["resources"][0]["resource"] == "file"
    assert items["tch"]["resources"][0]["last_success_at"] is not None


def test_registry_lives_in_tch_file_loads_and_marks_consolidated_files(db_session) -> None:
    sha = uuid.uuid4().hex * 2
    registry.register(db_session, sha, "a.xlsx", 10, rows_loaded=7)
    registry.register(db_session, sha, "a.xlsx", 10, rows_loaded=7)  # idempotente
    load = db_session.get(TchFileLoad, sha)
    assert load is not None and load.rows_loaded == 7 and load.consolidated_at is None
    registry.mark_consolidated(db_session, registry.consolidation_snapshot(db_session))
    db_session.refresh(load)
    assert load.consolidated_at is not None
