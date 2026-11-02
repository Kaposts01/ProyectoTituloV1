"""TK-PAR-07 (Clientes) y TK-PAR-09 (Pagos v2, Liquidaciones): parser y carga. Solo fixtures SINTETICAS.

Los encabezados son supuestos (no se abrieron reportes reales): se prueban la firma, los alias, la lectura por posicion
de columnas sin datos personales y que los sentinelas de PII nunca lleguen a los registros, a la base ni a los errores.
"""

import dataclasses
from datetime import date
from decimal import Decimal

import pytest
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session
from toku_reports_support import (
    COLUMNS,
    PEPPER,
    PII_SENTINELS,
    default_row,
    write_report,
    write_unsupported,
)

from app.core.config import settings
from app.db.session import engine
from app.models.toku_report import (
    TkReportCustomer,
    TkReportFile,
    TkReportPayment,
    TkReportSettlement,
)
from app.services.toku_report_import import import_report
from app.services.toku_report_parser import (
    CustomerRecord,
    PaymentReportRecord,
    ReportFormatError,
    SettlementRecord,
    UnsupportedReportError,
    open_report,
)

NEW_TYPES = ("clientes", "pagos", "liquidaciones")


def _read(path):
    with open_report(path, pepper=PEPPER) as rep:
        return rep.meta, list(rep.records()), rep.stats


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
    monkeypatch.setattr(settings, "toku_report_hash_pepper", PEPPER)


# ---- parser -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("report_type", NEW_TYPES)
def test_detects_new_types_without_personal_data(tmp_path, report_type):
    meta, records, stats = _read(write_report(tmp_path / f"{report_type}.xlsx", report_type))
    assert meta.report_type == report_type and len(records) == 3 and stats.rows_skipped == 0
    blob = repr(records)
    for sentinel in PII_SENTINELS:
        assert sentinel not in blob, (report_type, sentinel)
    forbidden = {"name", "nombre", "mail", "email", "phone", "rut", "external_ref", "card", "account"}
    assert not ({f.name for f in dataclasses.fields(records[0])} & forbidden)


def test_customer_record_fields(tmp_path):
    rows = [default_row("clientes", 1, **{"Fecha de Eliminación": "2026-02-01T09:00:00",
                                          "Silenciado hasta": "2026-12-31"})]
    _, records, _ = _read(write_report(tmp_path / "c.xlsx", "clientes", rows=rows))
    rec = records[0]
    assert isinstance(rec, CustomerRecord) and rec.customer_external_id == "cus_T0001"
    assert rec.deleted_at_source is not None and rec.silenced_until.date() == date(2026, 12, 31)


def test_customer_without_cus_prefix_is_skipped(tmp_path):
    rows = [default_row("clientes", 1, ID="SENTINELA-NOMBRE"), default_row("clientes", 2)]
    _, records, stats = _read(write_report(tmp_path / "c.xlsx", "clientes", rows=rows))
    assert [r.customer_external_id for r in records] == ["cus_T0002"]
    assert stats.skip_reasons == {"invalid_id": 1}


def test_payment_record_and_installments_aliases(tmp_path):
    cols = [c if c != "N.º Cuotas" else "N° de cuotas" for c in COLUMNS["pagos"]]
    rows = [{**default_row("pagos", 1), "N° de cuotas": 3}, {**default_row("pagos", 2), "N° de cuotas": "x"}]
    _, records, stats = _read(write_report(tmp_path / "p.xlsx", "pagos", rows=rows, columns=cols))
    assert len(records) == 1 and stats.skip_reasons == {"invalid_installments": 1}
    rec = records[0]
    assert isinstance(rec, PaymentReportRecord)
    assert (rec.payment_external_id, rec.installments, rec.payment_type, rec.amount) == (
        "pay_T0001", 3, "Crédito", Decimal("10000.00"),
    )
    assert rec.debt_external_id == "in_T0001" and rec.customer_external_id == "cus_T0001" and rec.status == "PAGADO"


def test_free_text_in_id_columns_is_never_kept(tmp_path):
    rows = [default_row("pagos", 1, Cliente="SENTINELA-NOMBRE", Deuda="sentinela@example.invalid")]
    _, records, _ = _read(write_report(tmp_path / "p.xlsx", "pagos", rows=rows))
    assert records[0].customer_external_id is None and records[0].debt_external_id is None


def test_settlement_record_and_header_not_starting_with_id(tmp_path):
    cols = ["Deuda", "ID", "Cliente", "Monto", "Comisión", "Monto Neto", "Fecha de Depósito", "Liquidado"]
    _, records, _ = _read(write_report(tmp_path / "l.xlsx", "liquidaciones", columns=cols))
    rec = records[0]
    assert isinstance(rec, SettlementRecord)
    assert (rec.commission, rec.net_amount, rec.deposit_date, rec.settled) == (
        Decimal("350.00"), Decimal("9650.00"), date(2026, 10, 10), True,
    )


def test_first_sheet_without_header_is_skipped(tmp_path):
    path = write_report(tmp_path / "l.xlsx", "liquidaciones")
    from openpyxl import load_workbook

    wb = load_workbook(path)
    summary = wb.create_sheet("Resumen", 0)
    summary.cell(row=1, column=1, value="Resumen de liquidaciones")
    summary.cell(row=2, column=1, value="Total depositado")
    wb.save(path)
    wb.close()
    meta, records, _ = _read(path)
    assert meta.report_type == "liquidaciones" and len(records) == 3


def test_partial_new_signature_lists_missing_names_only(tmp_path):
    path = write_report(tmp_path / "p.xlsx", "pagos", drop_columns=("N.º Cuotas",))
    with pytest.raises(ReportFormatError) as exc:
        open_report(path, pepper=PEPPER)
    msg = str(exc.value)
    assert "numero de cuotas" in msg and "pagos" in msg
    assert not any(s in msg for s in PII_SENTINELS)


def test_other_reports_stay_unsupported(tmp_path):
    with pytest.raises(UnsupportedReportError):
        open_report(write_unsupported(tmp_path / "c.xlsx"), pepper=PEPPER)
    wb = Workbook()
    ws = wb.active
    for i, h in enumerate(["ID", "Fecha de Creación", "Fecha de Eliminación", "Motivo", "Monto"], start=1):
        ws.cell(row=1, column=i, value=h)  # Contracargos: solo columnas comunes, sin firma propia
    path = tmp_path / "contracargos.xlsx"
    wb.save(path)
    wb.close()
    with pytest.raises(UnsupportedReportError):
        open_report(path, pepper=PEPPER)


# ---- carga ------------------------------------------------------------------------------------------------------


def test_import_new_types_is_idempotent_and_without_pii(tmp_path, db_session: Session):
    loaded = {}
    for report_type, model in (("clientes", TkReportCustomer), ("pagos", TkReportPayment),
                               ("liquidaciones", TkReportSettlement)):
        path = write_report(tmp_path / f"{report_type}.xlsx", report_type)
        summary = import_report(db_session, path, filename=path.name, uploaded_by_user_id=None)
        assert summary.report_type == report_type and summary.rows_new == 3, report_type
        again = import_report(db_session, path, filename=path.name, uploaded_by_user_id=None)
        assert again.already_loaded
        rows = db_session.scalars(select(model)).all()
        loaded[report_type] = rows
        for row in rows:
            blob = repr({c.name: getattr(row, c.name) for c in model.__table__.columns})
            assert not any(s in blob for s in PII_SENTINELS)
    assert {r.payment_external_id for r in loaded["pagos"]} >= {"pay_T0001", "pay_T0002", "pay_T0003"}
    assert db_session.scalar(select(TkReportFile.status).where(TkReportFile.report_type == "liquidaciones")) == "completed"


def test_customer_deletion_is_sticky_with_older_report(tmp_path, db_session: Session):
    deleted = [default_row("clientes", 7, **{"Fecha de Eliminación": "2026-03-01T10:00:00"})]
    new = write_report(tmp_path / "new.xlsx", "clientes", rows=deleted, generated="2026-10-20 10:00:00")
    old = write_report(tmp_path / "old.xlsx", "clientes", rows=[default_row("clientes", 7)], generated="2026-08-09 09:00:00")
    import_report(db_session, new, filename="new.xlsx", uploaded_by_user_id=None)
    import_report(db_session, old, filename="old.xlsx", uploaded_by_user_id=None)
    row = db_session.scalar(select(TkReportCustomer).where(TkReportCustomer.customer_external_id == "cus_T0007"))
    assert row.deleted_at_source is not None
