import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.routes.recovery import (
    _cancelled_rows,
    _rejected_rows,
    _retry_history_rows,
)
from app.core.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal, engine
from app.main import app
from app.models.auth import Permission, Role, User
from app.models.charge_recovery import ChargeRecovery
from app.models.crm import Charge, Client, Payment, Subscription
from app.models.write_run import WriteRun
from app.services.charge_recovery import needs_card_change, reconcile_charge_recoveries
from app.services.rbac import seed_permissions


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


def test_retry_history_shows_pending_reconciliation_for_in_progress_runs(db_session: Session) -> None:
    # T6: completed write_run with no ChargeRecovery entry → "pendiente_de_conciliacion"
    # Found by /review on 2026-10-20
    write_run = WriteRun(
        source="virtualpos1", resource_type="charge", external_id="pending-recon-charge",
        operation="retry_charge", status="completed", request_payload={"charge_id": "pending-recon-charge"},
    )
    db_session.add(write_run)
    db_session.flush()

    rows = _retry_history_rows(db_session, None, None)

    row = next((r for r in rows if r["external_id"] == "pending-recon-charge"), None)
    assert row is not None
    assert row["result"] == "pendiente_de_conciliacion"


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


def _setup_recovery_viewer(monkeypatch, suffix: str) -> tuple[TestClient, dict]:
    """Create a user with virtualpos.recovery.view and return a logged-in client + headers."""
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-jwt-secret-with-at-least-32-chars")
    db = SessionLocal()
    try:
        seed_permissions(db)
        view_perm = db.scalar(select(Permission).where(Permission.code == "virtualpos.recovery.view"))
        viewer_role = Role(name=f"viewer-{suffix}", permissions=[view_perm])
        viewer_user = User(username=f"viewer-{suffix}", password_hash=hash_password("View-pw-12345"), is_active=True, roles=[viewer_role])
        db.add_all([viewer_role, viewer_user])
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    login = client.post("/api/v1/auth/login", json={"username": f"viewer-{suffix}", "password": "View-pw-12345"})
    assert login.status_code == 200
    return client, {"X-CSRF-Token": login.json()["csrf_token"]}


def test_retry_history_endpoint_returns_items_and_total(monkeypatch) -> None:
    # T1: GET /recovery/retry-history retorna estructura {items, total, offset, limit} con datos
    # Found by /review on 2026-10-20
    suffix = uuid.uuid4().hex[:12]
    client, _ = _setup_recovery_viewer(monkeypatch, suffix)

    db = SessionLocal()
    try:
        db.add(WriteRun(
            source="virtualpos1", resource_type="charge", external_id=f"ep-charge-{suffix}",
            operation="retry_charge", status="completed", request_payload={"charge_id": f"ep-charge-{suffix}"},
        ))
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/v1/recovery/retry-history")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data and "total" in data
    assert data["total"] >= 1
    ids = {r["external_id"] for r in data["items"]}
    assert f"ep-charge-{suffix}" in ids


def test_retry_history_endpoint_date_filter_excludes_outside_range(monkeypatch) -> None:
    # T2: GET /recovery/retry-history?date_from=&date_to= filtra por fecha en SQL
    # Found by /review on 2026-10-20
    suffix = uuid.uuid4().hex[:12]
    client, _ = _setup_recovery_viewer(monkeypatch, suffix)

    db = SessionLocal()
    try:
        db.add_all([
            WriteRun(
                source="virtualpos1", resource_type="charge", external_id=f"in-range-ep-{suffix}",
                operation="retry_charge", status="completed", request_payload={"charge_id": f"in-range-ep-{suffix}"},
                started_at=datetime(2099, 6, 15, 12, 0, 0, tzinfo=UTC),
            ),
            WriteRun(
                source="virtualpos1", resource_type="charge", external_id=f"out-range-ep-{suffix}",
                operation="retry_charge", status="completed", request_payload={"charge_id": f"out-range-ep-{suffix}"},
                started_at=datetime(2099, 1, 1, 12, 0, 0, tzinfo=UTC),
            ),
        ])
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/v1/recovery/retry-history?date_from=2099-06-01&date_to=2099-06-30")
    assert resp.status_code == 200
    ids = {r["external_id"] for r in resp.json()["items"]}
    assert f"in-range-ep-{suffix}" in ids
    assert f"out-range-ep-{suffix}" not in ids
