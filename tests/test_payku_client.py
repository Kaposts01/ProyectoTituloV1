import asyncio

from app.core.config import settings
from app.integrations.payku.auth import build_sign
from app.integrations.payku.client import PaykuClient


def test_payku_client_sends_public_token_as_bearer() -> None:
    client = PaykuClient()
    try:
        expected_token = settings.payku_api_key.removeprefix("Bearer ").strip()
        assert client._client.headers["Authorization"] == f"Bearer {expected_token}"
    finally:
        asyncio.run(client._client.aclose())


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
