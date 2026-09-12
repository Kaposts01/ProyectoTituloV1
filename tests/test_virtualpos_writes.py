import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.main import app
from app.models.crm import Client
from app.models.write_run import WriteRun
from app.services import write_virtualpos


class SuccessfulVirtualPOSClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def update_client(self, client_id: str, changes: dict) -> dict:
        return {"uuid": client_id, **changes}

    async def get_client(self, client_id: str) -> dict:
        raise AssertionError("The update response already includes the client")

    async def create_client(self, data: dict) -> dict:
        return {"uuid": "client-created-1", **data}


class FailingVirtualPOSClient(SuccessfulVirtualPOSClient):
    async def update_client(self, client_id: str, changes: dict) -> dict:
        raise RuntimeError("VirtualPOS rejected update")


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


def _client() -> Client:
    return Client(
        source="virtualpos1",
        external_id="client-write-1",
        first_name="Antes",
        raw_payload={"uuid": "client-write-1", "first_name": "Antes"},
    )


def test_update_client_persists_provider_response_locally_and_canonically(monkeypatch, db_session) -> None:
    db_session.add(_client())
    db_session.flush()
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", True)
    monkeypatch.setattr(write_virtualpos, "VirtualPOSClient", SuccessfulVirtualPOSClient)
    stored: list[tuple[str, dict]] = []
    monkeypatch.setattr(write_virtualpos, "_ensure_local_client_exists", lambda _: None)
    monkeypatch.setattr(write_virtualpos, "_update_local_client", lambda client_id, payload: stored.append((client_id, payload)))

    updated = asyncio.run(write_virtualpos.update_client(db_session, "client-write-1", {"first_name": "Después"}))

    assert updated.first_name == "Después"
    assert stored == [("client-write-1", {"uuid": "client-write-1", "first_name": "Después"})]
    write_run = db_session.scalars(select(WriteRun).where(WriteRun.external_id == "client-write-1")).one()
    assert write_run.status == "completed"
    assert write_run.response_payload == {"uuid": "client-write-1", "first_name": "Después"}


def test_update_client_does_not_change_local_data_when_provider_rejects(monkeypatch, db_session) -> None:
    client = _client()
    db_session.add(client)
    db_session.flush()
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", True)
    monkeypatch.setattr(write_virtualpos, "VirtualPOSClient", FailingVirtualPOSClient)
    monkeypatch.setattr(write_virtualpos, "_ensure_local_client_exists", lambda _: None)

    with pytest.raises(RuntimeError, match="rejected"):
        asyncio.run(write_virtualpos.update_client(db_session, "client-write-1", {"first_name": "Después"}))

    db_session.refresh(client)
    assert client.first_name == "Antes"
    assert db_session.scalars(select(WriteRun).where(WriteRun.external_id == "client-write-1")).one().status == "failed"


def test_update_client_marks_reconciliation_when_local_persistence_fails(monkeypatch, db_session) -> None:
    db_session.add(_client())
    db_session.flush()
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", True)
    monkeypatch.setattr(write_virtualpos, "VirtualPOSClient", SuccessfulVirtualPOSClient)
    monkeypatch.setattr(write_virtualpos, "_ensure_local_client_exists", lambda _: None)
    monkeypatch.setattr(
        write_virtualpos,
        "_update_local_client",
        lambda *_: (_ for _ in ()).throw(RuntimeError("local database unavailable")),
    )

    with pytest.raises(write_virtualpos.ReconciliationRequiredError):
        asyncio.run(write_virtualpos.update_client(db_session, "client-write-1", {"first_name": "Después"}))

    write_run = db_session.scalars(select(WriteRun).where(WriteRun.external_id == "client-write-1")).one()
    assert write_run.status == "reconciliation_required"


def test_update_client_saves_private_note_without_calling_virtualpos(db_session) -> None:
    client = _client()
    db_session.add(client)
    db_session.flush()

    updated = asyncio.run(write_virtualpos.update_client(db_session, "client-write-1", {"private_note": "Uso interno"}))

    assert updated.private_note == "Uso interno"
    assert db_session.scalars(select(WriteRun).where(WriteRun.external_id == "client-write-1")).all() == []


def test_create_client_persists_provider_response_locally_and_canonically(monkeypatch, db_session) -> None:
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", True)
    monkeypatch.setattr(write_virtualpos, "VirtualPOSClient", SuccessfulVirtualPOSClient)
    stored: list[tuple[str, dict]] = []
    monkeypatch.setattr(write_virtualpos, "_create_local_client", lambda client_id, payload: stored.append((client_id, payload)))

    created = asyncio.run(write_virtualpos.create_client(db_session, {
        "first_name": "Nueva", "email": "nueva@example.com", "social_id_type": "1", "social_id": "12.345.678-5",
    }))

    assert created.external_id == "client-created-1"
    assert created.social_id == "12345678-5"
    assert stored == [("client-created-1", {"uuid": "client-created-1", "first_name": "Nueva", "email": "nueva@example.com", "social_id_type": "1", "social_id": "12345678-5"})]
    assert db_session.scalars(select(WriteRun).where(WriteRun.external_id == "client-created-1")).one().status == "completed"


def test_normalize_rut_accepts_common_formats_and_rejects_invalid_values() -> None:
    assert write_virtualpos.normalize_rut("12.345.678-5") == "12345678-5"
    assert write_virtualpos.normalize_rut("123456785") == "12345678-5"
    with pytest.raises(write_virtualpos.InvalidClientDataError):
        write_virtualpos.normalize_rut("12.345.678-0")


def test_update_client_route_requires_authentication() -> None:
    response = TestClient(app).put(
        "/api/v1/writes/virtualpos/clients/client-write-1",
        json={"first_name": "Después"},
    )

    assert response.status_code == 401
