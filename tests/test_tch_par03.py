"""TCH-PAR-03 + D13: una cuota (ficha, periodo real, cuota) = una fila con el ULTIMO estado.

Excel sinteticos de reportes consecutivos: no hay datos personales. El rechazo previo se conserva como atributo.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.tch import TchTransaction
from scripts import etl_tch
from tests.tch_synthetic import write_report

F1, F2 = 910001, 910002


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


def _filas(db, file_number: int) -> list[TchTransaction]:
    return list(db.scalars(select(TchTransaction).where(TchTransaction.file_number == file_number).order_by(TchTransaction.period, TchTransaction.installment_number)))


def _report_january(tmp_path):
    # Enero: la cuota 3 de F1 fue RECHAZADA (con motivo y fecha); la cuota 1 de F2 fue aceptada.
    return write_report(
        tmp_path / "20260131 TCH IG ENERO 2026.xlsx",
        rechazados=[{"ficha": F1, "cuota": 3, "mes": "ENE 26", "monto": 10000, "fecha": date(2026, 1, 15), "motivo": "Fondos insuficientes"}],
        aceptados=[{"ficha": F2, "cuota": 1, "mes": "ENE 26", "monto": 10000, "fecha": date(2026, 1, 20)}],
    )


def _report_february(tmp_path):
    # Febrero: el historial de 12 meses dice que la cuota 3 de enero ya esta PAGADA (reintento); F2/enero se repite
    # (cuota repetida entre reportes). Los cargos de febrero traen la cuota 4.
    return write_report(
        tmp_path / "20260228 TCH IG FEBRERO 2026.xlsx",
        active=[
            {"ficha": F1, "historial": {(2026, 1): (3, "Pagada", 10000), (2026, 2): (4, "Pagada", 10000)}},
            {"ficha": F2, "historial": {(2026, 1): (1, "Pagada", 10000), (2026, 2): (2, "Pagada", 10000)}},
        ],
        aceptados=[
            {"ficha": F1, "cuota": 4, "mes": "FEB 26", "monto": 10000, "fecha": date(2026, 2, 10)},
            {"ficha": F2, "cuota": 1, "mes": "ENE 26", "monto": 10000, "fecha": date(2026, 1, 20)},
        ],
    )


def _reporte_marzo(tmp_path):
    # Marzo reexpresa febrero: la cuota 4 de F1 ahora figura RECHAZADA y con otro monto.
    return write_report(
        tmp_path / "20260331 TCH IG MARZO 2026.xlsx",
        active=[{"ficha": F1, "historial": {(2026, 2): (4, "Rechazada", 12000), (2026, 3): (5, "Pagada", 12000)}}],
        aceptados=[{"ficha": F1, "cuota": 5, "mes": "MAR 26", "monto": 12000, "fecha": date(2026, 3, 10)}],
    )


def test_dedupe_key_is_file_number_and_period_without_installment_status_nor_amount() -> None:
    assert etl_tch._dedupe_key(101, "2026-08") == "101|2026-08"
    assert etl_tch._dedupe_key(101, None) == "101|"


def test_same_installment_rejected_then_accepted_is_one_row_with_the_previous_rejection(db_session, tmp_path) -> None:
    etl_tch._process_file(_report_january(tmp_path), db_session)
    etl_tch._process_file(_report_february(tmp_path), db_session)

    january = [r for r in _filas(db_session, F1) if r.period == "2026-01"]
    assert len(january) == 1  # antes: una fila RECHAZADA y otra ACEPTADA
    fila = january[0]
    assert fila.installment_number == "3"
    assert fila.status == "ACEPTADA"  # el ultimo reporte gana
    assert fila.previous_rejection is True
    assert fila.previous_rejection_reason == "Fondos insuficientes"
    assert fila.previous_rejection_at == "2026-01-15"
    assert fila.rejection_reason is None  # una cuota aceptada no conserva el motivo como rechazo vigente
    assert fila.origin == "cargo"  # el detalle del cargo (fecha, entidad) no lo pisa el historial


def test_installment_repeated_between_monthly_and_closing_report_is_one_row(db_session, tmp_path) -> None:
    etl_tch._process_file(_report_january(tmp_path), db_session)
    etl_tch._process_file(_report_february(tmp_path), db_session)

    filas = [r for r in _filas(db_session, F2) if r.period == "2026-01"]
    assert len(filas) == 1
    assert filas[0].status == "ACEPTADA"
    assert filas[0].previous_rejection in (None, False)


def test_three_consecutive_reports_keep_a_single_row_per_installment(db_session, tmp_path) -> None:
    for build in (_report_january, _report_february, _reporte_marzo):
        etl_tch._process_file(build(tmp_path), db_session)

    keys = list(db_session.scalars(select(TchTransaction.dedupe_key).where(TchTransaction.file_number.in_((F1, F2)))))
    assert len(keys) == len(set(keys))
    per_installment = db_session.execute(
        select(TchTransaction.file_number, TchTransaction.period, TchTransaction.installment_number, func.count())
        .where(TchTransaction.file_number.in_((F1, F2)))
        .group_by(TchTransaction.file_number, TchTransaction.period, TchTransaction.installment_number)
    ).all()
    assert all(cantidad == 1 for *_, cantidad in per_installment)
    assert len(per_installment) == 5  # F1: ene/3, feb/4, mar/5; F2: ene/1, feb/2


def test_restatement_in_a_later_report_replaces_status_and_amount(db_session, tmp_path) -> None:
    for build in (_report_january, _report_february, _reporte_marzo):
        etl_tch._process_file(build(tmp_path), db_session)

    february = [r for r in _filas(db_session, F1) if r.period == "2026-02"]
    assert len(february) == 1
    assert february[0].status == "RECHAZADA"  # marzo reexpreso febrero
    assert february[0].amount == "12000"
    assert february[0].origin == "cargo"  # conserva el detalle del cargo de febrero


def test_an_older_report_loaded_late_does_not_overwrite_a_newer_state(db_session, tmp_path) -> None:
    etl_tch._process_file(_report_february(tmp_path), db_session)
    etl_tch._process_file(_report_january(tmp_path), db_session)  # fuera de orden: enero llega despues

    january = [r for r in _filas(db_session, F1) if r.period == "2026-01"]
    assert len(january) == 1
    assert january[0].status == "ACEPTADA"  # febrero (mas nuevo) ya habia dicho PAGADA
    assert january[0].origin == "cargo"  # pero el detalle del cargo de enero si completa la fila


def test_reprocessing_the_same_report_is_idempotent(db_session, tmp_path) -> None:
    etl_tch._process_file(_report_january(tmp_path), db_session)
    etl_tch._process_file(_report_february(tmp_path), db_session)
    before = db_session.scalar(select(func.count()).select_from(TchTransaction).where(TchTransaction.file_number.in_((F1, F2))))
    etl_tch._process_file(_report_february(tmp_path), db_session)
    after = db_session.scalar(select(func.count()).select_from(TchTransaction).where(TchTransaction.file_number.in_((F1, F2))))
    assert before == after
    fila = next(r for r in _filas(db_session, F1) if r.period == "2026-01")
    assert fila.previous_rejection is True and fila.previous_rejection_reason == "Fondos insuficientes"


def test_same_report_with_accepted_and_rejected_rows_for_one_installment_keeps_the_accepted(db_session, tmp_path) -> None:
    path = write_report(
        tmp_path / "20260131 TCH IG ENERO 2026.xlsx",
        rechazados=[{"ficha": F1, "cuota": 3, "mes": "ENE 26", "fecha": date(2026, 1, 5), "motivo": "Cuenta cerrada", "transaccion": "Normal"}],
        aceptados=[{"ficha": F1, "cuota": 3, "mes": "ENE 26", "fecha": date(2026, 1, 12), "transaccion": "Reintento"}],
    )
    etl_tch._process_file(path, db_session)
    filas = _filas(db_session, F1)
    assert len(filas) == 1
    assert filas[0].status == "ACEPTADA"
    assert filas[0].previous_rejection_reason == "Cuenta cerrada"
    assert filas[0].previous_rejection_at == "2026-01-05"
    assert filas[0].charge_date == "2026-01-12"
    assert filas[0].transaction_type == "Reintento"


def test_legacy_keys_are_detected_before_an_incremental_load(db_session) -> None:
    assert etl_tch._has_legacy_dedupe_keys(db_session) is False
    db_session.add(TchTransaction(file_number=1, status="ACEPTADA", dedupe_key="1|2026-01|1|ACEPTADA|10000"))
    db_session.flush()
    assert etl_tch._has_legacy_dedupe_keys(db_session) is True


def test_keys_with_the_installment_are_legacy_too(db_session) -> None:
    # d223: la clave ficha|periodo|cuota (D13) tambien es antigua; la vigente ficha|periodo no lo es.
    db_session.add(TchTransaction(file_number=2, period="2026-01", status="ACEPTADA", dedupe_key="2|2026-01"))
    db_session.flush()
    assert etl_tch._has_legacy_dedupe_keys(db_session) is False
    db_session.add(TchTransaction(file_number=3, period="2026-01", status="ACEPTADA", dedupe_key="3|2026-01|7"))
    db_session.flush()
    assert etl_tch._has_legacy_dedupe_keys(db_session) is True


def _row(origin: str, installment: str, status: str, **extra) -> dict:
    return {
        "numero_ficha": 940001, "periodo": "2024-12", "numero_cuota": installment, "monto": "10000", "estado": status,
        "archivo_origen": "x.xlsx", "dedupe_key": etl_tch._dedupe_key(940001, "2024-12"), "origen": origin,
        "raw_payload": {"source": "test"}, **extra,
    }


@pytest.mark.parametrize("cargo_first", [False, True])
def test_history_and_charge_with_different_installment_numbers_are_one_row(db_session, cargo_first) -> None:
    # d223: el historial numera la cuota 18 y CARGOS la 6 (difieren en multiplos de 12). Antes quedaban dos filas.
    history = _row(etl_tch.ORIGIN_HISTORY, "18", "RECHAZADA")
    charge = _row(etl_tch.ORIGIN_CHARGE, "6", "ACEPTADA", fecha_cargo="2024-12-10", tipo_transaccion="Cargo")
    for row in ([charge, history] if cargo_first else [history, charge]):
        etl_tch._load_transactions(db_session, [row], "x.xlsx")
    filas = _filas(db_session, 940001)
    assert len(filas) == 1
    fila = filas[0]
    assert (fila.origin, fila.installment_number, fila.charge_date) == (etl_tch.ORIGIN_CHARGE, "6", "2024-12-10")


def test_currency_column_wins_over_the_payload_when_resolving_currency() -> None:
    from types import SimpleNamespace

    from app.services.core_tch_etl import _resolve_currency

    assert _resolve_currency(SimpleNamespace(currency="UF", raw_payload={"moneda_vigente": "CLP"})) == "UF"
    assert _resolve_currency(SimpleNamespace(currency=None, raw_payload={"moneda_vigente": "UF"})) == "UF"


def test_core_prunes_charges_with_the_installment_key_once_the_reload_replaced_them(db_session) -> None:
    # d223: tras la recarga, core_charges no debe quedar con la clave ficha|periodo|cuota junto a la nueva.
    from app.models.core import CoreCharge
    from app.services import core_tch_etl

    db_session.add(TchTransaction(file_number=950001, period="2024-12", status="ACEPTADA", dedupe_key="950001|2024-12"))
    db_session.add(TchTransaction(file_number=950002, period="2024-12", status="ACEPTADA", dedupe_key="950002|2024-12|3"))
    db_session.add_all([
        CoreCharge(source="tch", external_id="950001|2024-12|6"),  # antigua y reemplazada: se borra
        CoreCharge(source="tch", external_id="950001|2024-12"),  # vigente: se queda
        CoreCharge(source="tch", external_id="950002|2024-12|3"),  # antigua pero aun en tch_transacciones: se queda
    ])
    db_session.flush()
    assert core_tch_etl._prune_legacy_charges(db_session) == 1
    quedan = set(db_session.scalars(select(CoreCharge.external_id).where(CoreCharge.external_id.like("95000_|%"))))
    assert quedan == {"950001|2024-12", "950002|2024-12|3"}
