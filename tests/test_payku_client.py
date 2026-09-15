import asyncio

import httpx

from app.core.config import settings
from app.integrations.payku import client as payku_client
from app.integrations.payku.auth import build_sign
from app.integrations.payku.client import PaykuClient


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
    monkeypatch.setattr(payku_client.asyncio, "sleep", no_sleep)
    http_client = PaykuTimeoutThenSuccessClient()
    client = PaykuClient()
    original_client = client._client
    client._client = http_client  # type: ignore[assignment]

    async def read() -> dict[str, list]:
        await original_client.aclose()
        return await client._get("/api/transaction")

    assert asyncio.run(read()) == {"data": []}
    assert http_client.calls == 2


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
