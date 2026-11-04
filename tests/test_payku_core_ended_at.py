"""PK-PAR-03: la fecha de termino de una suscripcion Payku en Core sale de `logs.status[]` con respaldo a `end_date`."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.core import CoreSubscription
from app.models.payku_channel import PaykuSubscription
from app.services import core_payku_etl


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


def _log(*entries: tuple[str, str, str]) -> dict:
    return {"logs": {"status": [
        {"change_date": date, "initial_status": initial, "final_status": final} for date, initial, final in entries
    ]}}


def _ended_at(db: Session, *, status: str, payload: dict | None = None, end_date: str | None = None):
    external_id = f"pk03-{uuid.uuid4().hex[:10]}"
    db.add(PaykuSubscription(external_id=external_id, status=status, end_date=end_date, raw_payload=payload))
    db.flush()
    core_payku_etl._materialize_subscriptions(db)
    return db.scalar(
        select(CoreSubscription.ended_at).where(CoreSubscription.source == "payku", CoreSubscription.external_id == external_id)
    )


def test_cancelled_subscription_takes_the_date_of_the_transition_to_its_current_status(db_session) -> None:
    ended = _ended_at(db_session, status="cancel", payload=_log(("2025-01-10 09:00:00", "register", "active"),
                                                               ("2025-03-04 10:00:00", "active", "cancel")))
    assert (ended.year, ended.month, ended.day) == (2025, 3, 4)


def test_the_log_wins_over_end_date(db_session) -> None:
    ended = _ended_at(db_session, status="cancel", end_date="2025-05-01",
                      payload=_log(("2025-03-04 10:00:00", "active", "cancel")))
    assert (ended.year, ended.month, ended.day) == (2025, 3, 4)


def test_the_most_recent_matching_transition_is_used(db_session) -> None:
    ended = _ended_at(db_session, status="suspended", payload=_log(
        ("2024-02-01 00:00:00", "active", "suspended"),
        ("2024-04-01 00:00:00", "suspended", "active"),
        ("2024-06-15 00:00:00", "active", "SUSPENDED"),  # mayusculas: se compara sin distinguirlas
    ))
    assert (ended.year, ended.month, ended.day) == (2024, 6, 15)


def test_falls_back_to_end_date_without_a_matching_log(db_session) -> None:
    assert _ended_at(db_session, status="delete", end_date="2025-07-20", payload={}).day == 20
    other = _ended_at(db_session, status="delete", end_date="2025-07-21",
                      payload=_log(("2025-01-01 00:00:00", "register", "active")))
    assert other.day == 21  # el log existe pero no tiene la transicion al estado actual


def test_no_log_and_no_end_date_stays_null(db_session) -> None:
    assert _ended_at(db_session, status="cancel", payload=None) is None
    assert _ended_at(db_session, status="delete", payload=_log(("sin-fecha", "x", "delete"))) is None


def test_active_like_statuses_keep_using_end_date(db_session) -> None:
    """Una transicion a `active` es un alta, no un termino: para estados vigentes no se usa el log."""
    ended = _ended_at(db_session, status="active", end_date="2026-12-31",
                      payload=_log(("2025-03-04 10:00:00", "register", "active")))
    assert (ended.year, ended.month, ended.day) == (2026, 12, 31)
    assert _ended_at(db_session, status="register", payload=_log(("2025-03-04 10:00:00", "x", "register"))) is None


def test_malformed_logs_do_not_break_the_etl(db_session) -> None:
    for payload in ({"logs": None}, {"logs": {"status": "x"}}, {"logs": {"status": [None, 3, {"final_status": "cancel"}]}}):
        assert _ended_at(db_session, status="cancel", payload=payload, end_date="2025-02-02").month == 2
