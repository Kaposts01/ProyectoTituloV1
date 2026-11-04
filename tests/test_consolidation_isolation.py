"""Aislamiento por SAVEPOINT en consolidate_to_centralized y wiring de sync_virtualpos."""
import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.sync_run import SyncRun
from app.models.write_run import WriteRun  # noqa: F401
from app.services import channel_consolidation, virtualpos_sync
from app.services.channel_consolidation import (
    ConsolidationError,
    consolidate_to_centralized,
)


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


def _install_fns(monkeypatch, ran: list[str]):
    def bad(db):
        db.execute(text("SELECT 1/0"))  # error de BD: aborta la transaccion de PG
        return 0

    def good(db):
        db.execute(text("SELECT 1"))
        ran.append("good")
        return 5

    monkeypatch.setitem(channel_consolidation._SOURCE_FNS, "virtualpos", [bad, good])


def test_db_error_in_one_fn_does_not_poison_session(monkeypatch, db_session) -> None:
    ran: list[str] = []
    _install_fns(monkeypatch, ran)

    total = consolidate_to_centralized(db_session, ["virtualpos"])

    assert ran == ["good"]
    assert total >= 5
    assert db_session.execute(select(1)).scalar_one() == 1  # sesion sigue usable


def test_raise_on_error_reports_failed_functions(monkeypatch, db_session) -> None:
    ran: list[str] = []
    _install_fns(monkeypatch, ran)

    with pytest.raises(ConsolidationError) as excinfo:
        consolidate_to_centralized(db_session, ["virtualpos"], raise_on_error=True)

    assert ran == ["good"]
    assert excinfo.value.failures == ["virtualpos.bad"]
    assert db_session.execute(select(1)).scalar_one() == 1


def test_sync_virtualpos_rejects_unknown_platform_before_provider(monkeypatch, db_session) -> None:
    def boom(*_a, **_k):
        raise AssertionError("no debe llamar al proveedor")

    monkeypatch.setattr(virtualpos_sync, "VirtualPOSClient", boom)

    with pytest.raises(ValueError):
        asyncio.run(virtualpos_sync.sync_virtualpos(db_session, platform="virtualpos9"))

    assert db_session.scalars(select(SyncRun).where(SyncRun.source == "virtualpos9")).first() is None


def test_sync_virtualpos_marks_run_failed_when_consolidation_fails(monkeypatch, db_session) -> None:
    from test_sync_gaps import _FakeVpClient

    monkeypatch.setattr(virtualpos_sync, "VirtualPOSClient", lambda: _FakeVpClient())
    _install_fns(monkeypatch, [])

    with pytest.raises(ConsolidationError):
        asyncio.run(virtualpos_sync.sync_virtualpos(db_session))

    run = db_session.scalars(select(SyncRun).where(SyncRun.source == "virtualpos1").order_by(SyncRun.started_at.desc())).first()
    assert run.status == "failed"
    assert "virtualpos.bad" in (run.error_message or "")
