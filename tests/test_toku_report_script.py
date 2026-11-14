"""TK-19: script manual scripts/maintenance/import_toku_reports.py (dry-run por defecto; --apply no se usa contra bases reales)."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from toku_reports_support import PEPPER, PII_SENTINELS, write_report, write_unsupported

from app.core.config import settings
from app.db.session import engine
from app.models.toku_report import TkReportAttempt, TkReportFile, TkReportProduct

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "maintenance" / "import_toku_reports.py"


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
    monkeypatch.setattr(settings, "toku_report_hash_pepper", PEPPER)


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("import_toku_reports_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def folder(tmp_path):
    # nombres en orden alfabetico inverso al de carga: «Intentos» debe cargarse despues de «Productos»
    write_report(tmp_path / "A-Intentos.xlsx", "intentos", n_rows=2)
    write_report(tmp_path / "B-Productos.xlsx", "productos", n_rows=2)
    return tmp_path


def test_dry_run_is_the_default_reads_only_and_prints_counts(script, db_session, folder, capsys):
    assert script.main(["--dir", str(folder)], session_factory=lambda: db_session) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "archivos: 2" in out
    assert "tipo=productos" in out and "tipo=intentos" in out and "ya_cargado=no" in out
    assert not any(s in out for s in PII_SENTINELS)
    assert db_session.scalar(select(func.count()).select_from(TkReportFile)) == 0


def test_apply_loads_products_first_so_attempts_resolve_and_is_idempotent(script, db_session, folder, capsys):
    assert script.main(["--dir", str(folder), "--apply"], session_factory=lambda: db_session) == 0
    out = capsys.readouterr().out
    assert "APPLY" in out and "Fallas: 0" in out and out.index("B-Productos") < out.index("A-Intentos")
    assert db_session.scalar(select(func.count()).select_from(TkReportFile)) == 2
    assert db_session.scalar(select(func.count()).select_from(TkReportProduct)) == 2
    unresolved = db_session.scalar(
        select(func.count()).select_from(TkReportAttempt).where(TkReportAttempt.subscription_external_id.is_(None))
    )
    assert unresolved == 0
    assert not any(s in out for s in PII_SENTINELS)
    assert script.main(["--dir", str(folder), "--apply"], session_factory=lambda: db_session) == 0
    assert "YA CARGADO" in capsys.readouterr().out
    assert db_session.scalar(select(func.count()).select_from(TkReportFile)) == 2


def test_missing_pepper_refuses_before_reading_anything(script, db_session, folder, capsys, monkeypatch):
    monkeypatch.setattr(settings, "toku_report_hash_pepper", "")
    assert script.main(["--dir", str(folder), "--apply"], session_factory=lambda: db_session) == 3
    out = capsys.readouterr().out
    assert "TOKU_REPORT_HASH_PEPPER" in out and not any(s in out for s in PII_SENTINELS)
    assert db_session.scalar(select(func.count()).select_from(TkReportFile)) == 0


def test_unsupported_file_is_reported_without_content_and_exit_code_is_1(script, db_session, tmp_path, capsys):
    bad = write_unsupported(tmp_path / "Clientes.xlsx")
    assert script.main([str(bad)], session_factory=lambda: db_session) == 1
    out = capsys.readouterr().out
    assert "ERROR" in out and "SENTINELA" not in out


def test_missing_inputs_exit_cleanly(script, db_session, tmp_path, capsys):
    assert script.main(["--dir", str(tmp_path)], session_factory=lambda: db_session) == 2
    with pytest.raises(SystemExit):
        script.main([str(tmp_path / "no-existe.xlsx")], session_factory=lambda: db_session)


def test_load_order_covers_every_supported_report_type() -> None:
    from app.services.toku_report_parser import SUPPORTED_TYPES
    from scripts.maintenance.import_toku_reports import LOAD_ORDER

    assert set(LOAD_ORDER) == set(SUPPORTED_TYPES)
    assert LOAD_ORDER[0] == "productos"


@pytest.mark.parametrize("module", ["scripts.maintenance.import_toku_reports", "scripts.maintenance.import_vp_reports"])
def test_import_script_registers_users_table_on_its_own(module: str) -> None:
    """En un proceso limpio (como en OPS-11) el script debe registrar `users`: sin eso el flush falla con NoReferencedTableError."""
    import subprocess
    import sys

    code = (
        f"import {module}\n"
        "from app.models.toku_report import TkReportFile\n"
        "print('users' in TkReportFile.metadata.tables)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "True"
