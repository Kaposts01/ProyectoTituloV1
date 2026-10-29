from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.tch import TchSuscripcion, TchTransaccion
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


def test_transform_suscripciones_sanitizes_raw_account_data() -> None:
    frame = pd.DataFrame({
        "Ficha DUES": [101],
        "SOCIO Rut": ["12345678-9"],
        "Numero Cuenta": ["1234567890"],
        "PAN": ["4111111111111111"],
        "Monto Vigente": ["$12.000"],
    })

    rows = etl_tch._transform_suscripciones(frame, "VIGENTE")

    assert len(rows) == 1
    assert rows[0]["numero_ficha"] == 101
    assert rows[0]["numero_cuenta"] == "1234567890"
    assert "Numero Cuenta" not in rows[0]["raw_payload"]
    assert "PAN" not in rows[0]["raw_payload"]


def test_transform_transacciones_sanitizes_raw_account_data() -> None:
    frame = pd.DataFrame({
        "Numero Ficha": [101],
        "Periodo": [1],
        "N Cuota": ["3"],
        "Cuota Mes": ["AGOSTO 2026"],
        "Monto Cuota": ["$12.000"],
        "Numero Cuenta": ["1234567890"],
    })

    rows = etl_tch._transform_transacciones(frame, "ACEPTADA", "tch.xlsx")

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
        "dedupe_key": "987654|2026-08|1|ACEPTADA|12000",
        "raw_payload": {"source": "test"},
    }]

    etl_tch._load_suscripciones(db_session, [dict(row) for row in subscriptions])
    etl_tch._load_suscripciones(db_session, [dict(row) for row in subscriptions])
    etl_tch._load_transacciones(db_session, transactions, "tch.xlsx")
    etl_tch._load_transacciones(db_session, transactions, "tch.xlsx")

    assert db_session.scalar(select(func.count()).select_from(TchSuscripcion).where(TchSuscripcion.numero_ficha == 987654)) == 1
    assert db_session.scalar(select(func.count()).select_from(TchTransaccion).where(TchTransaccion.dedupe_key == transactions[0]["dedupe_key"])) == 1


def test_safe_error_message_redacts_account_like_values() -> None:
    message = etl_tch._safe_error_message(RuntimeError("failed account 1234567890"))

    assert "1234567890" not in message
    assert "[redacted]" in message


# --- SYNC-GAP-02: _dedupe_key fijado (caracterizacion). ---
# Relevancia: el dedupe_key incluye estado y monto, por lo que la unicidad de BD
# (uq_tch_transaccion_dedupe_key) NO impide dos filas para la misma
# (numero_ficha, periodo, numero_cuota). Estos tests fijan el formato actual;
# cambiar la construccion de la clave genera duplicados al reprocesar.

def test_dedupe_key_exact_format() -> None:
    assert etl_tch._dedupe_key(101, "2026-08", "3", "ACEPTADA", "12000") == "101|2026-08|3|ACEPTADA|12000"


def test_dedupe_key_same_cuota_different_estado_yields_different_keys() -> None:
    # Fija hoy: misma cuota rechazada y luego aceptada produce DOS claves (ambas filas se conservan).
    rejected = etl_tch._dedupe_key(101, "2026-08", "3", "RECHAZADA", "12000")
    accepted = etl_tch._dedupe_key(101, "2026-08", "3", "ACEPTADA", "12000")
    assert rejected == "101|2026-08|3|RECHAZADA|12000"
    assert rejected != accepted


def test_dedupe_key_same_cuota_different_monto_yields_different_keys() -> None:
    # Fija hoy: un cambio de monto en la misma cuota/estado no colapsa en una sola fila.
    assert etl_tch._dedupe_key(101, "2026-08", "3", "ACEPTADA", "12000") != etl_tch._dedupe_key(
        101, "2026-08", "3", "ACEPTADA", "15000"
    )


def test_dedupe_key_none_fields_become_empty_segments() -> None:
    assert etl_tch._dedupe_key(101, None, None, "ACEPTADA", None) == "101|||ACEPTADA|"
    assert etl_tch._dedupe_key(101, "", "", "ACEPTADA", "") == "101|||ACEPTADA|"


def test_dedupe_key_none_and_empty_are_equivalent_but_zero_is_not() -> None:
    # None y "" colapsan igual; "0" es un valor distinto (no se trata como vacio).
    assert etl_tch._dedupe_key(1, "2026-08", None, "ACEPTADA", None) == etl_tch._dedupe_key(
        1, "2026-08", "", "ACEPTADA", ""
    )
    assert etl_tch._dedupe_key(1, "2026-08", "0", "ACEPTADA", "0") == "1|2026-08|0|ACEPTADA|0"


def test_dedupe_key_only_normalizes_the_cuota() -> None:
    # Fija hoy: sin strip ni upper en periodo, estado y monto (se normalizan antes, en transform).
    # La cuota si se normaliza a entero (TCH-PAR-02). No incluye RUT: la identidad es solo numero_ficha.
    assert etl_tch._dedupe_key(101, " 2026-08", "3 ", "aceptada", " 12000") == "101| 2026-08|3|aceptada| 12000"
    assert etl_tch._dedupe_key(101, "2026-08", "3", "ACEPTADA", "12000") != etl_tch._dedupe_key(
        101, "2026-08", "3", "aceptada", "12000"
    )


def test_dedupe_key_is_str_ficha_not_zero_padded() -> None:
    assert etl_tch._dedupe_key(7, "2026-08", "1", "ACEPTADA", "1") == "7|2026-08|1|ACEPTADA|1"


def test_transform_transacciones_dedupe_key_matches_helper() -> None:
    frame = pd.DataFrame({
        "Numero Ficha": [101, 101],
        "Periodo": [1, 2],
        "N Cuota": ["3", "4"],
        "Cuota Mes": ["AGOSTO 2026", "JULIO 2026"],
        "Monto Cuota": ["$12.000", "$12.000"],
    })
    rows = etl_tch._transform_transacciones(frame, "ACEPTADA", "tch.xlsx")
    keys = [r["dedupe_key"] for r in rows]
    assert "101|2026-08|3|ACEPTADA|12000" in keys
    assert "101|2026-07|4|ACEPTADA|12000" in keys


def test_transform_same_cuota_accepted_and_rejected_keep_two_distinct_keys() -> None:
    frame = pd.DataFrame({
        "Numero Ficha": [101],
        "Periodo": [1],
        "N Cuota": ["3"],
        "Cuota Mes": ["AGOSTO 2026"],
        "Monto Cuota": ["$12.000"],
    })
    accepted = etl_tch._transform_transacciones(frame, "ACEPTADA", "a.xlsx")[0]["dedupe_key"]
    rejected = etl_tch._transform_transacciones(frame, "RECHAZADA", "r.xlsx")[0]["dedupe_key"]
    assert accepted != rejected  # gap: la misma cuota queda duplicada entre archivos aceptado/rechazado


# --- TCH-PAR-01: el periodo del cargo sale de "Cuota Mes", no de "Periodo" ni del nombre del archivo. ---
# Los datos son sinteticos: mismas columnas que la hoja CARGOS real, sin informacion personal.

def _cargos_frame(cuota_mes: list, periodo: list | None = None) -> pd.DataFrame:
    n = len(cuota_mes)
    return pd.DataFrame({
        "Numero Ficha": list(range(1, n + 1)),
        "Periodo": periodo if periodo is not None else list(range(1, n + 1)),
        "N Cuota": ["1"] * n,
        "Cuota Mes": cuota_mes,
        "Moneda": ["Pesos"] * n,
        "Monto Cuota": ["$10.000"] * n,
    })


def test_transform_transacciones_reads_cuota_mes_and_ignores_numeric_periodo() -> None:
    # "Periodo" es un correlativo 1..n (no un mes): con valores 1 y 2 antes caia al nombre del archivo.
    frame = _cargos_frame(["SEPT 26", "ABRIL 2026"], periodo=[1, 2])
    rows = etl_tch._transform_transacciones(frame, "ACEPTADA", "20260101 TCH IG DICIEMBRE 2025.xlsx")
    assert [r["periodo"] for r in rows] == ["2026-09", "2026-04"]


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("ENE 26", "2026-01"), ("FEB 26", "2026-02"), ("MAR 26", "2026-03"), ("ABR 26", "2026-04"),
        ("MAY 26", "2026-05"), ("JUN 26", "2026-06"), ("JUL 26", "2026-07"), ("AGO 26", "2026-08"),
        ("SEPT 26", "2026-09"), ("SEP 26", "2026-09"), ("SEPT. 26", "2026-09"), ("SEPT-26", "2026-09"),
        ("SEPTIEMBRE 2026", "2026-09"), ("Setiembre 2026", "2026-09"), ("sept 2026", "2026-09"),
        ("OCT 25", "2025-10"), ("NOV 25", "2025-11"), ("DIC 25", "2025-12"), ("DICIEMBRE 2017", "2017-12"),
        ("  Diciembre   2025 ", "2025-12"), ("SEPT26", "2026-09"),
    ],
)
def test_transform_transacciones_parses_spanish_month_variants_and_two_digit_years(texto: str, esperado: str) -> None:
    rows = etl_tch._transform_transacciones(_cargos_frame([texto]), "ACEPTADA", "x.xlsx")
    assert rows[0]["periodo"] == esperado


def test_transform_transacciones_accepts_real_dates_in_cuota_mes() -> None:
    rows = etl_tch._transform_transacciones(_cargos_frame([pd.Timestamp("2026-09-01")]), "ACEPTADA", "x.xlsx")
    assert rows[0]["periodo"] == "2026-09"


def test_transform_transacciones_skips_rows_without_a_readable_cuota_mes() -> None:
    frame = _cargos_frame(["SEPT 26", None, "sin mes"])
    rows = etl_tch._transform_transacciones(frame, "ACEPTADA", "20260101 x.xlsx")
    assert [r["numero_ficha"] for r in rows] == [1]  # nunca se inventa un periodo desde el nombre del archivo


def test_transform_transacciones_without_cuota_mes_column_returns_nothing() -> None:
    frame = _cargos_frame(["SEPT 26"]).drop(columns=["Cuota Mes"])
    assert etl_tch._transform_transacciones(frame, "ACEPTADA", "20260930 x.xlsx") == []


def _write_cargos_workbook(path, sheet: str, cuota_mes: list[str]) -> None:
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
    for i, mes in enumerate(cuota_mes, start=1):
        ws.append([910000 + i, 800000 + i, i, 1.0, mes, "Pesos", 10000])
    wb.save(path)


def test_closing_file_named_after_next_month_does_not_shift_the_period(db_session, tmp_path) -> None:
    # Cierre de diciembre 2025 cuyo nombre lleva la fecha del dia siguiente (20260101): los cargos son de 2025-12.
    xlsx = tmp_path / "20260101 TCH IG DICIEMBRE 2025.xlsx"
    _write_cargos_workbook(xlsx, etl_tch.SHEET_ACEPTADOS, ["DIC 25", "DICIEMBRE 2025"])

    frame = etl_tch._read_sheet(xlsx, etl_tch.SHEET_ACEPTADOS)
    assert frame is not None
    rows = etl_tch._transform_transacciones(frame, "ACEPTADA", xlsx.name)
    assert [r["periodo"] for r in rows] == ["2025-12", "2025-12"]

    etl_tch._process_file(xlsx, db_session, set())
    periods = set(db_session.scalars(select(TchTransaccion.periodo).where(TchTransaccion.archivo_origen == xlsx.name)))
    assert periods == {"2025-12"}


def test_monthly_file_without_date_in_name_still_gets_real_periods(db_session, tmp_path) -> None:
    # Los mensuales de 2025 se llaman "NN - TCH IG MES 2025" (sin fecha): antes quedaban con periodo NULL.
    xlsx = tmp_path / "03 - TCH IG MARZO 2025.xlsx"
    _write_cargos_workbook(xlsx, etl_tch.SHEET_ACEPTADOS, ["MAR 25"])
    etl_tch._process_file(xlsx, db_session, set())
    rows = db_session.scalars(select(TchTransaccion).where(TchTransaccion.archivo_origen == xlsx.name)).all()
    assert [r.periodo for r in rows] == ["2025-03"]
    assert rows[0].dedupe_key.startswith("910001|2025-03|")


# --- TCH-PAR-02: numero_cuota siempre entero y dedupe_key estable ---

@pytest.mark.parametrize("cuota", ["12", "12.0", 12.0, 12, " 12 ", "12,0", "012"])
def test_norm_cuota_always_returns_plain_integer_text(cuota) -> None:
    assert etl_tch._norm_cuota(cuota) == "12"


@pytest.mark.parametrize("vacio", [None, float("nan"), "", "   "])
def test_norm_cuota_returns_none_for_empty_values(vacio) -> None:
    assert etl_tch._norm_cuota(vacio) is None


def test_norm_cuota_keeps_zero_and_non_numeric_text() -> None:
    assert etl_tch._norm_cuota(0.0) == "0"
    assert etl_tch._norm_cuota("S/N") == "S/N"


def test_dedupe_key_is_identical_for_string_float_text_and_float_cuota() -> None:
    claves = {
        etl_tch._dedupe_key(101, "2026-08", cuota, "ACEPTADA", "12000")
        for cuota in ("12", "12.0", 12.0, 12)
    }
    assert claves == {"101|2026-08|12|ACEPTADA|12000"}


def test_transform_transacciones_cuota_and_dedupe_key_do_not_depend_on_dtype() -> None:
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
    resultados = [etl_tch._transform_transacciones(f, "ACEPTADA", "x.xlsx") for f in formas]
    for rows in resultados[:3]:
        assert [r["numero_cuota"] for r in rows] == ["12", "12"]
        assert [r["total_cuotas"] for r in rows] == ["24", "24"]
        assert [r["dedupe_key"] for r in rows] == ["101|2026-08|12|ACEPTADA|12000", "102|2026-08|12|ACEPTADA|12000"]
    assert resultados[3][0]["dedupe_key"] == resultados[0][0]["dedupe_key"]


def test_transform_historial_cargos_normalizes_cuota_like_cargos() -> None:
    # Hoja VIGENTES: ventana de 12 meses, bloques "N / Estado / Monto" desde la columna 62.
    columnas = [("Ficha DUES", "Ficha DUES")] + [(f"relleno{i}", "x") for i in range(61)]
    columnas += [("ENERO 2026", "N"), ("ENERO 2026", "Estado"), ("ENERO 2026", "Monto")]
    valores = [101] + [None] * 61
    filas = []
    for cuota in (12.0, "12.0", "12", 12):
        filas.append([*valores, cuota, "Pagada", 12000])
    frame = pd.DataFrame(filas, columns=pd.MultiIndex.from_tuples(columnas))
    rows = etl_tch._transform_historial_cargos(frame, "x.xlsx")
    assert {r["numero_cuota"] for r in rows} == {"12"}
    assert {r["dedupe_key"] for r in rows} == {"101|2026-01|12|ACEPTADA|12000"}


# --- TCH-PAR-05: monto y moneda de la suscripcion salen de "Monto Vigente" / "Moneda Vigente" ---

def _vigentes_frame(ingreso, monto, moneda) -> pd.DataFrame:
    columnas = [
        ("Ficha DUES", "Ficha DUES"),
        ("SOCIO", "Rut"),
        ("ANTECEDENTES Y ESTADO MANDATO", "Ingreso"),
        ("MANDATO ACTUAL", "Moneda Vigente"),
        ("MANDATO ACTUAL", "Monto Vigente"),
        ("MANDATO ACTUAL", "Equivalente en Pesos"),
    ]
    return pd.DataFrame([[101, "12345678-9", ingreso, moneda, monto, 12000]], columns=pd.MultiIndex.from_tuples(columnas))


def test_transform_suscripciones_monto_comes_from_monto_vigente_not_ingreso() -> None:
    # "Ingreso" es una fecha: antes alimentaba monto y dejaba NULL el 100 % de las suscripciones.
    frame = _vigentes_frame(pd.Timestamp("2024-03-15"), 12000, "Pesos")
    row = etl_tch._transform_suscripciones(frame, "VIGENTE")[0]
    assert row["monto"] == "12000"
    assert row["equivalente_pesos"] == "12000"


def test_transform_suscripciones_monto_is_none_when_monto_vigente_is_empty() -> None:
    frame = _vigentes_frame(pd.Timestamp("2024-03-15"), None, "Pesos")
    assert etl_tch._transform_suscripciones(frame, "VIGENTE")[0]["monto"] is None


@pytest.mark.parametrize(("moneda", "esperada"), [("Pesos", "CLP"), ("UF", "UF"), (" uf ", "UF"), (None, None)])
def test_transform_suscripciones_keeps_moneda_vigente_in_raw_payload(moneda, esperada) -> None:
    frame = _vigentes_frame(pd.Timestamp("2024-03-15"), 12000, moneda)
    row = etl_tch._transform_suscripciones(frame, "VIGENTE")[0]
    assert row["raw_payload"].get("moneda_vigente") == esperada
