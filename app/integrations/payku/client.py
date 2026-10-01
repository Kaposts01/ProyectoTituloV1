import asyncio
import json
from typing import Any, Self

import httpx

from app.core.config import settings
from app.integrations.payku.auth import build_sign


class PaykuClient:
    """Client for the Payku API (/api/* endpoints)."""

    def __init__(self) -> None:
        api_key = settings.payku_api_key.strip()
        if api_key.lower().startswith("bearer "):
            api_key = api_key[7:].strip()
        self._client = httpx.AsyncClient(
            base_url=settings.payku_base_url.rstrip("/"),
            timeout=settings.payku_timeout_seconds,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ #
    # Clientes de Suscripción (/api/suclient)                              #
    # ------------------------------------------------------------------ #

    async def create_client(self, data: dict[str, Any]) -> Any:
        return await self._post("/api/suclient", data)

    async def update_client(self, identifier: str, data: dict[str, Any]) -> Any:
        return await self._put(f"/api/suclient/{identifier}", data)

    async def get_client(self, identifier: str) -> Any:
        return await self._get(f"/api/suclient/{identifier}")

    async def delete_client(self, identifier: str) -> Any:
        return await self._delete(f"/api/suclient/{identifier}")

    async def list_clients(self, page: int = 1, per_page: int = 50) -> Any:
        return await self._get("/api/suclient/customers", params={"page": page, "per_page": per_page})

    # ------------------------------------------------------------------ #
    # Planes de Suscripción (/api/suplan)                                  #
    # ------------------------------------------------------------------ #

    async def create_plan(self, data: dict[str, Any]) -> Any:
        return await self._post("/api/suplan", data)

    async def get_plan(self, identifier: str) -> Any:
        return await self._get(f"/api/suplan/{identifier}")

    async def list_plans(self) -> Any:
        return await self._get("/api/suplan/plans")

    # ------------------------------------------------------------------ #
    # Suscripciones (/api/sususcription)                                   #
    # ------------------------------------------------------------------ #

    async def create_subscription(self, data: dict[str, Any]) -> Any:
        return await self._post("/api/sususcription", data)

    async def delete_subscription(self, identifier: str) -> Any:
        return await self._delete(f"/api/sususcription/{identifier}")

    async def get_subscription(self, identifier: str) -> Any:
        return await self._get(f"/api/sususcription/{identifier}")

    async def list_subscriptions(
        self,
        page: int = 1,
        per_page: int = 50,
        date_init: str | None = None,
        date_end: str | None = None,
        status: str | None = None,
    ) -> Any:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if date_init is not None:
            params["date_init"] = date_init
        if date_end is not None:
            params["date_end"] = date_end
        if status is not None:
            params["status"] = status
        return await self._get("/api/sususcription", params=params)

    async def list_subscriptions_v3(
        self,
        page: int = 1,
        per_page: int = 50,
        date_init: str | None = None,
        date_end: str | None = None,
        active: bool | None = None,
    ) -> Any:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if date_init is not None:
            params["date_init"] = date_init
        if date_end is not None:
            params["date_end"] = date_end
        if active is not None:
            params["active"] = str(active).lower()
        return await self._get("/api/sususcriptionv3", params=params)

    async def affiliate_card(self, data: dict[str, Any]) -> Any:
        return await self._post("/api/suinscriptionscards", data)

    async def create_consumption_transaction(self, data: dict[str, Any]) -> Any:
        return await self._post("/api/sutransaction", data)

    async def delete_subscription_card(self, data: dict[str, Any]) -> Any:
        return await self._post("/api/suscriptionsdeletecards", data)

    # ------------------------------------------------------------------ #
    # Transacciones (/api/transaction)                                     #
    # ------------------------------------------------------------------ #

    async def create_transaction(self, data: dict[str, Any]) -> Any:
        return await self._post("/api/transaction", data)

    async def get_transaction(self, identifier: str) -> Any:
        return await self._get(f"/api/transaction/{identifier}")

    async def list_transactions(
        self,
        date_init: str | None = None,
        date_end: str | None = None,
        success: bool | None = None,
        pending: bool | None = None,
        rejected: bool | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> Any:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if date_init is not None:
            params["date_init"] = date_init
        if date_end is not None:
            params["date_end"] = date_end
        if success is not None:
            params["success"] = str(success).lower()
        if pending is not None:
            params["pending"] = str(pending).lower()
        if rejected is not None:
            params["rejected"] = str(rejected).lower()
        return await self._get("/api/transaction", params=params)

    # ------------------------------------------------------------------ #
    # Wallet (/api/wallet)                                                 #
    # ------------------------------------------------------------------ #

    async def get_wallet_balance(self) -> Any:
        return await self._get("/api/wallet")

    async def list_wallet_movements(self, page: int = 1, per_page: int = 50) -> Any:
        return await self._get("/api/wallet/list", params={"page": page, "per_page": per_page})

    async def get_wallet_movement(self, identifier: str) -> Any:
        return await self._get(f"/api/wallet/{identifier}")

    async def wallet_withdraw(self, data: dict[str, Any]) -> Any:
        return await self._post("/api/wallet/withdraw", data)

    async def wallet_payout(self, data: dict[str, Any]) -> Any:
        return await self._post("/api/wallet/payout", data)

    async def get_payout(self, identifier: str) -> Any:
        return await self._get(f"/api/payout/{identifier}")

    async def get_payout_v3(self, identifier: str) -> Any:
        return await self._get(f"/api/payoutv3/{identifier}")

    # ------------------------------------------------------------------ #
    # Marketplace (/api/maclient, /api/maaffiliation)                      #
    # ------------------------------------------------------------------ #

    async def create_marketplace_client(self, data: dict[str, Any]) -> Any:
        return await self._post("/api/maclient", data)

    async def update_marketplace_client(self, identifier: str, data: dict[str, Any]) -> Any:
        return await self._put(f"/api/maclient/{identifier}", data)

    async def get_marketplace_client(self, identifier: str) -> Any:
        return await self._get(f"/api/maclient/{identifier}")

    async def delete_marketplace_client(self, identifier: str) -> Any:
        return await self._delete(f"/api/maclient/{identifier}")

    async def create_affiliation(self, data: dict[str, Any]) -> Any:
        return await self._post("/api/maaffiliation", data)

    async def get_affiliation(self, identifier: str) -> Any:
        return await self._get(f"/api/maaffiliation/{identifier}")

    async def delete_affiliation(self, identifier: str) -> Any:
        return await self._delete(f"/api/maaffiliation/{identifier}")

    # ------------------------------------------------------------------ #
    # Mall (/api/mall)                                                     #
    # ------------------------------------------------------------------ #

    async def create_mall_transaction(self, data: dict[str, Any]) -> Any:
        return await self._post("/api/mall", data)

    async def get_mall_transaction(self, identifier: str) -> Any:
        return await self._get(f"/api/mall/{identifier}")

    # ------------------------------------------------------------------ #
    # Anulación (/api/nullification)                                       #
    # ------------------------------------------------------------------ #

    async def create_nullification(self, data: dict[str, Any]) -> Any:
        return await self._post("/api/nullification", data)

    async def get_nullification(self, identifier: str) -> Any:
        return await self._get(f"/api/nullification/{identifier}")

    # ------------------------------------------------------------------ #
    # Evento (/api/event)                                                  #
    # ------------------------------------------------------------------ #

    async def create_event(self, data: dict[str, Any]) -> Any:
        return await self._post("/api/event", data)

    async def get_event(self, identifier: str) -> Any:
        return await self._get(f"/api/event/{identifier}")

    # ------------------------------------------------------------------ #
    # Utilitarios                                                          #
    # ------------------------------------------------------------------ #

    async def get_banks(self, currency: str = "clp") -> Any:
        return await self._get("/api/banks", params={"currency": currency})

    async def get_payment_methods(self) -> Any:
        return await self._get("/api/paymentmethods")

    async def get_payment_methods_by_currency(self, currency: str) -> Any:
        return await self._get("/api/paymentmethods", params={"currency": currency})

    async def get_conciliations(self, data: dict[str, Any]) -> Any:
        return await self._post("/api/conciliation", data)

    async def authorize_escrow(self, data: dict[str, Any]) -> Any:
        return await self._post("/api/escrow", data)

    # ------------------------------------------------------------------ #
    # HTTP primitives                                                      #
    # ------------------------------------------------------------------ #

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        for attempt in range(settings.payku_read_retries + 1):
            try:
                response = await self._client.get(
                    path,
                    params=params,
                    headers={"Sign": build_sign(path, params or {}, settings.payku_secret_key)},
                )
                break
            except (httpx.ReadTimeout, httpx.ReadError, httpx.ConnectError):
                if attempt == settings.payku_read_retries:
                    raise
                await asyncio.sleep(2**attempt)
        response.raise_for_status()
        return response.json()

    async def _post(self, path: str, data: dict[str, Any]) -> Any:
        body = json.dumps(data, separators=(",", ":"))
        sign = build_sign(path, data, settings.payku_secret_key)
        response = await self._client.post(
            path,
            content=body,
            headers={"Content-Type": "application/json", "Sign": sign},
        )
        response.raise_for_status()
        return response.json()

    async def _put(self, path: str, data: dict[str, Any]) -> Any:
        body = json.dumps(data, separators=(",", ":"))
        sign = build_sign(path, data, settings.payku_secret_key)
        response = await self._client.put(
            path,
            content=body,
            headers={"Content-Type": "application/json", "Sign": sign},
        )
        response.raise_for_status()
        return response.json()

    async def _delete(self, path: str) -> Any:
        response = await self._client.delete(path)
        response.raise_for_status()
        return response.json()
