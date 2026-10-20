from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.api.v1.routes.recovery import (
    _cancelled_rows,
    _rejected_rows,
    _retry_history_rows,
)
from app.db.session import engine
from app.models.charge_recovery import ChargeRecovery
from app.models.crm import Charge, Client, Payment, Subscription
from app.models.write_run import WriteRun
from app.services.charge_recovery import needs_card_change, reconcile_charge_recoveries


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


def test_needs_card_change_classifies_card_and_blocked_account_rejections() -> None:
    assert needs_card_change("E-CARD", "Tarjeta vencida")
    assert needs_card_change(None, "Cuenta bloqueada por el emisor")
    assert not needs_card_change("E-FUNDS", "Fondos insuficientes")


def test_reconcile_charge_recoveries_closes_paid_and_rejected_cycles(db_session: Session) -> None:
    now = datetime.now(UTC)
    write_run = WriteRun(
        source="virtualpos1", resource_type="charge", external_id="paid-charge", operation="retry_charge",
        status="completed", request_payload={"charge_id": "paid-charge"},
    )
    db_session.add_all([
        write_run,
        Charge(source="virtualpos1", external_id="paid-charge", status="pagado"),
        Charge(source="virtualpos1", external_id="rejected-charge", status="rechazado"),
    ])
    db_session.flush()
    db_session.add_all([
        ChargeRecovery(source="virtualpos1", charge_external_id="paid-charge", write_run_id=write_run.id, closes_at=now - timedelta(days=1)),
        ChargeRecovery(source="virtualpos1", charge_external_id="rejected-charge", write_run_id=write_run.id, closes_at=now - timedelta(days=1)),
    ])
    db_session.flush()

    reconcile_charge_recoveries(db_session, "virtualpos1")

    statuses = {
        row.charge_external_id: row.status
        for row in db_session.query(ChargeRecovery).filter_by(source="virtualpos1").all()
        if row.charge_external_id in {"paid-charge", "rejected-charge"}
    }
    assert statuses == {"paid-charge": "cobrado", "rejected-charge": "no_cobrado"}


def test_cancelled_rows_include_lifetime_paid_amount_and_contact(db_session: Session) -> None:
    db_session.add_all([
        Client(source="virtualpos1", external_id="client-1", social_id="11111111-1", first_name="Ana", last_name="Rios", email="ana@example.com", phone_number="123"),
        Subscription(source="virtualpos1", external_id="sub-1", client_external_id="client-1", suscription_date="2099-01-01", canceled_at="2099-02-01", currency="CLP"),
        Charge(source="virtualpos1", external_id="charge-1", subscription_external_id="sub-1"),
        Payment(source="virtualpos1", external_id="payment-1", charge_external_id="charge-1", status="pagado", amount="12500"),
    ])
    db_session.flush()

    rows = _cancelled_rows(db_session, date(2099, 2, 1), date(2099, 2, 1))

    assert rows == [{
        "source": "virtualpos1", "subscription_id": "sub-1", "external_id": "sub-1", "rut": "11111111-1",
        "client_name": "Ana Rios", "started_at": "2099-01-01", "cancelled_at": "2099-02-01", "antiquity_days": 31,
        "amount": 12500.0, "currency": "CLP", "email": "ana@example.com", "phone": "123",
    }]


def test_rejected_rows_resolve_client_through_subscription(db_session: Session) -> None:
    db_session.add_all([
        Client(source="virtualpos1", external_id="wrong-client", first_name="Felipe", last_name="Rubilar"),
        Client(source="virtualpos1", external_id="correct-client", first_name="Ana", last_name="Rios"),
        Subscription(source="virtualpos1", external_id="sub-1", client_external_id="correct-client"),
        Charge(
            source="virtualpos1",
            external_id="charge-1",
            client_external_id="wrong-client",
            subscription_external_id="sub-1",
            status="rechazado",
            charge_date="2099-01-01",
        ),
    ])
    db_session.flush()

    rows = _rejected_rows(db_session, None, None, "retry")

    assert rows[0]["client_name"] == "Ana Rios"


def test_rejected_rows_use_subscription_payload_when_client_is_not_materialized(db_session: Session) -> None:
    db_session.add_all([
        Subscription(
            source="virtualpos2",
            external_id="sub-with-embedded-client",
            raw_payload={"client": {"first_name": "Ana", "last_name": "Rios"}},
        ),
        Charge(
            source="virtualpos2",
            external_id="charge-without-reason",
            subscription_external_id="sub-with-embedded-client",
            status="rechazado",
            charge_date="2099-01-01",
        ),
    ])
    db_session.flush()

    rows = _rejected_rows(db_session, None, None, "retry")

    row = next(row for row in rows if row["external_id"] == "charge-without-reason")
    assert row["client_name"] == "Ana Rios"
    assert row["rejection_reason"] == "No informado por VirtualPOS"


def test_rejected_rows_date_filter_excludes_outside_range(db_session: Session) -> None:
    # Regression: PERF-2 — status+date filters pushed to SQL in _rejected_rows
    # Found by /qa on 2026-10-20
    db_session.add_all([
        Charge(source="virtualpos1", external_id="in-range", status="rechazado", charge_date="2099-06-15"),
        Charge(source="virtualpos1", external_id="out-range", status="rechazado", charge_date="2099-01-01"),
        Charge(source="virtualpos1", external_id="wrong-status", status="pagado", charge_date="2099-06-15"),
    ])
    db_session.flush()

    rows = _rejected_rows(db_session, date(2099, 6, 1), date(2099, 6, 30), "retry")

    ids = {r["external_id"] for r in rows}
    assert "in-range" in ids
    assert "out-range" not in ids
    assert "wrong-status" not in ids


def test_retry_history_date_filter_excludes_outside_range(db_session: Session) -> None:
    # Regression: PERF-2 — date filter pushed to SQL for WriteRun.started_at in _retry_history_rows
    # Found by /qa on 2026-10-20
    inside_run = WriteRun(
        source="virtualpos1", resource_type="charge", external_id="wr-in-range", operation="retry_charge",
        status="failed", request_payload={"charge_id": "wr-in-range"},
        started_at=datetime(2099, 6, 15, 12, 0, 0, tzinfo=UTC),
    )
    outside_run = WriteRun(
        source="virtualpos1", resource_type="charge", external_id="wr-out-range", operation="retry_charge",
        status="failed", request_payload={"charge_id": "wr-out-range"},
        started_at=datetime(2099, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    db_session.add_all([inside_run, outside_run])
    db_session.flush()

    rows = _retry_history_rows(db_session, date(2099, 6, 1), date(2099, 6, 30))

    ids = {r["external_id"] for r in rows}
    assert "wr-in-range" in ids
    assert "wr-out-range" not in ids


def test_retry_history_includes_accepted_and_immediately_rejected_attempts(db_session: Session) -> None:
    accepted_run = WriteRun(
        source="virtualpos1", resource_type="charge", external_id="accepted-charge", operation="retry_charge",
        status="completed", request_payload={"charge_id": "accepted-charge"},
    )
    rejected_run = WriteRun(
        source="virtualpos1", resource_type="charge", external_id="rejected-charge", operation="retry_charge",
        status="failed", request_payload={"charge_id": "rejected-charge"},
    )
    db_session.add_all([accepted_run, rejected_run])
    db_session.flush()
    db_session.add(ChargeRecovery(
        source="virtualpos1",
        charge_external_id="accepted-charge",
        write_run_id=accepted_run.id,
        status="cobrado",
        closes_at=datetime.now(UTC),
    ))
    db_session.flush()

    rows = _retry_history_rows(db_session, None, None)
    outcomes = {row["external_id"]: row["result"] for row in rows}

    assert outcomes["accepted-charge"] == "cobrado"
    assert outcomes["rejected-charge"] == "rechazado_inmediato"
