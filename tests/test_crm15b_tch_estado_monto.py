"""CRM-15B: estado y monto de los mandatos TCH en el recuperador («Mandatos eliminados»).

* Una ficha con «Fecha Eliminado» no queda VIGENTE aunque la columna ESTADO diga «Activo» (IG dic-2017: 5 fichas de
  la hoja ELIMINADOS).
* «El reporte mas nuevo gana» tambien para la ficha: un reporte anterior cargado despues no revierte el estado, la
  fecha de eliminacion ni el monto que dejo uno posterior.
* El monto sale de «Monto Vigente» y llega al recuperador.

Excel sinteticos (sin datos personales): RUT 11.111.111-1 de prueba, fichas 95xxxx.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.core import CoreSubscription
from app.models.tch import TchSubscription
from app.services import core_tch_etl, recovery_tch
from scripts import etl_tch
from tests.tch_synthetic import write_report

FECHA_ELIMINADO = ("ANTECEDENTES Y ESTADO MANDATOS", "Fecha Eliminado")
F_ACTIVO_ELIMINADO, F_ORDEN, F_MONTO, F_LEGADO = 950001, 950002, 950003, 950004


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


def _ficha(file_number: int, estado: str, monto: int, fecha_eliminado: date | None = None) -> dict:
    return {"ficha": file_number, "estado": estado, "monto": monto, "extra": {FECHA_ELIMINADO: fecha_eliminado}}


def _sub(db, file_number: int) -> TchSubscription:
    return db.scalars(select(TchSubscription).where(TchSubscription.file_number == file_number)).one()


# --- Estado dentro de un reporte ---

def _frame(estado: str | None, fecha_eliminado) -> pd.DataFrame:
    columns = [("Ficha DUES", "Ficha DUES"), ("SOCIO", "Rut"), ("ANTECEDENTES Y ESTADO MANDATOS", "ESTADO"), FECHA_ELIMINADO]
    return pd.DataFrame([[101, "11111111-1", estado, fecha_eliminado]], columns=pd.MultiIndex.from_tuples(columns))


@pytest.mark.parametrize("hoja", ["ELIMINADA", "VIGENTE"])
@pytest.mark.parametrize("estado", ["Activo", "Pendiente", None])
def test_a_mandate_with_deletion_date_is_never_left_active(hoja: str, estado: str | None) -> None:
    row = etl_tch._transform_subscriptions(_frame(estado, pd.Timestamp("2017-11-20")), hoja)[0]
    assert (row["estado"], row["fecha_eliminacion"]) == ("ELIMINADA", "2017-11-20")


def test_deletion_date_does_not_hide_a_rejected_mandate() -> None:
    row = etl_tch._transform_subscriptions(_frame("Rechazado", pd.Timestamp("2017-11-20")), "ELIMINADA")[0]
    assert row["estado"] == "RECHAZADA"


def test_active_mandate_without_deletion_date_stays_active() -> None:
    assert etl_tch._transform_subscriptions(_frame("Activo", None), "VIGENTE")[0]["estado"] == "VIGENTE"


def test_eliminados_sheet_with_active_status_loads_as_deleted(db_session, tmp_path) -> None:
    xlsx = write_report(
        tmp_path / "20171229 TECHO INFORME GESTION DICIEMBRE 2017.xlsx",
        active=[], eliminados=[_ficha(F_ACTIVO_ELIMINADO, "Activo", 5000, date(2017, 11, 20))], extra_headers=[FECHA_ELIMINADO],
    )
    etl_tch._process_file(xlsx, db_session)
    sus = _sub(db_session, F_ACTIVO_ELIMINADO)
    assert (sus.status, sus.deletion_date, sus.amount) == ("ELIMINADA", "2017-11-20", "5000")


# --- Precedencia entre reportes de distintos meses ---

def _september(tmp_path):
    return write_report(
        tmp_path / "20260930 TCH IG SEPTIEMBRE 2026.xlsx",
        active=[_ficha(F_ORDEN, "Activo", 8000)], extra_headers=[FECHA_ELIMINADO],
    )


def _october(tmp_path):
    return write_report(
        tmp_path / "20261030 TCH IG GESTION OCTUBRE 2026.xlsx",
        active=[], eliminados=[_ficha(F_ORDEN, "Eliminado", 9000, date(2026, 10, 5))], extra_headers=[FECHA_ELIMINADO],
    )


def test_newer_report_wins_when_loaded_in_order(db_session, tmp_path) -> None:
    etl_tch._process_file(_september(tmp_path), db_session)
    assert _sub(db_session, F_ORDEN).status == "VIGENTE"
    etl_tch._process_file(_october(tmp_path), db_session)
    sus = _sub(db_session, F_ORDEN)
    assert (sus.status, sus.deletion_date, sus.amount) == ("ELIMINADA", "2026-10-05", "9000")
    assert sus.raw_payload[etl_tch.REPORT_PERIOD_KEY] == "2026-10"


def test_an_older_report_loaded_later_does_not_revert_the_mandate(db_session, tmp_path) -> None:
    etl_tch._process_file(_october(tmp_path), db_session)
    totals = etl_tch._process_file(_september(tmp_path), db_session)  # fuera de orden: septiembre llega despues
    sus = _sub(db_session, F_ORDEN)
    assert (sus.status, sus.deletion_date, sus.amount) == ("ELIMINADA", "2026-10-05", "9000")
    assert sus.raw_payload[etl_tch.REPORT_PERIOD_KEY] == "2026-10"
    assert (totals["sus_ins"], totals["sus_upd"]) == (0, 0)  # la ficha no se toco


def test_upload_with_temporary_name_uses_the_given_period(db_session, tmp_path) -> None:
    etl_tch._process_file(_october(tmp_path), db_session)
    temporary = _september(tmp_path).rename(tmp_path / "upload_tmp.xlsx")
    etl_tch._process_file(temporary, db_session, "2026-09")
    assert _sub(db_session, F_ORDEN).status == "ELIMINADA"


def test_rows_loaded_before_the_period_key_are_still_updated(db_session, tmp_path) -> None:
    # Filas de la carga de produccion (sin `_reporte_periodo`): la primera carga nueva las actualiza.
    etl_tch._load_subscriptions(db_session, [{"numero_ficha": F_LEGADO, "estado": "VIGENTE", "raw_payload": {}}])
    xlsx = write_report(
        tmp_path / "20261030 TCH IG GESTION OCTUBRE 2026.xlsx",
        active=[], eliminados=[_ficha(F_LEGADO, "Eliminado", 7000, date(2026, 10, 1))], extra_headers=[FECHA_ELIMINADO],
    )
    etl_tch._process_file(xlsx, db_session)
    sus = _sub(db_session, F_LEGADO)
    assert (sus.status, sus.amount) == ("ELIMINADA", "7000")


# --- Monto hasta el recuperador ---

def test_deleted_view_shows_status_and_amount_from_the_report(db_session, tmp_path) -> None:
    xlsx = write_report(
        tmp_path / "20261030 TCH IG GESTION OCTUBRE 2026.xlsx",
        active=[], eliminados=[_ficha(F_MONTO, "Activo", 12000, date(2026, 10, 7))], extra_headers=[FECHA_ELIMINADO],
    )
    etl_tch._process_file(xlsx, db_session)
    core_tch_etl._materialize_subscriptions(db_session)
    core = db_session.scalars(
        select(CoreSubscription).where(CoreSubscription.source == "tch", CoreSubscription.external_id == str(F_MONTO))
    ).one()
    assert (core.status, float(core.amount)) == ("ELIMINADA", 12000.0)

    page = recovery_tch.deleted(db_session, date(2026, 10, 7), date(2026, 10, 7), 0, 50)
    item = next(i for i in page["items"] if i["subscription_id"] == str(F_MONTO))
    assert (item["status"], item["amount"], item["cancelled_at"]) == ("ELIMINADA", 12000.0, "2026-10-07")
    assert not [i for i in page["items"] if i["status"] in ("VIGENTE", "PENDIENTE")]
