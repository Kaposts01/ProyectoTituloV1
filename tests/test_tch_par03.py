"""TCH-PAR-03 + D13: una cuota (ficha, periodo real, cuota) = una fila con el ULTIMO estado.

Excel sinteticos de reportes consecutivos: no hay datos personales. El rechazo previo se conserva como atributo.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.tch import TchTransaccion
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


def _filas(db, ficha: int) -> list[TchTransaccion]:
    return list(db.scalars(select(TchTransaccion).where(TchTransaccion.numero_ficha == ficha).order_by(TchTransaccion.periodo, TchTransaccion.numero_cuota)))


def _reporte_enero(tmp_path):
    # Enero: la cuota 3 de F1 fue RECHAZADA (con motivo y fecha); la cuota 1 de F2 fue aceptada.
    return write_report(
        tmp_path / "20260131 TCH IG ENERO 2026.xlsx",
        rechazados=[{"ficha": F1, "cuota": 3, "mes": "ENE 26", "monto": 10000, "fecha": date(2026, 1, 15), "motivo": "Fondos insuficientes"}],
        aceptados=[{"ficha": F2, "cuota": 1, "mes": "ENE 26", "monto": 10000, "fecha": date(2026, 1, 20)}],
    )


def _reporte_febrero(tmp_path):
    # Febrero: el historial de 12 meses dice que la cuota 3 de enero ya esta PAGADA (reintento); F2/enero se repite
    # (cuota repetida entre reportes). Los cargos de febrero traen la cuota 4.
    return write_report(
        tmp_path / "20260228 TCH IG FEBRERO 2026.xlsx",
        vigentes=[
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
        vigentes=[{"ficha": F1, "historial": {(2026, 2): (4, "Rechazada", 12000), (2026, 3): (5, "Pagada", 12000)}}],
        aceptados=[{"ficha": F1, "cuota": 5, "mes": "MAR 26", "monto": 12000, "fecha": date(2026, 3, 10)}],
    )


def test_dedupe_key_is_ficha_periodo_cuota_without_estado_nor_monto() -> None:
    assert etl_tch._dedupe_key(101, "2026-08", "3") == "101|2026-08|3"
    assert etl_tch._dedupe_key(101, "2026-08", 3.0) == "101|2026-08|3"
    assert etl_tch._dedupe_key(101, None, None) == "101||"


def test_same_cuota_rejected_then_accepted_is_one_row_with_the_previous_rejection(db_session, tmp_path) -> None:
    etl_tch._process_file(_reporte_enero(tmp_path), db_session)
    etl_tch._process_file(_reporte_febrero(tmp_path), db_session)

    enero = [r for r in _filas(db_session, F1) if r.periodo == "2026-01"]
    assert len(enero) == 1  # antes: una fila RECHAZADA y otra ACEPTADA
    fila = enero[0]
    assert fila.numero_cuota == "3"
    assert fila.estado == "ACEPTADA"  # el ultimo reporte gana
    assert fila.rechazo_previo is True
    assert fila.rechazo_previo_motivo == "Fondos insuficientes"
    assert fila.rechazo_previo_en == "2026-01-15"
    assert fila.razon_rechazo is None  # una cuota aceptada no conserva el motivo como rechazo vigente
    assert fila.origen == "cargo"  # el detalle del cargo (fecha, entidad) no lo pisa el historial


def test_cuota_repeated_between_monthly_and_closing_report_is_one_row(db_session, tmp_path) -> None:
    etl_tch._process_file(_reporte_enero(tmp_path), db_session)
    etl_tch._process_file(_reporte_febrero(tmp_path), db_session)

    filas = [r for r in _filas(db_session, F2) if r.periodo == "2026-01"]
    assert len(filas) == 1
    assert filas[0].estado == "ACEPTADA"
    assert filas[0].rechazo_previo in (None, False)


def test_three_consecutive_reports_keep_a_single_row_per_cuota(db_session, tmp_path) -> None:
    for build in (_reporte_enero, _reporte_febrero, _reporte_marzo):
        etl_tch._process_file(build(tmp_path), db_session)

    keys = list(db_session.scalars(select(TchTransaccion.dedupe_key).where(TchTransaccion.numero_ficha.in_((F1, F2)))))
    assert len(keys) == len(set(keys))
    por_cuota = db_session.execute(
        select(TchTransaccion.numero_ficha, TchTransaccion.periodo, TchTransaccion.numero_cuota, func.count())
        .where(TchTransaccion.numero_ficha.in_((F1, F2)))
        .group_by(TchTransaccion.numero_ficha, TchTransaccion.periodo, TchTransaccion.numero_cuota)
    ).all()
    assert all(cantidad == 1 for *_, cantidad in por_cuota)
    assert len(por_cuota) == 5  # F1: ene/3, feb/4, mar/5; F2: ene/1, feb/2


def test_restatement_in_a_later_report_replaces_estado_and_monto(db_session, tmp_path) -> None:
    for build in (_reporte_enero, _reporte_febrero, _reporte_marzo):
        etl_tch._process_file(build(tmp_path), db_session)

    febrero = [r for r in _filas(db_session, F1) if r.periodo == "2026-02"]
    assert len(febrero) == 1
    assert febrero[0].estado == "RECHAZADA"  # marzo reexpreso febrero
    assert febrero[0].monto == "12000"
    assert febrero[0].origen == "cargo"  # conserva el detalle del cargo de febrero


def test_an_older_report_loaded_late_does_not_overwrite_a_newer_state(db_session, tmp_path) -> None:
    etl_tch._process_file(_reporte_febrero(tmp_path), db_session)
    etl_tch._process_file(_reporte_enero(tmp_path), db_session)  # fuera de orden: enero llega despues

    enero = [r for r in _filas(db_session, F1) if r.periodo == "2026-01"]
    assert len(enero) == 1
    assert enero[0].estado == "ACEPTADA"  # febrero (mas nuevo) ya habia dicho PAGADA
    assert enero[0].origen == "cargo"  # pero el detalle del cargo de enero si completa la fila


def test_reprocessing_the_same_report_is_idempotent(db_session, tmp_path) -> None:
    etl_tch._process_file(_reporte_enero(tmp_path), db_session)
    etl_tch._process_file(_reporte_febrero(tmp_path), db_session)
    antes = db_session.scalar(select(func.count()).select_from(TchTransaccion).where(TchTransaccion.numero_ficha.in_((F1, F2))))
    etl_tch._process_file(_reporte_febrero(tmp_path), db_session)
    despues = db_session.scalar(select(func.count()).select_from(TchTransaccion).where(TchTransaccion.numero_ficha.in_((F1, F2))))
    assert antes == despues
    fila = next(r for r in _filas(db_session, F1) if r.periodo == "2026-01")
    assert fila.rechazo_previo is True and fila.rechazo_previo_motivo == "Fondos insuficientes"


def test_same_report_with_accepted_and_rejected_rows_for_one_cuota_keeps_the_accepted(db_session, tmp_path) -> None:
    ruta = write_report(
        tmp_path / "20260131 TCH IG ENERO 2026.xlsx",
        rechazados=[{"ficha": F1, "cuota": 3, "mes": "ENE 26", "fecha": date(2026, 1, 5), "motivo": "Cuenta cerrada", "transaccion": "Normal"}],
        aceptados=[{"ficha": F1, "cuota": 3, "mes": "ENE 26", "fecha": date(2026, 1, 12), "transaccion": "Reintento"}],
    )
    etl_tch._process_file(ruta, db_session)
    filas = _filas(db_session, F1)
    assert len(filas) == 1
    assert filas[0].estado == "ACEPTADA"
    assert filas[0].rechazo_previo_motivo == "Cuenta cerrada"
    assert filas[0].rechazo_previo_en == "2026-01-05"
    assert filas[0].fecha_cargo == "2026-01-12"
    assert filas[0].tipo_transaccion == "Reintento"


def test_legacy_keys_are_detected_before_an_incremental_load(db_session) -> None:
    assert etl_tch._has_legacy_dedupe_keys(db_session) is False
    db_session.add(TchTransaccion(numero_ficha=1, estado="ACEPTADA", dedupe_key="1|2026-01|1|ACEPTADA|10000"))
    db_session.flush()
    assert etl_tch._has_legacy_dedupe_keys(db_session) is True


def test_moneda_column_wins_over_the_payload_when_resolving_currency() -> None:
    from types import SimpleNamespace

    from app.services.core_tch_etl import _resolve_currency

    assert _resolve_currency(SimpleNamespace(moneda="UF", raw_payload={"moneda_vigente": "CLP"})) == "UF"
    assert _resolve_currency(SimpleNamespace(moneda=None, raw_payload={"moneda_vigente": "UF"})) == "UF"
