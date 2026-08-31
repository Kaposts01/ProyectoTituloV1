from typing import Any, Self

import httpx

from app.core.config import settings
from app.integrations.virtualpos.auth import build_signature


class VirtualPOSClient:
    """Client for the VirtualPOS Sandbox API (v3)."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.virtualpos_base_url.rstrip("/"),
            timeout=settings.virtualpos_timeout_seconds,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": settings.virtualpos_api_key,
                "Signature": build_signature(settings.virtualpos_api_key, settings.virtualpos_secret_key),
            },
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def list_clients(self) -> Any:
        return await self._get("/v3/clients")

    async def list_plans(self) -> Any:
        return await self._get("/v3/plans")

    async def list_subscriptions(self, page: int = 1, limit: int = 100) -> Any:
        return await self._get("/v3/suscriptions", params={"page": page, "limit": limit})

    async def list_payments(self) -> Any:
        return await self._get("/v3/payments")

    async def list_charges(self, subscription_id: str) -> Any:
        return await self._get(f"/v3/suscription/{subscription_id}/charges")

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()
