"""VP-PAR-06: el vinculo pago -> cobro de VirtualPOS sobrevive a la sync y se rehace hacia adelante. Datos sinteticos."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from vp_reports_support import (
    PEPPER,
    charge_id,
    payment_row,
    sub_id,
    uuid_of,
    write_report,
)

from app.core.config import settings
from app.db.session import engine
from app.models.core import CoreCharge, CorePayment
from app.models.vp import VpCharge, VpPayment
from app.services import core_vp_etl
from app.services.channel_store import extract_vp_payment, store_vp_resources
from app.services.vp_report_import import import_report

P1 = "virtualpos1"


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


@pytest.fixture(autouse=True)
def pepper(monkeypatch):
    monkeypatch.setattr(settings, "vp_report_hash_pepper", PEPPER)


def _api_payment(n: int, status: str = "pagado") -> dict:
    """Forma del listado `GET /payments`: sin referencia al cobro."""
    return {"order": {"uuid": uuid_of(n), "status": status, "amount": 9990, "currency": "CLP",
                      "created_at": "2026-10-05 09:30:00"}}


def _import_paid(db, tmp_path, *ns):
    path = write_report(tmp_path / "TransaccionesPAT-VirtualPOS-1792500000.csv", "transacciones",
                        [payment_row(n) for n in ns])
    return import_report(db, path, filename=path.name, uploaded_by_user_id=None)


def _charge(db, n, **raw):
    db.add(VpCharge(platform=P1, external_id=charge_id(n), subscription_external_id=sub_id(n), status="pagado",
                    raw_payload=raw or {}))
    db.flush()


def test_extract_vp_payment_never_writes_the_charge_link() -> None:
    values = extract_vp_payment({**_api_payment(1), "charge_id": "cid_x"})
    assert "charge_external_id" not in values
    assert values["external_id"] == uuid_of(1) and values["status"] == "pagado"


def test_approved_payment_link_survives_a_second_sync(db_session, tmp_path):
    _charge(db_session, 1)
    store_vp_resources(db_session, "payment", [_api_payment(1)], platform=P1)
    summary = _import_paid(db_session, tmp_path, 1)
    assert summary.links["vp_payments"] == 1
    linked = db_session.scalar(select(VpPayment.charge_external_id).where(VpPayment.external_id == uuid_of(1)))
    assert linked == charge_id(1)

    # segunda sync: el mismo pago vuelve del listado (con otro estado) y el vinculo NO se borra
    store_vp_resources(db_session, "payment", [_api_payment(1, status="pagado"), _api_payment(2)], platform=P1)
    db_session.expire_all()
    rows = {p.external_id: p for p in db_session.scalars(select(VpPayment))}
    assert rows[uuid_of(1)].charge_external_id == charge_id(1)
    assert rows[uuid_of(2)].charge_external_id is None


def test_core_etl_links_payments_created_after_the_report_was_loaded(db_session, tmp_path):
    _charge(db_session, 1)
    store_vp_resources(db_session, "payment", [_api_payment(1)], platform=P1)
    _import_paid(db_session, tmp_path, 1)  # todavia no hay core_payments: solo se vincula vp_payments
    charge = CoreCharge(source=P1, external_id=charge_id(1), source_status="pagado")
    payment = CorePayment(source=P1, external_id=uuid_of(1), source_status="pagado")
    db_session.add_all([charge, payment])
    db_session.flush()

    links = core_vp_etl._link_payments_to_charges(db_session)
    assert links["reports"] == 1
    db_session.refresh(payment)
    assert payment.charge_id == charge.id
    assert core_vp_etl._link_payments_to_charges(db_session) == {
        "reports": 0, "rejection_details": 0, "charge_payloads": 0,
    }


def test_charge_payload_with_payment_uuid_links_exactly_one_to_one(db_session):
    _charge(db_session, 1, payment={"order": {"uuid": uuid_of(1)}})
    _charge(db_session, 2, payment={"order": {"uuid": uuid_of(9)}})
    _charge(db_session, 3, payment={"order": {"uuid": uuid_of(9)}})  # UUID repetido: nunca se vincula
    db_session.add_all([
        VpPayment(platform=P1, external_id=uuid_of(1), status="pagado", raw_payload={}),
        VpPayment(platform=P1, external_id=uuid_of(9), status="pagado", raw_payload={}),
    ])
    db_session.flush()
    assert core_vp_etl.link_payments_from_charge_payloads(db_session)["vp_payments"] == 1
    rows = {p.external_id: p.charge_external_id for p in db_session.scalars(select(VpPayment))}
    assert rows == {uuid_of(1): charge_id(1), uuid_of(9): None}
