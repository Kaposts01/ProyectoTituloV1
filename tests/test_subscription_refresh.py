"""MGT-06: `refresh_subscription` relee UNA suscripcion (y sus cobros/pagos) del proveedor por GET y actualiza las
tablas del canal y la consolidacion centralizada SOLO de ese registro. Idempotente; solo clientes falsos (sin red).
"""

import asyncio
import uuid
from datetime import datetime
from typing import ClassVar

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.crm import Charge, Payment, Subscription
from app.models.payku_channel import PaykuSubscription, PaykuTransaction
from app.models.source_record import SourceRecord
from app.models.status_change import StatusChangeEvent
from app.models.toku_channel import TokuInvoice, TokuSubscription
from app.models.vp import VpCharge, VpSubscription
from app.services import subscription_refresh as sr

STATE: dict = {}
CALLS: list[tuple] = []


class _CM:
    def __init__(self, *_: object, **__: object) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeVP(_CM):
    async def get_subscription(self, subscription_id):
        CALLS.append(("get_subscription", subscription_id))
        if STATE.get("get_error"):
            raise RuntimeError("proveedor caido")
        return STATE["sub"]

    async def list_charges(self, subscription_id, page=1, limit=100, status=None):
        CALLS.append(("list_charges", subscription_id, status))
        if STATE.get("list_error"):
            raise RuntimeError("listado caido")
        return {"charges": [dict(c) for c in STATE["charges"]], "pagination": {"pages": 1, "page": 1}}


class FakeToku(_CM):
    async def get_subscription(self, subscription_id):
        CALLS.append(("get_subscription", subscription_id))
        return STATE["sub"]

    async def list_subscription_invoices(self, subscription_id, general_statuses=None, page_size=100):
        CALLS.append(("list_invoices", subscription_id, general_statuses))
        return {"invoices": [dict(i) for i in STATE["invoices"]]}


class FakePayku(_CM):
    calls: ClassVar[list] = []

    async def get_subscription(self, subscription_id):
        CALLS.append(("get_subscription", subscription_id))
        return STATE["sub"]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    CALLS.clear()
    STATE.clear()
    monkeypatch.setattr(sr, "VirtualPOSClient", FakeVP)
    monkeypatch.setattr(sr, "TokuClient", FakeToku)
    monkeypatch.setattr(sr, "PaykuClient", FakePayku)


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


def _events(db, entity, external_id):
    return list(db.scalars(select(StatusChangeEvent).where(
        StatusChangeEvent.entity_type == entity, StatusChangeEvent.external_id == external_id)))


# ----------------------------- VirtualPOS -----------------------------


def _seed_vp(db):
    for sid in ("sub-r1", "sub-r2"):
        db.add(VpSubscription(platform="virtualpos1", external_id=sid, status="ACTIVA", plan_external_id="p1",
                              client_social_id=f"soc-{sid}", amount="9900", raw_payload={"id": sid}))
        db.add(Subscription(source="virtualpos1", external_id=sid, status="ACTIVA", plan_external_id="p1",
                            amount="9900", raw_payload={"id": sid}))
        for cid in (f"{sid}-c1", f"{sid}-c2"):
            db.add(VpCharge(platform="virtualpos1", external_id=cid, subscription_external_id=sid, status="pendiente",
                            amount="9900", charge_date="2026-12-05", raw_payload={"id": cid}))
            db.add(Charge(source="virtualpos1", external_id=cid, subscription_external_id=sid, status="pendiente",
                          amount="9900", charge_date="2026-12-05", raw_payload={"id": cid}))
    db.commit()


def _vp_provider_state(c1="cancelado", c2="procesando"):
    STATE["sub"] = {"id": "sub-r1", "status": "CANCELADA", "plan_id": "p1", "amount": 9900, "currency": "CLP",
                    "canceled_at": "2026-10-29"}
    STATE["charges"] = [
        {"id": "sub-r1-c1", "charge_date": "2026-12-05", "amount": 9900, "status": c1},
        {"id": "sub-r1-c2", "charge_date": "2027-01-05", "amount": 9900, "status": c2},
        {"id": "sub-r1-c3", "charge_date": "2026-10-05", "amount": 9900, "status": "pagado"},
    ]


def test_vp_refresh_updates_channel_and_centralized_only_that_subscription(db_session) -> None:
    _seed_vp(db_session)
    _vp_provider_state()
    run_id = uuid.uuid4()
    res = asyncio.run(sr.refresh_subscription(db_session, "virtualpos1", "sub-r1", run_id=run_id))

    assert (res.status_before, res.status_after) == ("ACTIVA", "CANCELADA")
    assert res.changed is True
    assert res.pending_charges == 0 and res.pending_charge_ids == []
    assert res.processing_charges == 1 and res.processing_charge_ids == ["sub-r1-c2"]
    assert res.run_id == run_id
    assert {c[0] for c in CALLS} == {"get_subscription", "list_charges"}  # solo GET

    vp = db_session.scalar(select(VpSubscription).where(VpSubscription.external_id == "sub-r1"))
    # VP-PAR-13: `vp_subscriptions.canceled_at` es timestamp; `subscriptions` (crm) sigue en texto canonico.
    assert vp.status == "CANCELADA" and vp.canceled_at == datetime(2026, 10, 29)  # noqa: DTZ001
    central = db_session.scalar(select(Subscription).where(Subscription.external_id == "sub-r1"))
    assert central.status == "CANCELADA" and central.canceled_at == "2026-10-29"
    charges = {c.external_id: c.status for c in db_session.scalars(
        select(Charge).where(Charge.subscription_external_id == "sub-r1"))}
    assert charges == {"sub-r1-c1": "cancelado", "sub-r1-c2": "procesando", "sub-r1-c3": "pagado"}
    assert db_session.scalar(select(SourceRecord).where(
        SourceRecord.source == "virtualpos1", SourceRecord.resource_type == "subscription",
        SourceRecord.external_id == "sub-r1")) is not None

    # la otra suscripcion no se toca (ni canal ni centralizado)
    other = db_session.scalar(select(Subscription).where(Subscription.external_id == "sub-r2"))
    assert other.status == "ACTIVA"
    other_charges = {c.status for c in db_session.scalars(select(Charge).where(Charge.subscription_external_id == "sub-r2"))}
    assert other_charges == {"pendiente"}
    assert db_session.scalar(select(VpSubscription).where(VpSubscription.external_id == "sub-r2")).status == "ACTIVA"

    # evento de estado con el run_id de la operacion
    ev = [e for e in _events(db_session, "subscription", "sub-r1") if e.event_kind == "status_changed"]
    assert len(ev) == 1 and (ev[0].from_value, ev[0].to_value) == ("ACTIVA", "CANCELADA")
    assert ev[0].run_id == run_id and ev[0].is_baseline is False
    assert _events(db_session, "subscription", "sub-r2") == []


def test_vp_refresh_reports_pending_charges(db_session) -> None:
    _seed_vp(db_session)
    _vp_provider_state(c1="pendiente", c2="pendiente")
    res = asyncio.run(sr.refresh_subscription(db_session, "virtualpos1", "sub-r1"))
    assert res.pending_charges == 2 and sorted(res.pending_charge_ids) == ["sub-r1-c1", "sub-r1-c2"]
    assert res.processing_charges == 0


def test_vp_refresh_is_idempotent(db_session) -> None:
    _seed_vp(db_session)
    _vp_provider_state()
    first = asyncio.run(sr.refresh_subscription(db_session, "virtualpos1", "sub-r1"))
    n_events = db_session.query(StatusChangeEvent).count()
    second = asyncio.run(sr.refresh_subscription(db_session, "virtualpos1", "sub-r1"))
    assert second.status_before == first.status_after == second.status_after == "CANCELADA"
    assert second.changed is False
    assert db_session.query(StatusChangeEvent).count() == n_events  # sin eventos nuevos
    assert db_session.query(VpCharge).filter_by(subscription_external_id="sub-r1").count() == 3
    assert db_session.query(Charge).filter_by(subscription_external_id="sub-r1").count() == 3
    assert (second.pending_charges, second.processing_charges) == (first.pending_charges, first.processing_charges)


def test_vp_refresh_accepts_wrapped_subscription_payload(db_session) -> None:
    _seed_vp(db_session)
    _vp_provider_state()
    STATE["sub"] = {"suscription": STATE["sub"]}
    res = asyncio.run(sr.refresh_subscription(db_session, "virtualpos1", "sub-r1"))
    assert res.status_after == "CANCELADA"


def test_vp_refresh_creates_rows_when_missing_locally(db_session) -> None:
    _vp_provider_state()
    res = asyncio.run(sr.refresh_subscription(db_session, "virtualpos1", "sub-r1"))
    assert res.status_before is None and res.status_after == "CANCELADA"
    assert db_session.scalar(select(Subscription).where(Subscription.external_id == "sub-r1")) is not None


@pytest.mark.parametrize("failing", ["get_error", "list_error"])
def test_vp_refresh_fails_closed_when_provider_read_fails(db_session, failing) -> None:
    _seed_vp(db_session)
    _vp_provider_state()
    STATE[failing] = True
    with pytest.raises(sr.RefreshError) as e:
        asyncio.run(sr.refresh_subscription(db_session, "virtualpos1", "sub-r1"))
    assert e.value.code == "PROVIDER_READ_FAILED"
    assert "caido" not in str(e.value)  # sin texto libre del proveedor
    assert db_session.scalar(select(Subscription).where(Subscription.external_id == "sub-r1")).status == "ACTIVA"
    assert {c.status for c in db_session.scalars(
        select(Charge).where(Charge.subscription_external_id == "sub-r1"))} == {"pendiente"}


def test_vp_refresh_fails_closed_on_empty_subscription_payload(db_session) -> None:
    _seed_vp(db_session)
    _vp_provider_state()
    STATE["sub"] = {}
    with pytest.raises(sr.RefreshError) as e:
        asyncio.run(sr.refresh_subscription(db_session, "virtualpos1", "sub-r1"))
    assert e.value.code == "EMPTY_SUBSCRIPTION"


def test_unsupported_source_is_rejected(db_session) -> None:
    with pytest.raises(sr.RefreshError) as e:
        asyncio.run(sr.refresh_subscription(db_session, "tch", "x"))
    assert e.value.code == "UNSUPPORTED_SOURCE"
    assert CALLS == []


# ----------------------------- Toku -----------------------------


def test_toku_refresh_subscription_and_invoices_only_that_subscription(db_session) -> None:
    for sid in ("sub_t1", "sub_t2"):
        db_session.add(TokuSubscription(external_id=sid, status="ACTIVE", amount="5000", raw_payload={"id": sid}))
        db_session.add(Subscription(source="toku", external_id=sid, status="ACTIVE", raw_payload={"id": sid}))
        db_session.add(TokuInvoice(external_id=f"{sid}-in0", subscription_id=sid, status="UNPAID", amount="5000",
                                   raw_payload={"id": f"{sid}-in0"}))
        db_session.add(Charge(source="toku", external_id=f"{sid}-in0", subscription_external_id=sid, status="UNPAID",
                              raw_payload={"id": f"{sid}-in0"}))
    db_session.commit()
    STATE["sub"] = {"subscription": {"id": "sub_t1", "status": "CANCELLED", "amount": 5000, "customer": {"id": "cus_1"}}}
    STATE["invoices"] = [
        {"id": "sub_t1-in0", "status": "VOID", "general_status": "void", "amount": 5000},
        {"id": "sub_t1-in1", "status": "UNPAID", "general_status": "unpaid", "amount": 5000},
        {"id": "sub_t1-in2", "status": "UNPAID", "general_status": "unpaid", "in_progress": True, "amount": 5000},
        {"id": "sub_t1-in3", "status": "PAID", "general_status": "paid", "amount": 5000},
    ]
    res = asyncio.run(sr.refresh_subscription(db_session, "toku", "sub_t1"))

    assert (res.status_before, res.status_after) == ("ACTIVE", "CANCELLED")
    assert res.pending_charges == 1 and res.pending_charge_ids == ["sub_t1-in1"]
    assert res.processing_charges == 1 and res.processing_charge_ids == ["sub_t1-in2"]
    assert {c[0] for c in CALLS} == {"get_subscription", "list_invoices"}
    inv = {c.external_id: c.status for c in db_session.scalars(select(Charge).where(Charge.subscription_external_id == "sub_t1"))}
    assert inv["sub_t1-in0"] == "VOID" and len(inv) == 4
    assert db_session.scalar(select(Subscription).where(Subscription.external_id == "sub_t2")).status == "ACTIVE"
    assert db_session.scalar(select(Charge).where(Charge.external_id == "sub_t2-in0")).status == "UNPAID"
    assert db_session.scalar(select(TokuSubscription).where(TokuSubscription.external_id == "sub_t1")).status == "CANCELLED"
    assert [e.to_value for e in _events(db_session, "subscription", "sub_t1") if e.event_kind == "status_changed"] == ["CANCELLED"]


def test_toku_refresh_idempotent(db_session) -> None:
    STATE["sub"] = {"id": "sub_t1", "status": "ACTIVE", "amount": 5000}
    STATE["invoices"] = [{"id": "sub_t1-in1", "status": "UNPAID", "general_status": "unpaid", "amount": 5000}]
    a = asyncio.run(sr.refresh_subscription(db_session, "toku", "sub_t1"))
    n = db_session.query(StatusChangeEvent).count()
    b = asyncio.run(sr.refresh_subscription(db_session, "toku", "sub_t1"))
    assert a.status_after == b.status_after == "ACTIVE" and b.changed is False
    assert db_session.query(StatusChangeEvent).count() == n
    assert db_session.query(TokuInvoice).filter_by(subscription_id="sub_t1").count() == 1


# ----------------------------- Payku -----------------------------


def test_payku_refresh_subscription_and_transactions(db_session) -> None:
    for sid in ("sub_p1", "sub_p2"):
        db_session.add(PaykuSubscription(external_id=sid, status="active", raw_payload={"id": sid}))
        db_session.add(Subscription(source="payku", external_id=sid, status="active", raw_payload={"id": sid}))
        db_session.add(PaykuTransaction(external_id=f"{sid}-t0", subscription_id=sid, status="pending", amount="3000",
                                        raw_payload={"id": f"{sid}-t0"}))
        db_session.add(Payment(source="payku", external_id=f"{sid}-t0", charge_external_id=sid, status="pending",
                               raw_payload={"id": f"{sid}-t0"}))
    db_session.commit()
    STATE["sub"] = {"data": {"id": "sub_p1", "status": "cancel", "amount": "3000", "transactions": [
        {"id": "sub_p1-t0", "status": "failed", "amount": "3000", "created_at": "2026-10-01"},
        {"id": "sub_p1-t1", "status": "retry", "amount": "3000", "created_at": "2026-10-20"},
        {"id": "sub_p1-t2", "status": "success", "amount": "3000", "created_at": "2026-09-01"},
    ]}}
    res = asyncio.run(sr.refresh_subscription(db_session, "payku", "sub_p1"))

    assert (res.status_before, res.status_after) == ("active", "cancel")
    assert res.pending_charges == 1 and res.pending_charge_ids == ["sub_p1-t1"]
    assert {c[0] for c in CALLS} == {"get_subscription"}
    pays = {p.external_id: p.status for p in db_session.scalars(select(Payment).where(Payment.charge_external_id == "sub_p1"))}
    assert pays == {"sub_p1-t0": "failed", "sub_p1-t1": "retry", "sub_p1-t2": "success"}
    assert db_session.scalar(select(Payment).where(Payment.external_id == "sub_p2-t0")).status == "pending"
    assert db_session.scalar(select(Subscription).where(Subscription.external_id == "sub_p2")).status == "active"
    assert db_session.scalar(select(PaykuSubscription).where(PaykuSubscription.external_id == "sub_p1")).status == "cancel"
