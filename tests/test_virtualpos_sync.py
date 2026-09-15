import asyncio
from typing import Self

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.models.crm import Charge, Client, Payment, Plan, Subscription
from app.models.source_record import SourceRecord
from app.models.sync_run import SyncRun
from app.services import virtualpos_sync


class PaginatedClient:
    def __init__(self) -> None:
        self.client_pages: list[int] = []
        self.payment_pages: list[int] = []
        self.subscription_pages: list[int] = []
        self.charge_subscriptions: list[str] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def list_clients(self, page: int = 1, limit: int = 100):
        self.client_pages.append(page)
        return {"clients": [{"uuid": "test-client-1", "first_name": "Test", "status": "ACTIVE"}]}

    async def list_plans(self):
        return {"plans": [{"id": "test-plan-1", "name": "Test plan"}]}

    async def list_payments(self, page: int = 1, limit: int = 100):
        self.payment_pages.append(page)
        return {
            "payments": [
                {"order": {"uuid": "test-payment-1", "amount": 1000, "card_number": "4111111111111111"}}
            ]
        }

    async def list_subscriptions(self, page: int = 1, limit: int = 100):
        self.subscription_pages.append(page)
        return {
            "suscriptions": [{"id": f"test-subscription-{page}", "plan_id": "test-plan-1"}],
            "pagination": {"page": page, "pages": 2, "limit": limit, "total": 2},
        }

    async def list_charges(self, subscription_id: str, page: int = 1, limit: int = 100):
        self.charge_subscriptions.append(subscription_id)
        return {"charges": [{"id": f"test-charge-{subscription_id}", "amount": 1000, "status": "PENDING"}]}


class FailingClient(PaginatedClient):
    async def list_clients(self, page: int = 1, limit: int = 100):
        raise RuntimeError(f"provider rejected {settings.virtualpos_api_key} with card 4111111111111111")


class ClientsAndPaymentsPaginatedClient(PaginatedClient):
    async def list_clients(self, page: int = 1, limit: int = 100):
        self.client_pages.append(page)
        return {
            "clients": [{"uuid": f"paged-client-{page}"}],
            "pagination": {"page": page, "pages": 2, "limit": limit},
        }

    async def list_payments(self, page: int = 1, limit: int = 100):
        self.payment_pages.append(page)
        return {
            "payments": [{"order": {"uuid": f"paged-payment-{page}", "amount": 1000}}],
            "pagination": {"page": page, "pages": 2, "limit": limit},
        }


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


def test_sync_stages_all_pages_materializes_records_and_is_idempotent(monkeypatch, db_session) -> None:
    client = PaginatedClient()
    monkeypatch.setattr(virtualpos_sync, "VirtualPOSClient", lambda: client)

    first_run = asyncio.run(virtualpos_sync.sync_virtualpos(db_session))
    second_run = asyncio.run(virtualpos_sync.sync_virtualpos(db_session))

    assert first_run.status == "completed"
    assert first_run.records_processed == 7
    assert second_run.records_processed == 0
    assert client.client_pages == [1, 1]
    assert client.payment_pages == [1, 1]
    assert client.subscription_pages == [1, 2, 1, 2]
    assert client.charge_subscriptions == [
        "test-subscription-1",
        "test-subscription-2",
        "test-subscription-1",
        "test-subscription-2",
    ]
    assert db_session.scalars(select(Client).where(Client.external_id == "test-client-1")).one().status == "ACTIVE"
    assert db_session.scalars(select(Plan).where(Plan.external_id == "test-plan-1")).one().name == "Test plan"
    assert db_session.scalars(select(Subscription).where(Subscription.external_id == "test-subscription-2")).one()
    assert db_session.scalars(select(Charge).where(Charge.external_id == "test-charge-test-subscription-1")).one()
    payment = db_session.scalars(select(Payment).where(Payment.external_id == "test-payment-1")).one()
    source_payment = db_session.get(SourceRecord, payment.source_record_id)
    assert source_payment is not None
    assert "card_number" not in source_payment.payload["order"]
    assert (
        db_session.scalars(select(SourceRecord).where(SourceRecord.external_id == "test-charge-test-subscription-1"))
        .one()
        .sync_context
        == {"subscription_external_id": "test-subscription-1"}
    )


def test_sync_paginates_clients_and_payments(monkeypatch, db_session) -> None:
    client = ClientsAndPaymentsPaginatedClient()
    monkeypatch.setattr(virtualpos_sync, "VirtualPOSClient", lambda: client)

    run = asyncio.run(virtualpos_sync.sync_virtualpos(db_session))

    assert run.status == "completed"
    assert client.client_pages == [1, 2]
    assert client.payment_pages == [1, 2]
    assert db_session.scalars(select(Client).where(Client.external_id == "paged-client-2")).one()
    assert db_session.scalars(select(Payment).where(Payment.external_id == "paged-payment-2")).one()


def test_sync_records_sanitized_failure_without_persisting_test_data(monkeypatch, db_session) -> None:
    monkeypatch.setattr(virtualpos_sync, "VirtualPOSClient", FailingClient)

    with pytest.raises(RuntimeError, match="provider rejected"):
        asyncio.run(virtualpos_sync.sync_virtualpos(db_session))

    failed_run = db_session.scalars(
        select(SyncRun).where(SyncRun.source == virtualpos_sync.SOURCE, SyncRun.status == "failed").order_by(SyncRun.started_at.desc())
    ).first()
    assert failed_run is not None
    assert failed_run.error_message is not None
    assert settings.virtualpos_api_key not in failed_run.error_message
    assert "4111111111111111" not in failed_run.error_message
    assert "[redacted]" in failed_run.error_message
