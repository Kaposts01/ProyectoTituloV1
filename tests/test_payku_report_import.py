"""PK-PAR-10 / PK-PAR-11 (d115 b): parser e importador de reportes de Payku. Solo fixtures SINTETICAS.

Los encabezados replican los medidos en la auditoria (parity_payku.md, seccion 1); no hay documentacion oficial del
formato. Se prueba la validacion de encabezados, que la PII nunca se lea ni se guarde, la idempotencia y la proyeccion
de comision, neto, medio de pago, numero de cuota y proxima fecha de cobro a `p_*`.
"""

import dataclasses
from datetime import date, datetime
from decimal import Decimal

import pytest
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.payku_channel import PaykuSubscription, PaykuTransaction
from app.models.payku_report import (
    PkReportFile,
    PkReportSettlement,
    PkReportTransaction,
)
from app.services.payku_report_import import import_report
from app.services.payku_report_parser import (
    ReportFormatError,
    UnsupportedReportError,
    installment_from_concept,
    parse_report,
)

SENT_NAME, SENT_MAIL, SENT_PHONE, SENT_DIGITS = "SENTINELA-NOMBRE", "sentinela@example.invalid", "+56900000000", "4242"
PII = (SENT_NAME, SENT_MAIL, SENT_PHONE, SENT_DIGITS)

DATA_TX = ["Transacción", "Comercio ID", "Fecha de Transacción", "Proveedor", "Tipo de Pago", "Nombre Origen",
           "Teléfono Origen", "Email Origen", "Orden", "Concepto", "Monto", "Comisión", "Monto Final"]
CONS_TX = ["Identificador/vaucher", "Fecha", "Concepto", "Orden", "Monto", "Comisión", "Monto Final", "Email",
           "Liquidación", "4 últimos dígitos", "Medio de pago", "Orden Externa", "Débito/Crédito"]
CONS_WALLET = ["Identificador Monedero", "Orden", "Concepto", "Fecha", "Ingreso/Egreso", "Monto", "Balance",
               "Liquidación Origen", "Estatus", "Tipo movimiento"]
CONS_SETTLE = ["Liquidación", "Monto", "Estatus", "Fecha Depósito"]
SUBS = ["Email", "Nombre", "Teléfono", "Suscripción ID", "Estatus", "Nombre Plan", "Frecuencia de Cobro",
        "Tipo de Monto", "Última Fecha Cobro", "Próxima Fecha Cobro", "Monto"]


def _sheet(ws, header, rows):
    ws.append(header)
    for row in rows:
        ws.append([row.get(h) for h in header])


def data_tx_row(n: int, **over):
    base = {"Transacción": f"tzp{n:013d}", "Comercio ID": "999", "Fecha de Transacción": "2026-10-05 10:11:12",
            "Proveedor": "Webpay", "Tipo de Pago": "Débito", "Nombre Origen": SENT_NAME, "Teléfono Origen": SENT_PHONE,
            "Email Origen": SENT_MAIL, "Orden": f"{n:07d}", "Concepto": f"Cobro: # {n}", "Monto": 10000,
            "Comisión": 350, "Monto Final": 9650}
    return {**base, **over}


def write_data_tx(path, rows=None, header=DATA_TX):
    wb = Workbook()
    ws = wb.active
    ws.title = "Export"
    _sheet(ws, header, rows if rows is not None else [data_tx_row(1), data_tx_row(2)])
    wb.save(path)
    wb.close()
    return path


def write_consolidado(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Transacciones"
    _sheet(ws, CONS_TX, [
        {"Identificador/vaucher": "tzc0000000000001", "Fecha": "05-09-2026 08:00", "Concepto": "ARRIBA CHILE - Juntos",
         "Orden": "1000001", "Monto": "$ 5.000", "Comisión": "175", "Monto Final": "4.825", "Email": SENT_MAIL,
         "Liquidación": "L-77", "4 últimos dígitos": SENT_DIGITS, "Medio de pago": "Webpay", "Débito/Crédito": "Crédito"},
    ])
    _sheet(wb.create_sheet("Monedero"), CONS_WALLET, [{"Identificador Monedero": "m1", "Monto": 1}])
    _sheet(wb.create_sheet("Liquidaciones"), CONS_SETTLE, [
        {"Liquidación": "L-77", "Monto": 4825, "Estatus": "Pagado", "Fecha Depósito": "2026-09-10"},
    ])
    wb.create_sheet("Retiros")
    wb.save(path)
    wb.close()
    return path


def write_subs(path, rows):
    wb = Workbook()
    _sheet(wb.active, SUBS, rows)
    wb.save(path)
    wb.close()
    return path


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


# ---- parser -----------------------------------------------------------------------------------------------------


def test_parses_data_transacciones_without_personal_data(tmp_path):
    sheets = parse_report(write_data_tx(tmp_path / "Payku_dataTransacciones.xlsx"))
    assert [s.layout for s in sheets] == ["data_transacciones"]
    rec = sheets[0].records[0]
    assert (rec.transaction_external_id, rec.order_ref, rec.installment_number, rec.is_installment) == (
        "tzp0000000000001", "0000001", 1, True)
    assert (rec.amount, rec.commission, rec.net_amount) == (Decimal("10000.00"), Decimal("350.00"), Decimal("9650.00"))
    assert (rec.payment_provider, rec.payment_type) == ("Webpay", "Débito")
    assert rec.occurred_at.year == 2026 and rec.occurred_at.hour == 10
    assert not any(s in repr(sheets) for s in PII)
    forbidden = {"name", "email", "phone", "last4", "concept", "description"}
    assert not ({f.name for f in dataclasses.fields(rec)} & forbidden)
    assert "comercio id" in sheets[0].extra_columns and "email origen" not in sheets[0].extra_columns


def test_parses_consolidado_sheets_and_ignores_wallet(tmp_path):
    sheets = parse_report(write_consolidado(tmp_path / "consolidado_2026.xlsx"))
    assert [s.layout for s in sheets] == ["consolidado", "liquidaciones"]
    tx = sheets[0].records[0]
    assert (tx.amount, tx.commission, tx.net_amount) == (Decimal("5000.00"), Decimal("175.00"), Decimal("4825.00"))
    assert (tx.payment_method, tx.payment_type, tx.settlement_external_id) == ("Webpay", "Crédito", "L-77")
    assert tx.is_installment is False and tx.installment_number is None  # donacion: el texto no se guarda
    assert tx.occurred_at.day == 5 and tx.occurred_at.month == 9  # dd-mm-aaaa
    st = sheets[1].records[0]
    assert (st.settlement_external_id, st.status, st.deposit_date) == ("L-77", "Pagado", date(2026, 9, 10))
    assert not any(s in repr(sheets) for s in PII)


def test_invalid_rows_are_counted_without_values(tmp_path):
    rows = [data_tx_row(1), data_tx_row(1), data_tx_row(3, **{"Transacción": "con espacio y " + SENT_NAME}),
            data_tx_row(4, **{"Fecha de Transacción": "ayer"}), data_tx_row(5, Monto="mucho")]
    sheet = parse_report(write_data_tx(tmp_path / "t.xlsx", rows))[0]
    assert len(sheet.records) == 1 and sheet.rows_total == 5
    assert sheet.skip_reasons == {"duplicate_in_file": 1, "invalid_id": 1, "invalid_date": 1, "invalid_amount": 1}


def test_header_validation_lists_missing_column_names_only(tmp_path):
    header = [h for h in DATA_TX if h != "Comisión"]
    with pytest.raises(ReportFormatError) as exc:
        parse_report(write_data_tx(tmp_path / "t.xlsx", [data_tx_row(1)], header=header))
    msg = str(exc.value)
    assert "comision" in msg and "data_transacciones" in msg
    assert not any(s in msg for s in PII)


def test_unknown_report_is_unsupported(tmp_path):
    wb = Workbook()
    wb.active.append(["Foo", "Bar"])
    wb.active.append([SENT_NAME, 1])
    path = tmp_path / "otro.xlsx"
    wb.save(path)
    wb.close()
    with pytest.raises(UnsupportedReportError) as exc:
        parse_report(path)
    assert SENT_NAME not in str(exc.value)


def test_installment_from_concept():
    assert installment_from_concept("Cobro: # 12") == 12
    assert installment_from_concept("cobro:#3 mensual") == 3
    assert installment_from_concept("Donación puntual") is None
    assert installment_from_concept(None) is None


# ---- carga y proyeccion -------------------------------------------------------------------------------------------


def test_import_is_idempotent_and_projects_financial_fields(tmp_path, db_session: Session):
    db_session.add_all([
        PaykuTransaction(external_id="tzp0000000000001", subscription_id="s1", amount="10000", status="success",
                         description="Cobro: # 1"),
        PaykuTransaction(external_id="tzp0000000000009", subscription_id="s1", amount="10000", status="rejected",
                         description="Cobro: # 9"),  # no esta en el reporte: solo se completa la cuota
    ])
    db_session.flush()
    path = write_data_tx(tmp_path / "Payku_dataTransacciones.xlsx")
    summary = import_report(db_session, path, filename=path.name, uploaded_by_user_id=None)
    assert (summary.report_type, summary.rows_total, summary.rows_new) == ("transacciones", 2, 2)
    assert summary.transactions_enriched == 1 and summary.installments_filled == 1
    again = import_report(db_session, path, filename=path.name, uploaded_by_user_id=None)
    assert again.already_loaded and again.rows_new == 2

    tx = db_session.scalar(select(PaykuTransaction).where(PaykuTransaction.external_id == "tzp0000000000001"))
    db_session.refresh(tx)
    assert (tx.commission, tx.net_amount, tx.payment_method, tx.installment_number) == (
        Decimal("350.00"), Decimal("9650.00"), "Débito", 1)
    other = db_session.scalar(select(PaykuTransaction).where(PaykuTransaction.external_id == "tzp0000000000009"))
    db_session.refresh(other)
    assert other.installment_number == 9 and other.commission is None

    for model in (PkReportTransaction, PkReportFile):
        for row in db_session.scalars(select(model)).all():
            blob = repr({c.name: getattr(row, c.name) for c in model.__table__.columns})
            assert not any(s in blob for s in PII)


def test_ambiguous_vouchers_are_not_projected(tmp_path, db_session: Session):
    db_session.add(PaykuTransaction(external_id="tzpDUP", amount="10000", status="success"))
    db_session.flush()
    rows = [data_tx_row(1, **{"Transacción": "tzpDUP", "Orden": "1"}), data_tx_row(2, **{"Transacción": "tzpDUP", "Orden": "2"})]
    path = write_data_tx(tmp_path / "dup.xlsx", rows)
    summary = import_report(db_session, path, filename=path.name, uploaded_by_user_id=None)
    assert summary.rows_new == 2 and summary.transactions_enriched == 0
    tx = db_session.scalar(select(PaykuTransaction).where(PaykuTransaction.external_id == "tzpDUP"))
    assert tx.commission is None


def test_consolidado_loads_settlements(tmp_path, db_session: Session):
    path = write_consolidado(tmp_path / "consolidado_2026.xlsx")
    summary = import_report(db_session, path, filename=path.name, uploaded_by_user_id=None)
    assert summary.report_type == "consolidado" and summary.sheets == ("consolidado", "liquidaciones")
    settlement = db_session.scalar(select(PkReportSettlement).where(PkReportSettlement.settlement_external_id == "L-77"))
    assert settlement.amount == Decimal("4825.00") and settlement.deposit_date == date(2026, 9, 10)


def test_subscriptions_report_sets_next_charge_date(tmp_path, db_session: Session):
    db_session.add(PaykuSubscription(external_id="suspk1", status="active"))
    db_session.flush()
    rows = [{"Email": SENT_MAIL, "Nombre": SENT_NAME, "Teléfono": SENT_PHONE, "Suscripción ID": "suspk1",
             "Estatus": "Activa", "Monto": 20000,
             "Próxima Fecha Cobro": datetime(2026, 11, 5)}]  # noqa: DTZ001 - celda Excel sin zona
    path = write_subs(tmp_path / "Payku_datasubscripciones.xlsx", rows)
    summary = import_report(db_session, path, filename=path.name, uploaded_by_user_id=None)
    assert summary.report_type == "suscripciones" and summary.subscriptions_next_date == 1
    sub = db_session.scalar(select(PaykuSubscription).where(PaykuSubscription.external_id == "suspk1"))
    db_session.refresh(sub)
    assert sub.next_charge_date == date(2026, 11, 5)
