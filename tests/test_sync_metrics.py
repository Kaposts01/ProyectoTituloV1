"""SYNC-O-01: instrumentacion por fase y recurso, sin migracion.

Las duraciones (extraccion API, upsert, consolidacion, ETL Core) se guardan en una fila de `source_records`
(`source='sync_metrics'`, `external_id=<run_id>`) y en un log estructurado `sync.metrics`; ver
`docs/data/sync-idempotency.md`. Nunca se guardan datos personales ni del proveedor.
"""

import asyncio
import json
import logging
import uuid
from types import SimpleNamespace
from typing import Self

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, engine
from app.models.etl_run import EtlRun
from app.models.source_record import SourceRecord
from app.scheduler.jobs import sync_all
from app.services import (
    channel_consolidation,
    payku_sync,
    read_only_provider_sync,
    sync_metrics,
    virtualpos_sync,
)
from app.services.sync_metrics import RunMetrics


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


def _row(db: Session, run_id: str) -> dict | None:
    return db.scalar(
        select(SourceRecord.payload).where(
            SourceRecord.source == sync_metrics.SOURCE, SourceRecord.external_id == run_id
        )
    )


# --- RunMetrics -----------------------------------------------------------------------------------


def test_timed_records_phase_resource_seconds_and_counts() -> None:
    metrics = RunMetrics("r1")
    with metrics.timed("consolidate", "toku.customers") as info:
        info["records"] = 5
    entry = metrics.phases[0]
    assert entry["phase"] == "consolidate" and entry["resource"] == "toku.customers" and entry["records"] == 5
    assert entry["seconds"] >= 0


def test_persist_writes_one_idempotent_row_and_a_structured_log(db_session, caplog) -> None:
    run_id = str(uuid.uuid4())
    metrics = RunMetrics(run_id)
    metrics.add("sync", "toku", 1.5, records=3)
    metrics.note("tch_consolidation", "omitida")
    with caplog.at_level(logging.INFO, logger="sync.metrics"):
        metrics.persist(db_session)
        metrics.add("core_etl", "toku", 2.0)
        metrics.persist(db_session)  # segunda vez: actualiza la misma fila
    row = _row(db_session, run_id)
    assert row["run_id"] == run_id and [p["phase"] for p in row["phases"]] == ["sync", "core_etl"]
    assert row["notes"] == {"tch_consolidation": "omitida"}
    count = db_session.scalars(select(SourceRecord).where(SourceRecord.external_id == run_id)).all()
    assert len(count) == 1
    logged = [r.message for r in caplog.records if r.name == "sync.metrics"]
    assert logged and json.loads(logged[-1].split("sync_metrics ", 1)[1])["run_id"] == run_id


def test_persist_never_raises_even_with_a_broken_session() -> None:
    class Broken:
        def execute(self, *_a, **_k):
            raise RuntimeError("db caida")

        def flush(self):
            raise RuntimeError("db caida")

    RunMetrics("r2").persist(Broken())  # no debe lanzar


def test_extra_values_are_limited_to_plain_scalars() -> None:
    metrics = RunMetrics("r3")
    metrics.add("sync", "toku", 1.0, records=3, note={"a": "b" * 500}, other=None)
    entry = metrics.phases[0]
    assert entry["records"] == 3 and entry["other"] is None
    assert isinstance(entry["note"], str) and len(entry["note"]) <= 100  # nada de estructuras ni textos largos


# --- recursos: extraccion API vs upsert ------------------------------------------------------------


def _by_resource(metrics: RunMetrics) -> dict[str, dict]:
    return {p["resource"]: p for p in metrics.phases if p["phase"] == "sync_resource"}


def test_read_only_provider_sync_times_api_and_upsert_per_resource(db_session) -> None:
    class Client:
        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    async def read_customers(_client, page):
        return {"customers": [{"id": f"m-c{page}-1"}, {"id": f"m-c{page}-2"}], "next_cursor": "x" if page == 1 else None}

    async def read_invoices(_client, page):
        return {"data": [{"id": "m-i1"}]}

    metrics = RunMetrics("rs")
    token = sync_metrics.activate(metrics)
    try:
        asyncio.run(read_only_provider_sync.sync_read_only_provider(
            db_session, source="toku", client_factory=Client, secrets=(),
            resources=[("customer", 100, True, read_customers), ("invoice", 100, False, read_invoices)],
        ))
    finally:
        sync_metrics.deactivate(token)
    by = _by_resource(metrics)
    assert set(by) == {"toku.customer", "toku.invoice"}
    assert by["toku.customer"]["pages"] == 2 and by["toku.customer"]["records"] == 4
    assert by["toku.invoice"]["pages"] == 1 and by["toku.invoice"]["records"] == 1
    for entry in by.values():
        assert entry["api_seconds"] >= 0 and entry["upsert_seconds"] >= 0


def test_without_an_active_collector_the_sync_runs_unchanged(db_session) -> None:
    class Client:
        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    async def read(_client, page):
        return {"data": [{"id": "m-solo"}]}

    run = asyncio.run(read_only_provider_sync.sync_read_only_provider(
        db_session, source="toku", client_factory=Client, secrets=(), resources=[("invoice", 100, False, read)],
    ))
    assert run.status == "completed" and run.records_processed == 1


class _VpClient:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def list_clients(self, page: int = 1, limit: int = 100):
        return {"clients": [{"uuid": "mv-c1"}]}

    async def list_plans(self):
        return {"plans": [{"id": "mv-plan"}]}

    async def list_payments(self, page: int = 1, limit: int = 100):
        return {"payments": [{"order": {"uuid": "mv-p1", "amount": 1}}]}

    async def list_subscriptions(self, page: int = 1, limit: int = 100):
        return {"suscriptions": [{"id": "mv-s1", "plan_id": "mv-plan",
                                  "charge_program": [{"id": "mv-ch1", "amount": 1}, {"id": "mv-ch2", "amount": 1}]}]}


def test_virtualpos_sync_reports_each_resource(monkeypatch, db_session) -> None:
    monkeypatch.setattr(virtualpos_sync, "VirtualPOSClient", lambda *_a: _VpClient())
    metrics = RunMetrics("rv")
    token = sync_metrics.activate(metrics)
    try:
        asyncio.run(virtualpos_sync.sync_virtualpos(db_session, "virtualpos1", consolidate=False))
    finally:
        sync_metrics.deactivate(token)
    by = _by_resource(metrics)
    assert {"virtualpos1.client", "virtualpos1.payment", "virtualpos1.plan", "virtualpos1.subscription",
            "virtualpos1.charge"} <= set(by)
    assert by["virtualpos1.charge"]["records"] == 2


def test_payku_sync_reports_each_resource(monkeypatch, db_session) -> None:
    class PkClient(_VpClient):
        async def list_clients(self, page: int = 1, per_page: int = 100):
            return {"customers": [{"id": "mp-c1"}]}

        async def list_plans(self):
            return {"plans": [{"id": "mp-plan"}]}

        async def list_subscriptions(self, page: int = 1, per_page: int = 100):
            return {"subscriptions": [{"id": "mp-s1", "transactions": [{"id": "mp-t1"}]}]}

    monkeypatch.setattr(payku_sync, "PaykuClient", PkClient)
    metrics = RunMetrics("rp")
    token = sync_metrics.activate(metrics)
    try:
        asyncio.run(payku_sync.sync_payku(db_session))
    finally:
        sync_metrics.deactivate(token)
    by = _by_resource(metrics)
    assert {"payku.client", "payku.plan", "payku.subscription", "payku.transaction"} <= set(by)
    assert by["payku.transaction"]["records"] == 1


# --- consolidacion --------------------------------------------------------------------------------


def test_consolidation_reports_per_function_timings(db_session) -> None:
    timings: list[dict] = []
    channel_consolidation.consolidate_to_centralized(db_session, ["payku"], timings=timings)
    names = {(t["source"], t["fn"]) for t in timings}
    assert ("payku", "payku_clients") in names or ("payku", "clients") in names
    assert all(t["seconds"] >= 0 and "records" in t for t in timings)


# --- corrida completa: queda guardado ----------------------------------------------------------------


def test_a_full_run_persists_its_phases(monkeypatch) -> None:
    run_id = str(uuid.uuid4())
    cleanup = SessionLocal()
    try:
        cleanup.execute(delete(EtlRun))
        cleanup.commit()
    finally:
        cleanup.close()

    monkeypatch.setattr(sync_all, "skip_disabled_channel", lambda _c: False)
    monkeypatch.setattr(sync_all, "_CORE_ETL_RUNNERS", {"toku": lambda _db: {"charges_upserted": 4}})

    async def toku(_db, _cb=None):
        return SimpleNamespace(id=uuid.uuid4(), records_processed=9)

    def consolidate(_db, sources, failures=None, timings=None, **_k):
        if timings is not None:
            timings.append({"source": "toku", "fn": "toku_customers", "seconds": 0.25, "records": 9})
        return 0

    monkeypatch.setattr(sync_all, "sync_toku", toku)
    monkeypatch.setattr(sync_all, "consolidate_to_centralized", consolidate)
    try:
        asyncio.run(sync_all.sync_all_channels(run_id, ["toku"]))
        db = SessionLocal()
        try:
            payload = _row(db, run_id)
        finally:
            db.close()
        assert payload is not None
        phases = {(p["phase"], p["resource"]) for p in payload["phases"]}
        assert ("sync", "toku") in phases
        assert ("consolidate", "toku.toku_customers") in phases
        assert ("core_etl", "toku") in phases
        assert ("consolidate_total", None) in phases
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.execute(delete(EtlRun))
            cleanup.execute(delete(SourceRecord).where(SourceRecord.source == sync_metrics.SOURCE))
            cleanup.commit()
        finally:
            cleanup.close()
