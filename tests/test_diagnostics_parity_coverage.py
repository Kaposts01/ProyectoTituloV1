"""L1-SYNC: guarda `_test`/`--read-only` de los diagnosticos, paridad Toku (TK-PAR-10), paridad VirtualPOS PAT vs base
(VP-PAR-11, script y job) y completitud por mes y canal (SYNC-D-12 / SYNC-O-14).

Todo con datos sinteticos dentro de una transaccion que se revierte; nada sale de la base de test.
"""

import asyncio
import hashlib
import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.models.crm import Charge
from app.models.etl_run import EtlRun
from app.models.tch import TchMonthlyCollection, TchTransaction
from app.models.toku_channel import TokuTransaction
from app.models.toku_report import TkReportAttempt, TkReportFile
from app.models.vp import VpCharge
from app.models.vp_report import VpReportFile, VpReportPayment
from app.scheduler.jobs import vp_parity_job
from app.services import rejected_month, vp_parity
from scripts.diagnostics import (
    coverage_report,
    parity_check,
    readonly_guard,
    vp_parity_check,
)

GEN = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def chile_today(monkeypatch):
    monkeypatch.setattr(rejected_month, "now_chile", lambda: datetime(2026, 10, 29, 12, tzinfo=rejected_month.CHILE_TZ))


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    # Tablas comparadas en blanco dentro de la transaccion (se revierte al final): resultados exactos.
    for model in (VpReportPayment, VpCharge, TkReportAttempt, TokuTransaction):
        session.execute(delete(model))
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _sha(tag: str) -> str:
    return hashlib.sha256(f"{tag}-{uuid.uuid4()}".encode()).hexdigest()


# --- Guarda: base _test o --read-only explicito -----------------------------------------------------------------


def test_guard_accepts_a_test_database() -> None:
    assert readonly_guard.enforce_database_guard(False, "crm_l1sync_test") == "crm_l1sync_test"


@pytest.mark.parametrize("name", ["crm", "crm_sandbox", "crm_test_copy", ""])
def test_guard_aborts_outside_test_without_read_only(name, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        readonly_guard.enforce_database_guard(False, name)
    assert exc.value.code == 2
    assert "--read-only" in capsys.readouterr().err


def test_guard_allows_another_database_only_with_explicit_read_only() -> None:
    assert readonly_guard.enforce_database_guard(True, "crm") == "crm"


@pytest.mark.parametrize(
    ("module", "opener"),
    [(parity_check, "parity_check"), (vp_parity_check, "guard"), (coverage_report, "guard")],
)
def test_clis_abort_on_a_non_test_database_before_opening_a_session(module, opener, monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://u@localhost:5433/crm")

    def _forbidden():
        pytest.fail("no debe abrir sesion contra una base que no es _test")

    monkeypatch.setattr(parity_check, "open_readonly_session", _forbidden)
    monkeypatch.setattr(readonly_guard, "open_readonly_session", _forbidden)
    with pytest.raises(SystemExit) as exc:
        module.main([])
    assert exc.value.code == 2


def test_clis_run_on_a_non_test_database_with_read_only(db_session, monkeypatch, capsys) -> None:
    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://u@localhost:5433/crm")
    monkeypatch.setattr(parity_check, "open_readonly_session", lambda: db_session)
    monkeypatch.setattr(readonly_guard, "open_readonly_session", lambda: db_session)
    assert parity_check.main(["--channel", "payku", "--read-only"]) == 0
    assert vp_parity_check.main(["--read-only"]) == 0  # sin reportes: nada que comparar
    assert coverage_report.main(["--channel", "payku", "--read-only"]) == 0
    assert "Base: crm" in capsys.readouterr().err


def test_read_only_session_only_lets_select_through() -> None:
    db = readonly_guard.open_readonly_session()
    try:
        assert db.execute(text("SELECT 1")).scalar() == 1
        assert db.execute(text("WITH x AS (SELECT 2 AS v) SELECT v FROM x")).scalar() == 2
        for statement in ("UPDATE etl_runs SET status = 'x'", "DELETE FROM etl_runs", "CREATE TABLE t_l1sync (x int)",
                          "SET TRANSACTION READ WRITE"):
            with pytest.raises(readonly_guard.ReadOnlyViolation):
                db.execute(text(statement))
    finally:
        db.rollback()
        db.close()


# --- TK-PAR-10: paridad Toku reporte vs base --------------------------------------------------------------------


def _tk_file(db) -> TkReportFile:
    f = TkReportFile(report_type="intentos", file_sha256=_sha("tk"), filename="intentos.xlsx", status="completed")
    db.add(f)
    db.flush()
    return f


def _attempt(f, status, attempted_at) -> TkReportAttempt:
    return TkReportAttempt(attempt_external_id=f"at-{uuid.uuid4().hex[:10]}", debt_external_id="in_x", customer_external_id="cus_x",
                           attempted_at=attempted_at, status=status, source_generated_at=GEN, last_file_id=f.id)


def _tk_tx(status, created) -> TokuTransaction:
    return TokuTransaction(external_id=f"tx-{uuid.uuid4().hex[:10]}", status=status, created_at_api=created)


def test_toku_parity_buckets_by_chile_month_and_maps_statuses(db_session) -> None:
    f = _tk_file(db_session)
    db_session.add_all([
        # 2026-06-01 02:00 UTC = 2026-05-31 22:00 en Chile: cae en mayo a ambos lados.
        _attempt(f, "AUTORIZADO", datetime(2026, 6, 1, 2, tzinfo=timezone.utc)),
        _attempt(f, "FALLIDO", datetime(2026, 6, 10, 12, tzinfo=timezone.utc)),
        _attempt(f, "EN PROCESO", datetime(2026, 6, 11, 12, tzinfo=timezone.utc)),  # la API lo muestra FAILED
        _attempt(f, "FALLIDO", datetime(2026, 10, 19, 12, tzinfo=timezone.utc)),  # ultimo intento del reporte = corte
        _tk_tx("SUCCESS", "2026-06-01T02:00:00Z"),
        _tk_tx("FAILED", "2026-06-10T12:00:00Z"),
        _tk_tx("FAILED", "2026-06-11T12:00:00Z"),
        _tk_tx("FAILED", "2026-06-12T12:00:00Z"),  # uno mas que el reporte
        _tk_tx("FAILED", "2026-10-19T12:00:00Z"),
        _tk_tx("FAILED", "2026-10-27T12:00:00Z"),  # posterior al corte del reporte: no se compara
    ])
    db_session.flush()
    rows = {(r["month"], r["status"]): r for r in parity_check.toku_report_parity(db_session)}
    assert rows[("2026-05", "autorizado")] == {"month": "2026-05", "status": "autorizado", "report": 1, "base": 1, "diff": 0}
    assert (rows[("2026-06", "fallido")]["report"], rows[("2026-06", "fallido")]["base"]) == (2, 3)
    assert rows[("2026-06", "fallido")]["diff"] == 1
    assert (rows[("2026-10", "fallido")]["report"], rows[("2026-10", "fallido")]["base"]) == (1, 1)
    assert ("2026-06", "autorizado") not in rows


def test_toku_parity_is_empty_without_a_report_and_cli_reports_it(db_session, monkeypatch, capsys) -> None:
    assert parity_check.toku_report_parity(db_session) == []
    monkeypatch.setattr(parity_check, "open_readonly_session", lambda: db_session)
    assert parity_check.main(["--channel", "toku", "--vs-report"]) == 0
    assert "tk_report_attempts vacio" in capsys.readouterr().out


def test_toku_parity_cli_exits_1_on_differences(db_session, monkeypatch, capsys) -> None:
    f = _tk_file(db_session)
    db_session.add_all([_attempt(f, "AUTORIZADO", datetime(2026, 3, 5, 15, tzinfo=timezone.utc))])
    db_session.flush()
    monkeypatch.setattr(parity_check, "open_readonly_session", lambda: db_session)
    assert parity_check.main(["--channel", "toku", "--vs-report"]) == 1
    out = capsys.readouterr().out
    assert "2026-03" in out and "diferencias" in out


# --- VP-PAR-11: paridad PAT vs base ------------------------------------------------------------------------------


def _vp_file(db) -> VpReportFile:
    f = VpReportFile(report_type="transacciones", file_sha256=_sha("vp"), filename="TransaccionesPAT.csv", status="completed")
    db.add(f)
    db.flush()
    return f


def _pat(f, cid, status, scheduled) -> VpReportPayment:
    return VpReportPayment(charge_external_id=cid, charge_status=status, scheduled_date=scheduled, amount=Decimal("5000"),
                           source_generated_at=GEN, last_file_id=f.id)


def _vp_charge(cid, status, charge_date, platform="virtualpos1") -> VpCharge:
    return VpCharge(external_id=cid, platform=platform, status=status, charge_date=charge_date)


def _seed_vp(db) -> None:
    f = _vp_file(db)
    db.add_all([
        _pat(f, "cid_a", "pagado", date(2026, 3, 5)),
        _pat(f, "cid_b", "rechazado", date(2026, 3, 6)),
        _pat(f, "cid_c", "pagado", date(2026, 4, 2)),  # falta en la base
        _pat(f, "cid_d", "procesando", date(2026, 4, 30)),
        _vp_charge("cid_a", "pagado", "2026-03-05"),
        _vp_charge("cid_b", "Rechazado ", "2026-03-06"),  # mismo estado con otra grafia
        _vp_charge("cid_d", "rechazado", "2026-04-30T00:00:00"),  # estado distinto
        _vp_charge("cid_x", "pagado", "2026-04-15", "virtualpos2"),  # en la ventana, ningun reporte lo trae
        _vp_charge("cid_y", "pagado", "2026-05-15"),  # fuera de la ventana del reporte: no se compara
    ])
    db.flush()


def test_vp_parity_by_month_within_the_report_window(db_session) -> None:
    _seed_vp(db_session)
    result = vp_parity.compute_vp_parity(db_session)
    assert (result.window_start, result.window_end) == (date(2026, 3, 5), date(2026, 4, 30))
    months = {m.month: m for m in result.months}
    assert set(months) == {"2026-03", "2026-04"}
    march, april = months["2026-03"], months["2026-04"]
    assert march.ok and (march.report, march.base) == (2, 2)
    assert (april.report, april.base, april.only_report, april.only_base, april.status_mismatch) == (2, 2, 1, 1, 1)
    assert not april.ok and not result.ok
    assert result.totals() == {"report": 4, "base": 4, "only_report": 1, "only_base": 1, "status_mismatch": 1}
    text = vp_parity.format_result(result)
    assert "2026-04" in text and "Paridad con diferencias en 1 mes(es)" in text
    assert "cid_" not in text  # salida agregada: sin identificadores


def test_vp_parity_month_filter_and_clean_window(db_session) -> None:
    _seed_vp(db_session)
    result = vp_parity.compute_vp_parity(db_session, from_month="2026-03", to_month="2026-03")
    assert [m.month for m in result.months] == ["2026-03"]
    assert result.ok


def test_vp_parity_without_reports(db_session) -> None:
    result = vp_parity.compute_vp_parity(db_session)
    assert not result.has_report and not result.ok and result.months == []
    assert "vp_report_payments vacio" in vp_parity.format_result(result)


class _Kept:
    """La sesion del test sin rollback/close: los datos sinteticos sobreviven a varias llamadas al CLI."""

    def __init__(self, db) -> None:
        self._db = db

    def __getattr__(self, name):
        return getattr(self._db, name)

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_vp_parity_cli_exit_codes(db_session, monkeypatch, capsys) -> None:
    kept = _Kept(db_session)
    monkeypatch.setattr(readonly_guard, "open_readonly_session", lambda: kept)
    monkeypatch.setattr(parity_check, "open_readonly_session", lambda: kept)
    _seed_vp(db_session)
    assert vp_parity_check.main([]) == 1
    assert vp_parity_check.main(["--from", "2026-03", "--to", "2026-03"]) == 0
    assert parity_check.main(["--channel", "virtualpos", "--vs-report"]) == 1
    assert "Ventana de los reportes" in capsys.readouterr().out


# --- VP-PAR-11: job apagado por defecto ---------------------------------------------------------------------------


def test_vp_parity_job_is_off_by_default_and_noop(monkeypatch) -> None:
    assert type(settings).model_fields["vp_parity_check_enabled"].default is False
    monkeypatch.setattr(settings, "vp_parity_check_enabled", False)
    monkeypatch.setattr(vp_parity_job, "SessionLocal", lambda: pytest.fail("no debe abrir sesion"))
    asyncio.run(vp_parity_job.vp_parity_check())


def test_vp_parity_job_logs_differences_when_enabled(monkeypatch, caplog) -> None:
    result = vp_parity.VpParityResult(date(2026, 3, 1), date(2026, 3, 31), [vp_parity.MonthParity("2026-03", 3, 2, 1)])
    monkeypatch.setattr(settings, "vp_parity_check_enabled", True)
    monkeypatch.setattr(vp_parity_job, "_run_parity", lambda: result)
    with caplog.at_level(logging.WARNING, logger=vp_parity_job.__name__):
        asyncio.run(vp_parity_job.vp_parity_check())
    assert "diferencias en 1 mes(es)" in caplog.text and "2026-03" in caplog.text


def test_vp_parity_job_skips_while_a_sync_is_running(db_session, monkeypatch) -> None:
    db_session.add(EtlRun(status="running"))
    db_session.flush()
    monkeypatch.setattr(vp_parity_job, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(vp_parity.__name__ + ".compute_vp_parity", lambda *_a, **_k: pytest.fail("no debe comparar"))
    assert vp_parity_job._run_parity() is None


def test_vp_parity_job_never_breaks_the_scheduler(monkeypatch) -> None:
    monkeypatch.setattr(settings, "vp_parity_check_enabled", True)

    def _boom():
        raise RuntimeError("caida")

    monkeypatch.setattr(vp_parity_job, "_run_parity", _boom)
    asyncio.run(vp_parity_job.vp_parity_check())  # no propaga


def test_vp_parity_job_is_registered_without_touching_the_others() -> None:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from app.scheduler import engine as sched_engine

    sched = AsyncIOScheduler(timezone="America/Santiago")
    sched_engine.register_jobs(sched)
    jobs = {j.id: j for j in sched.get_jobs()}
    assert vp_parity_job.JOB_VP_PARITY in jobs
    trigger = str(jobs[vp_parity_job.JOB_VP_PARITY].trigger)
    assert "hour='6'" in trigger and "minute='40'" in trigger
    assert {"sync_all_channels", "retry_failed_channels", "alerts_check"} <= set(jobs)
    n_jobs = len(jobs)
    sched_engine.register_jobs(sched)
    assert len(sched.get_jobs()) == n_jobs


# --- SYNC-D-12 / SYNC-O-14: completitud por mes y canal ---------------------------------------------------------


def test_month_range_crosses_years() -> None:
    assert coverage_report.month_range("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert coverage_report.month_range("2026-03", "2026-02") == []


def test_coverage_flags_gaps_differences_and_missing_reference(db_session) -> None:
    f = _vp_file(db_session)
    db_session.add_all([
        Charge(source="virtualpos1", external_id=f"cv-{uuid.uuid4().hex[:8]}", status="pagado", charge_date="2026-07-03", amount="1"),
        Charge(source="virtualpos1", external_id=f"cv-{uuid.uuid4().hex[:8]}", status="pagado", charge_date="2026-07-04", amount="1"),
        Charge(source="virtualpos1", external_id=f"cv-{uuid.uuid4().hex[:8]}", status="pagado", charge_date="2026-09-04", amount="1"),
        _pat(f, "cid_r1", "pagado", date(2026, 7, 3)),
        _pat(f, "cid_r2", "pagado", date(2026, 7, 4)),
        _pat(f, "cid_r3", "pagado", date(2026, 9, 4)),
        _pat(f, "cid_r4", "pagado", date(2026, 9, 5)),
    ])
    db_session.flush()
    rows = {r["month"]: r for r in coverage_report.coverage(db_session, "virtualpos", from_month="2026-06", to_month="2026-10")}
    assert list(rows) == ["2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    assert rows["2026-07"]["base"] >= 2 and rows["2026-07"]["reference"] == 2
    assert rows["2026-09"]["reference"] == 2
    if rows["2026-09"]["base"] == 1:  # sin otros cobros sinteticos ese mes: 1 vs 2 difiere
        assert rows["2026-09"]["state"] == "difiere" and rows["2026-09"]["diff"] == -1
    if rows["2026-08"]["base"] == 0:
        assert rows["2026-08"]["state"] == "hueco"
    assert rows["2026-10"]["reference"] is None  # fuera de lo que cubre el reporte


def test_coverage_tch_uses_the_monthly_control_and_payku_has_no_reference(db_session) -> None:
    db_session.add_all([
        TchTransaction(file_number=9_991_001, period="2016-03", status="ACEPTADA", amount="1", dedupe_key=f"cv-{uuid.uuid4().hex}"),
        TchTransaction(file_number=9_991_002, period="2016-03", status="RECHAZADA", amount="1", dedupe_key=f"cv-{uuid.uuid4().hex}"),
        TchMonthlyCollection(period="2016-03", accepted_count=1, accepted_amount="1", rejected_count=1, rejected_amount="1",
                             source_file="x.xlsx"),
        TchMonthlyCollection(period="2016-04", accepted_count=5, accepted_amount="1", rejected_count=0, rejected_amount="0",
                             source_file="x.xlsx"),
    ])
    db_session.flush()
    rows = {r["month"]: r for r in coverage_report.coverage(db_session, "tch", from_month="2016-03", to_month="2016-04")}
    assert rows["2016-03"]["reference"] == 2 and rows["2016-03"]["base"] >= 2
    assert rows["2016-04"]["reference"] == 5
    payku = coverage_report.coverage(db_session, "payku", from_month="2026-01", to_month="2026-02")
    assert all(r["reference"] is None and r["state"] in ("hueco", "sin_referencia") for r in payku)


def test_coverage_default_range_starts_at_the_expected_month_and_stops_today(db_session) -> None:
    rows = coverage_report.coverage(db_session, "virtualpos")
    assert rows[0]["month"] == coverage_report.EXPECTED_START["virtualpos"] == "2025-02"
    assert rows[-1]["month"] == "2026-10"  # hoy (fijado) en Chile
    with pytest.raises(ValueError):
        coverage_report.coverage(db_session, "otro")


def test_coverage_cli_strict_and_only_problems(db_session, monkeypatch, capsys) -> None:
    monkeypatch.setattr(readonly_guard, "open_readonly_session", lambda: db_session)
    assert coverage_report.main(["--channel", "payku", "--from", "1990-01", "--to", "1990-02"]) == 0
    assert coverage_report.main(["--channel", "payku", "--from", "1990-01", "--to", "1990-02", "--strict"]) == 1
    out = capsys.readouterr().out
    assert "huecos=2" in out and "1990-01" in out
    assert coverage_report.main(["--channel", "payku", "--from", "1990-01", "--to", "1990-01", "--format", "csv"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "canal,mes,base,referencia,diferencia,estado"
