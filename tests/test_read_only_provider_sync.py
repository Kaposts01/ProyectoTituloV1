import asyncio
from typing import Self

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.integrations.toku import client as toku_client
from app.models.source_record import SourceRecord
from app.models.sync_run import SyncRun
from app.services import payku_sync, toku_sync


class TokuReadOnlyClient:
    def __init__(self) -> None:
        self.subscription_pages: list[int] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def list_customers(self, page: int, page_size: int):
        return {"data": [{"id": "toku-client-1", "email": "client@example.test"}]}

    async def list_invoices(self, page: int, page_size: int):
        return {"data": [{"id": "toku-invoice-1", "amount": 1000}]}

    async def list_payment_methods(self, page: int, page_size: int):
        return {"data": [{"id": "toku-method-1", "card_number": "4111111111111111"}], "meta": {"pages": 1}}

    async def list_subscriptions(self, page: int, page_size: int):
        self.subscription_pages.append(page)
        return {"data": [{"id": f"toku-subscription-{page}"}], "meta": {"pages": 2}}

    async def list_transactions(self, page: int, page_size: int):
        return {"data": [{"id": "toku-transaction-1"}], "meta": {"pages": 1}}


class PaykuReadOnlyClient:
    def __init__(self) -> None:
        self.transaction_params: list[tuple[int, int, str | None, str | None]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def list_clients(self, page: int, per_page: int):
        return {"customers": [{"id": "payku-client-1"}], "pagination": {"pages": 1}}

    async def list_plans(self):
        return {"data": [{"id": "payku-plan-1"}]}

    async def list_subscriptions(
        self,
        page: int,
        per_page: int,
        date_init: str | None = None,
        date_end: str | None = None,
    ):
        return {"data": [{"id": "payku-subscription-1"}], "pagination": {"pages": 1}}

    async def list_transactions(
        self,
        page: int,
        per_page: int,
        date_init: str | None = None,
        date_end: str | None = None,
    ):
        self.transaction_params.append((page, per_page, date_init, date_end))
        return {"data": [{"id": "payku-transaction-1"}], "pagination": {"pages": 1}}


class TokuTimeoutThenSuccessClient:
    def __init__(self) -> None:
        self.calls = 0

    async def get(self, path: str, params: dict[str, int] | None = None) -> httpx.Response:
        self.calls += 1
        if self.calls == 1:
            raise httpx.ReadTimeout("provider did not respond")
        return httpx.Response(200, json={"data": []}, request=httpx.Request("GET", path))


def test_toku_client_retries_read_timeout(monkeypatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(toku_client.settings, "toku_read_retries", 1)
    monkeypatch.setattr(toku_client.asyncio, "sleep", no_sleep)
    http_client = TokuTimeoutThenSuccessClient()
    client = toku_client.TokuClient()
    original_client = client._client
    client._client = http_client  # type: ignore[assignment]

    async def read() -> dict[str, list]:
        await original_client.aclose()
        return await client._get("/payment-methods")

    assert asyncio.run(read()) == {"data": []}
    assert http_client.calls == 2


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


def test_toku_sync_stages_all_available_pages_and_sanitizes_records(monkeypatch, db_session) -> None:
    client = TokuReadOnlyClient()
    monkeypatch.setattr(toku_sync, "TokuClient", lambda: client)

    first_run = asyncio.run(toku_sync.sync_toku(db_session))
    second_run = asyncio.run(toku_sync.sync_toku(db_session))

    assert first_run.status == "completed"
    assert first_run.records_processed == 6
    assert second_run.records_processed == 0
    assert client.subscription_pages == [1, 2, 1, 2]
    payment_method = db_session.scalars(
        select(SourceRecord).where(SourceRecord.source == "toku", SourceRecord.resource_type == "payment_method")
    ).one()
    assert "card_number" not in payment_method.payload


def test_payku_sync_stages_read_only_collections(monkeypatch, db_session) -> None:
    client = PaykuReadOnlyClient()
    monkeypatch.setattr(payku_sync, "PaykuClient", lambda: client)
    monkeypatch.setattr(payku_sync.settings, "payku_date_init", "2020-08-04")
    monkeypatch.setattr(payku_sync.settings, "payku_date_end", "")

    run = asyncio.run(payku_sync.sync_payku(db_session))

    assert run.status == "completed"
    assert run.records_processed == 4
    assert db_session.get(SyncRun, run.id).status == "completed"
    assert client.transaction_params == [(1, 4000, "2020-08-04", None)]


def test_payku_sync_can_resume_transactions_from_a_page(monkeypatch, db_session) -> None:
    client = PaykuReadOnlyClient()
    monkeypatch.setattr(payku_sync, "PaykuClient", lambda: client)

    asyncio.run(payku_sync.sync_payku(db_session, transaction_start_page=44))

    assert client.transaction_params == [(44, 4000, "2020-08-04", None)]


def test_toku_sync_reports_page_progress(monkeypatch, db_session) -> None:
    client = TokuReadOnlyClient()
    progress: list[tuple[str, int, int, int | None, int | None]] = []

    def report(
        resource: str,
        page: int,
        records: int,
        total_records: int | None,
        total_pages: int | None,
    ) -> None:
        progress.append((resource, page, records, total_records, total_pages))

    monkeypatch.setattr(toku_sync, "TokuClient", lambda: client)

    asyncio.run(toku_sync.sync_toku(db_session, report))

    assert ("subscription", 1, 1, None, 2) in progress
    assert ("subscription", 2, 2, None, 2) in progress
    assert ("customer", 1, 1, None, None) in progress
