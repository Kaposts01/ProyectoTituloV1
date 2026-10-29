"""TCH-PAR-09: campos del reporte que se cargan a tch_suscripciones / tch_clientes. Datos sinteticos."""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.tch import TchClient, TchSubscription
from scripts import etl_tch
from tests.tch_synthetic import write_report

H = {
    "estrategia": ("Estrategia", "Estrategia"),
    "lugar": ("Lugar Captacion", "Lugar Captacion"),
    "folio": ("Folio", "Folio"),
    "ref": ("SOCIO", "Referencia"),
    "pers": ("DATOS TITULAR DE CUENTA", "Personalidad"),
    "t_rut": ("DATOS TITULAR DE CUENTA", "Rut"),
    "t_nombre": ("DATOS TITULAR DE CUENTA", "Nombre"),
    "region": ("TELEFONOS Y DIRECCION", "Region"),
    "pc_fecha": ("MANDATO ACTUAL", "Fecha Primer Cobro"),
    "pc_monto": ("MANDATO ACTUAL", "Monto Primer Cobro"),
    "cobradas": ("MANDATO ACTUAL", "Cuotas cobradas"),
    "m_cobrado": ("MANDATO ACTUAL", "Monto cobrado"),
    "ap_cuotas": ("APORTES ACUMULADOS", "Cuotas"),
    "ap_monto": ("APORTES ACUMULADOS", "Monto"),
    "promedio": ("APORTES ACUMULADOS", "Promedio Donacion"),
    "sin_aporte": ("APORTES ACUMULADOS", "Meses continuos sin aporte"),
    "p_meses": ("PERMANENCIA", "Meses"),
    "p_anos": ("PERMANENCIA", "Años"),
    "nvo": ("NVO", "NVO"),
    "rech": ("RECH MES", "RECH MES"),
    "eli": ("ELI MES", "ELI MES"),
}


def _frame(**values) -> pd.DataFrame:
    base = {
        ("Ficha DUES", "Ficha DUES"): [101],
        ("SOCIO", "Rut"): ["12345678-9"],
        ("MANDATO ACTUAL", "Monto Vigente"): [10000],
        ("SOCIO", "Nombre"): ["Socio Sintetico"],
    }
    for key, value in values.items():
        base[H[key]] = [value]
    return pd.DataFrame(base)


def _row(**values) -> dict:
    return etl_tch._transform_subscriptions(_frame(**values), "VIGENTE")[0]


def test_captation_and_identification_fields_are_loaded() -> None:
    row = _row(estrategia="Calle", lugar="Mall Centro", folio="F-77", ref="Sra", region="Metropolitana")
    assert (row["estrategia"], row["lugar_captacion"], row["folio"], row["referencia"]) == ("Calle", "Mall Centro", "F-77", "Sra")
    assert row["_cliente"]["region"] == "Metropolitana"


@pytest.mark.parametrize(("valor", "expected"), [("Natural", "Natural"), ("JURIDICA", "Juridica"), ("Jurídica", "Juridica")])
def test_personalidad_is_real_not_always_natural(valor: str, expected: str) -> None:
    row = _row(pers=valor)
    assert row["personalidad"] == expected
    assert row["_cliente"]["tipo_persona"] == expected


def test_personalidad_defaults_to_natural_when_the_column_is_missing() -> None:
    assert _row()["_cliente"]["tipo_persona"] == "Natural"


def test_titular_is_only_a_boolean_indicator_and_is_never_stored() -> None:
    different = _row(t_rut="98765432-1", t_nombre="Otra Persona")
    same = _row(t_rut="12345678-9", t_nombre="Mismo")
    assert different["titular_distinto"] is True and same["titular_distinto"] is False
    assert different["_cliente_titular"] is None  # ya no se crea un cliente con los datos del tercero
    guardado = str(different["raw_payload"]) + str(different["_cliente"])
    assert "98765432" not in guardado and "Otra Persona" not in guardado
    assert _row()["titular_distinto"] is None  # sin columna de titular no se sabe


def test_first_charge_contributions_permanence_and_flags_are_loaded() -> None:
    row = _row(
        pc_fecha=pd.Timestamp("2024-05-03"), pc_monto="$10.000", cobradas=0, m_cobrado=0, ap_cuotas=12, ap_monto="120000",
        promedio=10000.0, sin_aporte=2, p_meses=14, p_anos=1, nvo=1, rech="SI", eli=0,
    )
    assert row["fecha_primer_cobro"] == "2024-05-03" and row["monto_primer_cobro"] == "10000"
    assert row["cuotas_cobradas"] == 0 and row["monto_cobrado"] == "0"  # el cero es un valor, no un vacio
    assert (row["aportes_cuotas"], row["aportes_monto"], row["promedio_donacion"], row["meses_sin_aporte"]) == (12, "120000", "10000", 2)
    assert (row["permanencia_meses"], row["permanencia_anos"]) == (14, 1)
    assert (row["nvo_mes"], row["rech_mes"], row["eli_mes"]) == (True, True, False)


def test_empty_optional_columns_become_none() -> None:
    row = _row(ap_cuotas=None, nvo=None, p_meses=None)
    assert row["aportes_cuotas"] is None and row["nvo_mes"] is None and row["permanencia_meses"] is None


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


def test_fields_reach_the_database_from_a_synthetic_report(db_session, tmp_path) -> None:
    headers = [H["estrategia"], H["pers"], H["t_rut"], H["region"], H["ap_cuotas"], H["nvo"]]
    xlsx = write_report(
        tmp_path / "20260131 TCH IG ENERO 2026.xlsx",
        active=[{
            "ficha": 940001, "rut": "12345678-9",
            "extra": {H["estrategia"]: "Calle", H["pers"]: "Juridica", H["t_rut"]: "98765432-1", H["region"]: "Valparaiso", H["ap_cuotas"]: 7, H["nvo"]: 1},
        }],
        extra_headers=headers,
    )
    etl_tch._process_file(xlsx, db_session)
    sus = db_session.scalars(select(TchSubscription).where(TchSubscription.file_number == 940001)).one()
    assert (sus.strategy, sus.personality, sus.different_holder, sus.contribution_installments, sus.new_in_month) == ("Calle", "Juridica", True, 7, True)
    cliente = db_session.scalars(select(TchClient).where(TchClient.rut == "12.345.678-9")).one()
    assert (cliente.person_type, cliente.region) == ("Juridica", "Valparaiso")
    assert db_session.scalar(select(TchClient.id).where(TchClient.rut == "98.765.432-1")) is None
