"""BILL-14 (GB-RZ-30): lock por cargo en `retry_charge`.

Un doble `/retry` concurrente del mismo cargo (doble clic o dos usuarios) debe llamar a VirtualPOS una sola vez; el
segundo recibe `RetryInProgressError` (subclase de `RetryBlockedError`, que las rutas traducen a 409) sin crear un
`write_run`. Todo offline: cliente real sobre httpx.MockTransport, sin red ni credenciales.
"""

import asyncio

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.integrations.virtualpos.client import VirtualPOSClient
from app.models.crm import Charge, Subscription
from app.models.write_run import WriteRun
from app.services import write_virtualpos as svc

SUB = "sub-retry-lock"
CID = "c-retry-lock"


class SlowProvider:
    """Transporte falso asincrono: el reintento tarda un poco para que la segunda llamada llegue mientras tanto."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if request.url.path.endswith("/retry"):
            await asyncio.sleep(0.05)
            return httpx.Response(200, json={"status": "OK", "code": 200}, request=request)
        if request.url.path == f"/v3/charge/{CID}":
            return httpx.Response(200, json={"status": "OK", "code": 200, "charge": {"id": CID, "status": "procesando"}}, request=request)
        return httpx.Response(404, json={"status": "NOK", "code": 404}, request=request)

    def client(self, *_args: object, **_kwargs: object) -> VirtualPOSClient:
        real = VirtualPOSClient.__new__(VirtualPOSClient)
        real._client = httpx.AsyncClient(base_url="https://vp.test", transport=httpx.MockTransport(self.handler))
        return real

    def retries(self) -> int:
        return sum(1 for m, p in self.requests if m == "GET" and p.endswith("/retry"))


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "virtualpos_writes_enabled", True)


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


@pytest.fixture
def provider(monkeypatch) -> SlowProvider:
    fake = SlowProvider()
    monkeypatch.setattr(svc, "VirtualPOSClient", fake.client)
    return fake


def _seed(db) -> None:
    db.add(Subscription(source="virtualpos1", external_id=SUB))
    db.add(Charge(source="virtualpos1", external_id=CID, subscription_external_id=SUB, status="rechazado",
                  raw_payload={"id": CID, "status": "rechazado"}))
    db.flush()


def _runs(db) -> list[WriteRun]:
    return list(db.scalars(select(WriteRun).where(WriteRun.operation == "retry_charge", WriteRun.external_id == CID)))


def test_double_concurrent_retry_calls_provider_once(db_session, provider) -> None:
    _seed(db_session)

    async def both():
        return await asyncio.gather(
            svc.retry_charge(db_session, CID), svc.retry_charge(db_session, CID), return_exceptions=True
        )

    results = asyncio.run(both())
    errors = [r for r in results if isinstance(r, Exception)]
    assert len(errors) == 1
    assert isinstance(errors[0], svc.RetryInProgressError)
    assert isinstance(errors[0], svc.RetryBlockedError)  # las rutas lo traducen a 409
    assert provider.retries() == 1
    assert [r.status for r in _runs(db_session)] == ["completed"]


def test_retry_with_lock_taken_is_rejected_without_write_run(db_session, provider) -> None:
    _seed(db_session)
    with svc.charge_retry_lock(db_session, "virtualpos1", CID), pytest.raises(svc.RetryInProgressError):
        asyncio.run(svc.retry_charge(db_session, CID))
    assert provider.requests == []
    assert _runs(db_session) == []


def test_lock_is_released_after_retry(db_session, provider) -> None:
    _seed(db_session)
    asyncio.run(svc.retry_charge(db_session, CID))
    asyncio.run(svc.retry_charge(db_session, CID))
    assert provider.retries() == 2


def test_lock_is_per_charge(db_session) -> None:
    with svc.charge_retry_lock(db_session, "virtualpos1", CID), svc.charge_retry_lock(db_session, "virtualpos1", "otro"):
        pass
