"""TCH-PAR-21: `fecha_entrega_banco` debe actualizarse cuando un reporte posterior la trae. Datos sinteticos."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.tch import TchSubscription
from scripts import etl_tch
from tests.tch_synthetic import write_report

ENTREGA = ("ANTECEDENTES Y ESTADO MANDATOS", "Entrega Banco")


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


def _bank_delivery(db: Session, file_number: int) -> str | None:
    db.expire_all()
    return db.scalar(select(TchSubscription.bank_delivery_date).where(TchSubscription.file_number == file_number))


def test_later_report_updates_bank_delivery_date(db_session, tmp_path) -> None:
    first = write_report(
        tmp_path / "20260131 TCH IG ENERO 2026.xlsx",
        active=[
            {"ficha": 949101, "rut": "12345678-9"},  # aun sin entrega al banco
            {"ficha": 949102, "rut": "11111111-1", "extra": {ENTREGA: "10/01/2026"}},
        ],
        extra_headers=[ENTREGA],
    )
    etl_tch._process_file(first, db_session)
    assert _bank_delivery(db_session, 949101) is None
    assert _bank_delivery(db_session, 949102) == "2026-01-10"

    second = write_report(
        tmp_path / "20260228 TCH IG FEBRERO 2026.xlsx",
        active=[
            {"ficha": 949101, "rut": "12345678-9", "extra": {ENTREGA: datetime(2026, 2, 3)}},  # noqa: DTZ001
            {"ficha": 949102, "rut": "11111111-1", "extra": {ENTREGA: "12/02/2026"}},  # la fuente corrigio la fecha
        ],
        extra_headers=[ENTREGA],
    )
    etl_tch._process_file(second, db_session)
    assert _bank_delivery(db_session, 949101) == "2026-02-03"
    assert _bank_delivery(db_session, 949102) == "2026-02-12"
