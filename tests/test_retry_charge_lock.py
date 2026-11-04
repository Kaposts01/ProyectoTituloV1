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


# ----------------------------- RA-27: lock por suscripcion compartido con la Opcion A -----------------------------


def test_retry_while_a_change_holds_the_subscription_lock_is_rejected_without_write_run(db_session, provider) -> None:
    from app.services.billing_apply import subscription_lock

    _seed(db_session)
    with subscription_lock(db_session, "virtualpos1", SUB), pytest.raises(svc.RetrySubscriptionBusyError) as exc:
        asyncio.run(svc.retry_charge(db_session, CID))
    assert isinstance(exc.value, svc.RetryBlockedError)  # las rutas lo traducen a 409
    assert provider.requests == []
    assert _runs(db_session) == []


def test_concurrent_retry_and_change_share_the_subscription_lock(db_session, provider) -> None:
    """Un cambio aprobado que intenta tomar el lock mientras el reintento esta en curso recibe SubscriptionBusyError;
    al terminar el reintento el lock queda libre y el cambio puede tomarlo."""
    from app.services.billing_apply import SubscriptionBusyError, subscription_lock

    _seed(db_session)
    outcome: list[str] = []

    async def change_during_retry() -> None:
        while not any(p.endswith("/retry") for _m, p in provider.requests):  # el reintento ya tiene ambos locks
            await asyncio.sleep(0.005)
        try:
            with subscription_lock(db_session, "virtualpos1", SUB):
                outcome.append("change_applied")
        except SubscriptionBusyError:
            outcome.append("change_busy")

    async def both():
        return await asyncio.gather(svc.retry_charge(db_session, CID), change_during_retry())

    charge, _ = asyncio.run(both())
    assert charge.status == "procesando"
    assert outcome == ["change_busy"]
    assert provider.retries() == 1
    assert [r.status for r in _runs(db_session)] == ["completed"]
    with subscription_lock(db_session, "virtualpos1", SUB):  # liberado tras el reintento
        pass


def test_subscription_lock_is_released_when_the_retry_fails(db_session, provider, monkeypatch) -> None:
    from app.services.billing_apply import subscription_lock

    _seed(db_session)

    async def boom(_request):
        raise httpx.ConnectError("caido")

    monkeypatch.setattr(provider, "handler", boom)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(svc.retry_charge(db_session, CID))
    with subscription_lock(db_session, "virtualpos1", SUB), svc.charge_retry_lock(db_session, "virtualpos1", CID):
        pass
