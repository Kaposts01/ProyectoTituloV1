import asyncio
from typing import Any, Self

import httpx

from app.core.config import settings
from app.integrations.virtualpos.auth import build_signature


class VirtualPOSClient:
    """Client for the VirtualPOS API (v3). Supports both account 1 and account 2."""

    def __init__(self, platform: str = "virtualpos1") -> None:
        if platform == "virtualpos2":
            base_url = settings.virtualpos2_base_url
            api_key = settings.virtualpos2_api_key
            secret_key = settings.virtualpos2_secret_key
        else:
            base_url = settings.virtualpos_base_url
            api_key = settings.virtualpos_api_key
            secret_key = settings.virtualpos_secret_key

        if not base_url or not api_key:
            raise RuntimeError(f"VirtualPOS {platform} is not configured")

        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=settings.virtualpos_timeout_seconds,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": api_key,
                "Signature": build_signature(api_key, secret_key),
            },
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def list_clients(self, page: int = 1, limit: int = 100) -> Any:
        return await self._get("/v3/clients", params={"page": page, "limit": limit})

    async def get_client(self, client_id: str) -> Any:
        return await self._get(f"/v3/client/{client_id}")

    async def update_client(self, client_id: str, data: dict[str, Any]) -> Any:
        response = await self._client.put(f"/v3/client/{client_id}", json=data)
        response.raise_for_status()
        return response.json()

    async def create_client(self, data: dict[str, Any]) -> Any:
        response = await self._client.post("/v3/client", json=data)
        response.raise_for_status()
        return response.json()

    async def list_plans(self) -> Any:
        return await self._get("/v3/plans")

    async def get_plan(self, plan_id: str) -> Any:
        return await self._get(f"/v3/plan/{plan_id}")

    async def create_plan(self, data: dict[str, Any]) -> Any:
        response = await self._client.post("/v3/plan", json=data)
        response.raise_for_status()
        return response.json()

    async def list_subscriptions(self, page: int = 1, limit: int = 100) -> Any:
        return await self._get("/v3/suscriptions", params={"page": page, "limit": limit})

    async def get_subscription(self, subscription_id: str) -> Any:
        return await self._get(f"/v3/suscription/{subscription_id}")

    async def cancel_subscription(self, subscription_id: str) -> Any:
        response = await self._client.delete(f"/v3/suscription/{subscription_id}")
        response.raise_for_status()
        return response.json()

    async def create_card_change_link(self, subscription_id: str) -> Any:
        response = await self._client.put(f"/v3/suscription/{subscription_id}/changecard")
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    async def create_subscription(self, data: dict[str, Any]) -> Any:
        response = await self._client.post("/v3/suscription", json=data)
        response.raise_for_status()
        return response.json()

    async def list_payments(self, page: int = 1, limit: int = 100) -> Any:
        return await self._get("/v3/payments", params={"page": page, "limit": limit})

    async def get_payment(self, payment_uuid: str) -> Any:
        return await self._get(f"/v3/payment/{payment_uuid}")

    async def delete_payment(self, payment_uuid: str) -> Any:
        response = await self._client.delete(f"/v3/payment/{payment_uuid}")
        response.raise_for_status()
        return response.json()

    async def list_charges(self, subscription_id: str, page: int = 1, limit: int = 100) -> Any:
        return await self._get(f"/v3/suscription/{subscription_id}/charges", params={"page": page, "limit": limit})

    async def get_charge(self, charge_id: str) -> Any:
        return await self._get(f"/v3/charge/{charge_id}")

    async def create_charge(self, data: dict[str, Any]) -> Any:
        response = await self._client.post("/v3/charge", json=data)
        response.raise_for_status()
        return response.json()

    async def delete_charge(self, charge_id: str) -> Any:
        response = await self._client.delete(f"/v3/charge/{charge_id}")
        response.raise_for_status()
        if not response.content:
            return {}
        try:
            return response.json()
        except Exception:
            return {}

    async def retry_charge(self, charge_id: str) -> Any:
        return await self._get(f"/v3/charge/{charge_id}/retry")

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        for attempt in range(settings.virtualpos_read_retries + 1):
            try:
                response = await self._client.get(path, params=params)
                break
            except httpx.ReadTimeout:
                if attempt == settings.virtualpos_read_retries:
                    raise
                await asyncio.sleep(2**attempt)
        response.raise_for_status()
        try:
            return response.json()
        except Exception:
            return {}
