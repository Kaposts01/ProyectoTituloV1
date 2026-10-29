"""TCH-PAR-04: el historial mensual (estado por mandato, sin fecha) no se suma a los cargos reales.

Excel sinteticos, sin datos personales.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.tch import ORIGIN_CHARGE, ORIGIN_HISTORY, TchTransaction
from scripts import etl_tch
from tests.tch_synthetic import write_report

OK, NUNCA_COBRO, CON_COBRO = 920001, 920002, 920003


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


def _reporte(tmp_path):
    return write_report(
        tmp_path / "20260228 TCH IG FEBRERO 2026.xlsx",
        vigentes=[
            {"ficha": OK, "historial": {(2026, 1): (1, "Pagada", 10000), (2026, 2): (2, "Pagada", 10000)}},
            # Mandato rechazado que figura en VIGENTES con ESTADO Rechazado: nunca cobro, su "Rechazada" mensual es de mandato.
            {"ficha": NUNCA_COBRO, "estado": "Rechazado", "historial": {(2026, 1): (1, "Rechazada", 10000)}},
        ],
        rechazados_mandatos=[
            {"ficha": 920009, "estado": "Rechazado", "historial": {(2026, 1): (1, "Rechazada", 10000), (2026, 2): (2, "Rechazada", 10000)}},
        ],
        aceptados=[{"ficha": OK, "cuota": 2, "mes": "FEB 26", "fecha": date(2026, 2, 10)}],
        rechazados=[{"ficha": CON_COBRO, "cuota": 2, "mes": "FEB 26", "fecha": date(2026, 2, 11), "motivo": "Fondos insuficientes"}],
    )


def test_rejected_mandate_that_never_charged_is_not_a_rejected_charge(db_session, tmp_path) -> None:
    etl_tch._process_file(_reporte(tmp_path), db_session)

    fichas = set(db_session.scalars(select(TchTransaction.file_number)))
    assert NUNCA_COBRO not in fichas
    assert 920009 not in fichas  # la hoja RECHAZADOS es estado de mandato
    rechazadas = list(db_session.scalars(select(TchTransaction.file_number).where(TchTransaction.status == "RECHAZADA")))
    assert rechazadas == [CON_COBRO]  # solo el cargo rechazado real


def test_history_rows_are_marked_and_never_carry_a_charge_date(db_session, tmp_path) -> None:
    etl_tch._process_file(_reporte(tmp_path), db_session)

    historial = db_session.scalars(select(TchTransaction).where(TchTransaction.origin == ORIGIN_HISTORY)).all()
    assert [(r.file_number, r.period) for r in historial] == [(OK, "2026-01")]  # febrero lo cubre el cargo real
    assert all(r.charge_date is None for r in historial)
    cargos = db_session.scalars(select(TchTransaction).where(TchTransaction.origin == ORIGIN_CHARGE)).all()
    assert {r.file_number for r in cargos} == {OK, CON_COBRO}
    assert all(r.charge_date for r in cargos)


def test_history_and_charge_of_the_same_cuota_are_not_added_up(db_session, tmp_path) -> None:
    etl_tch._process_file(_reporte(tmp_path), db_session)
    filas = db_session.scalars(select(TchTransaction).where(TchTransaction.file_number == OK, TchTransaction.period == "2026-02")).all()
    assert len(filas) == 1 and filas[0].origin == ORIGIN_CHARGE
