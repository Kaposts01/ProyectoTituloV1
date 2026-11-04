"""VP-PAR-02: script manual scripts/maintenance/import_vp_reports.py (dry-run por defecto; --apply no se usa contra bases reales)."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from vp_reports_support import (
    PEPPER,
    PII_SENTINELS,
    payment_row,
    rejected_payment_row,
    subscription_row,
    write_report,
)

from app.core.config import settings
from app.db.session import engine
from app.models.vp_report import VpReportFile, VpReportPayment

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "maintenance" / "import_vp_reports.py"


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


@pytest.fixture(autouse=True)
def pepper(monkeypatch):
    monkeypatch.setattr(settings, "vp_report_hash_pepper", PEPPER)


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("import_vp_reports_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def folder(tmp_path):
    write_report(tmp_path / "TransaccionesPAT-VirtualPOS-1792546479.csv", "transacciones", [payment_row(1), rejected_payment_row(2)])
    write_report(tmp_path / "SuscriptoresPAT-VirtualPOS-1792546498.csv", "suscriptores", [subscription_row(1)])
    (tmp_path / "otro.csv").write_text("a,b\n1,2\n", encoding="utf-8")  # no coincide con los patrones: se ignora
    return tmp_path


def test_dry_run_is_the_default_reads_only_and_prints_counts(script, db_session, folder, capsys):
    code = script.main(["--dir", str(folder)], session_factory=lambda: db_session)
    out = capsys.readouterr().out
    assert code == 0 and "DRY-RUN" in out and "archivos: 2" in out
    assert "tipo=transacciones" in out and "tipo=suscriptores" in out and "filas=2" in out and "ya_cargado=no" in out
    assert "otro.csv" not in out
    assert not any(s in out for s in PII_SENTINELS)
    assert db_session.scalar(select(func.count()).select_from(VpReportFile)) == 0


def test_apply_loads_each_file_then_reconciles_and_is_idempotent(script, db_session, folder, capsys):
    assert script.main(["--dir", str(folder), "--apply"], session_factory=lambda: db_session) == 0
    out = capsys.readouterr().out
    assert "APPLY" in out and "Reconciliacion final" in out and "Fallas: 0" in out
    assert db_session.scalar(select(func.count()).select_from(VpReportFile)) == 2
    assert db_session.scalar(select(func.count()).select_from(VpReportPayment)) == 2
    assert not any(s in out for s in PII_SENTINELS)
    assert script.main(["--dir", str(folder), "--apply"], session_factory=lambda: db_session) == 0
    assert "YA CARGADO" in capsys.readouterr().out
    assert db_session.scalar(select(func.count()).select_from(VpReportFile)) == 2


def test_bad_file_is_reported_without_content_and_exit_code_is_1(script, db_session, tmp_path, capsys):
    bad = tmp_path / "malo.csv"
    bad.write_text("a,b,c\nSENTINELA-NOMBRE,2,3\n", encoding="utf-8")
    assert script.main([str(bad)], session_factory=lambda: db_session) == 1
    out = capsys.readouterr().out
    assert "ERROR" in out and "SENTINELA" not in out


def test_missing_inputs_exit_cleanly(script, db_session, tmp_path, capsys):
    assert script.main(["--dir", str(tmp_path)], session_factory=lambda: db_session) == 2
    with pytest.raises(SystemExit):
        script.main([str(tmp_path / "no-existe.csv")], session_factory=lambda: db_session)
