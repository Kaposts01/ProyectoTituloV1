"""MGT-03 + MGT-04: baja de una suscripcion VirtualPOS (`cancel_subscription`) con el mismo guard y lock que la Opcion A,
cierre de las solicitudes abiertas, verificacion posterior (sin cobros pendientes) y manejo de cobros `procesando`.

Solo FakeVP en memoria (ninguna red). Nunca se usa el DELETE plural de cobros.
"""

import asyncio
from datetime import date

import pytest
from billing_requests_support import api_error, make_user
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.models.billing import (
    BillingChangeRequest,
    BillingChangeRequestEvent,
    VpCalendarMark,
    VpManagedCharge,
)
from app.models.crm import Charge, Subscription
from app.models.write_run import WriteRun
from app.services import billing_apply as ba
from app.services import subscription_refresh as sr
from app.services import write_virtualpos as wv

SUB = "sub-cancel-1"
PLATFORM = "virtualpos1"
CALLS: list[tuple] = []
STATE: dict = {}


class FakeVPCancel:
    def __init__(self, platform: str = "virtualpos1") -> None:
        self.platform = platform

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def _by_id(self, charge_id):
        return next(c for c in STATE["charges"] if c["id"] == charge_id)

    async def cancel_subscription(self, subscription_id):
        CALLS.append(("cancel_subscription", subscription_id))
        if STATE.get("cancel_error"):
            raise api_error("E-050")
        STATE["sub_status"] = "CANCELADA"
        for c in STATE["charges"]:  # VP pasa los pendientes a cancelado (salvo los que "se quedan" en el escenario)
            if c["status"] == "pendiente" and c["id"] not in STATE["stay_pending"]:
                c["status"] = "cancelado"
        return {}

    async def get_subscription(self, subscription_id):
        CALLS.append(("get_subscription", subscription_id))
        return {"id": subscription_id, "status": STATE["sub_status"], "plan_id": "plan-1", "amount": 9900}

    async def list_charges(self, subscription_id, page=1, limit=100, status=None):
        CALLS.append(("list_charges", status))
        if STATE.get("list_error_after_cancel") and ("cancel_subscription", subscription_id) in CALLS:
            raise RuntimeError("listado caido")
        rows = [dict(c) for c in STATE["charges"] if status is None or c["status"] == status]
        return {"charges": rows, "pagination": {"pages": 1, "page": page}}

    async def delete_charge(self, charge_id):
        CALLS.append(("delete_charge", charge_id))
        if charge_id in STATE["delete_fail"]:
            raise api_error("E-050")
        self._by_id(charge_id)["status"] = "cancelado"
        return {}

    async def delete_subscription_charges(self, subscription_id):
        CALLS.append(("delete_plural", subscription_id))
        raise AssertionError("El DELETE plural esta prohibido en la baja")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    CALLS.clear()
    STATE.clear()
    STATE.update(
        sub_status="ACTIVA", stay_pending=set(), delete_fail=set(),
        charges=[
            {"id": "c-p1", "charge_date": "2026-12-05", "amount": 9900, "status": "pendiente"},
            {"id": "c-p2", "charge_date": "2027-01-05", "amount": 9900, "status": "pendiente"},
            {"id": "c-paid", "charge_date": "2026-10-05", "amount": 9900, "status": "pagado"},
        ],
    )
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", True)
    monkeypatch.setattr(wv, "VirtualPOSClient", FakeVPCancel)
    monkeypatch.setattr(sr, "VirtualPOSClient", FakeVPCancel)


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


def _seed(db):
    db.add(Subscription(source=PLATFORM, external_id=SUB, status="ACTIVA", plan_external_id="plan-1", amount="9900",
                        raw_payload={"id": SUB, "status": "ACTIVA"}))
    for c in STATE["charges"]:
        db.add(Charge(source=PLATFORM, external_id=c["id"], subscription_external_id=SUB, status=c["status"],
                      amount="9900", charge_date=c["charge_date"], raw_payload=dict(c)))
    db.commit()
    return make_user(db)


def _cancel(db, user):
    return asyncio.run(wv.cancel_subscription_with_outcome(db, SUB, requested_by_user_id=user.id))


def _run(db):
    return db.scalars(select(WriteRun).where(WriteRun.operation == "cancel_subscription", WriteRun.external_id == SUB)).one()


def _local_charges(db):
    return {c.external_id: c.status for c in db.scalars(select(Charge).where(Charge.subscription_external_id == SUB))}


def _request(db, user, status="pendiente", **over):
    values = dict(request_type="change_amount", platform=PLATFORM, subscription_external_id=SUB,
                  requested_by_user_id=user.id, status=status, new_amount=12000, rules_snapshot={}, plan_preview={})
    values.update(over)
    req = BillingChangeRequest(**values)
    db.add(req)
    db.commit()
    return req


def _no_plural():
    assert not any(c[0] == "delete_plural" for c in CALLS)


# ------------------------------------------------------------------ baja limpia


def test_clean_cancel_verifies_no_pending_and_sets_canceled_at(db_session) -> None:
    user = _seed(db_session)
    sub, outcome = _cancel(db_session, user)

    assert sub.status == "CANCELADA" and sub.canceled_at
    assert outcome.requires_reconciliation is False and outcome.reason is None
    assert outcome.pending_charges == 0 and outcome.processing_charges == 0
    assert _local_charges(db_session) == {"c-p1": "cancelado", "c-p2": "cancelado", "c-paid": "pagado"}
    run = _run(db_session)
    assert run.status == "completed" and run.requested_by_user_id == user.id
    assert ("delete_charge", "c-p1") not in CALLS  # el proveedor ya cancelo los pendientes: no hay reintento individual
    _no_plural()


def test_cancel_subscription_wrapper_keeps_signature_and_returns_subscription(db_session) -> None:
    _seed(db_session)
    sub = asyncio.run(wv.cancel_subscription(db_session, SUB))
    assert sub.external_id == SUB and sub.status == "CANCELADA"


# ------------------------------------------------------------------ guard, lock y solicitudes abiertas


def test_open_requests_closed_as_no_ejecutable_and_calendar_mark_retired(db_session) -> None:
    user = _seed(db_session)
    pend = _request(db_session, user, "pendiente")
    db_session.add(VpCalendarMark(platform=PLATFORM, subscription_external_id=SUB, last_scheduled_month="2027-10",
                                  last_scheduled_date=date(2027, 10, 5), scheduled_amount=12000, charge_day=5, is_active=True))
    db_session.add(VpManagedCharge(platform=PLATFORM, charge_id="c-p1", subscription_external_id=SUB, internal_code="x",
                                   month="2026-12", amount=12000, status="creado", request_id=pend.id))
    db_session.commit()

    _, outcome = _cancel(db_session, user)

    assert outcome.requires_reconciliation is False
    db_session.refresh(pend)
    assert pend.status == "no_ejecutable" and pend.error_message == "SUBSCRIPTION_CANCELLED"
    events = list(db_session.scalars(select(BillingChangeRequestEvent).where(BillingChangeRequestEvent.request_id == pend.id)))
    closing = [e for e in events if e.event_type == "no_ejecutable"]
    assert len(closing) == 1
    assert closing[0].detail["reason"] == "subscription_cancelled" and closing[0].actor_user_id == user.id
    assert db_session.scalar(select(VpCalendarMark)).is_active is False
    assert db_session.scalar(select(VpManagedCharge)).status == "cancelado"
    _no_plural()


def test_approved_request_is_also_closed(db_session) -> None:
    user = _seed(db_session)
    req = _request(db_session, user, "aprobada")
    _cancel(db_session, user)
    db_session.refresh(req)
    assert req.status == "no_ejecutable"


def test_request_being_applied_blocks_the_cancellation_before_any_write(db_session) -> None:
    user = _seed(db_session)
    _request(db_session, user, "aplicando")
    with pytest.raises(wv.BillingFlowConflictError):
        _cancel(db_session, user)
    assert CALLS == []
    assert db_session.scalars(select(WriteRun).where(WriteRun.external_id == SUB)).all() == []


def test_request_awaiting_reconciliation_blocks_the_cancellation(db_session) -> None:
    user = _seed(db_session)
    _request(db_session, user, "requiere_conciliacion")
    with pytest.raises(wv.BillingFlowConflictError):
        _cancel(db_session, user)
    assert CALLS == []


def test_managed_charge_in_reconciliation_blocks_the_cancellation(db_session) -> None:
    user = _seed(db_session)
    db_session.add(VpManagedCharge(platform=PLATFORM, charge_id="c-p1", subscription_external_id=SUB, internal_code="x",
                                   month="2026-12", amount=12000, status="requiere_conciliacion"))
    db_session.commit()
    with pytest.raises(wv.BillingFlowConflictError):
        _cancel(db_session, user)
    assert CALLS == []


def test_subscription_lock_is_taken_same_as_billing_apply(db_session) -> None:
    user = _seed(db_session)
    with ba.subscription_lock(db_session, PLATFORM, SUB), pytest.raises(ba.SubscriptionBusyError):
        _cancel(db_session, user)
    assert CALLS == []
    assert db_session.scalars(select(WriteRun).where(WriteRun.external_id == SUB)).all() == []


def test_provider_failure_keeps_open_requests_untouched(db_session) -> None:
    user = _seed(db_session)
    req = _request(db_session, user, "pendiente")
    STATE["cancel_error"] = True
    with pytest.raises(Exception, match=r"E-050|nok"):
        _cancel(db_session, user)
    db_session.refresh(req)
    assert req.status == "pendiente"
    assert _run(db_session).status == "failed"


# ------------------------------------------------------------------ verificacion: pendientes que quedan


def test_leftover_pending_charges_are_cancelled_individually_by_charge_id(db_session) -> None:
    user = _seed(db_session)
    STATE["stay_pending"] = {"c-p1", "c-p2"}  # el DELETE de suscripcion no los cancelo (reintento en vuelo)
    _, outcome = _cancel(db_session, user)

    assert outcome.requires_reconciliation is False
    assert [c[1] for c in CALLS if c[0] == "delete_charge"] == ["c-p1", "c-p2"]
    _no_plural()
    assert _local_charges(db_session)["c-p1"] == "cancelado" and _local_charges(db_session)["c-p2"] == "cancelado"
    assert _run(db_session).status == "completed"


def test_partial_failure_in_verification_flags_reconciliation_with_remaining_ids(db_session) -> None:
    user = _seed(db_session)
    STATE["stay_pending"] = {"c-p1", "c-p2"}
    STATE["delete_fail"] = {"c-p2"}
    sub, outcome = _cancel(db_session, user)

    assert sub.status == "CANCELADA" and sub.canceled_at  # la suscripcion SI quedo dada de baja
    assert outcome.requires_reconciliation is True and outcome.reason == "pending_charges_remain"
    assert outcome.pending_charge_ids == ["c-p2"]
    run = _run(db_session)
    assert run.status == "reconciliation_required"
    assert run.error_message == "pending_charges_remain"
    assert run.response_payload["outcome"]["pending_charge_ids"] == ["c-p2"]
    _no_plural()


def test_processing_charge_is_not_cancelled_and_flags_reconciliation(db_session) -> None:
    user = _seed(db_session)
    STATE["charges"].append({"id": "c-proc", "charge_date": "2026-11-06", "amount": 9900, "status": "procesando"})
    db_session.add(Charge(source=PLATFORM, external_id="c-proc", subscription_external_id=SUB, status="procesando",
                          amount="9900", charge_date="2026-11-06", raw_payload={}))
    db_session.commit()
    sub, outcome = _cancel(db_session, user)

    assert ("delete_charge", "c-proc") not in CALLS
    assert outcome.requires_reconciliation is True and outcome.reason == "processing_charges"
    assert outcome.processing_charge_ids == ["c-proc"]
    assert _local_charges(db_session)["c-proc"] == "procesando"
    run = _run(db_session)
    assert run.status == "reconciliation_required" and run.error_message == "processing_charges"
    assert sub.status == "CANCELADA"
    _no_plural()


def test_refresh_failure_flags_reconciliation_without_failing_the_cancellation(db_session) -> None:
    user = _seed(db_session)
    STATE["list_error_after_cancel"] = True
    sub, outcome = _cancel(db_session, user)
    assert sub.status == "CANCELADA" and sub.canceled_at
    assert outcome.requires_reconciliation is True and outcome.reason == "refresh_failed"
    assert _run(db_session).status == "reconciliation_required"
