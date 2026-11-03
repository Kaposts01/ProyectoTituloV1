"""d126 (opcion a), TK-PAR-07: estado de cliente de Toku desde el reporte de Clientes. Manda la API; el reporte solo
completa lo vacio. Datos SINTETICOS (sin PII)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from toku_reports_support import PEPPER, default_row, write_report

from app.core.config import settings
from app.db.session import engine
from app.models.crm import Client
from app.models.toku_channel import TokuCustomer
from app.services import channel_consolidation
from app.services.toku_client_status import (
    fill_blank_status,
    project_report_status,
    report_status,
    report_statuses,
)
from app.services.toku_report_import import import_report


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


def _status(db: Session, ext: str) -> str | None:
    return db.scalar(select(Client.status).where(Client.source == "toku", Client.external_id == ext))


def test_pure_rule() -> None:
    assert report_status(None) == "active"
    assert report_status(datetime(2026, 1, 1, tzinfo=UTC)) == "deleted"
    statuses = {"cus_1": "deleted"}
    assert fill_blank_status({"external_id": "cus_1", "status": None}, statuses)["status"] == "deleted"
    assert fill_blank_status({"external_id": "cus_1", "status": "  "}, statuses)["status"] == "deleted"
    # manda la API: un estado presente no se pisa
    assert fill_blank_status({"external_id": "cus_1", "status": "ACTIVE"}, statuses)["status"] == "ACTIVE"
    # sin fila en el reporte queda como estaba
    assert fill_blank_status({"external_id": "cus_9", "status": None}, statuses)["status"] is None


def test_import_of_clientes_fills_only_blank_status(tmp_path, db_session: Session) -> None:
    db_session.add_all([
        Client(source="toku", external_id="cus_T0001", status=None),  # vivo en el reporte -> active
        Client(source="toku", external_id="cus_T0002", status=""),  # eliminado en el reporte -> deleted
        Client(source="toku", external_id="cus_T0003", status="BLOCKED"),  # la API manda
        Client(source="virtualpos1", external_id="cus_T0001", status=None),  # otro canal: intacto
    ])
    db_session.flush()
    rows = [
        default_row("clientes", 1),
        default_row("clientes", 2, **{"Fecha de Eliminación": "2026-03-01T10:00:00"}),
        default_row("clientes", 3, **{"Fecha de Eliminación": "2026-03-01T10:00:00"}),
    ]
    path = write_report(tmp_path / "clientes.xlsx", "clientes", rows=rows)
    summary = import_report(db_session, path, filename=path.name, uploaded_by_user_id=None)
    assert summary.clients_status_filled == 2
    assert _status(db_session, "cus_T0001") == "active"
    assert _status(db_session, "cus_T0002") == "deleted"
    assert _status(db_session, "cus_T0003") == "BLOCKED"
    assert db_session.scalar(
        select(Client.status).where(Client.source == "virtualpos1", Client.external_id == "cus_T0001")
    ) is None
    assert project_report_status(db_session) == 0  # idempotente
    assert report_statuses(db_session, ["cus_T0002"]) == {"cus_T0002": "deleted"}


def test_api_consolidation_keeps_report_status_when_api_is_blank(tmp_path, db_session: Session) -> None:
    path = write_report(tmp_path / "clientes.xlsx", "clientes", rows=[
        default_row("clientes", 4, **{"Fecha de Eliminación": "2026-03-01T10:00:00"}), default_row("clientes", 5),
    ])
    import_report(db_session, path, filename=path.name, uploaded_by_user_id=None)
    db_session.add_all([
        TokuCustomer(external_id="cus_T0004", status=None, raw_payload={}),
        TokuCustomer(external_id="cus_T0005", status="ACTIVE", raw_payload={}),
    ])
    db_session.flush()
    channel_consolidation._consolidate_toku_clients(db_session)
    assert _status(db_session, "cus_T0004") == "deleted"  # API vacia -> completa el reporte
    assert _status(db_session, "cus_T0005") == "ACTIVE"  # API con estado -> manda la API
