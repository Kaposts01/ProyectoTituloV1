from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.api.v1.routes.recovery import _cancelled_rows
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
