"""Migraciones 0056 (TK-PAR-03) y 0057 (TK-PAR-07/09): cadena y reversibilidad real, solo en la base `*_test`."""

import importlib.util
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import make_url

from alembic import command

ROOT = Path(__file__).resolve().parent.parent
VERSIONS = ROOT / "alembic" / "versions"


def _load(pattern: str):
    path = next(VERSIONS.glob(pattern))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chain_0056_0057() -> None:
    m56, m57 = _load("*_0056_payment_rejection_columns.py"), _load("*_0057_toku_report_customers_payments_settlements.py")
    assert m56.revision == "20261102_0056" and m57.revision == "20261102_0057"
    assert m57.down_revision == m56.revision


def test_roundtrip_downgrade_and_upgrade_in_test_db() -> None:
    from app.core.config import settings
    from app.db.session import engine

    if not (make_url(settings.database_url).database or "").endswith("_test"):
        pytest.skip("settings no apunta a una base *_test; no se ejecuta por seguridad.")
    m56 = _load("*_0056_payment_rejection_columns.py")
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    try:
        command.downgrade(cfg, m56.down_revision)
        insp = inspect(engine)
        assert "rejection_code" not in {c["name"] for c in insp.get_columns("payments")}
        assert not {"tk_report_customers", "tk_report_payments", "tk_report_settlements"} & set(insp.get_table_names())
    finally:
        command.upgrade(cfg, "head")
    insp = inspect(engine)
    assert {"rejection_code", "rejection_reason", "rejected_at"} <= {c["name"] for c in insp.get_columns("payments")}
    assert {"tk_report_customers", "tk_report_payments", "tk_report_settlements"} <= set(insp.get_table_names())
