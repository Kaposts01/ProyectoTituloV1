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
        "Periodo": ["AGOSTO 2026"],
        "N Cuota": ["3"],
        "Monto Cuota": ["$12.000"],
        "Numero Cuenta": ["1234567890"],
    })

    rows = etl_tch._transform_transacciones(frame, "ACEPTADA", "tch.xlsx", None)

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


def test_dedupe_key_does_not_normalize_inputs() -> None:
    # Fija hoy: sin strip ni upper; la normalizacion ocurre antes (transform), no en la clave.
    # No incluye RUT: la identidad es solo numero_ficha.
    assert etl_tch._dedupe_key(101, " 2026-08", "3 ", "aceptada", " 12000") == "101| 2026-08|3 |aceptada| 12000"
    assert etl_tch._dedupe_key(101, "2026-08", "3", "ACEPTADA", "12000") != etl_tch._dedupe_key(
        101, "2026-08", "3", "aceptada", "12000"
    )


def test_dedupe_key_is_str_ficha_not_zero_padded() -> None:
    assert etl_tch._dedupe_key(7, "2026-08", "1", "ACEPTADA", "1") == "7|2026-08|1|ACEPTADA|1"


def test_transform_transacciones_dedupe_key_matches_helper_and_uses_period_fallback() -> None:
    frame = pd.DataFrame({
        "Numero Ficha": [101, 101],
        "Periodo": ["AGOSTO 2026", None],
        "N Cuota": ["3", "4"],
        "Monto Cuota": ["$12.000", "$12.000"],
    })
    rows = etl_tch._transform_transacciones(frame, "ACEPTADA", "tch.xlsx", "2026-07")
    keys = [r["dedupe_key"] for r in rows]
    assert "101|2026-08|3|ACEPTADA|12000" in keys
    assert "101|2026-07|4|ACEPTADA|12000" in keys


def test_transform_same_cuota_accepted_and_rejected_keep_two_distinct_keys() -> None:
    frame = pd.DataFrame({
        "Numero Ficha": [101],
        "Periodo": ["AGOSTO 2026"],
        "N Cuota": ["3"],
        "Monto Cuota": ["$12.000"],
    })
    accepted = etl_tch._transform_transacciones(frame, "ACEPTADA", "a.xlsx", None)[0]["dedupe_key"]
    rejected = etl_tch._transform_transacciones(frame, "RECHAZADA", "r.xlsx", None)[0]["dedupe_key"]
    assert accepted != rejected  # gap: la misma cuota queda duplicada entre archivos aceptado/rechazado
