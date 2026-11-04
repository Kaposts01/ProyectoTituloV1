"""TCH-PAR-19: pruebas de paridad con Excel SINTETICO en las 3 variantes de layout (A, B-2022, sin VIGENTES-2023).

Cubre nombres de archivo sin fecha, cuota entera/flotante, reintento (rechazo previo), idempotencia de la recarga y
la cadena de punta a punta Excel -> ETL -> Core -> consolidacion -> dashboard (VAL-TCH-01). Sin datos personales.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.routes import tch
from app.db.session import engine
from app.models.core import CoreCharge, CorePayment
from app.models.crm import Charge
from app.models.tch import (
    TchClient,
    TchMonthlyCollection,
    TchSubscription,
    TchTransaction,
)
from app.services import channel_consolidation
from app.services.core_tch_etl import run_tch_core_etl
from scripts import etl_tch
from tests.tch_layouts import (
    SOCIO_A,
    SOCIO_B,
    layout_a,
    layout_b_2022,
    layout_without_portfolio_2023,
)

FICHAS = (961001, 961002, 961003, 961004)


@pytest.fixture
def db_session(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    class _NoClose:
        def __getattr__(self, name):
            return getattr(session, name)

        def close(self) -> None:
            return None

    monkeypatch.setattr(tch, "_get_db", lambda: _NoClose())
    try:
        yield session
        session.close()
    finally:
        transaction.rollback()
        connection.close()


def _tx(db) -> dict[str, TchTransaction]:
    return {t.dedupe_key: t for t in db.scalars(select(TchTransaction).where(TchTransaction.file_number.in_(FICHAS)))}


def _subs(db) -> dict[int, TchSubscription]:
    return {s.file_number: s for s in db.scalars(select(TchSubscription).where(TchSubscription.file_number.in_(FICHAS)))}


@pytest.mark.parametrize(("build", "year"), [(layout_a, 2024), (layout_b_2022, 2022)])
def test_portfolio_layouts_load_identity_history_and_charges(db_session, tmp_path, build, year) -> None:
    totals = etl_tch._process_file(build(tmp_path), db_session)

    subs = _subs(db_session)
    assert set(subs) == set(FICHAS)
    assert subs[961001].client_rut == "11.111.111-1"  # layout B: antes el RUT no se encontraba (encabezado desplazado)
    assert subs[961002].first_charge_date == f"{year}-12-05"
    assert (subs[961003].status, subs[961004].status) == ("ELIMINADA", "RECHAZADA")
    assert set(totals["fichas"]) == set(FICHAS)

    tx = _tx(db_session)
    assert set(tx) == {f"961001|{year}-11|5", f"961001|{year}-12|6", f"961002|{year}-12|1", f"961003|{year}-11|2"}
    retry = tx[f"961001|{year}-12|6"]  # historial 6.0 "Impaga" + cargo rechazado + reintento aceptado = una fila
    assert (retry.status, retry.transaction_type, retry.previous_rejection) == ("ACEPTADA", "Reintento", True)
    assert retry.previous_rejection_reason == "Fondos insuficientes"
    assert tx[f"961002|{year}-12|1"].origin == "cargo"  # cuota 1.0 del cargo y 1 del historial: misma clave

    assert etl_tch.reconcile(db_session, months=[f"{year}-11", f"{year}-12"]).ok


def test_layout_b_header_is_detected_one_row_lower(tmp_path) -> None:
    with etl_tch.ReportBook(layout_b_2022(tmp_path)) as book:
        assert etl_tch._detect_header_rows(book.cells("VIGENTES")) == [6, 7]
        assert etl_tch._detect_header_rows(book.cells("CARGOS ACEPTADOS")) == [5, 6]
    with etl_tch.ReportBook(layout_a(tmp_path)) as book:
        assert etl_tch._detect_header_rows(book.cells("VIGENTES")) == [5, 6]


def test_report_without_portfolio_loads_the_rest_and_does_not_cancel_anyone(db_session, tmp_path) -> None:
    db_session.add(TchSubscription(file_number=961099, status="VIGENTE"))  # ficha previa: no debe darse de baja
    db_session.flush()

    totals = etl_tch._process_file(layout_without_portfolio_2023(tmp_path), db_session)

    assert totals["fichas"] == set()  # sin cartera no se infieren bajas
    assert etl_tch._apply_implicit_cancellations(db_session, totals["fichas"]) == 0
    subs = _subs(db_session)
    assert set(subs) == {961003, 961004}  # ELIMINADOS y RECHAZADOS si se cargan
    tx = _tx(db_session)
    assert {"961001|2023-12|6", "961002|2023-12|1", "961003|2023-11|2"} == set(tx)
    # Sin la cartera falta el estado mensual de los vigentes: noviembre queda bajo el control (limite de la fuente).
    result = etl_tch.reconcile(db_session, months=["2023-11", "2023-12"])
    assert result.failed_months == ["2023-11"]


@pytest.mark.parametrize(
    ("name", "period"),
    [
        ("12 - TCH IG DICIEMBRE 2024.xlsx", "2024-12"),  # sin fecha numerica
        ("20230102 TCH IG DICIEMBRE 2022.xlsx", "2022-12"),  # fecha del dia siguiente al cierre
        ("03 - TCH IG MARZO 2025.xlsx", "2025-03"),
    ],
)
def test_report_period_comes_from_the_month_name(tmp_path, name, period) -> None:
    assert etl_tch._report_period(tmp_path / name) == period


def _snapshot(db) -> tuple:
    tx = sorted(
        (t.dedupe_key, t.status, t.amount, t.charge_date, t.origin, t.previous_rejection, t.previous_rejection_reason)
        for t in db.scalars(select(TchTransaction))
    )
    subs = sorted((s.file_number, s.client_rut, s.status, s.amount, s.activation_date) for s in db.scalars(select(TchSubscription)))
    clients = sorted(db.scalars(select(TchClient.rut)))
    controls = sorted((c.period, c.accepted_count, c.rejected_count) for c in db.scalars(select(TchMonthlyCollection)))
    return tx, subs, clients, controls


def _three_layouts(tmp_path):
    for build in (layout_b_2022, layout_without_portfolio_2023, layout_a):
        build(tmp_path)
    return etl_tch._list_reports(tmp_path)


def test_full_reload_of_the_three_layouts_is_idempotent(db_session, tmp_path) -> None:
    files = _three_layouts(tmp_path)
    assert [etl_tch._report_period(f) for f in files] == ["2022-12", "2023-12", "2024-12"]
    excluded = {"2023-11"}  # el hueco de la cartera 2023 (ver test anterior)

    first = etl_tch.reload_full(db_session, files, apply=True, exclude_months=excluded)
    snapshot = _snapshot(db_session)
    second = etl_tch.reload_full(db_session, files, apply=True, exclude_months=excluded)

    assert first.committed and second.committed
    assert _snapshot(db_session) == snapshot
    assert first.total == second.total


def test_end_to_end_excel_to_dashboard_val_tch_01(db_session, tmp_path) -> None:
    files = _three_layouts(tmp_path)
    assert etl_tch.reload_full(db_session, files, apply=True, exclude_months={"2023-11"}).committed

    core = run_tch_core_etl(db_session)
    for step in (
        channel_consolidation._consolidate_tch_clients,
        channel_consolidation._consolidate_tch_subscriptions,
        channel_consolidation._consolidate_tch_transactions,
    ):
        step(db_session)

    n_tx = db_session.scalar(select(func.count()).select_from(TchTransaction)) or 0
    core_charges = db_session.scalar(select(func.count()).select_from(CoreCharge).where(CoreCharge.source == "tch"))
    core_payments = db_session.scalar(select(func.count()).select_from(CorePayment).where(CorePayment.source == "tch"))
    assert n_tx == core_charges == core_payments == core["charges_inserted"]
    linked = db_session.scalar(
        select(func.count()).select_from(Charge).where(
            Charge.source == "tch", Charge.client_external_id.isnot(None), Charge.source_record_id.isnot(None)
        )
    )
    assert linked == n_tx

    summary = tch.tch_summary()
    assert summary["transacciones_fuente"] == "recaudacion_mensual"
    controls = db_session.scalars(select(TchMonthlyCollection)).all()
    assert summary["transacciones"]["aceptadas"] == sum(c.accepted_count for c in controls)
    assert summary["suscripciones"]["vigentes"] == 2
    assert summary["kpis"]["active_clients"] == len({SOCIO_A, SOCIO_B})
    assert summary["activaciones_fuente"]["fecha_primer_cobro"] == 1  # alta sin fecha de activacion (TCH-PAR-17)
