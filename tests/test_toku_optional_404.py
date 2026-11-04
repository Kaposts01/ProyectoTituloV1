"""L7-CIERRE: un 404 en un recurso secundario de Toku no tumba la sync entera.

En el sandbox `/organization/payments` responde 404 (docs/tasks.md, hallazgos Toku 2026-10-28) y antes la corrida
fallaba completa sin guardar nada. Ahora: el recurso queda omitido en `resource_stats`, la corrida sigue con los
demas y termina `partial` guardando lo leido. 401/403 y el 404 de un recurso esencial siguen siendo fatales. Cliente
falso y base de pruebas con rollback: no se llama al proveedor.
"""

import asyncio
import uuid
from types import SimpleNamespace
from typing import Self
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.channel_errors import is_config_or_credential_error
from app.db.session import engine
from app.models.source_record import SourceRecord
from app.services import toku_sync
from app.services.read_only_provider_sync import OPTIONAL_SKIPPED_PREFIX
from tests.test_sync_config_errors import _patch_sync_all


def _http_error(status: int, path: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", f"https://toku.invalid{path}")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"Client error '{status}' for url '{request.url}'", request=request, response=response)


class FakeTokuClient:
    """Cliente falso: cada recurso devuelve una pagina; `failures` fuerza un error HTTP por recurso."""

    def __init__(self, failures: dict[str, int] | None = None, token: str | None = None) -> None:
        self.failures = failures or {}
        self.token = token or uuid.uuid4().hex
        self.calls: list[str] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def _page(self, resource: str, path: str):
        self.calls.append(resource)
        if resource in self.failures:
            raise _http_error(self.failures[resource], path)
        return {"data": [{"id": f"{self.token}-{resource}"}], "meta": {"pages": 1}}

    async def list_customers(self, page: int, page_size: int):
        return await self._page("customer", "/customers")

    async def list_subscriptions(self, page: int, page_size: int):
        return await self._page("subscription", "/subscriptions")

    async def list_invoices(self, page: int, page_size: int):
        return await self._page("invoice", "/invoices")

    async def list_transactions(self, page: int, page_size: int, **_kwargs):
        return await self._page("transaction", "/transactions")

    async def list_payments(self, page: int, page_size: int):
        return await self._page("payment", "/organization/payments")

    async def list_payment_methods(self, page: int, page_size: int):
        return await self._page("payment_method", "/payment-methods")


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


def _stored(db, token: str) -> set[str]:
    rows = db.scalars(select(SourceRecord.resource_type).where(
        SourceRecord.source == "toku", SourceRecord.external_id.like(f"{token}-%")))
    return set(rows)


def test_a_404_on_payments_skips_it_and_keeps_the_rest(monkeypatch, db_session) -> None:
    client = FakeTokuClient({"payment": 404})
    monkeypatch.setattr(toku_sync, "TokuClient", lambda: client)

    run = asyncio.run(toku_sync.sync_toku(db_session))

    assert run.status == "partial"
    assert run.error_message == f"{OPTIONAL_SKIPPED_PREFIX}: payment"
    assert run.resource_stats["payment"]["skipped"] is True
    assert run.resource_stats["payment"]["reason"] == "http_404"
    # La corrida siguio despues del 404 (medios de pago se leen despues de payments) y guardo lo leido.
    assert client.calls[-1] == "payment_method"
    assert _stored(db_session, client.token) == {"customer", "subscription", "invoice", "transaction", "payment_method"}
    # Sin datos personales ni URL en el aviso, y no se clasifica como error de configuracion o credencial (d139a).
    assert "toku.invalid" not in run.error_message
    assert not is_config_or_credential_error(run.error_message)


def test_404_on_both_secondary_resources_lists_both(monkeypatch, db_session) -> None:
    client = FakeTokuClient({"payment": 404, "payment_method": 404})
    monkeypatch.setattr(toku_sync, "TokuClient", lambda: client)
    run = asyncio.run(toku_sync.sync_toku(db_session))
    assert run.status == "partial"
    assert run.error_message.endswith("payment, payment_method")


@pytest.mark.parametrize("resource", ["customer", "subscription", "invoice", "transaction"])
def test_a_404_on_an_essential_resource_is_still_fatal(monkeypatch, db_session, resource) -> None:
    monkeypatch.setattr(toku_sync, "TokuClient", lambda: FakeTokuClient({resource: 404}))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(toku_sync.sync_toku(db_session))


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("resource", ["payment", "customer"])
def test_credential_errors_stay_fatal_even_on_secondary_resources(monkeypatch, db_session, status, resource) -> None:
    monkeypatch.setattr(toku_sync, "TokuClient", lambda: FakeTokuClient({resource: status}))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(toku_sync.sync_toku(db_session))


def test_a_500_on_a_secondary_resource_is_still_fatal(monkeypatch, db_session) -> None:
    monkeypatch.setattr(toku_sync, "TokuClient", lambda: FakeTokuClient({"payment": 500}))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(toku_sync.sync_toku(db_session))


def test_without_failures_the_run_stays_completed(monkeypatch, db_session) -> None:
    monkeypatch.setattr(toku_sync, "TokuClient", lambda: FakeTokuClient())
    run = asyncio.run(toku_sync.sync_toku(db_session))
    assert run.status == "completed" and run.error_message is None
    assert not run.resource_stats["payment"].get("skipped")


def test_orchestrator_marks_the_global_run_partial(monkeypatch) -> None:
    store: dict = {}
    sync_all = _patch_sync_all(monkeypatch, store, vp2_error=RuntimeError("no se usa"))

    async def partial_toku(_db, _cb=None):
        return SimpleNamespace(records_processed=5, status="partial")

    monkeypatch.setattr(sync_all, "sync_toku", partial_toku)
    asyncio.run(sync_all.sync_all_channels(channels=["toku"]))
    run = store["run"]
    assert run.status == "partial"
    assert run.channels_processed == ["toku"]
    assert not run.channels_failed  # no se reintenta: el 404 es determinista
    assert "Recursos opcionales omitidos en: toku" in run.error_message


def test_full_sync_marks_the_run_partial(monkeypatch) -> None:
    from app.api.v1.routes import etl

    updates: list[dict] = []
    monkeypatch.setattr(etl, "_update_run", lambda _run_id, **fields: updates.append(fields))
    monkeypatch.setattr(etl, "_SYNC_FN", {"toku": AsyncMock(return_value=SimpleNamespace(records_processed=5, status="partial"))})
    monkeypatch.setattr(etl, "settings", SimpleNamespace(channel_enabled=lambda _c: True, env_mode="test"))
    monkeypatch.setattr(etl, "SessionLocal", MagicMock())
    monkeypatch.setattr(etl, "consolidate_to_centralized", MagicMock(return_value=0))

    asyncio.run(etl._run_full_sync_background(uuid.uuid4(), ["toku"]))

    final = updates[-1]
    assert final["status"] == "partial"
    assert final["channels_processed"] == ["toku"] and final["channels_failed"] is None
    assert final["error_message"] == "Recursos opcionales omitidos en: toku"
    assert etl.full_sync_status(["toku"], [], [], ["toku"]) == "partial"
