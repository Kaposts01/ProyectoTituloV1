"""TCH-PAR-10: tablas de control adicionales (FLUJO MANDATOS CANT/MONTO, RECHAZOS, ENT RECHAZOS, KPI).

Excel SINTETICO (sin datos personales): el reporte de layout A de `tests/tch_layouts.py` mas las hojas de control con
rotulos inventados. Todo en una transaccion con rollback.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.tch import TchMandateFlow, TchRejectionReason, TchReportKpi
from scripts import etl_tch
from tests.tch_layouts import layout_a

ENTITY_A = "ENTIDAD SINTETICA UNO"
ENTITY_B = "ENTIDAD SINTETICA DOS"


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


def _flow_sheet(wb: openpyxl.Workbook, title: str, factor: int) -> None:
    ws = wb.create_sheet(title)
    ws.append(["FLUJO MANDATOS SINTETICO"])
    ws.append([])
    ws.append(["ENTIDAD", "CONCEPTO", "OCT 24", "NOV 24", "DIC 24", "ENE 25"])
    ws.append([ENTITY_A, "VIGENTES", 100 * factor, 102 * factor, 103 * factor, 0])
    ws.append([None, "ALTAS", 5 * factor, 4 * factor, 2 * factor, 0])  # entidad combinada en vertical
    ws.append([None, "BAJAS", 3 * factor, 2 * factor, 1 * factor, 0])
    ws.append([ENTITY_B])  # titulo de seccion
    ws.append(["Vigentes", None, 10 * factor, 11 * factor, 12 * factor, 0])


def _with_control_sheets(path: Path, *, kpi: bool = True) -> Path:
    wb = openpyxl.load_workbook(path)
    _flow_sheet(wb, "FLUJO MANDATOS CANT", 1)
    _flow_sheet(wb, "FLUJO MANDATOS MONTO", 1000)
    reasons = wb.create_sheet("RECHAZOS")
    reasons.append(["RECHAZOS DE MANDATOS"])
    reasons.append(["Motivo", "Cantidad", "Monto"])
    reasons.append(["Cuenta Erronea", 3, 30000])
    reasons.append(["Firma Disconforme", 2, 20000])
    reasons.append(["12.345.678-5", 1, 1000])  # forma de RUT: se descarta
    reasons.append(["TOTAL", 5, 50000])
    by_entity = wb.create_sheet("ENT RECHAZOS")
    by_entity.append(["Motivo", ENTITY_A, ENTITY_B, "TOTAL"])
    by_entity.append(["Cuenta Erronea", 2, 1, 3])
    by_entity.append(["Falta de fondos", None, 4, 4])
    if kpi:
        sheet = wb.create_sheet("KPI")
        sheet.append(["INDICADORES DEL MES"])
        sheet.append(["Mandatos vigentes", None, 115])
        sheet.append(["Tasa de rechazo", 0.25])
        sheet.append(["Mandatos vigentes", 1])
    wb.save(path)
    return path


def _flow(db) -> dict[tuple[str, str, str], TchMandateFlow]:
    return {(r.period, r.entity, r.concept): r for r in db.scalars(select(TchMandateFlow))}


def test_mandate_flow_is_loaded_by_entity_concept_and_month(db_session, tmp_path) -> None:
    report = _with_control_sheets(layout_a(tmp_path))
    totals = etl_tch._process_file(report, db_session)

    flow = _flow(db_session)
    vigentes = flow[("2024-12", ENTITY_A, "VIGENTES")]
    assert (vigentes.kind, vigentes.count, vigentes.amount) == ("vigentes", 103, "103000")
    assert flow[("2024-11", ENTITY_A, "ALTAS")].kind == "altas"
    assert flow[("2024-10", ENTITY_A, "BAJAS")].count == 3
    assert flow[("2024-12", ENTITY_B, "Vigentes")].count == 12
    # ENE 25 es posterior al mes del reporte (dic-2024) y viene en cero: no se carga.
    assert not [key for key in flow if key[0] > "2024-12"]
    assert totals["controles_extra"]["flujo_mandatos"] == len(flow)


def test_rejection_reasons_and_entity_matrix(db_session, tmp_path) -> None:
    etl_tch._process_file(_with_control_sheets(layout_a(tmp_path)), db_session)

    rows = {(r.sheet, r.entity, r.reason): r for r in db_session.scalars(select(TchRejectionReason))}
    assert {key for key in rows if key[0] == "RECHAZOS"} == {
        ("RECHAZOS", "", "Cuenta Erronea"),
        ("RECHAZOS", "", "Firma Disconforme"),
    }  # sin TOTAL y sin el rotulo con forma de RUT
    first = rows[("RECHAZOS", "", "Cuenta Erronea")]
    assert (first.report_period, first.count, first.amount) == ("2024-12", 3, "30000")
    assert rows[("ENT RECHAZOS", ENTITY_B, "Cuenta Erronea")].count == 1
    assert rows[("ENT RECHAZOS", ENTITY_B, "Falta de fondos")].count == 4
    assert ("ENT RECHAZOS", ENTITY_A, "Falta de fondos") not in rows
    assert not [key for key in rows if key[1] == "TOTAL"]


def test_kpi_sheet_keeps_label_and_value_with_section_prefix(db_session, tmp_path) -> None:
    etl_tch._process_file(_with_control_sheets(layout_a(tmp_path)), db_session)

    kpis = {r.indicator: r.value for r in db_session.scalars(select(TchReportKpi))}
    assert kpis == {
        "INDICADORES DEL MES / Mandatos vigentes": "115",
        "INDICADORES DEL MES / Tasa de rechazo": "0.25",
        "INDICADORES DEL MES / Mandatos vigentes (2)": "1",
    }


def test_reloading_the_same_report_is_idempotent_and_a_missing_measure_is_kept(db_session, tmp_path) -> None:
    report = _with_control_sheets(layout_a(tmp_path))
    etl_tch._process_file(report, db_session)
    before = {key: (r.count, r.amount) for key, r in _flow(db_session).items()}

    wb = openpyxl.load_workbook(report)
    del wb["FLUJO MANDATOS MONTO"]
    wb.save(report)
    etl_tch._process_file(report, db_session)

    after = {key: (r.count, r.amount) for key, r in _flow(db_session).items()}
    assert after == before  # mismas filas; el monto que ya estaba no se borra
    assert len(db_session.scalars(select(TchReportKpi)).all()) == 3


def test_a_report_without_control_sheets_loads_normally(db_session, tmp_path) -> None:
    totals = etl_tch._process_file(layout_a(tmp_path), db_session)
    assert totals["controles_extra"] == {"flujo_mandatos": 0, "rechazos_motivo": 0, "kpi": 0}
    assert totals["trans"] > 0


def test_unrecognized_layouts_are_skipped_without_failing(db_session, tmp_path) -> None:
    report = layout_a(tmp_path)
    wb = openpyxl.load_workbook(report)
    wb.create_sheet("FLUJO MANDATOS CANT").append(["sin meses", 1, 2])
    wb.create_sheet("RECHAZOS").append(["sin motivo", 1])
    wb.save(report)
    totals = etl_tch._process_file(report, db_session)
    assert totals["controles_extra"]["flujo_mandatos"] == 0
    assert totals["controles_extra"]["rechazos_motivo"] == 0
    assert totals["trans"] > 0


def test_month_comes_from_content_when_the_file_name_has_none(db_session, tmp_path) -> None:
    report = _with_control_sheets(layout_a(tmp_path, name="reporte.xlsx"))
    totals = etl_tch._process_file(report, db_session)
    assert totals["periodo_reporte"] == "2024-12"  # ultimo "Cuota Mes" de CARGOS
    assert {r.report_period for r in db_session.scalars(select(TchReportKpi))} == {"2024-12"}


def test_full_clear_removes_the_control_tables(db_session, tmp_path) -> None:
    etl_tch._process_file(_with_control_sheets(layout_a(tmp_path)), db_session)
    etl_tch._clear_tch_data(db_session)
    for model in (TchMandateFlow, TchRejectionReason, TchReportKpi):
        assert db_session.scalars(select(model)).first() is None
