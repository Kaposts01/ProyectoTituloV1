"""Modelo de cargos Payku (PK-06) y estado normalizado (PK-PAR-07). Fixtures sinteticas: sin Payku, sin sandbox.

La forma de `paid[]` sigue el ejemplo de `GET /api/sususcriptionv3` (docs/integrations/payku/resources/
subscriptions.md); `paid[].transactions[]` no esta documentada (Q-05) y se prueban las dos formas plausibles.
"""

import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.core import CoreCharge, CorePayment, CoreSubscription
from app.models.payku_channel import PaykuCycle, PaykuSubscription, PaykuTransaction
from app.services import core_payku_etl, payku_status
from app.services.channel_store import (
    extract_payku_cycles,
    extract_payku_subscription,
    extract_payku_transaction,
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


def _paid(sub_tx: str) -> list[dict]:
    """Tres ciclos sinteticos: uno pagado, uno rechazado con dos intentos y uno pendiente sin transacciones."""
    return [
        {"payment_cycle_day": "2096-07-09", "payment_day": "2096-07-09", "status": "success", "amount_paid": 5000,
         "try_number": 1, "paid_number": 1, "transactions": [{"transaction": sub_tx}]},
        {"payment_cycle_day": "2096-08-09", "payment_day": None, "status": "rejected", "amount_paid": 0,
         "try_number": 1, "paid_number": 1, "transactions": []},
        {"payment_cycle_day": "2096-08-09", "payment_day": "2096-08-12", "status": "maximum attempt limit",
         "amount_paid": 0, "try_number": 3, "paid_number": 1, "transactions": ["rej-1", "rej-1"]},
        {"payment_cycle_day": "2096-09-09", "status": "pending", "amount_paid": 5000, "try_number": 1},
    ]


# -- Extractores (sin base) -----------------------------------------------------------------------------------------

def test_extract_cycles_keeps_last_try_and_transaction_ids() -> None:
    rows = extract_payku_cycles({"id": "su-x", "paid": _paid("tx-ok")})
    by_key = {row["external_id"]: row for row in rows}
    assert set(by_key) == {"su-x:2096-07-09", "su-x:2096-08-09", "su-x:2096-09-09"}
    rejected = by_key["su-x:2096-08-09"]
    assert rejected["try_number"] == 3 and rejected["status"] == "maximum attempt limit"
    assert rejected["status_normalized"] == "rejected" and rejected["transaction_ids"] == ["rej-1"]
    assert by_key["su-x:2096-07-09"]["transaction_ids"] == ["tx-ok"]
    assert by_key["su-x:2096-07-09"]["amount_paid"] == "5000" and by_key["su-x:2096-07-09"]["status_normalized"] == "paid"
    assert by_key["su-x:2096-09-09"]["transaction_ids"] == []


@pytest.mark.parametrize(
    "payload",
    [{"id": "su-x"}, {"id": "su-x", "paid": None}, {"id": "su-x", "paid": "x"}, {"paid": [{"payment_cycle_day": "2096-01-01"}]},
     {"id": "su-x", "paid": [None, {"status": "success"}]}],
)
def test_extract_cycles_tolerates_v1_and_odd_shapes(payload) -> None:
    assert extract_payku_cycles(payload) == []


def test_extract_cycles_falls_back_to_paid_number() -> None:
    rows = extract_payku_cycles({"id": "su-y", "paid": [{"paid_number": "4", "status": "success"}]})
    assert [r["external_id"] for r in rows] == ["su-y:n4"]


def test_extractors_write_normalized_status_without_touching_raw() -> None:
    sub = extract_payku_subscription({"id": "s1", "status": "delete"})
    assert sub["status"] == "delete" and sub["status_normalized"] == "cancelled"
    tx = extract_payku_transaction({"transaction": 7, "status": "Rejected", "order": "0012345", "description": "Cobro: # 3"})
    assert tx["status"] == "Rejected" and tx["status_normalized"] == "rejected"
    assert tx["order_ref"] == "0012345" and tx["description"] == "Cobro: # 3"
    assert extract_payku_transaction({"id": "t", "order": {"amount": 10}})["order_ref"] is None
    assert "verification_key" not in tx and "authorization_code" not in tx


@pytest.mark.parametrize(
    ("raw", "common"),
    [("success", "paid"), ("pending", "pending"), ("retry", "retrying"), ("rejected", "rejected"),
     ("first payment rejected", "rejected"), ("refunded partial", "refunded"), ("canceled by paymáster", "cancelled"),
     ("Canceled  by Customer", "cancelled"), ("otro", "unknown"), (None, "unknown")],
)
def test_charge_status_taxonomy(raw, common) -> None:
    assert payku_status.normalize_payku_charge_status(raw) == common


def test_etl_reexports_the_subscription_taxonomy() -> None:
    assert core_payku_etl.normalize_payku_status is payku_status.normalize_payku_status
    assert core_payku_etl._PAYKU_COMMON_STATUS == payku_status.PAYKU_COMMON_STATUS


# -- ETL (base de test, transaccion revertida) -----------------------------------------------------------------------

def test_etl_materializes_cycles_charges_and_links_idempotently(db_session: Session) -> None:
    tag = uuid.uuid4().hex[:8]
    sub_id, tx_ok, tx_rej = f"su-{tag}", f"tx-ok-{tag}", f"rej-{tag}"
    paid = _paid(tx_ok)
    paid[2]["transactions"] = [tx_rej]
    db_session.add(PaykuSubscription(external_id=sub_id, status="suspended", raw_payload={"id": sub_id, "paid": paid}))
    db_session.add_all([
        PaykuTransaction(external_id=tx_ok, subscription_id=sub_id, status="success", amount="5000",
                         created_at_api="2096-07-09 10:00:00"),
        PaykuTransaction(external_id=tx_rej, subscription_id=sub_id, status="rejected", amount="0",
                         created_at_api="2096-08-12 10:00:00"),
    ])
    db_session.flush()

    for _ in range(2):  # idempotente: la segunda pasada no duplica nada
        assert core_payku_etl._refresh_normalized_statuses(db_session) >= 0
        core_payku_etl._materialize_subscriptions(db_session)
        assert core_payku_etl._materialize_cycles(db_session) >= 3
        core_payku_etl._materialize_charges(db_session)
        core_payku_etl._materialize_payments(db_session)
        core_payku_etl._link_payments_to_charges(db_session)
    assert core_payku_etl._refresh_normalized_statuses(db_session) == 0
    assert core_payku_etl._link_payments_to_charges(db_session) == 0

    assert db_session.scalar(select(func.count()).select_from(PaykuCycle).where(PaykuCycle.subscription_id == sub_id)) == 3
    charges = {
        c.external_id: c
        for c in db_session.scalars(select(CoreCharge).where(CoreCharge.source == "payku", CoreCharge.external_id.like(f"{sub_id}:%")))
    }
    assert len(charges) == 3
    core_sub = db_session.scalar(select(CoreSubscription).where(CoreSubscription.source == "payku", CoreSubscription.external_id == sub_id))
    rejected = charges[f"{sub_id}:2096-08-09"]
    assert rejected.subscription_id == core_sub.id and rejected.period_reference == "2096-08"
    assert rejected.source_status == "maximum attempt limit"
    assert rejected.latest_rejection_reason == "maximum attempt limit"
    assert rejected.latest_rejection_at == datetime(2096, 8, 12, 4, 0, tzinfo=UTC)  # 00:00 de Chile (invierno)
    assert charges[f"{sub_id}:2096-07-09"].latest_rejection_at is None

    payments = {p.external_id: p for p in db_session.scalars(select(CorePayment).where(CorePayment.external_id.in_([tx_ok, tx_rej])))}
    assert payments[tx_ok].charge_id == charges[f"{sub_id}:2096-07-09"].id
    assert payments[tx_rej].charge_id == rejected.id

    sub = db_session.scalar(select(PaykuSubscription).where(PaykuSubscription.external_id == sub_id))
    assert sub.status == "suspended" and sub.status_normalized == "suspended"


def test_etl_without_v3_payload_creates_no_charges(db_session: Session) -> None:
    sub_id = f"su-v1-{uuid.uuid4().hex[:8]}"
    db_session.add(PaykuSubscription(external_id=sub_id, status="active", raw_payload={"id": sub_id, "transactions": []}))
    db_session.flush()
    core_payku_etl._materialize_cycles(db_session)
    assert not db_session.scalars(select(PaykuCycle).where(PaykuCycle.subscription_id == sub_id)).all()


# -- Migracion 0055 ---------------------------------------------------------------------------------------------------

def _migration():
    path = ROOT / "alembic" / "versions" / "20261102_0055_payku_cycles_status_recovery.py"
    spec = importlib.util.spec_from_file_location("mig_0055", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0055_chain_and_copies_match_code() -> None:
    from app.services import rbac

    mig = _migration()
    assert mig.revision == "20261102_0055" and mig.down_revision == "20261102_0057"
    assert mig.SUBSCRIPTION_STATUS == payku_status.PAYKU_COMMON_STATUS
    assert mig.CHARGE_STATUS == payku_status.PAYKU_CHARGE_STATUS
    assert mig.GRANT_RULES == rbac.PAYKU_RECOVERY_GRANT_RULES
    assert {code: rbac.PERMISSIONS[code] for code in mig.PERMISSIONS} == mig.PERMISSIONS


def test_migration_0055_backfill_matches_python_mapping(db_session: Session) -> None:
    mig = _migration()
    tag = uuid.uuid4().hex[:8]
    raws = ["register", "ACTIVE ", "delete", "weird", None]
    tx_raws = ["success", "canceled by paymáster", "Maximum  Attempt Limit", "rejected", "zzz"]
    for i, raw in enumerate(raws):
        db_session.add(PaykuSubscription(external_id=f"mig55-s{i}-{tag}", status=raw))
    for i, raw in enumerate(tx_raws):
        db_session.add(PaykuTransaction(external_id=f"mig55-t{i}-{tag}", status=raw))
    db_session.flush()
    mig.backfill_status(db_session.connection())
    db_session.expire_all()
    for i, raw in enumerate(raws):
        row = db_session.scalar(select(PaykuSubscription).where(PaykuSubscription.external_id == f"mig55-s{i}-{tag}"))
        assert row.status_normalized == payku_status.normalize_payku_status(raw), raw
    for i, raw in enumerate(tx_raws):
        row = db_session.scalar(select(PaykuTransaction).where(PaykuTransaction.external_id == f"mig55-t{i}-{tag}"))
        assert row.status_normalized == payku_status.normalize_payku_charge_status(raw), raw
