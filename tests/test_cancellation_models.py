"""MGT-07: esquema de las solicitudes de baja multicanal (tablas nuevas, estados en ingles) e inmutabilidad de sus eventos.

La Opcion A (`billing_change_requests`, estados en espanol) no cambia: se comprueba que sigue intacta. Las migraciones se
aplican solo por la sesion de pytest sobre `crm_test`.
"""

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.auth import User
from app.models.billing import REQUEST_STATUSES
from app.models.cancellation import (
    CHANNELS,
    OPEN_STATUSES,
    STATUSES,
    SubscriptionCancellationRequest,
    SubscriptionCancellationRequestEvent,
)

ROOT = Path(__file__).resolve().parent.parent


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


def _user(db: Session) -> User:
    user = User(username=f"u-{uuid.uuid4().hex[:10]}", password_hash="x", is_active=True)
    db.add(user)
    db.flush()
    return user


def _req(user: User, sub: str = "sub-1", **over) -> SubscriptionCancellationRequest:
    values = {
        "channel": "virtualpos1", "subscription_external_id": sub, "reason_code": "member_request",
        "reason_comment": "El socio pidio la baja", "requested_by_user_id": user.id,
    }
    values.update(over)
    return SubscriptionCancellationRequest(**values)


def _expect_integrity(db: Session, obj) -> None:
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(obj)
            db.flush()


def test_tables_exist_with_expected_columns(db_session: Session) -> None:
    insp = inspect(db_session.connection())
    cols = {c["name"] for c in insp.get_columns("subscription_cancellation_requests")}
    assert {
        "channel", "subscription_external_id", "status", "reason_code", "reason_comment", "requested_by_user_id",
        "approved_by_user_id", "options", "cascade_preview", "steps", "requires_reconciliation", "expires_at",
        "write_run_id", "self_approved", "approvals_required",
    } <= cols
    assert {c["name"] for c in insp.get_columns("subscription_cancellation_request_events")} >= {
        "request_id", "event_type", "actor_user_id", "detail", "created_at"}


def test_defaults_and_english_statuses(db_session: Session) -> None:
    user = _user(db_session)
    req = _req(user)
    db_session.add(req)
    db_session.flush()
    assert req.status == "pending" and req.steps == [] and req.options == {} and req.requires_reconciliation is False
    assert req.approvals_required == 1 and req.approvals_count == 0 and req.self_approved is False
    assert set(STATUSES).isdisjoint(REQUEST_STATUSES)  # no se mezclan con los estados en espanol de la Opcion A
    assert set(OPEN_STATUSES) <= set(STATUSES)


@pytest.mark.parametrize("status", STATUSES)
def test_every_valid_status_and_channel_is_accepted(db_session: Session, status: str) -> None:
    user = _user(db_session)
    extra = {"decision_comment": "no corresponde"} if status == "rejected" else {}
    db_session.add(_req(user, f"s-{status}", status=status, **extra))
    db_session.flush()


@pytest.mark.parametrize("channel", CHANNELS)
def test_every_channel_is_accepted(db_session: Session, channel: str) -> None:
    user = _user(db_session)
    extra = {"options": {"confirm_irreversible": True}} if channel == "payku" else {}
    db_session.add(_req(user, channel=channel, **extra))
    db_session.flush()


@pytest.mark.parametrize(
    "over",
    [
        {"channel": "otro"},
        {"status": "pendiente"},  # estados en espanol de la Opcion A: no valen aqui
        {"reason_code": "inventado"},
        {"reason_comment": "   "},
        {"reason_comment": ""},
        {"status": "rejected"},  # rechazo exige comentario
        {"approvals_required": 0},
        {"options": []},
        {"steps": {}},
        {"channel": "payku"},  # Payku es irreversible: exige confirm_irreversible
        {"channel": "payku", "options": {"confirm_irreversible": False}},
    ],
)
def test_check_constraints_reject_invalid(db_session: Session, over: dict) -> None:
    user = _user(db_session)
    _expect_integrity(db_session, _req(user, **over))


def test_one_open_request_per_subscription_partial_unique_index(db_session: Session) -> None:
    user = _user(db_session)
    first = _req(user)
    db_session.add(first)
    db_session.flush()
    _expect_integrity(db_session, _req(user))  # misma suscripcion y canal, abierta
    db_session.add(_req(user, channel="toku"))  # otro canal: permitido
    db_session.add(_req(user, "sub-2"))  # otra suscripcion: permitida
    db_session.flush()
    first.status = "completed"  # cerrada: ya no ocupa el cupo
    db_session.flush()
    db_session.add(_req(user))
    db_session.flush()
    # cada estado abierto ocupa el cupo
    for i, status in enumerate(OPEN_STATUSES):
        db_session.add(_req(user, f"open-{i}", status=status))
        db_session.flush()
        _expect_integrity(db_session, _req(user, f"open-{i}"))


def test_events_insert_and_are_immutable(db_session: Session) -> None:
    user = _user(db_session)
    req = _req(user)
    db_session.add(req)
    db_session.flush()
    event = SubscriptionCancellationRequestEvent(
        request_id=req.id, event_type="created", actor_user_id=user.id, detail={"k": 1})
    system_event = SubscriptionCancellationRequestEvent(request_id=req.id, event_type="expired")
    db_session.add_all([event, system_event])
    db_session.flush()
    assert event.created_at is not None and system_event.actor_user_id is None
    _expect_integrity(db_session, SubscriptionCancellationRequestEvent(request_id=req.id, event_type="creada"))
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE subscription_cancellation_request_events SET event_type = 'approved' WHERE id = :i"),
                {"i": event.id})
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("DELETE FROM subscription_cancellation_request_events WHERE id = :i"), {"i": event.id})


def test_event_fk_requires_existing_request(db_session: Session) -> None:
    _expect_integrity(db_session, SubscriptionCancellationRequestEvent(request_id=uuid.uuid4(), event_type="created"))


def test_option_a_tables_are_untouched(db_session: Session) -> None:
    insp = inspect(db_session.connection())
    assert "billing_change_requests" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("billing_change_requests")}
    assert {"request_type", "platform", "status"} <= cols and "channel" not in cols
    assert db_session.scalar(select(text("1"))) == 1


def test_migration_0051_chain_and_downgrade_defined() -> None:
    path = ROOT / "alembic" / "versions" / "20261029_0051_subscription_cancellation_requests.py"
    spec = importlib.util.spec_from_file_location("mig_0051", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "20261029_0051" and module.down_revision == "20261029_0050"
    assert callable(module.upgrade) and callable(module.downgrade)
    source = path.read_text(encoding="utf-8")
    assert "DROP TRIGGER IF EXISTS" in source and "billing_audit_immutable" in source
    assert "DROP FUNCTION" not in source  # la funcion es de la migracion 0038: no se elimina aqui


def test_migration_0051_downgrade_and_upgrade_roundtrip_in_rolled_back_transaction() -> None:
    """Ejecuta `downgrade()` y luego `upgrade()` de la 0051 dentro de una transaccion de `crm_test` que se revierte
    (DDL transaccional de PostgreSQL). No usa la CLI de Alembic."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = ROOT / "alembic" / "versions" / "20261029_0051_subscription_cancellation_requests.py"
    spec = importlib.util.spec_from_file_location("mig_0051_rt", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        with Operations.context(MigrationContext.configure(connection)):
            module.downgrade()
            names = set(inspect(connection).get_table_names())
            assert "subscription_cancellation_requests" not in names
            assert "subscription_cancellation_request_events" not in names
            assert "billing_change_requests" in names  # la Opcion A sigue
            fn = connection.execute(text("SELECT 1 FROM pg_proc WHERE proname = 'billing_audit_immutable'")).scalar()
            assert fn == 1  # la funcion de la 0038 no se elimina
            module.upgrade()
            assert "subscription_cancellation_requests" in set(inspect(connection).get_table_names())
    finally:
        transaction.rollback()
        connection.close()
