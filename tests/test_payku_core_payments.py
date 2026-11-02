"""Pagos Payku en Core: hora de Chile (PK-PAR-04). Datos sinteticos."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.core import CorePayment
from app.models.payku_channel import PaykuSubscription, PaykuTransaction
from app.services import core_payku_etl
from app.services.channel_store import extract_payku_transaction
from app.services.core_payku_etl import _parse_datetime_cl


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


def _sub(db: Session, **kw) -> str:
    external_id = f"pk-{uuid.uuid4().hex[:10]}"
    db.add(PaykuSubscription(external_id=external_id, status=kw.pop("status", "active"), **kw))
    db.flush()
    return external_id


def _tx(db: Session, sub: str, created_at: str, status: str = "success") -> str:
    external_id = f"tx-{uuid.uuid4().hex[:10]}"
    db.add(PaykuTransaction(external_id=external_id, subscription_id=sub, status=status, amount="10000",
                            created_at_api=created_at))
    db.flush()
    return external_id


def _payment(db: Session, external_id: str) -> CorePayment:
    return db.scalar(select(CorePayment).where(CorePayment.source == "payku", CorePayment.external_id == external_id))


# -- PK-PAR-04: hora y zona de Chile ------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected_utc"),
    [
        ("2026-01-31 22:30:00", datetime(2026, 2, 1, 1, 30, tzinfo=UTC)),    # verano: UTC-3
        ("2026-06-30 23:15:00", datetime(2026, 7, 1, 3, 15, tzinfo=UTC)),    # invierno: UTC-4
        ("2026-06-30T23:15:00Z", datetime(2026, 6, 30, 23, 15, tzinfo=UTC)),  # con zona: se respeta
        ("24-08-2023 12:29:35", datetime(2023, 8, 24, 16, 29, 35, tzinfo=UTC)),
        ("2026-03-10", datetime(2026, 3, 10, 3, 0, tzinfo=UTC)),
    ],
)
def test_parse_datetime_keeps_time_in_chile(raw: str, expected_utc: datetime) -> None:
    assert _parse_datetime_cl(raw) == expected_utc


def test_parse_datetime_rejects_garbage() -> None:
    assert _parse_datetime_cl(None) is None
    assert _parse_datetime_cl("  ") is None
    assert _parse_datetime_cl("ayer") is None


def test_extract_transaction_keeps_the_raw_text_with_time() -> None:
    assert extract_payku_transaction({"transaction": "t1", "created_at": "2026-01-31 22:30:00"})["created_at_api"] == \
        "2026-01-31 22:30:00"
    assert extract_payku_transaction({"transaction": "t2", "fecha": "24-08-2023 12:29:35"})["created_at_api"] == \
        "24-08-2023 12:29:35"


def test_core_payment_keeps_hour_and_existing_rows_are_corrected(db_session: Session) -> None:
    sub = _sub(db_session)
    core_payku_etl._materialize_subscriptions(db_session)
    tx = _tx(db_session, sub, "2026-01-31 22:30:00", status="rejected")
    core_payku_etl._materialize_payments(db_session)
    payment = _payment(db_session, tx)
    assert payment.occurred_at == datetime(2026, 2, 1, 1, 30, tzinfo=UTC)
    assert payment.rejection_reported_at == payment.occurred_at

    # una fila cargada antes con la fecha truncada a UTC se corrige con UPDATE explicito (el insert es do_nothing)
    payment.occurred_at = datetime(2026, 1, 31, tzinfo=UTC)
    db_session.flush()
    core_payku_etl._materialize_payments(db_session)
    db_session.refresh(payment)
    assert payment.occurred_at == datetime(2026, 2, 1, 1, 30, tzinfo=UTC)
    assert core_payku_etl._refresh_payment_times(db_session, {tx: (payment.occurred_at, payment.rejection_reported_at)}) == 0


# -- PK-PAR-06 / RJ-10: motivo minimo por suscripcion -------------------------------------------------------------------

def test_latest_rejection_takes_the_subscription_payment_status(db_session: Session) -> None:
    sub = _sub(db_session, status="suspended", last_status_current_payment="maximum attempt limit")
    other = _sub(db_session, last_status_current_payment="success")
    core_payku_etl._materialize_subscriptions(db_session)
    old = _tx(db_session, sub, "2026-03-05 10:00:00", status="rejected")
    new = _tx(db_session, sub, "2026-04-05 10:00:00", status="rejected")
    ok = _tx(db_session, sub, "2026-02-05 10:00:00")
    rejected_other = _tx(db_session, other, "2026-04-05 10:00:00", status="rejected")
    core_payku_etl._materialize_payments(db_session)

    assert core_payku_etl._apply_subscription_rejection_fallback(db_session) == 1
    assert _payment(db_session, new).rejection_reason == "maximum attempt limit"
    assert _payment(db_session, new).rejection_code is None
    assert _payment(db_session, old).rejection_reason is None
    assert _payment(db_session, ok).rejection_reason is None
    assert _payment(db_session, rejected_other).rejection_reason is None
    assert core_payku_etl._apply_subscription_rejection_fallback(db_session) == 0  # idempotente


def test_fallback_never_overwrites_an_existing_reason(db_session: Session) -> None:
    sub = _sub(db_session, last_status_current_payment="first payment rejected")
    core_payku_etl._materialize_subscriptions(db_session)
    tx = _tx(db_session, sub, "2026-04-05 10:00:00", status="rejected")
    core_payku_etl._materialize_payments(db_session)
    payment = _payment(db_session, tx)
    payment.rejection_reason = "Rechazo de transacción."
    db_session.flush()
    assert core_payku_etl._apply_subscription_rejection_fallback(db_session) == 0
    db_session.refresh(payment)
    assert payment.rejection_reason == "Rechazo de transacción."


def test_fallback_reason_has_a_readable_label() -> None:
    from app.services.rejection_format import format_rejection_reason

    assert format_rejection_reason("payku", None, "maximum attempt limit") == "Se agotaron los reintentos de cobro"
    assert format_rejection_reason("payku", None, "First Payment  Rejected") == "Falló el primer cobro"
    assert format_rejection_reason("payku", None, "canceled by customer") == "canceled by customer"
