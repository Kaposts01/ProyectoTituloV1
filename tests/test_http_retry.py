"""SYNC-D-10: reintentos de lectura con tope, `Retry-After` y 5xx en VirtualPOS y Payku.

Sin red: los clientes usan `httpx.MockTransport` y `asyncio.sleep` se reemplaza por un registro de esperas.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from app.core.config import settings
from app.integrations import http_retry
from app.integrations.payku.client import PaykuClient
from app.integrations.virtualpos.client import VirtualPOSClient


@pytest.fixture
def sleeps(monkeypatch):
    waits: list[float] = []

    async def _record(seconds):
        waits.append(seconds)

    monkeypatch.setattr(http_retry.asyncio, "sleep", _record)
    monkeypatch.setattr(settings, "http_retry_max_delay_seconds", 30)
    monkeypatch.setattr(settings, "virtualpos_read_retries", 2)
    monkeypatch.setattr(settings, "payku_read_retries", 2)
    monkeypatch.setattr(settings, "payku_secret_key", "test-secret")  # firma de prueba, nunca un secreto real
    return waits


class _Script:
    """Responde en orden la lista de (status, headers); registra metodo y ruta de cada llamada."""

    def __init__(self, *responses: tuple[int, dict[str, str]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        status, headers = self.responses[min(len(self.calls), len(self.responses)) - 1]
        return httpx.Response(status, headers=headers, json={"ok": status < 400})


def _vp(script: _Script) -> VirtualPOSClient:
    client = VirtualPOSClient.__new__(VirtualPOSClient)  # sin credenciales ni red
    client._client = httpx.AsyncClient(base_url="https://vp.test", transport=httpx.MockTransport(script))
    return client


def _payku(script: _Script) -> PaykuClient:
    client = PaykuClient.__new__(PaykuClient)
    client._client = httpx.AsyncClient(base_url="https://payku.test", transport=httpx.MockTransport(script))
    return client


# --- Retry-After ------------------------------------------------------------------------------------------------


def test_retry_after_seconds_and_http_date() -> None:
    now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    seconds = httpx.Response(429, headers={"Retry-After": "7"})
    date = httpx.Response(429, headers={"Retry-After": format_datetime(now + timedelta(seconds=12), usegmt=True)})
    assert http_retry.retry_after_seconds(seconds) == 7
    assert http_retry.retry_after_seconds(date, now=now) == 12
    assert http_retry.retry_after_seconds(httpx.Response(429)) is None
    assert http_retry.retry_after_seconds(httpx.Response(429, headers={"Retry-After": "pronto"})) is None
    assert http_retry.retry_after_seconds(httpx.Response(429, headers={"Retry-After": "-5"})) == 0


def test_vp_429_honours_retry_after(sleeps) -> None:
    script = _Script((429, {"Retry-After": "5"}), (200, {}))
    assert asyncio.run(_vp(script).get_charge("c1")) == {"ok": True}
    assert len(script.calls) == 2
    assert sleeps == [5]


def test_payku_429_honours_retry_after(sleeps) -> None:
    script = _Script((429, {"Retry-After": "3"}), (200, {}))
    assert asyncio.run(_payku(script).get_transaction("t1")) == {"ok": True}
    assert len(script.calls) == 2
    assert sleeps == [3]


def test_retry_after_longer_than_the_cap_is_not_retried(sleeps, monkeypatch) -> None:
    monkeypatch.setattr(settings, "http_retry_max_delay_seconds", 10)
    script = _Script((429, {"Retry-After": "120"}), (200, {}))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(_payku(script).get_transaction("t1"))
    assert len(script.calls) == 1
    assert sleeps == []


# --- 5xx --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_vp_transient_5xx_is_retried_with_backoff(sleeps, status) -> None:
    script = _Script((status, {}), (status, {}), (200, {}))
    assert asyncio.run(_vp(script).list_subscriptions()) == {"ok": True}
    assert len(script.calls) == 3
    assert sleeps == [1, 2]


def test_payku_5xx_is_retried(sleeps) -> None:
    script = _Script((503, {}), (200, {}))
    assert asyncio.run(_payku(script).list_subscriptions()) == {"ok": True}
    assert len(script.calls) == 2


def test_non_transient_4xx_is_not_retried(sleeps) -> None:
    script = _Script((404, {}), (200, {}))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(_payku(script).get_transaction("t1"))
    assert len(script.calls) == 1


# --- Tope -------------------------------------------------------------------------------------------------------


def test_retries_stop_at_the_cap_and_surface_the_error(sleeps) -> None:
    script = _Script((503, {}))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(_payku(script).get_transaction("t1"))
    assert len(script.calls) == settings.payku_read_retries + 1 == 3
    assert sleeps == [1, 2]


def test_backoff_never_exceeds_the_max_delay(sleeps, monkeypatch) -> None:
    monkeypatch.setattr(settings, "http_retry_max_delay_seconds", 1.5)
    monkeypatch.setattr(settings, "virtualpos_read_retries", 3)
    script = _Script((500, {}), (500, {}), (500, {}), (200, {}))
    assert asyncio.run(_vp(script).list_clients()) == {"ok": True}
    assert sleeps == [1, 1.5, 1.5]


def test_network_errors_are_retried_up_to_the_cap(sleeps) -> None:
    calls = 0

    async def send():
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("caida")

    with pytest.raises(httpx.ConnectError):
        asyncio.run(http_retry.send_with_retries(send, retries=2))
    assert calls == 3


# --- Operaciones con efectos: un solo intento ------------------------------------------------------------------


def test_vp_get_with_side_effects_is_never_retried(sleeps) -> None:
    script = _Script((503, {"Retry-After": "1"}), (200, {}))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(_vp(script).retry_charge("c1"))
    assert script.calls == [("GET", "/v3/charge/c1/retry")]
    assert sleeps == []


def test_vp_post_is_never_retried(sleeps) -> None:
    script = _Script((503, {}), (200, {}))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(_vp(script).create_charge({"x": 1}))
    assert script.calls == [("POST", "/v3/charge")]


def test_payku_post_is_never_retried(sleeps) -> None:
    script = _Script((503, {}), (200, {}))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(_payku(script).create_transaction({"x": 1}))
    assert script.calls == [("POST", "/api/transaction")]
    assert sleeps == []
