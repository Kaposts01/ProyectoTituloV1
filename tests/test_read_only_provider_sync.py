import asyncio
from typing import Self

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
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

    async def list_customers(self, page_size: int):
        return {"data": [{"id": "toku-client-1", "email": "client@example.test"}]}

    async def list_invoices(self, page_size: int):
        return {"data": [{"id": "toku-invoice-1", "amount": 1000}]}

    async def list_payment_methods(self, page: int, page_size: int):
        return {"data": [{"id": "toku-method-1", "card_number": "4111111111111111"}], "meta": {"pages": 1}}

    async def list_subscriptions(self, page: int, page_size: int):
        self.subscription_pages.append(page)
        return {"data": [{"id": f"toku-subscription-{page}"}], "meta": {"pages": 2}}

    async def list_transactions(self, page: int, page_size: int):
        return {"data": [{"id": "toku-transaction-1"}], "meta": {"pages": 1}}


class PaykuReadOnlyClient:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def list_clients(self, page: int, per_page: int):
        return {"customers": [{"id": "payku-client-1"}], "pagination": {"pages": 1}}

    async def list_plans(self):
        return {"data": [{"id": "payku-plan-1"}]}

    async def list_subscriptions(self, page: int, per_page: int):
        return {"data": [{"id": "payku-subscription-1"}], "pagination": {"pages": 1}}

    async def list_transactions(self, page: int, per_page: int):
        return {"data": [{"id": "payku-transaction-1"}], "pagination": {"pages": 1}}


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
    monkeypatch.setattr(payku_sync, "PaykuClient", PaykuReadOnlyClient)

    run = asyncio.run(payku_sync.sync_payku(db_session))

    assert run.status == "completed"
    assert run.records_processed == 4
    assert db_session.get(SyncRun, run.id).status == "completed"
