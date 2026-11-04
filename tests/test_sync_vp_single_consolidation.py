"""SYNC-O-04: VirtualPOS se consolida UNA sola vez por corrida de sync_all, con el mismo resultado final.

Antes: `sync_virtualpos` consolidaba (y reconciliaba recuperaciones) al final de cada cuenta y `sync_all_channels`
volvia a consolidar todo: VP se reescribia 3 veces. Ahora el orquestador llama `sync_virtualpos(consolidate=False)`
y consolida una vez al final; `reconcile_charge_recoveries` corre despues de esa consolidacion.
"""

import asyncio
import uuid
from types import SimpleNamespace
from typing import Self

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.crm import Charge, Client, Payment, Plan, Subscription
from app.models.etl_run import EtlRun
from app.scheduler.jobs import sync_all
from app.services import channel_consolidation, virtualpos_sync
from app.services.channel_consolidation import consolidate_to_centralized


class _Client:
    """Cliente falso de una cuenta; todos sus ids llevan `prefix` para poder comparar corridas distintas."""

    def __init__(self, prefix: str) -> None:
        self.p = prefix

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def list_clients(self, page: int = 1, limit: int = 100):
        return {"clients": [{"uuid": f"{self.p}c1", "first_name": "Ana", "status": "ACTIVE"},
                            {"uuid": f"{self.p}c2", "first_name": "Beto", "status": "ACTIVE"}]}

    async def list_plans(self):
        return {"plans": [{"id": f"{self.p}plan", "name": "Plan", "amount": 5000}]}

    async def list_payments(self, page: int = 1, limit: int = 100):
        return {"payments": [{"order": {"uuid": f"{self.p}pay1", "amount": 5000}}]}

    async def list_subscriptions(self, page: int = 1, limit: int = 100):
        return {"suscriptions": [{
            "id": f"{self.p}sub", "plan_id": f"{self.p}plan", "status": "ACTIVA",
            "charge_program": [
                {"id": f"{self.p}ch1", "amount": 5000, "status": "pagado", "charge_date": "2026-09-05"},
                {"id": f"{self.p}ch2", "amount": 5000, "status": "rechazado", "charge_date": "2026-10-05"},
            ],
        }]}


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


_VOLATILE = {"id", "created_at", "updated_at", "source_record_id", "last_seen_at", "first_seen_at"}


def _snapshot(db: Session, prefix: str) -> dict[str, list[tuple]]:
    """Filas canonicas de VP cuyo external_id empieza por `prefix`, sin ids/fechas tecnicas y sin el prefijo."""
    out: dict[str, list[tuple]] = {}
    for model in (Client, Plan, Subscription, Charge, Payment):
        rows = []
        for row in db.scalars(select(model).where(model.external_id.like(f"{prefix}%"))):
            values = tuple(
                (col.name, str(getattr(row, col.name)).replace(prefix, ""))
                for col in model.__table__.columns
                if col.name not in _VOLATILE
            )
            rows.append(values)
        out[model.__tablename__] = sorted(rows)
    return out


def _run_old_flow(db: Session, monkeypatch, prefix: str) -> None:
    """Flujo anterior: cada cuenta consolida dentro de su sync y luego una consolidacion final."""
    monkeypatch.setattr(virtualpos_sync, "VirtualPOSClient", lambda *_a: _Client(prefix))
    for platform in ("virtualpos1", "virtualpos2"):
        asyncio.run(virtualpos_sync.sync_virtualpos(db, platform))  # consolidate=True por defecto
    consolidate_to_centralized(db, None)


def _run_new_flow(db: Session, monkeypatch, prefix: str, calls: list[str]) -> None:
    """Flujo nuevo: ninguna cuenta consolida; una sola consolidacion final."""
    monkeypatch.setattr(virtualpos_sync, "VirtualPOSClient", lambda *_a: _Client(prefix))
    real = channel_consolidation.consolidate_to_centralized

    def counting(db_, sources=None, **kw):
        calls.append("consolidate")
        return real(db_, sources, **kw)

    monkeypatch.setattr(virtualpos_sync, "consolidate_to_centralized", counting)
    for platform in ("virtualpos1", "virtualpos2"):
        asyncio.run(virtualpos_sync.sync_virtualpos(db, platform, consolidate=False))
    counting(db, ["virtualpos"])


def test_new_flow_leaves_the_same_canonical_rows_as_the_old_flow(monkeypatch, db_session) -> None:
    _run_old_flow(db_session, monkeypatch, "old-")
    calls: list[str] = []
    _run_new_flow(db_session, monkeypatch, "new-", calls)

    old, new = _snapshot(db_session, "old-"), _snapshot(db_session, "new-")
    assert old == new
    # No es una igualdad vacia: ambas cuentas dejaron cliente, plan, suscripcion, 2 cobros y pago en cada tabla.
    assert {table: len(rows) for table, rows in new.items()} == {
        "clients": 4, "plans": 2, "subscriptions": 2, "charges": 4, "payments": 2,
    }
    assert calls == ["consolidate"]  # una sola consolidacion en todo el flujo nuevo


def test_sync_virtualpos_without_consolidation_does_not_touch_canonical_tables(monkeypatch, db_session) -> None:
    monkeypatch.setattr(virtualpos_sync, "VirtualPOSClient", lambda *_a: _Client("solo-"))
    run = asyncio.run(virtualpos_sync.sync_virtualpos(db_session, "virtualpos1", consolidate=False))
    assert run.status == "completed"
    assert db_session.scalars(select(Charge).where(Charge.external_id.like("solo-%"))).first() is None


# --- orquestador ---------------------------------------------------------------------------------


def _patch_orchestrator(monkeypatch, *, vp2_fails: bool = False, consolidation_failures: list[str] | None = None):
    events: list[tuple] = []

    class FakeDb:
        def scalar(self, *_a, **_k):
            return None

        def add(self, *_a):
            pass

        def commit(self):
            pass

        def close(self):
            pass

        def get(self, *_a):
            return run

    run = EtlRun(status="running")
    run.id = uuid.uuid4()
    monkeypatch.setattr(sync_all, "SessionLocal", FakeDb)
    monkeypatch.setattr(sync_all, "start_exclusive_run", lambda _db, **_f: run)
    monkeypatch.setattr(sync_all, "skip_disabled_channel", lambda _c: False)

    async def vp(_db, platform, _cb=None, consolidate=True):
        events.append(("sync", platform, consolidate))
        if vp2_fails and platform == "virtualpos2":
            raise RuntimeError("boom")
        return SimpleNamespace(id=uuid.uuid4(), records_processed=1)

    async def ok(_db, _cb=None):
        return SimpleNamespace(id=uuid.uuid4(), records_processed=1)

    def consolidate(_db, sources, failures=None, **_k):
        events.append(("consolidate", tuple(sources) if sources else None))
        if failures is not None and consolidation_failures:
            failures.extend(consolidation_failures)
        return 0

    monkeypatch.setattr(sync_all, "sync_virtualpos", vp)
    monkeypatch.setattr(sync_all, "sync_toku", ok)
    monkeypatch.setattr(sync_all, "sync_payku", ok)
    monkeypatch.setattr(sync_all, "consolidate_to_centralized", consolidate)
    monkeypatch.setattr(sync_all, "reconcile_charge_recoveries", lambda _db, platform: events.append(("reconcile", platform)))
    monkeypatch.setattr(sync_all, "_CORE_ETL_RUNNERS", {})  # el ETL Core se prueba en test_sync_core_etl.py
    monkeypatch.setattr(sync_all, "_mark_sync_run_failed", lambda *_a, **_k: events.append(("mark_failed",)))
    return events, run


def test_orchestrator_syncs_without_consolidating_and_consolidates_once(monkeypatch) -> None:
    events, run = _patch_orchestrator(monkeypatch)
    asyncio.run(sync_all.sync_all_channels(channels=["virtualpos1", "virtualpos2"]))
    assert events == [
        ("sync", "virtualpos1", False),
        ("sync", "virtualpos2", False),
        ("consolidate", ("virtualpos",)),
        ("reconcile", "virtualpos1"),
        ("reconcile", "virtualpos2"),
    ]
    assert run.status == "completed"


def test_orchestrator_nightly_consolidates_virtualpos_a_single_time(monkeypatch) -> None:
    events, _ = _patch_orchestrator(monkeypatch)
    asyncio.run(sync_all.sync_all_channels())
    consolidations = [e for e in events if e[0] == "consolidate"]
    assert len(consolidations) == 1  # antes: 2 dentro de las cuentas + 1 final


def test_failed_account_is_not_reconciled(monkeypatch) -> None:
    events, run = _patch_orchestrator(monkeypatch, vp2_fails=True)
    asyncio.run(sync_all.sync_all_channels(channels=["virtualpos1", "virtualpos2"]))
    assert ("reconcile", "virtualpos1") in events and ("reconcile", "virtualpos2") not in events
    assert run.channels_failed == ["virtualpos2"]


def test_virtualpos_consolidation_failure_keeps_the_accounts_retryable(monkeypatch) -> None:
    """Antes una consolidacion VP fallida dejaba la cuenta `failed` (y en channels_failed para el reintento)."""
    events, run = _patch_orchestrator(monkeypatch, consolidation_failures=["virtualpos.charges"])
    asyncio.run(sync_all.sync_all_channels(channels=["virtualpos1"]))
    assert run.channels_failed == ["virtualpos1"]
    assert run.status == "failed"
    assert ("mark_failed",) in events and ("reconcile", "virtualpos1") not in events
