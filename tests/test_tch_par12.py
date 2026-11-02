"""TCH-PAR-12: core_charges por cuota TCH, pagos ligados a su cuota y client_external_id en las canonicas.

Reportes Excel sinteticos (sin datos personales). Verifica idempotencia: dos corridas dejan el mismo resultado.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.core import CoreCharge, CorePayment, CoreSubscription
from app.models.crm import Charge, Subscription
from app.services import channel_consolidation
from app.services.core_tch_etl import run_tch_core_etl
from scripts import etl_tch
from tests.tch_synthetic import write_report

F1, F2 = 952001, 952002
RUT1 = "11.111.111-1"


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
        session.close()
    finally:
        transaction.rollback()
        connection.close()


def _january(tmp_path):
    return write_report(
        tmp_path / "20260131 TCH IG ENERO 2026.xlsx",
        active=[{"ficha": F1, "rut": "11111111-1"}, {"ficha": F2, "rut": "22222222-2"}],
        rechazados=[{"ficha": F1, "cuota": 3, "mes": "ENE 26", "monto": 10000, "fecha": date(2026, 1, 15), "motivo": "Fondos insuficientes"}],
        aceptados=[{"ficha": F2, "cuota": 1, "mes": "ENE 26", "monto": 8000, "fecha": date(2026, 1, 20)}],
    )


def _february(tmp_path):
    return write_report(
        tmp_path / "20260228 TCH IG FEBRERO 2026.xlsx",
        active=[
            {"ficha": F1, "rut": "11111111-1", "historial": {(2026, 1): (3, "Pagada", 10000)}},
            {"ficha": F2, "rut": "22222222-2"},
        ],
        aceptados=[{"ficha": F1, "cuota": 4, "mes": "FEB 26", "monto": 10000, "fecha": date(2026, 2, 10)}],
    )


def _charges(db) -> dict[str, CoreCharge]:
    return {c.external_id: c for c in db.scalars(select(CoreCharge).where(CoreCharge.source == "tch"))}


def _payments(db) -> dict[str, CorePayment]:
    return {p.external_id: p for p in db.scalars(select(CorePayment).where(CorePayment.source == "tch"))}


def _snapshot(db) -> tuple:
    charges = sorted(
        (c.external_id, c.subscription_id, c.period_reference, c.due_at, c.amount, c.source_status,
         c.latest_rejection_code, c.latest_rejection_reason, c.latest_rejection_at, c.latest_rejection_payment_id, c.id)
        for c in _charges(db).values()
    )
    payments = sorted(
        (p.external_id, p.id, p.charge_id, p.subscription_id, p.source_status, p.occurred_at, p.amount, p.rejection_reason)
        for p in _payments(db).values()
    )
    return charges, payments


def test_each_installment_becomes_a_core_charge_with_its_payment_linked(db_session, tmp_path) -> None:
    etl_tch._process_file(_january(tmp_path), db_session)
    result = run_tch_core_etl(db_session)

    charges, payments = _charges(db_session), _payments(db_session)
    key1, key2 = f"{F1}|2026-01|3", f"{F2}|2026-01|1"
    assert {key1, key2} <= set(charges) and set(charges) == set(payments)
    assert result["charges_inserted"] == len(charges)

    rejected = charges[key1]
    assert rejected.period_reference == "2026-01"
    assert rejected.due_at.date() == date(2026, 1, 15)
    assert rejected.source_status == "RECHAZADA"
    assert rejected.latest_rejection_reason == "Fondos insuficientes"
    assert rejected.latest_rejection_payment_id == payments[key1].id
    sub_id = db_session.scalar(select(CoreSubscription.id).where(CoreSubscription.source == "tch", CoreSubscription.external_id == str(F1)))
    assert rejected.subscription_id == sub_id == payments[key1].subscription_id
    for key, payment in payments.items():
        assert payment.charge_id == charges[key].id

    accepted = charges[key2]
    assert accepted.source_status == "ACEPTADA" and accepted.latest_rejection_payment_id is None
    assert accepted.latest_rejection_reason is None


def test_rejected_then_paid_installment_keeps_one_charge_and_the_previous_rejection(db_session, tmp_path) -> None:
    etl_tch._process_file(_january(tmp_path), db_session)
    run_tch_core_etl(db_session)
    charge_id = _charges(db_session)[f"{F1}|2026-01|3"].id

    etl_tch._process_file(_february(tmp_path), db_session)
    run_tch_core_etl(db_session)

    charge = _charges(db_session)[f"{F1}|2026-01|3"]
    assert charge.id == charge_id  # la misma cuota, no una segunda fila
    assert charge.source_status == "ACEPTADA"
    assert charge.latest_rejection_payment_id is None  # el pago vigente ya no es un rechazo
    assert charge.latest_rejection_reason == "Fondos insuficientes"  # pero el intento fallido no se pierde
    assert charge.latest_rejection_at.date() == date(2026, 1, 15)
    assert _payments(db_session)[f"{F1}|2026-01|3"].source_status == "ACEPTADA"
    assert _charges(db_session)[f"{F1}|2026-02|4"].period_reference == "2026-02"


def test_core_etl_twice_gives_the_same_result(db_session, tmp_path) -> None:
    etl_tch._process_file(_january(tmp_path), db_session)
    etl_tch._process_file(_february(tmp_path), db_session)
    run_tch_core_etl(db_session)
    first = _snapshot(db_session)

    second_result = run_tch_core_etl(db_session)

    assert _snapshot(db_session) == first
    assert second_result["charges_inserted"] == 0 and second_result["payments_inserted"] == 0


def test_history_only_month_gets_a_charge_due_on_the_first_day_of_the_period(db_session, tmp_path) -> None:
    path = write_report(
        tmp_path / "20260331 TCH IG MARZO 2026.xlsx",
        active=[{"ficha": F1, "rut": "11111111-1", "historial": {(2026, 3): (5, "Pagada", 10000)}}],
    )
    etl_tch._process_file(path, db_session)
    run_tch_core_etl(db_session)
    charge = _charges(db_session)[f"{F1}|2026-03|5"]
    assert charge.due_at.date() == date(2026, 3, 1)
    assert _payments(db_session)[f"{F1}|2026-03|5"].occurred_at is None  # el historial no trae fecha de cobro


def test_consolidation_fills_client_external_id_for_tch(db_session, tmp_path) -> None:
    etl_tch._process_file(_january(tmp_path), db_session)
    channel_consolidation._consolidate_tch_clients(db_session)
    channel_consolidation._consolidate_tch_subscriptions(db_session)
    channel_consolidation._consolidate_tch_transactions(db_session)

    sub = db_session.scalars(select(Subscription).where(Subscription.source == "tch", Subscription.external_id == str(F1))).one()
    assert sub.client_external_id == RUT1
    charge = db_session.scalars(select(Charge).where(Charge.source == "tch", Charge.external_id == f"{F1}|2026-01|3")).one()
    assert charge.client_external_id == RUT1
    assert charge.subscription_external_id == str(F1)
