import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.auth import User
from app.models.billing import (
    BillingChangeRequest,
    BillingChangeRequestEvent,
    BillingPolicy,
    BillingPolicyAudit,
    BillingRenewalTask,
    VpCalendarMark,
    VpManagedCharge,
)
from app.models.write_run import WriteRun


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
    user = User(username=f"u-{uuid.uuid4().hex[:10]}", password_hash="x")
    db.add(user)
    db.flush()
    return user


def _request(user: User, sub: str = "sub-1", **overrides) -> BillingChangeRequest:
    values = dict(
        request_type="change_amount",
        platform="virtualpos1",
        subscription_external_id=sub,
        requested_by_user_id=user.id,
        new_amount=Decimal("7000"),
        previous_amount=Decimal("9990"),
        rules_snapshot={"self_approval_enabled": True, "dual_approval_enabled": False},
        plan_preview={"create": [], "cancel": [], "covered": [], "manual_review": []},
    )
    values.update(overrides)
    return BillingChangeRequest(**values)


def _expect_integrity(db: Session, obj) -> None:
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(obj)
            db.flush()


def test_create_request_defaults(db_session: Session) -> None:
    user = _user(db_session)
    req = _request(user, expires_at=datetime.now(UTC) + timedelta(days=7))
    db_session.add(req)
    db_session.flush()
    db_session.refresh(req)
    assert req.status == "pendiente"
    assert req.horizon_months == 12
    assert req.approvals_required == 1 and req.approvals_count == 0
    assert req.self_approved is False
    assert req.write_run_id is None
    assert req.created_at is not None and req.updated_at is not None
    assert req.plan_preview == {"create": [], "cancel": [], "covered": [], "manual_review": []}


def test_all_four_request_types_accepted(db_session: Session) -> None:
    user = _user(db_session)
    db_session.add_all([
        _request(user, "s-amount", request_type="change_amount"),
        _request(user, "s-date", request_type="change_date", new_amount=None, new_charge_day=20),
        _request(user, "s-renew", request_type="renew_calendar"),
        _request(user, "s-oneoff", request_type="one_off_charge", new_charge_date=date(2026, 12, 1)),
    ])
    db_session.flush()


def test_one_pending_per_subscription_partial_unique_index(db_session: Session) -> None:
    user = _user(db_session)
    db_session.add(_request(user))
    db_session.flush()
    _expect_integrity(db_session, _request(user))
    # otra plataforma o suscripcion si se permite
    db_session.add_all([_request(user, platform="virtualpos2"), _request(user, "sub-2")])
    db_session.flush()


@pytest.mark.parametrize("open_status", ["aprobada", "aplicando", "requiere_conciliacion"])
def test_open_states_block_a_new_pending_request(db_session: Session, open_status: str) -> None:
    user = _user(db_session)
    db_session.add(_request(user, status=open_status))
    db_session.flush()
    _expect_integrity(db_session, _request(user))


@pytest.mark.parametrize("closed_status", ["ejecutada", "retirada", "expirada", "fallida", "no_ejecutable"])
def test_closed_states_do_not_block_a_new_pending_request(db_session: Session, closed_status: str) -> None:
    user = _user(db_session)
    db_session.add(_request(user, status=closed_status))
    db_session.flush()
    db_session.add(_request(user))
    db_session.flush()


def test_pending_plus_executed_allowed_and_new_pending_after_close(db_session: Session) -> None:
    user = _user(db_session)
    db_session.add(_request(user, status="ejecutada", executed_at=datetime.now(UTC)))
    db_session.add(_request(user))  # pendiente + ejecutada: ok
    db_session.flush()

    first = db_session.scalars(
        select(BillingChangeRequest).where(BillingChangeRequest.status == "pendiente")
    ).one()
    _expect_integrity(db_session, _request(user))
    first.status = "retirada"
    db_session.flush()
    db_session.add(_request(user))  # tras cerrarse la anterior: ok
    db_session.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "inexistente"},
        {"request_type": "otro"},
        {"platform": "toku"},
        {"new_amount": Decimal("0")},
        {"horizon_months": 0},
        {"new_charge_day": 32, "request_type": "change_date"},
        {"request_type": "change_amount", "new_amount": None},
        {"request_type": "one_off_charge", "new_charge_date": None},
        {"status": "rechazada", "decision_comment": "   "},
        {"status": "rechazada", "decision_comment": None},
    ],
)
def test_request_check_constraints_reject_invalid(db_session: Session, overrides: dict) -> None:
    user = _user(db_session)
    _expect_integrity(db_session, _request(user, **overrides))


def test_rejection_with_comment_and_every_valid_status(db_session: Session) -> None:
    user = _user(db_session)
    db_session.add(_request(user, "r0", status="rechazada", decision_comment="monto incorrecto"))
    for i, status in enumerate(
        ["aprobada", "aplicando", "ejecutada", "expirada", "retirada", "fallida", "requiere_conciliacion", "no_ejecutable"]
    ):
        db_session.add(_request(user, f"s-{i}", status=status))
    db_session.flush()


def test_request_fk_to_write_runs_and_write_run_back_reference(db_session: Session) -> None:
    user = _user(db_session)
    req = _request(user)
    db_session.add(req)
    db_session.flush()
    run = WriteRun(
        source="virtualpos1", resource_type="subscription", external_id="sub-1", operation="reassign_subscription_amount",
        status="completed", request_payload={}, request_id=req.id, requested_by_user_id=user.id,
    )
    db_session.add(run)
    db_session.flush()
    req.write_run_id = run.id
    db_session.flush()
    assert db_session.get(BillingChangeRequest, req.id).write_run_id == run.id

    bad = _request(user, "sub-x", write_run_id=uuid.uuid4())
    _expect_integrity(db_session, bad)
    # WriteRun existentes siguen funcionando sin los campos nuevos
    plain = WriteRun(
        source="virtualpos1", resource_type="charge", external_id="c1", operation="retry_charge",
        status="completed", request_payload={},
    )
    db_session.add(plain)
    db_session.flush()
    assert plain.request_id is None and plain.requested_by_user_id is None


def test_events_insert_and_are_immutable(db_session: Session) -> None:
    user = _user(db_session)
    req = _request(user)
    db_session.add(req)
    db_session.flush()
    event = BillingChangeRequestEvent(request_id=req.id, event_type="creada", actor_user_id=user.id, detail={"k": 1})
    system_event = BillingChangeRequestEvent(request_id=req.id, event_type="expirada")
    db_session.add_all([event, system_event])
    db_session.flush()
    assert event.created_at is not None and system_event.actor_user_id is None
    _expect_integrity(db_session, BillingChangeRequestEvent(request_id=req.id, event_type="cualquiera"))
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("UPDATE billing_change_request_events SET event_type = 'aprobada' WHERE id = :i"), {"i": event.id})
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM billing_change_request_events WHERE id = :i"), {"i": event.id})


def test_policy_default_row_and_values(db_session: Session) -> None:
    policy = db_session.scalars(select(BillingPolicy)).one()
    assert policy.singleton is True
    assert policy.approver_roles == ["admin"]
    assert policy.approver_user_ids == []
    assert policy.self_approval_enabled is True
    assert policy.dual_approval_enabled is False
    assert policy.dual_threshold_subscriptions == 20
    assert policy.dual_threshold_variation_pct == Decimal("50")
    assert policy.renewal_threshold_days == 60
    assert policy.request_expiry_days == 7
    assert policy.horizon_months == 12
    assert policy.window_days == 31


def test_policy_is_single_row_and_validates_ranges(db_session: Session) -> None:
    _expect_integrity(db_session, BillingPolicy())
    policy = db_session.scalars(select(BillingPolicy)).one()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            policy.renewal_threshold_days = 0
            db_session.flush()
    db_session.expire_all()
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.get(BillingPolicy, policy.id).approver_roles = {"x": 1}  # type: ignore[assignment]
            db_session.flush()


def test_policy_audit_insert_and_immutable(db_session: Session) -> None:
    user = _user(db_session)
    policy = db_session.scalars(select(BillingPolicy)).one()
    audit = BillingPolicyAudit(
        policy_id=policy.id, changed_by_user_id=user.id,
        before_values={"self_approval_enabled": True}, after_values={"self_approval_enabled": False}, reason="prueba",
    )
    db_session.add(audit)
    db_session.flush()
    assert audit.changed_at is not None
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("UPDATE billing_policy_audit SET reason = 'x' WHERE id = :i"), {"i": audit.id})
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM billing_policy_audit WHERE id = :i"), {"i": audit.id})


def _charge(**overrides) -> VpManagedCharge:
    values = dict(
        platform="virtualpos1", charge_id="ch-1", subscription_external_id="sub-1",
        internal_code="CRM-sub-1-202611", month="2026-11", amount=Decimal("7000"),
    )
    values.update(overrides)
    return VpManagedCharge(**values)


def test_managed_charge_unique_and_checks(db_session: Session) -> None:
    user = _user(db_session)
    req = _request(user)
    db_session.add(req)
    db_session.flush()
    charge = _charge(request_id=req.id)
    db_session.add(charge)
    db_session.flush()
    assert charge.status == "creado"
    _expect_integrity(db_session, _charge())  # mismo (plataforma, charge_id)
    db_session.add(_charge(platform="virtualpos2"))  # otra plataforma: ok
    db_session.add(_charge(charge_id="ch-2"))  # request_id NULL (cobro puntual): ok
    db_session.flush()
    _expect_integrity(db_session, _charge(charge_id="ch-3", month="2026-13"))
    _expect_integrity(db_session, _charge(charge_id="ch-4", status="otro"))
    _expect_integrity(db_session, _charge(charge_id="ch-5", amount=Decimal("0")))


def test_calendar_mark_unique_per_subscription(db_session: Session) -> None:
    def mark(**kw) -> VpCalendarMark:
        values = dict(
            platform="virtualpos1", subscription_external_id="sub-1", last_scheduled_month="2027-10",
            last_scheduled_date=date(2027, 10, 20), scheduled_amount=Decimal("7000"), charge_day=20,
        )
        values.update(kw)
        return VpCalendarMark(**values)

    db_session.add(mark())
    db_session.flush()
    _expect_integrity(db_session, mark())
    db_session.add(mark(platform="virtualpos2"))
    db_session.flush()
    _expect_integrity(db_session, mark(subscription_external_id="sub-2", charge_day=0))


def test_renewal_task_one_open_per_subscription(db_session: Session) -> None:
    def task(**kw) -> BillingRenewalTask:
        values = dict(
            platform="virtualpos1", subscription_external_id="sub-1",
            last_scheduled_date=date(2027, 1, 20), due_date=date(2026, 12, 20),
        )
        values.update(kw)
        return BillingRenewalTask(**values)

    first = task()
    db_session.add(first)
    db_session.flush()
    assert first.status == "abierta" and first.priority == "normal" and first.data_stale is False
    _expect_integrity(db_session, task())
    db_session.add(task(status="cerrada", closed_at=datetime.now(UTC)))  # cerradas no cuentan
    db_session.flush()
    first.status = "cerrada"
    db_session.flush()
    db_session.add(task())
    db_session.flush()
    _expect_integrity(db_session, task(subscription_external_id="sub-2", status="otro"))
