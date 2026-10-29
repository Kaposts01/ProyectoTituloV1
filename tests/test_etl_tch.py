from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.tch import TchSuscripcion, TchTransaccion
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


# --- TCH-PAR-06: estado de la ficha desde la columna ESTADO + baja implicita ---

def _mandatos_frame(filas: list[tuple[int, str | None]]) -> pd.DataFrame:
    columnas = [
        ("Ficha DUES", "Ficha DUES"),
        ("SOCIO", "Rut"),
        ("ANTECEDENTES Y ESTADO MANDATO", "ESTADO"),
        ("ULTIMOS MESES", "Estado"),  # los bloques mensuales traen otra columna "Estado": no debe usarse
    ]
    datos = [[ficha, f"1{ficha % 10}000000-0", estado, "Pagada"] for ficha, estado in filas]
    return pd.DataFrame(datos, columns=pd.MultiIndex.from_tuples(columnas))


@pytest.mark.parametrize(
    ("columna", "esperado"),
    [
        ("Activo", "VIGENTE"), ("ACTIVO", "VIGENTE"), ("Pendiente", "PENDIENTE"), (" pendiente ", "PENDIENTE"),
        ("Rechazado", "RECHAZADA"), ("Eliminado", "ELIMINADA"), ("ELIMINADA", "ELIMINADA"),
    ],
)
def test_transform_suscripciones_uses_the_estado_column_over_the_sheet(columna: str, esperado: str) -> None:
    # La hoja VIGENTES trae tambien Pendiente, Rechazado y Eliminado: manda la columna ESTADO.
    rows = etl_tch._transform_suscripciones(_mandatos_frame([(101, columna)]), "VIGENTE")
    assert rows[0]["estado"] == esperado


@pytest.mark.parametrize("columna", [None, "", "Desconocido"])
def test_transform_suscripciones_falls_back_to_the_sheet_when_estado_is_missing(columna) -> None:
    rows = etl_tch._transform_suscripciones(_mandatos_frame([(101, columna)]), "ELIMINADA")
    assert rows[0]["estado"] == "ELIMINADA"


def test_transform_suscripciones_without_estado_column_uses_the_sheet() -> None:
    frame = pd.DataFrame({"Ficha DUES": [101], "SOCIO Rut": ["12345678-9"]})
    assert etl_tch._transform_suscripciones(frame, "RECHAZADA")[0]["estado"] == "RECHAZADA"


def _cargar_fichas(db, estados: dict[int, str]) -> None:
    etl_tch._load_suscripciones(
        db,
        [
            {"numero_ficha": ficha, "estado": estado, "raw_payload": {}, "_cliente": None, "_cliente_titular": None}
            for ficha, estado in estados.items()
        ],
    )


def _estado(db, ficha: int) -> tuple[str, str | None]:
    row = db.execute(
        select(TchSuscripcion.estado, TchSuscripcion.razon_baja).where(TchSuscripcion.numero_ficha == ficha)
    ).one()
    return row.estado, row.razon_baja


def test_implicit_baja_keeps_vigente_and_pendiente_and_closes_the_absent(db_session) -> None:
    # 3 casos: ficha vigente y ficha pendiente en el ultimo reporte; ficha vigente por un cierre viejo y ausente hoy.
    _cargar_fichas(db_session, {930001: "VIGENTE", 930002: "PENDIENTE", 930003: "VIGENTE", 930004: "ELIMINADA"})

    cambiadas = etl_tch._apply_implicit_bajas(db_session, {930001, 930002, 930004})

    assert cambiadas == 1
    assert _estado(db_session, 930001)[0] == "VIGENTE"
    assert _estado(db_session, 930002)[0] == "PENDIENTE"
    estado, razon = _estado(db_session, 930003)
    assert estado == "ELIMINADA"
    assert razon and "ausente" in razon.lower()
    assert _estado(db_session, 930004)[0] == "ELIMINADA"


def test_implicit_baja_keeps_an_existing_razon_baja(db_session) -> None:
    _cargar_fichas(db_session, {930010: "VIGENTE"})
    db_session.execute(
        TchSuscripcion.__table__.update().where(TchSuscripcion.numero_ficha == 930010).values(razon_baja="motivo previo")
    )
    etl_tch._apply_implicit_bajas(db_session, {1})
    assert _estado(db_session, 930010) == ("ELIMINADA", "motivo previo")


def test_implicit_baja_never_runs_with_an_empty_last_report(db_session) -> None:
    # Si el ultimo reporte no trajo cartera (p. ej. la hoja VIGENTES de dic-2023), no se da de baja a nadie.
    _cargar_fichas(db_session, {930020: "VIGENTE"})
    assert etl_tch._apply_implicit_bajas(db_session, set()) == 0
    assert _estado(db_session, 930020)[0] == "VIGENTE"


@pytest.mark.parametrize(
    ("previo", "reporte", "esperado"),
    [
        (None, "2026-09", True), ("2026-08", "2026-09", True), ("2026-09", "2026-09", True),
        ("2026-09", "2026-03", False),  # un reporte viejo no puede dar de baja lo cargado despues
        ("2026-09", None, False),
    ],
)
def test_implicit_baja_only_applies_to_the_latest_report(previo, reporte, esperado) -> None:
    assert etl_tch._is_latest_report(previo, reporte) is esperado


def test_process_file_without_a_readable_vigentes_sheet_reports_no_fichas(db_session, tmp_path) -> None:
    # Solo hoja de cargos: no hay cartera, por lo que no se pueden inferir bajas implicitas.
    xlsx = tmp_path / "20260331 TCH IG MARZO 2026.xlsx"
    _write_cargos_workbook(xlsx, etl_tch.SHEET_ACEPTADOS, ["MAR 26"])
    assert etl_tch._process_file(xlsx, db_session, set())["fichas"] == set()


# --- TCH-PAR-15: sin periodos futuros en el control mensual y sin reportes duplicados (sha256) ---

def _write_control_workbook(path, periodos: list[tuple[str, int, int]]) -> None:
    """Hojas HISTORICO RECAUDACION CAN / FLUJO sinteticas: (periodo, aceptadas, rechazadas) por columna."""
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for hoja, factor in ((etl_tch.SHEET_HISTORICO_RECAUDACION_CAN, 1), (etl_tch.SHEET_HISTORICO_RECAUDACION_FLUJO, 1000)):
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
    rows = etl_tch._transform_recaudacion_mensual(xlsx)
    assert [r["periodo"] for r in rows] == ["2026-07", "2026-08"]


def test_recaudacion_cutoff_uses_the_closed_month_not_the_filename_date(tmp_path) -> None:
    # Cierre de diciembre 2025 con fecha de archivo 2026-01-01: enero 2026 aun no esta cerrado.
    xlsx = tmp_path / "20260101 TCH IG DICIEMBRE 2025.xlsx"
    _write_control_workbook(xlsx, [("NOVIEMBRE 2025", 10, 2), ("DICIEMBRE 2025", 12, 4), ("ENERO 2026", 0, 0)])
    assert [r["periodo"] for r in etl_tch._transform_recaudacion_mensual(xlsx)] == ["2025-11", "2025-12"]


def test_recaudacion_cutoff_without_month_in_name_uses_last_month_with_charges(tmp_path) -> None:
    xlsx = tmp_path / "reporte.xlsx"
    _write_control_workbook(xlsx, [("MAYO 2026", 0, 0), ("JUNIO 2026", 5, 1), ("JULIO 2026", 6, 1), ("AGOSTO 2026", 0, 0)])
    # Un mes en cero dentro del rango cerrado se conserva; solo se cortan los futuros.
    assert [r["periodo"] for r in etl_tch._transform_recaudacion_mensual(xlsx)] == ["2026-05", "2026-06", "2026-07"]


def test_purge_future_recaudacion_removes_only_trailing_zero_months(db_session) -> None:
    from app.models.tch import TchRecaudacionMensual

    def fila(periodo: str, cantidad: int) -> TchRecaudacionMensual:
        return TchRecaudacionMensual(
            periodo=periodo, aceptadas_cantidad=cantidad, aceptadas_monto="0",
            rechazadas_cantidad=0, rechazadas_monto="0", archivo_origen="x.xlsx",
        )

    db_session.add_all([fila("2090-02", 0), fila("2090-06", 7), fila("2090-07", 0), fila("2091-01", 0)])
    db_session.flush()

    assert etl_tch._purge_future_recaudacion(db_session) == 2
    quedan = set(db_session.scalars(select(TchRecaudacionMensual.periodo).where(TchRecaudacionMensual.periodo >= "2090")))
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
    dos = tmp_path / "20260101 TCH IG DICIEMBRE 2025.XLSX"
    otro = tmp_path / "20260131 TCH IG ENERO 2026.XLSX"
    uno.write_bytes(b"A")
    dos.write_bytes(b"A")
    otro.write_bytes(b"B")
    unicos, omitidos = etl_tch._unique_reports_by_sha256([uno, dos, otro])
    assert unicos == [uno, otro]
    assert omitidos == [dos]
