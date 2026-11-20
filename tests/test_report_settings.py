"""REP-02: configuracion de los reportes por correo y tabla `report_dispatches` (migracion 20261120_0085)."""

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models.report_dispatch import ReportDispatch
from tests.test_config_environments import _clean_env, make, sandbox  # noqa: F401

TO = "persona@ejemplo.org"


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


def test_flags_are_off_by_default_and_recipient_is_empty() -> None:
    s = make()
    assert s.reports_weekly_enabled is False and s.reports_monthly_enabled is False
    assert s.report_email_to == ""
    assert (s.report_weekly_hour, s.report_monthly_hour) == (7, 7)


def test_production_accepts_several_recipients() -> None:
    assert make(report_email_to=f"{TO}, otra@ejemplo.org").report_email_to


@pytest.mark.parametrize("env", ["sandbox", "qa"])
def test_sandbox_allows_one_recipient_and_rejects_two(env: str) -> None:
    assert sandbox(env=env, report_email_to=TO).report_email_to == TO
    assert sandbox(env=env).report_email_to == ""
    with pytest.raises(ValidationError) as err:
        sandbox(env=env, report_email_to=f"{TO},otra@ejemplo.org")
    assert "REPORT_EMAIL_TO" in str(err.value)
    assert TO not in str(err.value)  # nunca se imprime la direccion


@pytest.mark.parametrize("hour", [-1, 24])
def test_invalid_hours_are_rejected(hour: int) -> None:
    with pytest.raises(ValidationError, match="REPORT_WEEKLY_HOUR"):
        make(report_weekly_hour=hour)
    with pytest.raises(ValidationError, match="REPORT_MONTHLY_HOUR"):
        make(report_monthly_hour=hour)


def test_migration_0085_chain_and_table() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config("alembic.ini")
    config.set_main_option("path_separator", "os")
    migration = ScriptDirectory.from_config(config).get_revision("20261120_0085").module
    assert migration.down_revision == "20261119_0084"
    inspector = inspect(engine)
    assert "report_dispatches" in inspector.get_table_names()
    uniques = {u["name"]: u["column_names"] for u in inspector.get_unique_constraints("report_dispatches")}
    assert uniques["uq_report_dispatches_kind_period"] == ["report_kind", "period_key"]


def test_unique_kind_period_and_status_check(db_session) -> None:
    db_session.add(ReportDispatch(report_kind="weekly", period_key="weekly:2099-W01"))
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(ReportDispatch(report_kind="weekly", period_key="weekly:2099-W01"))
        db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(ReportDispatch(report_kind="weekly", period_key="weekly:2099-W02", status="otro"))
        db_session.flush()
