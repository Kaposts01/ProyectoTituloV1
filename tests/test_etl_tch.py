from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.tch import TchSubscription, TchTransaction
from app.services import tch_report_registry as report_registry
from scripts import etl_tch


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


def test_transform_subscriptions_sanitizes_raw_account_data() -> None:
    frame = pd.DataFrame({
        "Ficha DUES": [101],
        "SOCIO Rut": ["12345678-9"],
        "Numero Cuenta": ["1234567890"],
        "PAN": ["4111111111111111"],
        "Monto Vigente": ["$12.000"],
    })

    rows = etl_tch._transform_subscriptions(frame, "VIGENTE")

    assert len(rows) == 1
    assert rows[0]["numero_ficha"] == 101
    assert rows[0]["numero_cuenta"] == "1234567890"
    assert "Numero Cuenta" not in rows[0]["raw_payload"]
    assert "PAN" not in rows[0]["raw_payload"]


def test_transform_transactions_sanitizes_raw_account_data() -> None:
    frame = pd.DataFrame({
        "Numero Ficha": [101],
        "Periodo": [1],
        "N Cuota": ["3"],
        "Cuota Mes": ["AGOSTO 2026"],
        "Monto Cuota": ["$12.000"],
        "Numero Cuenta": ["1234567890"],
    })

    rows = etl_tch._transform_transactions(frame, "ACEPTADA", "tch.xlsx")

    assert len(rows) == 1
    assert rows[0]["periodo"] == "2026-08"
    assert rows[0]["monto"] == "12000"
    assert "Numero Cuenta" not in rows[0]["raw_payload"]


def test_load_tch_rows_is_idempotent(db_session) -> None:
    subscriptions = [{
        "numero_ficha": 987654,
        "estado": "VIGENTE",
        "raw_payload": {"source": "test"},
        "_cliente": None,
        "_cliente_titular": None,
    }]
    transactions = [{
        "numero_ficha": 987654,
        "periodo": "2026-08",
        "numero_cuota": "1",
        "monto": "12000",
        "estado": "ACEPTADA",
        "archivo_origen": "tch.xlsx",
        "dedupe_key": "987654|2026-08|1",
        "raw_payload": {"source": "test"},
    }]

    etl_tch._load_subscriptions(db_session, [dict(row) for row in subscriptions])
    etl_tch._load_subscriptions(db_session, [dict(row) for row in subscriptions])
    etl_tch._load_transactions(db_session, transactions, "tch.xlsx")
    etl_tch._load_transactions(db_session, transactions, "tch.xlsx")

    assert db_session.scalar(select(func.count()).select_from(TchSubscription).where(TchSubscription.file_number == 987654)) == 1
    assert db_session.scalar(select(func.count()).select_from(TchTransaction).where(TchTransaction.dedupe_key == transactions[0]["dedupe_key"])) == 1


def test_safe_error_message_redacts_account_like_values() -> None:
    message = etl_tch._safe_error_message(RuntimeError("failed account 1234567890"))

    assert "1234567890" not in message
    assert "[redacted]" in message


# --- TCH-PAR-03 (D13): la clave es (ficha, periodo real, cuota), sin estado ni monto. ---
# Resuelve SYNC-GAP-02: la misma cuota rechazada y luego aceptada, o con otro monto, es UNA fila.

def test_dedupe_key_exact_format() -> None:
    assert etl_tch._dedupe_key(101, "2026-08", "3") == "101|2026-08|3"


def test_dedupe_key_does_not_depend_on_status_nor_amount() -> None:
    frame = pd.DataFrame({
        "Numero Ficha": [101],
        "Periodo": [1],
        "N Cuota": ["3"],
        "Cuota Mes": ["AGOSTO 2026"],
        "Monto Cuota": ["$12.000"],
    })
    accepted = etl_tch._transform_transactions(frame, "ACEPTADA", "a.xlsx")[0]["dedupe_key"]
    rejected = etl_tch._transform_transactions(frame, "RECHAZADA", "r.xlsx")[0]["dedupe_key"]
    frame["Monto Cuota"] = ["$15.000"]
    other_amount = etl_tch._transform_transactions(frame, "ACEPTADA", "a.xlsx")[0]["dedupe_key"]
    assert accepted == rejected == other_amount == "101|2026-08|3"


def test_dedupe_key_none_fields_become_empty_segments() -> None:
    assert etl_tch._dedupe_key(101, None, None) == "101||"
    assert etl_tch._dedupe_key(101, "", "") == "101||"


def test_dedupe_key_none_and_empty_are_equivalent_but_zero_is_not() -> None:
    assert etl_tch._dedupe_key(1, "2026-08", None) == etl_tch._dedupe_key(1, "2026-08", "")
    assert etl_tch._dedupe_key(1, "2026-08", "0") == "1|2026-08|0"


def test_dedupe_key_only_normalizes_the_installment() -> None:
    # Sin strip en periodo (se normaliza antes, en transform); la cuota si se normaliza a entero (TCH-PAR-02).
    assert etl_tch._dedupe_key(101, " 2026-08", "3 ") == "101| 2026-08|3"
    assert etl_tch._dedupe_key(101, "2026-08", "3") != etl_tch._dedupe_key(101, "2026-09", "3")


def test_dedupe_key_is_str_file_number_not_zero_padded() -> None:
    assert etl_tch._dedupe_key(7, "2026-08", "1") == "7|2026-08|1"


def test_transform_transactions_dedupe_key_matches_helper() -> None:
    frame = pd.DataFrame({
        "Numero Ficha": [101, 101],
        "Periodo": [1, 2],
        "N Cuota": ["3", "4"],
        "Cuota Mes": ["AGOSTO 2026", "JULIO 2026"],
        "Monto Cuota": ["$12.000", "$12.000"],
    })
    rows = etl_tch._transform_transactions(frame, "ACEPTADA", "tch.xlsx")
    keys = [r["dedupe_key"] for r in rows]
    assert "101|2026-08|3" in keys
    assert "101|2026-07|4" in keys


# --- TCH-PAR-01: el periodo del cargo sale de "Cuota Mes", no de "Periodo" ni del nombre del archivo. ---
# Los datos son sinteticos: mismas columnas que la hoja CARGOS real, sin informacion personal.

def _charges_frame(installment_month: list, period: list | None = None) -> pd.DataFrame:
    n = len(installment_month)
    return pd.DataFrame({
        "Numero Ficha": list(range(1, n + 1)),
        "Periodo": period if period is not None else list(range(1, n + 1)),
        "N Cuota": ["1"] * n,
        "Cuota Mes": installment_month,
        "Moneda": ["Pesos"] * n,
        "Monto Cuota": ["$10.000"] * n,
    })


def test_transform_transactions_reads_installment_month_and_ignores_numeric_period() -> None:
    # "Periodo" es un correlativo 1..n (no un mes): con valores 1 y 2 antes caia al nombre del archivo.
    frame = _charges_frame(["SEPT 26", "ABRIL 2026"], period=[1, 2])
    rows = etl_tch._transform_transactions(frame, "ACEPTADA", "20260101 TCH IG DICIEMBRE 2025.xlsx")
    assert [r["periodo"] for r in rows] == ["2026-09", "2026-04"]


@pytest.mark.parametrize(
    ("texto", "expected"),
    [
        ("ENE 26", "2026-01"), ("FEB 26", "2026-02"), ("MAR 26", "2026-03"), ("ABR 26", "2026-04"),
        ("MAY 26", "2026-05"), ("JUN 26", "2026-06"), ("JUL 26", "2026-07"), ("AGO 26", "2026-08"),
        ("SEPT 26", "2026-09"), ("SEP 26", "2026-09"), ("SEPT. 26", "2026-09"), ("SEPT-26", "2026-09"),
        ("SEPTIEMBRE 2026", "2026-09"), ("Setiembre 2026", "2026-09"), ("sept 2026", "2026-09"),
        ("OCT 25", "2025-10"), ("NOV 25", "2025-11"), ("DIC 25", "2025-12"), ("DICIEMBRE 2017", "2017-12"),
        ("  Diciembre   2025 ", "2025-12"), ("SEPT26", "2026-09"),
    ],
)
def test_transform_transactions_parses_spanish_month_variants_and_two_digit_years(texto: str, expected: str) -> None:
    rows = etl_tch._transform_transactions(_charges_frame([texto]), "ACEPTADA", "x.xlsx")
    assert rows[0]["periodo"] == expected


def test_transform_transactions_accepts_real_dates_in_installment_month() -> None:
    rows = etl_tch._transform_transactions(_charges_frame([pd.Timestamp("2026-09-01")]), "ACEPTADA", "x.xlsx")
    assert rows[0]["periodo"] == "2026-09"


def test_transform_transactions_skips_rows_without_a_readable_installment_month() -> None:
    frame = _charges_frame(["SEPT 26", None, "sin mes"])
    rows = etl_tch._transform_transactions(frame, "ACEPTADA", "20260101 x.xlsx")
    assert [r["numero_ficha"] for r in rows] == [1]  # nunca se inventa un periodo desde el nombre del archivo


def test_transform_transactions_without_installment_month_column_returns_nothing() -> None:
    frame = _charges_frame(["SEPT 26"]).drop(columns=["Cuota Mes"])
    assert etl_tch._transform_transactions(frame, "ACEPTADA", "20260930 x.xlsx") == []


def _write_charges_workbook(path, sheet: str, installment_month: list[str]) -> None:
    """Escribe la hoja con el layout real: rotulos de grupo en la fila 6, de columna en la 7, datos desde la 8."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    grupo = [None, None, "DETALLE DEL PAGO", None, None, None, None]
    hoja = ["Numero Ficha", "Numero Mandato", "Periodo", "N Cuota", "Cuota Mes", "Moneda", "Monto Cuota"]
    ws.append([])
    for _ in range(4):
        ws.append([])
    ws.append(grupo)
    ws.append(hoja)
    for i, mes in enumerate(installment_month, start=1):
        ws.append([910000 + i, 800000 + i, i, 1.0, mes, "Pesos", 10000])
    wb.save(path)


def test_closing_file_named_after_next_month_does_not_shift_the_period(db_session, tmp_path) -> None:
    # Cierre de diciembre 2025 cuyo nombre lleva la fecha del dia siguiente (20260101): los cargos son de 2025-12.
    xlsx = tmp_path / "20260101 TCH IG DICIEMBRE 2025.xlsx"
    _write_charges_workbook(xlsx, etl_tch.SHEET_ACCEPTED_CHARGES, ["DIC 25", "DICIEMBRE 2025"])

    frame = etl_tch._read_sheet(xlsx, etl_tch.SHEET_ACCEPTED_CHARGES)
    assert frame is not None
    rows = etl_tch._transform_transactions(frame, "ACEPTADA", xlsx.name)
    assert [r["periodo"] for r in rows] == ["2025-12", "2025-12"]

    etl_tch._process_file(xlsx, db_session)
    periods = set(db_session.scalars(select(TchTransaction.period).where(TchTransaction.source_file == xlsx.name)))
    assert periods == {"2025-12"}


def test_monthly_file_without_date_in_name_still_gets_real_periods(db_session, tmp_path) -> None:
    # Los mensuales de 2025 se llaman "NN - TCH IG MES 2025" (sin fecha): antes quedaban con periodo NULL.
    xlsx = tmp_path / "03 - TCH IG MARZO 2025.xlsx"
    _write_charges_workbook(xlsx, etl_tch.SHEET_ACCEPTED_CHARGES, ["MAR 25"])
    etl_tch._process_file(xlsx, db_session)
    rows = db_session.scalars(select(TchTransaction).where(TchTransaction.source_file == xlsx.name)).all()
    assert [r.period for r in rows] == ["2025-03"]
    assert rows[0].dedupe_key.startswith("910001|2025-03|")


# --- TCH-PAR-02: numero_cuota siempre entero y dedupe_key estable ---

@pytest.mark.parametrize("installment", ["12", "12.0", 12.0, 12, " 12 ", "12,0", "012"])
def test_norm_installment_always_returns_plain_integer_text(installment) -> None:
    assert etl_tch._norm_installment(installment) == "12"


@pytest.mark.parametrize("empty", [None, float("nan"), "", "   "])
def test_norm_installment_returns_none_for_empty_values(empty) -> None:
    assert etl_tch._norm_installment(empty) is None


def test_norm_installment_keeps_zero_and_non_numeric_text() -> None:
    assert etl_tch._norm_installment(0.0) == "0"
    assert etl_tch._norm_installment("S/N") == "S/N"


def test_dedupe_key_is_identical_for_string_float_text_and_float_installment() -> None:
    claves = {
        etl_tch._dedupe_key(101, "2026-08", installment)
        for installment in ("12", "12.0", 12.0, 12)
    }
    assert claves == {"101|2026-08|12"}


def test_transform_transactions_installment_and_dedupe_key_do_not_depend_on_dtype() -> None:
    # Con NaN en la columna pandas la vuelve float (12.0); sin NaN queda entera o texto.
    base = {
        "Numero Ficha": [101, 102],
        "Cuota Mes": ["AGOSTO 2026", "AGOSTO 2026"],
        "Monto Cuota": ["$12.000", "$12.000"],
        "Numero Pagos del Mandato": [24.0, 24.0],
    }
    formas = [
        pd.DataFrame({**base, "N Cuota": [12, 12]}),
        pd.DataFrame({**base, "N Cuota": [12.0, 12.0]}),
        pd.DataFrame({**base, "N Cuota": ["12", "12.0"]}),
        pd.DataFrame({**base, "N Cuota": [12.0, None]}),
    ]
    resultados = [etl_tch._transform_transactions(f, "ACEPTADA", "x.xlsx") for f in formas]
    for rows in resultados[:3]:
        assert [r["numero_cuota"] for r in rows] == ["12", "12"]
        assert [r["total_cuotas"] for r in rows] == ["24", "24"]
        assert [r["dedupe_key"] for r in rows] == ["101|2026-08|12", "102|2026-08|12"]
    assert resultados[3][0]["dedupe_key"] == resultados[0][0]["dedupe_key"]


def test_transform_history_charges_normalizes_installment_like_charges() -> None:
    # Hoja VIGENTES: ventana de 12 meses, bloques "N / Estado / Monto" desde la columna 62.
    columns = [("Ficha DUES", "Ficha DUES")] + [(f"relleno{i}", "x") for i in range(61)]
    columns += [("ENERO 2026", "N"), ("ENERO 2026", "Estado"), ("ENERO 2026", "Monto")]
    values = [101] + [None] * 61
    filas = []
    for installment in (12.0, "12.0", "12", 12):
        filas.append([*values, installment, "Pagada", 12000])
    frame = pd.DataFrame(filas, columns=pd.MultiIndex.from_tuples(columns))
    rows = etl_tch._transform_charge_history(frame, "x.xlsx")
    assert {r["numero_cuota"] for r in rows} == {"12"}
    assert {r["dedupe_key"] for r in rows} == {"101|2026-01|12"}


# --- TCH-PAR-05: monto y moneda de la suscripcion salen de "Monto Vigente" / "Moneda Vigente" ---

def _active_frame(income, amount, currency) -> pd.DataFrame:
    columns = [
        ("Ficha DUES", "Ficha DUES"),
        ("SOCIO", "Rut"),
        ("ANTECEDENTES Y ESTADO MANDATO", "Ingreso"),
        ("MANDATO ACTUAL", "Moneda Vigente"),
        ("MANDATO ACTUAL", "Monto Vigente"),
        ("MANDATO ACTUAL", "Equivalente en Pesos"),
    ]
    return pd.DataFrame([[101, "12345678-9", income, currency, amount, 12000]], columns=pd.MultiIndex.from_tuples(columns))


def test_transform_subscriptions_amount_comes_from_current_amount_not_income() -> None:
    # "Ingreso" es una fecha: antes alimentaba monto y dejaba NULL el 100 % de las suscripciones.
    frame = _active_frame(pd.Timestamp("2024-03-15"), 12000, "Pesos")
    row = etl_tch._transform_subscriptions(frame, "VIGENTE")[0]
    assert row["monto"] == "12000"
    assert row["equivalente_pesos"] == "12000"


def test_transform_subscriptions_amount_is_none_when_current_amount_is_empty() -> None:
    frame = _active_frame(pd.Timestamp("2024-03-15"), None, "Pesos")
    assert etl_tch._transform_subscriptions(frame, "VIGENTE")[0]["monto"] is None


@pytest.mark.parametrize(("currency", "expected"), [("Pesos", "CLP"), ("UF", "UF"), (" uf ", "UF"), (None, None)])
def test_transform_subscriptions_keeps_current_currency_in_raw_payload(currency, expected) -> None:
    frame = _active_frame(pd.Timestamp("2024-03-15"), 12000, currency)
    row = etl_tch._transform_subscriptions(frame, "VIGENTE")[0]
    assert row["raw_payload"].get("moneda_vigente") == expected


# --- TCH-PAR-06: estado de la ficha desde la columna ESTADO + baja implicita ---

def _mandatos_frame(filas: list[tuple[int, str | None]]) -> pd.DataFrame:
    columns = [
        ("Ficha DUES", "Ficha DUES"),
        ("SOCIO", "Rut"),
        ("ANTECEDENTES Y ESTADO MANDATO", "ESTADO"),
        ("ULTIMOS MESES", "Estado"),  # los bloques mensuales traen otra columna "Estado": no debe usarse
    ]
    data = [[file_number, f"1{file_number % 10}000000-0", status, "Pagada"] for file_number, status in filas]
    return pd.DataFrame(data, columns=pd.MultiIndex.from_tuples(columns))


@pytest.mark.parametrize(
    ("columna", "expected"),
    [
        ("Activo", "VIGENTE"), ("ACTIVO", "VIGENTE"), ("Pendiente", "PENDIENTE"), (" pendiente ", "PENDIENTE"),
        ("Rechazado", "RECHAZADA"), ("Eliminado", "ELIMINADA"), ("ELIMINADA", "ELIMINADA"),
    ],
)
def test_transform_subscriptions_uses_the_status_column_over_the_sheet(columna: str, expected: str) -> None:
    # La hoja VIGENTES trae tambien Pendiente, Rechazado y Eliminado: manda la columna ESTADO.
    rows = etl_tch._transform_subscriptions(_mandatos_frame([(101, columna)]), "VIGENTE")
    assert rows[0]["estado"] == expected


@pytest.mark.parametrize("columna", [None, "", "Desconocido"])
def test_transform_subscriptions_falls_back_to_the_sheet_when_status_is_missing(columna) -> None:
    rows = etl_tch._transform_subscriptions(_mandatos_frame([(101, columna)]), "ELIMINADA")
    assert rows[0]["estado"] == "ELIMINADA"


def test_transform_subscriptions_without_status_column_uses_the_sheet() -> None:
    frame = pd.DataFrame({"Ficha DUES": [101], "SOCIO Rut": ["12345678-9"]})
    assert etl_tch._transform_subscriptions(frame, "RECHAZADA")[0]["estado"] == "RECHAZADA"


def _load_file_numbers(db, statuses: dict[int, str]) -> None:
    etl_tch._load_subscriptions(
        db,
        [
            {"numero_ficha": file_number, "estado": status, "raw_payload": {}, "_cliente": None, "_cliente_titular": None}
            for file_number, status in statuses.items()
        ],
    )


def _status(db, file_number: int) -> tuple[str, str | None]:
    row = db.execute(
        select(TchSubscription.status, TchSubscription.cancellation_reason).where(TchSubscription.file_number == file_number)
    ).one()
    return row.status, row.cancellation_reason


def test_implicit_cancellation_keeps_current_and_pending_and_closes_the_absent(db_session) -> None:
    # 3 casos: ficha vigente y ficha pendiente en el ultimo reporte; ficha vigente por un cierre viejo y ausente hoy.
    _load_file_numbers(db_session, {930001: "VIGENTE", 930002: "PENDIENTE", 930003: "VIGENTE", 930004: "ELIMINADA"})

    cambiadas = etl_tch._apply_implicit_cancellations(db_session, {930001, 930002, 930004})

    assert cambiadas == 1
    assert _status(db_session, 930001)[0] == "VIGENTE"
    assert _status(db_session, 930002)[0] == "PENDIENTE"
    status, reason = _status(db_session, 930003)
    assert status == "ELIMINADA"
    assert reason and "ausente" in reason.lower()
    assert _status(db_session, 930004)[0] == "ELIMINADA"


def test_implicit_cancellation_keeps_an_existing_cancellation_reason(db_session) -> None:
    _load_file_numbers(db_session, {930010: "VIGENTE"})
    db_session.execute(
        TchSubscription.__table__.update().where(TchSubscription.file_number == 930010).values({"razon_baja": "motivo previo"})
    )
    etl_tch._apply_implicit_cancellations(db_session, {1})
    assert _status(db_session, 930010) == ("ELIMINADA", "motivo previo")


def test_implicit_cancellation_never_runs_with_an_empty_last_report(db_session) -> None:
    # Si el ultimo reporte no trajo cartera (p. ej. la hoja VIGENTES de dic-2023), no se da de baja a nadie.
    _load_file_numbers(db_session, {930020: "VIGENTE"})
    assert etl_tch._apply_implicit_cancellations(db_session, set()) == 0
    assert _status(db_session, 930020)[0] == "VIGENTE"


@pytest.mark.parametrize(
    ("previo", "reporte", "expected"),
    [
        (None, "2026-09", True), ("2026-08", "2026-09", True), ("2026-09", "2026-09", True),
        ("2026-09", "2026-03", False),  # un reporte viejo no puede dar de baja lo cargado despues
        ("2026-09", None, False),
    ],
)
def test_implicit_cancellation_only_applies_to_the_latest_report(previo, reporte, expected) -> None:
    assert etl_tch._is_latest_report(previo, reporte) is expected


def test_process_file_without_a_readable_current_sheet_reports_no_file_numbers(db_session, tmp_path) -> None:
    # Solo hoja de cargos: no hay cartera, por lo que no se pueden inferir bajas implicitas.
    xlsx = tmp_path / "20260331 TCH IG MARZO 2026.xlsx"
    _write_charges_workbook(xlsx, etl_tch.SHEET_ACCEPTED_CHARGES, ["MAR 26"])
    assert etl_tch._process_file(xlsx, db_session)["fichas"] == set()


# --- TCH-PAR-15: sin periodos futuros en el control mensual y sin reportes duplicados (sha256) ---

def _write_control_workbook(path, periodos: list[tuple[str, int, int]]) -> None:
    """Hojas HISTORICO RECAUDACION CAN / FLUJO sinteticas: (periodo, aceptadas, rechazadas) por columna."""
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for hoja, factor in ((etl_tch.SHEET_COLLECTION_HISTORY_CAN, 1), (etl_tch.SHEET_COLLECTION_HISTORY_FLOW, 1000)):
        ws = wb.create_sheet(hoja)
        ws.append([None, None, None, *[p for p, _, _ in periodos]])
        ws.append(["TOTAL RECAUDACION EFECTUADA", None, None, *[a * factor for _, a, _ in periodos]])
        ws.append(["TOTAL COBROS RECHAZADOS", None, None, *[r * factor for _, _, r in periodos]])
    wb.save(path)


def test_recaudacion_cutoff_drops_future_zero_months(tmp_path) -> None:
    xlsx = tmp_path / "20260831 TCH IG AGOSTO 2026.xlsx"
    _write_control_workbook(
        xlsx,
        [("JULIO 2026", 10, 2), ("AGOSTO 2026", 11, 3), ("SEPTIEMBRE 2026", 0, 0), ("DICIEMBRE 2027", 0, 0)],
    )
    rows = etl_tch._transform_monthly_collection(xlsx)
    assert [r["periodo"] for r in rows] == ["2026-07", "2026-08"]


def test_recaudacion_cutoff_uses_the_closed_month_not_the_filename_date(tmp_path) -> None:
    # Cierre de diciembre 2025 con fecha de archivo 2026-01-01: enero 2026 aun no esta cerrado.
    xlsx = tmp_path / "20260101 TCH IG DICIEMBRE 2025.xlsx"
    _write_control_workbook(xlsx, [("NOVIEMBRE 2025", 10, 2), ("DICIEMBRE 2025", 12, 4), ("ENERO 2026", 0, 0)])
    assert [r["periodo"] for r in etl_tch._transform_monthly_collection(xlsx)] == ["2025-11", "2025-12"]


def test_recaudacion_cutoff_without_month_in_name_uses_last_month_with_charges(tmp_path) -> None:
    xlsx = tmp_path / "reporte.xlsx"
    _write_control_workbook(xlsx, [("MAYO 2026", 0, 0), ("JUNIO 2026", 5, 1), ("JULIO 2026", 6, 1), ("AGOSTO 2026", 0, 0)])
    # Un mes en cero dentro del rango cerrado se conserva; solo se cortan los futuros.
    assert [r["periodo"] for r in etl_tch._transform_monthly_collection(xlsx)] == ["2026-05", "2026-06", "2026-07"]


def test_purge_future_recaudacion_removes_only_trailing_zero_months(db_session) -> None:
    from app.models.tch import TchMonthlyCollection

    def fila(period: str, cantidad: int) -> TchMonthlyCollection:
        return TchMonthlyCollection(
            period=period, accepted_count=cantidad, accepted_amount="0",
            rejected_count=0, rejected_amount="0", source_file="x.xlsx",
        )

    db_session.add_all([fila("2090-02", 0), fila("2090-06", 7), fila("2090-07", 0), fila("2091-01", 0)])
    db_session.flush()

    assert etl_tch._purge_future_collection(db_session) == 2
    quedan = set(db_session.scalars(select(TchMonthlyCollection.period).where(TchMonthlyCollection.period >= "2090")))
    assert quedan == {"2090-02", "2090-06"}


def test_file_sha256_matches_hashlib_and_ignores_the_name(tmp_path) -> None:
    import hashlib

    a = tmp_path / "12 - TCH IG DICIEMBRE 2025 (1).XLSX"
    b = tmp_path / "20260101 TCH IG DICIEMBRE 2025.XLSX"
    a.write_bytes(b"contenido sintetico")
    b.write_bytes(b"contenido sintetico")
    assert report_registry.file_sha256(a) == report_registry.file_sha256(b) == hashlib.sha256(b"contenido sintetico").hexdigest()


def test_report_registry_remembers_loaded_hashes(db_session) -> None:
    sha = "ab" * 32
    assert not report_registry.is_registered(db_session, sha)
    report_registry.register(db_session, sha, "a.xlsx", 10)
    report_registry.register(db_session, sha, "a.xlsx", 10)  # idempotente
    assert report_registry.is_registered(db_session, sha)


def test_import_incremental_rejects_a_report_already_loaded(tmp_path, monkeypatch) -> None:
    xlsx = tmp_path / "20260930 TCH IG SEPTIEMBRE 2026.xlsx"
    xlsx.write_bytes(b"x")
    session_ids = {"registered": False}

    class FakeRun:
        id = "run"
        status = "running"

    class FakeDb:
        def get(self, *_a):
            return FakeRun()
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass

    monkeypatch.setattr(etl_tch, "SessionLocal", lambda: FakeDb())
    monkeypatch.setattr(etl_tch.report_registry, "is_registered", lambda _db, _sha: True)
    monkeypatch.setattr(etl_tch, "_process_file", lambda *a, **k: session_ids.update(registered=True))
    with pytest.raises(etl_tch.ReportAlreadyLoadedError):
        etl_tch.import_incremental_file(xlsx, run_id="run")
    assert session_ids["registered"] is False  # no se proceso nada


def test_unique_reports_by_sha256_skips_exact_duplicates(tmp_path) -> None:
    # El cierre de diciembre 2025 existe dos veces con el mismo contenido bajo nombres distintos.
    uno = tmp_path / "12 - TCH IG DICIEMBRE 2025 (1).XLSX"
    two = tmp_path / "20260101 TCH IG DICIEMBRE 2025.XLSX"
    other = tmp_path / "20260131 TCH IG ENERO 2026.XLSX"
    uno.write_bytes(b"A")
    two.write_bytes(b"A")
    other.write_bytes(b"B")
    unicos, omitidos = etl_tch._unique_reports_by_sha256([uno, two, other])
    assert unicos == [uno, other]
    assert omitidos == [two]


# --- TCH-PAR-18: codigo_respuesta y razon_rechazo desde el "Motivo" del reporte ---

def _rechazados_frame(motivos: list) -> pd.DataFrame:
    n = len(motivos)
    return pd.DataFrame({
        "Numero Ficha": list(range(1, n + 1)),
        "Periodo": [3] * n,  # correlativo; antes se leia como razon_rechazo por el rotulo "DETALLE DEL RECHAZO"
        "N Cuota": [1] * n,
        "Cuota Mes": ["SEPT 26"] * n,
        "Monto Cuota": [10000] * n,
        "TOTAL RECHAZADO": [10000] * n,
        "Motivo": motivos,
    })


def test_rejected_charges_take_reason_and_code_from_reason() -> None:
    rows = etl_tch._transform_transactions(_rechazados_frame(["Fondos insuficientes", "Cuenta cerrada"]), "RECHAZADA", "x.xlsx")
    assert [r["razon_rechazo"] for r in rows] == ["Fondos insuficientes", "Cuenta cerrada"]
    assert [r["codigo_respuesta"] for r in rows] == ["FONDOS_INSUFICIENTES", "CUENTA_CERRADA"]


def test_response_code_keeps_a_numeric_code_prefix_of_the_reason() -> None:
    rows = etl_tch._transform_transactions(_rechazados_frame(["R02 - Cuenta cerrada", "51: Fondos insuficientes"]), "RECHAZADA", "x.xlsx")
    assert [r["codigo_respuesta"] for r in rows] == ["R02", "51"]
    assert rows[0]["razon_rechazo"] == "R02 - Cuenta cerrada"


def test_reason_code_is_accent_insensitive_and_bounded() -> None:
    assert etl_tch._code_from_reason("Cuenta Inexistente / Cancelada") == "CUENTA_INEXISTENTE_CANCELADA"
    assert etl_tch._code_from_reason("Mandato sin autorización") == "MANDATO_SIN_AUTORIZACION"
    assert len(etl_tch._code_from_reason("x" * 200) or "") <= 50
    assert etl_tch._code_from_reason(None) is None
    assert etl_tch._code_from_reason("   ") is None


def test_an_explicit_code_column_wins_over_the_derived_one() -> None:
    frame = _rechazados_frame(["Fondos insuficientes"])
    frame["Codigo Respuesta"] = ["R01"]
    assert etl_tch._transform_transactions(frame, "RECHAZADA", "x.xlsx")[0]["codigo_respuesta"] == "R01"


def test_accepted_charges_have_no_reason_nor_code() -> None:
    frame = _rechazados_frame([None]).drop(columns=["Motivo", "TOTAL RECHAZADO"])
    row = etl_tch._transform_transactions(frame, "ACEPTADA", "x.xlsx")[0]
    assert row["razon_rechazo"] is None
    assert row["codigo_respuesta"] is None


def test_rejection_reason_is_not_the_numeric_period_column() -> None:
    row = etl_tch._transform_transactions(_rechazados_frame([None]), "RECHAZADA", "x.xlsx")[0]
    assert row["razon_rechazo"] is None


def test_rejection_reason_ignores_the_detail_of_the_rejection_group_label() -> None:
    # En la hoja real el grupo se llama "DETALLE DEL RECHAZO": buscar "rechazo" caia en la columna Periodo.
    columns = pd.MultiIndex.from_tuples([
        ("Numero Ficha", "Numero Ficha"),
        ("DETALLE DEL RECHAZO", "Periodo"),
        ("Unnamed: 2_level_0", "N Cuota"),
        ("Unnamed: 3_level_0", "Cuota Mes"),
        ("Unnamed: 4_level_0", "TOTAL RECHAZADO"),
        ("Unnamed: 5_level_0", "Motivo"),
    ])
    frame = pd.DataFrame([[101, 7, 3, "SEPT 26", 10000, "Fondos insuficientes"]], columns=columns)
    row = etl_tch._transform_transactions(frame, "RECHAZADA", "x.xlsx")[0]
    assert row["razon_rechazo"] == "Fondos insuficientes"
    assert row["periodo"] == "2026-09"


def test_rows_per_chunk_stays_under_postgres_parameter_limit() -> None:
    from app.models.tch import TchSubscription
    from scripts.etl_tch import _PG_MAX_PARAMS, _rows_per_chunk

    width = len(TchSubscription.__table__.columns)
    rows = [{f"c{i}": None for i in range(width)}] * 3
    chunk = _rows_per_chunk(rows, 2500)
    assert chunk * width <= _PG_MAX_PARAMS < 65535
    assert _rows_per_chunk([{"a": 1}], 2500) == 2500  # tope respetado
    assert _rows_per_chunk([], 10) == 10
    assert _rows_per_chunk([{f"c{i}": 1 for i in range(70000)}], 10) == 1
