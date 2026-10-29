"""TK-PAR-05: script manual scripts/maintenance/toku_report_lifecycle.py (dry-run por defecto)."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from toku_signals_support import World, uid

from app.models.core import CoreSubscription
from tests.test_charge_recovery import db_session  # noqa: F401  (fixture)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "maintenance" / "toku_report_lifecycle.py"


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("toku_report_lifecycle_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _count(db, sub):
    return db.scalar(select(CoreSubscription).where(CoreSubscription.external_id == sub))


def test_dry_run_is_default_and_writes_nothing(script, db_session, capsys):  # noqa: F811
    sub = uid("sub")
    World(db_session).product(sub, deleted=datetime(2025, 1, 15, 15, 0, tzinfo=UTC))
    assert script.main([], session_factory=lambda: db_session) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "deleted_created" in out and sub not in out
    assert _count(db_session, sub) is None


def test_apply_creates_the_baja_record(script, db_session, capsys):  # noqa: F811
    sub = uid("sub")
    World(db_session).product(sub, deleted=datetime(2025, 1, 15, 15, 0, tzinfo=UTC))
    assert script.main(["--apply"], session_factory=lambda: db_session) == 0
    assert "APPLY" in capsys.readouterr().out
    assert _count(db_session, sub).status == "deleted_at_source"
