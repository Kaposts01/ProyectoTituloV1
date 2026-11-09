import asyncio

import httpx
import pytest

from app.core.config import Settings, settings
from app.integrations import http_retry
from app.integrations.payku import client as payku_client
from app.integrations.payku.auth import build_sign
from app.integrations.payku.client import PaykuClient, normalize_base_url


@pytest.fixture(autouse=True)
def _payku_settings(monkeypatch):
    """Credenciales sinteticas: los tests no dependen de las llaves reales del .env local."""
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "payku_base_url", "https://payku.example.test")
    monkeypatch.setattr(settings, "payku_api_key", "test-public-token")
    monkeypatch.setattr(settings, "payku_secret_key", "test-secret-key")


class PaykuTimeoutThenSuccessClient:
    def __init__(self) -> None:
        self.calls = 0

    async def get(self, path: str, **_: object) -> httpx.Response:
        self.calls += 1
        if self.calls == 1:
            raise httpx.ReadTimeout("provider did not respond")
        return httpx.Response(200, json={"data": []}, request=httpx.Request("GET", path))


def test_payku_client_sends_public_token_as_bearer() -> None:
    client = PaykuClient()
    try:
        expected_token = settings.payku_api_key.removeprefix("Bearer ").strip()
        assert client._client.headers["Authorization"] == f"Bearer {expected_token}"
    finally:
        asyncio.run(client._client.aclose())


def test_payku_client_retries_read_timeout(monkeypatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(settings, "payku_read_retries", 1)
    monkeypatch.setattr(http_retry.asyncio, "sleep", no_sleep)
    http_client = PaykuTimeoutThenSuccessClient()
    client = PaykuClient()
    original_client = client._client
    client._client = http_client  # type: ignore[assignment]

    async def read() -> dict[str, list]:
        await original_client.aclose()
        return await client._get("/api/transaction")

    assert asyncio.run(read()) == {"data": []}
    assert http_client.calls == 2


def test_payku_delete_sends_sign_header(monkeypatch) -> None:
    # T3: Regression BUG-PK-02 — _delete must include Sign header (was missing before fix)
    # Found by /qa on 2026-10-20
    captured: dict = {}

    class CapturingDeleteClient:
        async def delete(self, path: str, **kwargs: object) -> httpx.Response:
            captured["path"] = path
            captured["headers"] = dict(kwargs.get("headers", {}))
            return httpx.Response(200, json={}, request=httpx.Request("DELETE", path))

    monkeypatch.setattr(settings, "payku_secret_key", "fe551abcef62fcf002dc598922e68f0a")
    client = PaykuClient()
    original = client._client
    client._client = CapturingDeleteClient()  # type: ignore[assignment]

    async def run() -> None:
        await original.aclose()
        await client._delete("/api/suclient/test-id")

    asyncio.run(run())
    assert "Sign" in captured["headers"], "_delete must send Sign header (BUG-PK-02)"
    expected_sign = build_sign("/api/suclient/test-id", {}, "fe551abcef62fcf002dc598922e68f0a")
    assert captured["headers"]["Sign"] == expected_sign


def test_payku_signature_matches_documented_example() -> None:
    signature = build_sign(
        "/api/suclient",
        {
            "email": "johndoe@example.com",
            "name": "John Doe",
            "phone": "923122312",
            "address": "Moneda 101",
            "country": "Chile",
            "region": "Metropolitana",
            "city": "Santiago",
            "postal_code": "850000",
            "additional_parameters": {"parameter_1": "example"},
        },
        "fe551abcef62fcf002dc598922e68f0a",
    )

    assert signature == "c9c86202b1246f6ebeb080d08b3b99a22d36d0e8cffb7fd4e65af0fea4dd12bb"


# d183: la doc oficial publica la base como `https://<host>/api`; el cliente ya agrega `/api/...` a cada ruta.
_SANDBOX_BASES = ("https://des.payku.cl", "https://des.payku.cl/", "https://des.payku.cl/api", "https://des.payku.cl/api/")
_PRODUCTION_BASES = ("https://app.payku.cl", "https://app.payku.cl/", "https://app.payku.cl/api", "https://app.payku.cl/api/")


def _request_url(monkeypatch, cfg: Settings) -> str:
    monkeypatch.setattr(payku_client, "settings", cfg)
    client = payku_client.PaykuClient()
    try:
        return str(client._client.build_request("GET", "/api/transaction").url)
    finally:
        asyncio.run(client._client.aclose())


@pytest.mark.parametrize("base", _SANDBOX_BASES)
def test_payku_sandbox_base_url_does_not_duplicate_api(monkeypatch, base: str) -> None:
    cfg = Settings(
        _env_file=None,
        app_env="sandbox",
        database_url="postgresql+psycopg://u:p@localhost/crm",
        sandbox_database_url="postgresql+psycopg://u:p@localhost/crm_sandbox",
        payku_sandbox_base_url=base,
        payku_sandbox_public_token="sbx-pk-public",
        payku_sandbox_private_token="sbx-pk-private",
    )
    assert _request_url(monkeypatch, cfg) == "https://des.payku.cl/api/transaction"


@pytest.mark.parametrize("base", _PRODUCTION_BASES)
def test_payku_production_base_url_does_not_duplicate_api(monkeypatch, base: str) -> None:
    cfg = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql+psycopg://u:p@localhost/crm",
        virtualpos_base_url="https://api.virtualpos.cl",
        virtualpos_api_key="prod-vk",
        virtualpos_secret_key="prod-vs",
        payku_base_url=base,
        payku_api_key="prod-pk-public",
        payku_secret_key="prod-pk-private",
    )
    assert _request_url(monkeypatch, cfg) == "https://app.payku.cl/api/transaction"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://app.payku.cl/API/", "https://app.payku.cl"),
        ("  https://des.payku.cl/api  ", "https://des.payku.cl"),
        ("https://payku.example.test/apis", "https://payku.example.test/apis"),
        ("https://payku.example.test/v1/api", "https://payku.example.test/v1"),
    ],
)
def test_normalize_base_url_edge_cases(raw: str, expected: str) -> None:
    assert normalize_base_url(raw) == expected
