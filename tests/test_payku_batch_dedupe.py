"""PK-PAR-01: duplicados dentro del mismo lote no provocan CardinalityViolation en el upsert."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.payku_channel import PaykuTransaction
from app.services.channel_store import store_payku_resources


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


def test_duplicate_transactions_in_same_batch_are_deduped(db_session) -> None:
    batch = [
        {"id": "pkdup-1", "status": "pending", "amount": 1000},
        {"id": "pkdup-1", "status": "success", "amount": 1000},
        {"id": "pkdup-2", "status": "success", "amount": 500},
    ]
    assert store_payku_resources(db_session, "transaction", batch) == 2
    assert store_payku_resources(db_session, "transaction", batch) == 2  # idempotente
    n = db_session.scalar(
        select(func.count()).select_from(PaykuTransaction).where(PaykuTransaction.external_id.like("pkdup-%"))
    )
    assert n == 2
