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
