"""SYNC-D-03: corrida baseline (eventos is_baseline) y comando manual de consolidacion baseline."""

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import session as db_session_module
from app.db.session import engine
from app.models.status_change import StatusChangeEvent
from app.models.toku_channel import TokuInvoice
from app.models.vp import VpCharge
from app.services import status_events
from app.services.channel_consolidation import consolidate_to_centralized

ROOT = Path(__file__).resolve().parent.parent


def _load_script():
    spec = importlib.util.spec_from_file_location("consolidate_baseline", ROOT / "scripts" / "maintenance" / "consolidate_baseline.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _invoice(db: Session, ext: str = "in_b1", status: str = "UNPAID") -> None:
    row = db.scalars(select(TokuInvoice).where(TokuInvoice.external_id == ext)).first()
    if row is None:
        row = TokuInvoice(external_id=ext, subscription_id="sub_b", currency="CLP", amount="5000")
        db.add(row)
    row.status = status
    db.flush()


def _flags(db: Session) -> list[tuple[str, str, bool]]:
    return [(e.event_kind, e.external_id, e.is_baseline) for e in db.scalars(
        select(StatusChangeEvent).order_by(StatusChangeEvent.detected_at, StatusChangeEvent.external_id))]


def test_baseline_marca_los_eventos_de_la_corrida(db_session: Session) -> None:
    _invoice(db_session)
    consolidate_to_centralized(db_session, ["toku"], run_id=uuid.uuid4(), baseline=True)
    assert _flags(db_session) == [("created", "in_b1", True)]
    _invoice(db_session, status="PAID")  # la corrida siguiente, normal, SI es novedad
    consolidate_to_centralized(db_session, ["toku"], run_id=uuid.uuid4())
    assert _flags(db_session)[-1] == ("status_changed", "in_b1", False)


def test_baseline_en_las_cuatro_fuentes(db_session: Session) -> None:
    db_session.add(VpCharge(external_id="vpb", platform="virtualpos2", status="PAGADO", amount="1"))
    _invoice(db_session)
    db_session.flush()
    consolidate_to_centralized(db_session, None, run_id=uuid.uuid4(), baseline=True)
    assert db_session.scalar(select(func.count()).select_from(StatusChangeEvent)) >= 2
    assert db_session.scalar(
        select(func.count()).select_from(StatusChangeEvent).where(StatusChangeEvent.is_baseline.is_(False))) == 0


def test_configuracion_activa_baseline_y_el_parametro_manda(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(status_events.settings, "status_events_baseline", True)
    _invoice(db_session, "in_c1")
    consolidate_to_centralized(db_session, ["toku"])  # sin parametro: usa la configuracion
    _invoice(db_session, "in_c2")
    consolidate_to_centralized(db_session, ["toku"], baseline=False)  # el parametro explicito gana
    assert _flags(db_session) == [("created", "in_c1", True), ("created", "in_c2", False)]


# ── Comando manual ─────────────────────────────────────────────────────────────────────────────────────


def test_guarda_de_confirmacion_de_base() -> None:
    script = _load_script()
    with pytest.raises(script.BaselineNotConfirmedError):
        script.check_apply_allowed("crm", None)
    with pytest.raises(script.BaselineNotConfirmedError):
        script.check_apply_allowed("crm", "crm_sandbox")
    script.check_apply_allowed("crm_test", "crm_test")


def test_comando_dry_run_no_escribe(db_session: Session, monkeypatch) -> None:
    script = _load_script()
    monkeypatch.setattr(db_session_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)  # el comando cierra su sesion; la del test debe sobrevivir
    _invoice(db_session, "in_d1")
    report = script.run(["toku"], apply=False, confirm_database=None)
    assert report["mode"] == "dry-run" and "baseline_events_created" not in report
    assert db_session.scalar(select(func.count()).select_from(StatusChangeEvent)) == 0


def test_comando_apply_exige_confirmacion_y_marca_baseline(db_session: Session, monkeypatch) -> None:
    script = _load_script()
    monkeypatch.setattr(db_session_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)  # el comando cierra su sesion; la del test debe sobrevivir
    _invoice(db_session, "in_a1")
    with pytest.raises(script.BaselineNotConfirmedError):
        script.run(["toku"], apply=True, confirm_database="otra_base")
    assert db_session.scalar(select(func.count()).select_from(StatusChangeEvent)) == 0
    current = db_session.connection().exec_driver_sql("select current_database()").scalar()
    report = script.run(["toku"], apply=True, confirm_database=current)
    assert report["failures"] == [] and report["baseline_events_created"] == 1
    assert _flags(db_session) == [("created", "in_a1", True)]
