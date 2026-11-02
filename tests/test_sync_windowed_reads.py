"""SYNC-O-02 / SYNC-O-05 / SYNC-D-17: lectura por ventana (bandera apagada por defecto), solape, respaldo completo
si el proveedor ignora el filtro, y estadisticas por recurso en `sync_runs`. Sin proveedores reales (fakes)."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Self

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.v1.routes import sync_runs
from app.core.config import settings
from app.core.security import get_current_user
from app.db.session import engine
from app.main import app
from app.models.sync_cursor import SyncCursor
from app.models.sync_run import SyncRun
from app.models.write_run import (
    WriteRun,  # noqa: F401 — registra la tabla antes de resolver FKs
)
from app.services import (
    sync_cursors,
    sync_metrics,
    sync_window,
    toku_sync,
    virtualpos_sync,
)
from app.services.sync_window import ReadWindow


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


def _recent() -> str:
    return datetime.now(UTC).isoformat()


class TokuFake:
    def __init__(self, ignore_filter: bool = False) -> None:
        self.transaction_calls: list[dict] = []
        self.ignore_filter = ignore_filter
        self.now = _recent()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def _empty(self, page: int, page_size: int):
        return {"data": [], "meta": {"pages": 1}}

    list_customers = list_subscriptions = list_invoices = list_payments = list_payment_methods = _empty

    async def list_transactions(self, page: int, page_size: int, start_date=None, end_date=None):
        self.transaction_calls.append({"start_date": start_date, "end_date": end_date})
        old = {"id": "tx-old", "transaction_date": "2025-01-01T00:00:00Z", "initialization_date": "2025-01-01T00:00:00Z"}
        new = {"id": "tx-new", "transaction_date": self.now}
        windowed = start_date is not None
        data = [new] if windowed and not self.ignore_filter else [old, new]
        return {"data": data, "meta": {"pages": 1}}


def _mark_full(db, source, resource, ago: timedelta, seen: int = 2) -> datetime:
    at = datetime.now(UTC) - ago
    sync_cursors.record_success(db, source, resource, "full", started_at=at, records_seen=seen)
    return at


def _cursor(db, source, resource, mode):
    return sync_cursors.get(db, source, resource, mode)


def test_flag_is_off_by_default() -> None:
    assert type(settings).model_fields["sync_windowed_reads_enabled"].default is False


def test_flag_off_reads_everything_even_with_a_recent_full_mark(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "sync_windowed_reads_enabled", False)
    _mark_full(db_session, "toku", "transaction", timedelta(hours=1))
    fake = TokuFake()
    monkeypatch.setattr(toku_sync, "TokuClient", lambda: fake)
    run = asyncio.run(toku_sync.sync_toku(db_session))
    assert run.status == "completed"
    assert fake.transaction_calls == [{"start_date": None, "end_date": None}]
    assert run.resource_stats["transaction"]["mode"] == "full"


def test_without_a_full_mark_the_first_read_is_full_and_leaves_marks(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "sync_windowed_reads_enabled", True)
    fake = TokuFake()
    monkeypatch.setattr(toku_sync, "TokuClient", lambda: fake)
    asyncio.run(toku_sync.sync_toku(db_session))
    assert fake.transaction_calls == [{"start_date": None, "end_date": None}]
    for resource in ("customer", "invoice", "transaction", "payment_method"):
        assert _cursor(db_session, "toku", resource, "full").last_success_at is not None


def test_window_starts_at_last_success_minus_the_overlap(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "sync_windowed_reads_enabled", True)
    monkeypatch.setattr(settings, "sync_window_overlap_hours", 48)
    last = _mark_full(db_session, "toku", "transaction", timedelta(days=1))
    fake = TokuFake()
    monkeypatch.setattr(toku_sync, "TokuClient", lambda: fake)
    run = asyncio.run(toku_sync.sync_toku(db_session))
    expected_start = (last - timedelta(hours=48)).date().isoformat()
    expected_end = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    assert fake.transaction_calls == [{"start_date": expected_start, "end_date": expected_end}]
    assert run.resource_stats["transaction"]["mode"] == "window"
    assert _cursor(db_session, "toku", "transaction", "window").last_success_at is not None
    assert _cursor(db_session, "toku", "transaction", "full").last_success_at == last  # la completa no avanza


def test_ignored_filter_falls_back_to_a_full_read(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "sync_windowed_reads_enabled", True)
    last = _mark_full(db_session, "toku", "transaction", timedelta(hours=6))
    fake = TokuFake(ignore_filter=True)
    monkeypatch.setattr(toku_sync, "TokuClient", lambda: fake)
    run = asyncio.run(toku_sync.sync_toku(db_session))
    assert run.status == "completed"
    assert len(fake.transaction_calls) == 2
    assert fake.transaction_calls[0]["start_date"] is not None and fake.transaction_calls[1]["start_date"] is None
    assert run.resource_stats["transaction"]["mode"] == "full"
    assert _cursor(db_session, "toku", "transaction", "full").last_success_at > last


def test_full_reread_when_the_last_full_read_is_too_old(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "sync_windowed_reads_enabled", True)
    monkeypatch.setattr(settings, "sync_window_full_refresh_days", 7)
    _mark_full(db_session, "toku", "transaction", timedelta(days=8))
    fake = TokuFake()
    monkeypatch.setattr(toku_sync, "TokuClient", lambda: fake)
    asyncio.run(toku_sync.sync_toku(db_session))
    assert fake.transaction_calls == [{"start_date": None, "end_date": None}]


def test_resource_stats_count_inserted_updated_and_unchanged(monkeypatch, db_session) -> None:
    fake = TokuFake()
    monkeypatch.setattr(toku_sync, "TokuClient", lambda: fake)
    monkeypatch.setattr(settings, "sync_windowed_reads_enabled", False)
    tag = uuid.uuid4().hex
    old_list = fake.list_transactions

    async def unique_transactions(page, page_size, start_date=None, end_date=None):
        response = await old_list(page, page_size, start_date, end_date)
        response["data"] = [{**r, "id": f"{r['id']}-{tag}"} for r in response["data"]]
        return response

    fake.list_transactions = unique_transactions
    first = asyncio.run(toku_sync.sync_toku(db_session))
    second = asyncio.run(toku_sync.sync_toku(db_session))
    assert (first.resource_stats["transaction"]["inserted"], first.resource_stats["transaction"]["unchanged"]) == (2, 0)
    assert (second.resource_stats["transaction"]["inserted"], second.resource_stats["transaction"]["updated"]) == (0, 0)
    assert second.resource_stats["transaction"]["unchanged"] == 2
    assert second.resource_stats["transaction"]["seconds"] >= 0


def test_sync_run_carries_the_global_run_id(monkeypatch, db_session) -> None:
    monkeypatch.setattr(toku_sync, "TokuClient", TokuFake)
    etl_run_id = uuid.uuid4()
    token = sync_metrics.activate(sync_metrics.RunMetrics(str(etl_run_id)))
    try:
        run = asyncio.run(toku_sync.sync_toku(db_session))
    finally:
        sync_metrics.deactivate(token)
    assert run.etl_run_id == etl_run_id


def test_list_endpoint_filters_by_etl_run_and_exposes_stats(db_session) -> None:
    etl_run_id = uuid.uuid4()
    started = datetime(2099, 1, 1, tzinfo=UTC)
    db_session.add(SyncRun(source="toku", status="completed", started_at=started, finished_at=started + timedelta(seconds=90),
                           etl_run_id=etl_run_id, resource_stats={"transaction": {"mode": "window", "inserted": 3}}))
    db_session.add(SyncRun(source="toku", status="completed", started_at=started))
    db_session.flush()
    app.dependency_overrides[sync_runs.get_db] = lambda: db_session
    user = SimpleNamespace(
        id=uuid.uuid4(), is_active=True,
        roles=[SimpleNamespace(name="r", permissions=[SimpleNamespace(code="sync_runs.view")])],
    )
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = TestClient(app).get(f"/api/v1/sync-runs?etl_run_id={etl_run_id}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["etl_run_id"] == str(etl_run_id)
    assert rows[0]["duration_seconds"] == 90.0
    assert rows[0]["resource_stats"]["transaction"]["inserted"] == 3


# --- VirtualPOS ----------------------------------------------------------------------------------------------


class VpFake:
    def __init__(self, ignore_filter: bool = False, total: int | None = None) -> None:
        self.client_calls: list[dict] = []
        self.payment_calls: list[dict] = []
        self.ignore_filter = ignore_filter
        self.total = total

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def list_clients(self, page: int = 1, limit: int = 100, **filters):
        self.client_calls.append(filters)
        return {"data": [{"uuid": "vpw-client-1", "created": "2026-11-01 10:00:00"}], "page": 1, "limit": limit, "total": 1}

    async def list_payments(self, page: int = 1, limit: int = 100, **filters):
        self.payment_calls.append(filters)
        recent = {"order": {"uuid": "vpw-pay-new", "created_at": _recent(), "authorized_at": _recent()}}
        old = {"order": {"uuid": "vpw-pay-old", "created_at": "2025-03-01 10:00:00", "authorized_at": "2025-03-01 10:01:00"}}
        data = [recent] if filters and not self.ignore_filter else [recent, old]
        pagination = {"page": 1, "pages": 1, "limit": limit}
        if self.total is not None:
            pagination["total"] = self.total
        return {"payments": data, "pagination": pagination}

    async def list_plans(self):
        return {"data": []}

    async def list_subscriptions(self, page: int = 1, limit: int = 100):
        return {"data": [], "pagination": {"page": 1, "pages": 1}}


def _vp_run(monkeypatch, db, fake):
    monkeypatch.setattr(virtualpos_sync, "VirtualPOSClient", lambda: fake)
    return asyncio.run(virtualpos_sync.sync_virtualpos(db, consolidate=False))


def test_vp_window_reads_payments_by_creation_and_by_authorization(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "sync_windowed_reads_enabled", True)
    for resource in ("client", "payment"):
        _mark_full(db_session, "virtualpos1", resource, timedelta(hours=12))
    fake = VpFake()
    run = _vp_run(monkeypatch, db_session, fake)
    assert run.status == "completed"
    assert set(fake.client_calls[0]) == {"created_from", "created_to"}
    assert [set(c) for c in fake.payment_calls] == [{"created_from", "created_to"}, {"authorization_from", "authorization_to"}]
    assert run.resource_stats["payment"]["mode"] == "window"
    assert run.resource_stats["subscription"]["mode"] == "full"  # suscripciones siempre completas


def test_vp_ignored_date_filter_falls_back_to_full(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "sync_windowed_reads_enabled", True)
    _mark_full(db_session, "virtualpos1", "payment", timedelta(hours=12))
    fake = VpFake(ignore_filter=True)
    run = _vp_run(monkeypatch, db_session, fake)
    assert fake.payment_calls[0] != {} and fake.payment_calls[-1] == {}
    assert run.resource_stats["payment"]["mode"] == "full"


def test_vp_total_not_reduced_by_the_filter_falls_back_to_full(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "sync_windowed_reads_enabled", True)
    _mark_full(db_session, "virtualpos1", "payment", timedelta(hours=12), seen=5000)
    fake = VpFake(total=5000)  # las fechas parecen bien, pero el total no bajo: el filtro no recorto nada
    run = _vp_run(monkeypatch, db_session, fake)
    assert fake.payment_calls[-1] == {}
    assert run.resource_stats["payment"]["mode"] == "full"


# --- guardas unitarias --------------------------------------------------------------------------------------


def test_records_outside_uses_the_newest_known_date_and_nested_fields() -> None:
    window = ReadWindow(start=datetime(2026, 10, 10, tzinfo=UTC), end=datetime(2026, 10, 12, tzinfo=UTC))
    records = [
        {"transaction_date": "2026-09-01T00:00:00Z", "initialization_date": "2026-10-11T00:00:00Z"},  # dentro (DEC-03)
        {"transaction_date": "2026-09-01T00:00:00Z"},  # fuera
        {"order": {"created_at": "2026-10-09 23:00:00"}},  # dentro por la tolerancia de 1 dia
        {"other": "sin fecha"},  # no decide
    ]
    assert sync_window.records_outside(records, window, ("transaction_date", "initialization_date")) == 1
    assert sync_window.records_outside(records, window, ("order.created_at",)) == 0
    assert window.end_date == "2026-10-13"
