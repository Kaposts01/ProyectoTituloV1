"""Migraciones 0064 y 0065 (lote L4-DATA): cadena, y que los modelos coincidan con la base migrada de la suite.

Comparacion de solo lectura con `alembic.autogenerate.compare_metadata` limitada a las tablas y columnas nuevas (si
saliera algo, `alembic revision --autogenerate` no estaria vacio para ellas).
"""

import importlib.util
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import make_url

import app.models.export_job
import app.models.payku_report  # noqa: F401
from alembic import command
from app.db.session import Base, engine

ROOT = Path(__file__).resolve().parents[1]
NEW_TABLES = {"export_jobs", "p_report_files", "p_report_transactions", "p_report_settlements"}
NEW_COLUMNS = {
    ("p_transactions", "commission"), ("p_transactions", "net_amount"), ("p_transactions", "payment_method"),
    ("p_transactions", "installment_number"), ("p_subscriptions", "next_charge_date"),
}


def _load(name: str):
    path = ROOT / "alembic" / "versions" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chain_0064_0065() -> None:
    m64 = _load("20261102_0064_seed_unified_view_permissions.py")
    m65 = _load("20261102_0065_export_jobs_payku_reports.py")
    assert (m64.revision, m64.down_revision) == ("20261102_0064", "20261102_0061")
    assert (m65.revision, m65.down_revision) == ("20261102_0065", "20261102_0064")
    assert callable(m65.downgrade) and callable(m64.downgrade)


def test_new_tables_and_columns_match_models() -> None:
    def include(obj, name, type_, reflected, compare_to):
        if type_ == "table":
            return name in NEW_TABLES or name in {"p_transactions", "p_subscriptions"}
        table = getattr(obj, "table", None)
        if table is None:
            return True
        if table.name in NEW_TABLES:
            return True
        return type_ == "column" and (table.name, name) in NEW_COLUMNS

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"include_object": include, "compare_type": True})
        diff = compare_metadata(context, Base.metadata)
    assert diff == []


def test_downgrade_to_0061_and_back_in_test_db() -> None:
    """Reversibilidad de 0065 y 0064, solo contra la base de la suite (conftest la fija a *_test)."""
    from app.core.config import settings

    if not (make_url(settings.database_url).database or "").endswith("_test"):
        pytest.skip("settings no apunta a una base *_test; no se ejecuta por seguridad.")
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    try:
        command.downgrade(cfg, "20261102_0061")
        insp = inspect(engine)
        assert not (NEW_TABLES & set(insp.get_table_names()))
        assert "commission" not in {c["name"] for c in insp.get_columns("p_transactions")}
    finally:
        command.upgrade(cfg, "head")
    assert NEW_TABLES <= set(inspect(engine).get_table_names())
