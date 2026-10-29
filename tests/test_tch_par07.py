"""TCH-PAR-07: recarga completa transaccional con conciliacion contra el control oficial. Excel sinteticos."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.tch import TchMonthlyCollection, TchSubscription, TchTransaction
from app.scheduler.run_lock import ActiveRunError
from scripts import etl_tch
from tests.tch_synthetic import write_report


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


def _tx(periodo: str, estado: str, n: int, base: int = 1) -> list[TchTransaction]:
    return [
        TchTransaction(file_number=base + i, period=periodo, installment_number="1", status=estado, dedupe_key=f"{base + i}|{periodo}|1")
        for i in range(n)
    ]


def _control(periodo: str, acep: int, rech: int) -> TchMonthlyCollection:
    return TchMonthlyCollection(
        period=periodo, accepted_count=acep, accepted_amount="0", rejected_count=rech, rejected_amount="0", source_file="x.xlsx"
    )


def _reporte(tmp_path, control_acep: int, control_rech: int):
    return write_report(
        tmp_path / "20260131 TCH IG ENERO 2026.xlsx",
        vigentes=[{"ficha": 930001, "historial": {(2026, 1): (1, "Pagada", 10000)}}],
        aceptados=[{"ficha": 930000 + i, "cuota": 1, "mes": "ENE 26", "fecha": date(2026, 1, 10)} for i in range(2, 5)],
        rechazados=[{"ficha": 930010, "cuota": 1, "mes": "ENE 26", "fecha": date(2026, 1, 11), "motivo": "Cuenta cerrada"}],
        control=[("ENERO 2026", control_acep, control_rech)],
    )


def _sembrar_base_previa(db) -> None:
    db.add(TchSubscription(file_number=999001, status="VIGENTE"))
    db.add(TchTransaction(file_number=999001, period="2025-01", status="ACEPTADA", dedupe_key="999001|2025-01|1|ACEPTADA|1"))
    db.commit()


def _totales(db) -> tuple[int, int]:
    return (
        db.scalar(select(func.count()).select_from(TchTransaction)) or 0,
        db.scalar(select(func.count()).select_from(TchSubscription)) or 0,
    )


# --- conciliacion ---

def test_reconcile_accepts_a_month_within_the_monthly_threshold(db_session) -> None:
    db_session.add_all([*_tx("2090-01", "ACEPTADA", 1004), *_tx("2090-01", "RECHAZADA", 200, base=5000), _control("2090-01", 1000, 200)])
    db_session.flush()
    result = etl_tch.reconcile(db_session, tolerance_month=0.005, tolerance_total=0.01, months=["2090-01"])
    assert result.ok and result.failed_months == []


def test_reconcile_flags_a_month_over_the_monthly_threshold(db_session) -> None:
    db_session.add_all([*_tx("2090-01", "ACEPTADA", 1006), _control("2090-01", 1000, 0)])
    db_session.flush()
    result = etl_tch.reconcile(db_session, tolerance_month=0.005, tolerance_total=0.01, months=["2090-01"])
    assert not result.ok
    assert result.failed_months == ["2090-01"]


def test_reconcile_total_threshold_is_independent_of_the_monthly_one(db_session) -> None:
    filas = []
    for indice, mes in enumerate(("2090-01", "2090-02", "2090-03")):
        filas += [*_tx(mes, "ACEPTADA", 1004, base=(indice + 1) * 100000), _control(mes, 1000, 0)]
    db_session.add_all(filas)
    db_session.flush()
    result = etl_tch.reconcile(db_session, tolerance_month=0.005, tolerance_total=0.001, months=["2090-01", "2090-02", "2090-03"])
    assert result.failed_months == []  # cada mes cuadra (0,4 %)
    assert result.total_ok is False  # pero el total se desvia 0,4 % > 0,1 %
    assert not result.ok


def test_reconcile_can_exclude_months_without_source_detail(db_session) -> None:
    db_session.add_all([*_tx("2090-01", "ACEPTADA", 10), _control("2090-01", 1000, 0)])
    db_session.flush()
    assert not etl_tch.reconcile(db_session, months=["2090-01"]).ok
    assert etl_tch.reconcile(db_session, months=["2090-01"], exclude_months={"2090-01"}).ok


def test_reconcile_report_prints_only_counts_and_differences(db_session) -> None:
    db_session.add_all([*_tx("2090-01", "ACEPTADA", 5), _control("2090-01", 6, 0)])
    db_session.flush()
    text = etl_tch.format_reconciliation(etl_tch.reconcile(db_session, months=["2090-01"]))
    assert "2090-01" in text and "FALLA" in text


# --- recarga transaccional ---

def test_reload_that_reconciles_is_committed(db_session, tmp_path) -> None:
    _sembrar_base_previa(db_session)
    outcome = etl_tch.reload_full(db_session, [_reporte(tmp_path, 4, 1)], apply=True)
    assert outcome.committed and outcome.reconciliation.ok
    filas = list(db_session.scalars(select(TchTransaction.file_number)))
    assert 999001 not in filas  # la base previa se reconstruyo
    assert len(filas) == 5  # 3 cargos aceptados + 1 rechazado + 1 estado mensual (historial) de la ficha 930001


def test_reload_that_does_not_reconcile_rolls_back_and_leaves_the_database_intact(db_session, tmp_path) -> None:
    _sembrar_base_previa(db_session)
    antes = _totales(db_session)
    outcome = etl_tch.reload_full(db_session, [_reporte(tmp_path, 99, 1)], apply=True)
    assert not outcome.committed and not outcome.reconciliation.ok
    assert outcome.reconciliation.failed_months == ["2026-01"]
    assert _totales(db_session) == antes
    assert db_session.scalar(select(TchTransaction.id).where(TchTransaction.file_number == 999001)) is not None


def test_dry_run_reports_counts_and_always_rolls_back(db_session, tmp_path) -> None:
    _sembrar_base_previa(db_session)
    antes = _totales(db_session)
    outcome = etl_tch.reload_full(db_session, [_reporte(tmp_path, 4, 1)], apply=False)
    assert outcome.reconciliation.ok and not outcome.committed
    assert _totales(db_session) == antes


# --- CLI ---

def test_apply_requires_the_exact_database_name(tmp_path) -> None:
    carpeta = tmp_path / "r"
    carpeta.mkdir()
    for argv in (
        ["--mode", "full", "--folder", str(carpeta), "--apply"],
        ["--mode", "full", "--folder", str(carpeta), "--apply", "--confirm-database", "otra_base"],
    ):
        with pytest.raises(SystemExit) as exc:
            etl_tch.main(argv)
        assert exc.value.code == 2


def test_full_reload_is_blocked_while_another_sync_runs(db_session, tmp_path, monkeypatch) -> None:
    _sembrar_base_previa(db_session)
    antes = _totales(db_session)
    _reporte(tmp_path, 4, 1)
    monkeypatch.setattr(etl_tch, "SessionLocal", lambda: db_session)

    def activa(*_a, **_k):
        raise ActiveRunError(None)

    monkeypatch.setattr(etl_tch, "start_exclusive_run", activa)
    with pytest.raises(SystemExit) as exc:
        etl_tch.main(["--mode", "full", "--folder", str(tmp_path)])
    assert exc.value.code == 2
    assert _totales(db_session) == antes
