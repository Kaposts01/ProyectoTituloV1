import asyncio

import httpx
import pytest

from app.core.config import settings
from app.integrations.virtualpos.client import VirtualPOSClient


class _TimeoutThenOk:
    """Falla con ReadTimeout las primeras `fail` veces y luego responde 200."""

    def __init__(self, fail: int) -> None:
        self.fail = fail
        self.calls = 0

    async def get(self, path, params=None):
        self.calls += 1
        if self.calls <= self.fail:
            raise httpx.ReadTimeout("timeout")
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("GET", "https://example.test" + path))


def _client(fake) -> VirtualPOSClient:
    client = VirtualPOSClient.__new__(VirtualPOSClient)  # sin red ni credenciales
    client._client = fake
    return client


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def _instant(_seconds):
        return None

    monkeypatch.setattr("app.integrations.virtualpos.client.asyncio.sleep", _instant)
    monkeypatch.setattr(settings, "virtualpos_read_retries", 2)


def test_lecturas_normales_se_reintentan_ante_timeout():
    fake = _TimeoutThenOk(fail=2)
    assert asyncio.run(_client(fake).get_charge("c1")) == {"ok": True}
    assert fake.calls == 3


def test_retry_charge_no_se_reintenta_ante_timeout():
    # /retry cambia estado: un timeout no puede disparar un segundo reintento de cobro.
    fake = _TimeoutThenOk(fail=1)
    with pytest.raises(httpx.ReadTimeout):
        asyncio.run(_client(fake).retry_charge("c1"))
    assert fake.calls == 1


def test_retry_charge_exitoso_hace_una_sola_llamada():
    fake = _TimeoutThenOk(fail=0)
    assert asyncio.run(_client(fake).retry_charge("c1")) == {"ok": True}
    assert fake.calls == 1
