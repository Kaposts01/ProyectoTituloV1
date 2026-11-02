"""TCH-PAR-16: el ETL abre cada reporte una vez y recorre cada hoja una sola vez. Excel sinteticos, sin datos personales."""

from __future__ import annotations

from datetime import date

import openpyxl
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from sqlalchemy.orm import Session

from app.db.session import engine
from scripts import etl_tch
from tests.tch_synthetic import write_report


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


def _report(tmp_path):
    return write_report(
        tmp_path / "20260131 TCH IG ENERO 2026.xlsx",
        active=[
            {"ficha": 960001, "historial": {(2025, 12): (1, "Pagada", 10000), (2026, 1): (2, "Impaga", 10000)}},
            {"ficha": 960002, "monto": 7500},
        ],
        eliminados=[{"ficha": 960003, "estado": "Eliminado"}],
        aceptados=[{"ficha": 960001, "cuota": 2, "mes": "ENE 26", "fecha": date(2026, 1, 5)}],
        rechazados=[{"ficha": 960002, "cuota": 1, "mes": "ENE 26", "fecha": date(2026, 1, 6), "motivo": "Cuenta cerrada"}],
        control=[("DICIEMBRE 2025", 1, 0), ("ENERO 2026", 1, 1)],
    )


def _tables_sheet(path) -> None:
    wb = openpyxl.load_workbook(path)
    ws = wb.create_sheet("TABLAS")
    ws.append(["Catalogo"])
    ws.append([])
    ws.append(["NOMBRE", "COD INTERNO", "COD GRUPO"])
    ws.append(["BANCO SINTETICO", 1, 10])
    ws.append(["OTRO BANCO", 2.5, None])
    wb.save(path)


@pytest.mark.parametrize(
    ("sheet", "header"),
    [
        ("VIGENTES", [5, 6]),
        ("VIGENTES", None),
        ("ELIMINADOS", [4, 5, 6]),
        ("CARGOS ACEPTADOS", [5, 6]),
        ("CARGOS RECHAZADOS", [5, 6]),
        ("HISTORICO RECAUDACION CAN", None),
        ("TABLAS", 2),
    ],
)
def test_report_book_frames_are_identical_to_read_excel(tmp_path, sheet, header) -> None:
    path = _report(tmp_path)
    _tables_sheet(path)
    with etl_tch.ReportBook(path) as book:
        ours = book.frame(sheet, header=header)
    theirs = pd.read_excel(path, sheet_name=sheet, header=header)
    assert_frame_equal(ours, theirs)


def test_process_file_reads_each_sheet_once_and_never_calls_read_excel(tmp_path, db_session, monkeypatch) -> None:
    path = _report(tmp_path)
    _tables_sheet(path)
    books: list[etl_tch.ReportBook] = []

    class SpyBook(etl_tch.ReportBook):
        def __init__(self, filepath):
            super().__init__(filepath)
            books.append(self)

    def _no_read_excel(*_args, **_kwargs):
        raise AssertionError("el ETL no debe reabrir el libro con pd.read_excel")

    monkeypatch.setattr(etl_tch, "ReportBook", SpyBook)
    monkeypatch.setattr(etl_tch.pd, "read_excel", _no_read_excel)

    totals = etl_tch._process_file(path, db_session)

    assert len(books) == 1, "el reporte se abre una sola vez"
    reads = books[0].sheet_reads
    assert reads and set(reads.values()) == {1}, reads
    assert {"VIGENTES", "ELIMINADOS", "CARGOS ACEPTADOS", "CARGOS RECHAZADOS", "TABLAS",
            "HISTORICO RECAUDACION CAN", "HISTORICO RECAUDACION FLUJO"} <= set(reads)
    assert totals["trans"] > 0 and totals["controles"] == 2


def test_fallback_header_detection_reuses_the_cells_already_read(tmp_path) -> None:
    """Encabezado fuera de las filas 6-7: el sondeo y la relectura con el encabezado detectado no recorren de nuevo."""
    path = tmp_path / "shifted.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "VIGENTES"
    for _ in range(9):
        ws.append([])
    ws.append(["Ficha DUES", "SOCIO", "ANTECEDENTES Y ESTADO MANDATO"])
    ws.append(["Ficha DUES", "Rut", "ESTADO"])
    ws.append([970001, "11111111-1", "Activo"])
    wb.save(path)
    with etl_tch.ReportBook(path) as book:
        frame = etl_tch._read_sheet(book, "VIGENTES")
        assert book.sheet_reads == {"VIGENTES": 1}
    assert frame is not None and len(frame) == 1


def test_missing_sheet_returns_none_without_error(tmp_path) -> None:
    path = write_report(tmp_path / "solo_cargos.xlsx", aceptados=[{"ficha": 1, "mes": "ENE 26"}])
    with etl_tch.ReportBook(path) as book:
        assert etl_tch._read_sheet(book, "VIGENTES") is None
