"""CRM-14B: fuera de produccion la sync de Toku no pide `/organization/payments`.

Reproduce las corridas `failed`/`partial` de crm_sandbox: con la llave de sandbox ese endpoint (no documentado en la
referencia publica de Toku) responde 404 siempre. En sandbox/qa el recurso `payment` no se pide, queda omitido en
`resource_stats` con motivo `not_available_in_sandbox` y la corrida termina `completed`. En produccion nada cambia.
Cliente falso y base de pruebas con rollback: no se llama al proveedor.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.services import toku_sync
from tests.test_toku_optional_404 import (  # noqa: F401 (fixture)
    FakeTokuClient,
    _stored,
    db_session,
)


def _settings(mode: str) -> SimpleNamespace:
    return SimpleNamespace(is_production=mode == "production", env_mode=mode, toku_api_key="")


@pytest.mark.parametrize("mode", ["sandbox", "qa"])
def test_sandbox_does_not_request_payments_and_completes(monkeypatch, db_session, mode) -> None:  # noqa: F811
    # El cliente falso responde 404 en payments como el sandbox real; si se pidiera, la corrida quedaria `partial`.
    client = FakeTokuClient({"payment": 404})
    monkeypatch.setattr(toku_sync, "TokuClient", lambda: client)
    monkeypatch.setattr(toku_sync, "settings", _settings(mode))

    run = asyncio.run(toku_sync.sync_toku(db_session))

    assert run.status == "completed" and run.error_message is None
    assert "payment" not in client.calls
    assert run.resource_stats["payment"] == {
        "records": 0, "pages": 0, "skipped": True, "reason": "not_available_in_sandbox",
    }
    assert _stored(db_session, client.token) == {"customer", "subscription", "invoice", "transaction", "payment_method"}


def test_sandbox_still_fails_on_essential_resources(monkeypatch, db_session) -> None:  # noqa: F811
    import httpx

    monkeypatch.setattr(toku_sync, "TokuClient", lambda: FakeTokuClient({"invoice": 404}))
    monkeypatch.setattr(toku_sync, "settings", _settings("sandbox"))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(toku_sync.sync_toku(db_session))


def test_production_still_requests_payments(monkeypatch, db_session) -> None:  # noqa: F811
    client = FakeTokuClient({"payment": 404})
    monkeypatch.setattr(toku_sync, "TokuClient", lambda: client)
    monkeypatch.setattr(toku_sync, "settings", _settings("production"))

    run = asyncio.run(toku_sync.sync_toku(db_session))

    assert "payment" in client.calls
    assert run.status == "partial"
    assert run.resource_stats["payment"]["reason"] == "http_404"
