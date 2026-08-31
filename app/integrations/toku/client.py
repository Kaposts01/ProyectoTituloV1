from typing import Any, Self

import httpx

from app.core.config import settings


class TokuClient:
    """Client for the Toku API (x-api-key authentication)."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.toku_base_url.rstrip("/"),
            timeout=settings.toku_timeout_seconds,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "x-api-key": settings.toku_api_key,
            },
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ #
    # Checkout Session                                                     #
    # ------------------------------------------------------------------ #

    async def create_checkout_session(self, data: dict[str, Any]) -> Any:
        return await self._post("/cl/checkout-sessions", data)

    # ------------------------------------------------------------------ #
    # Customers                                                            #
    # ------------------------------------------------------------------ #

    async def list_customers(self, page_size: int = 100) -> Any:
        return await self._get("/customers", params={"page_size": page_size})

    async def create_customer(self, data: dict[str, Any]) -> Any:
        return await self._post("/customers", data)

    async def lookup_customer(self, mail: str) -> Any:
        return await self._get("/customers/lookup", params={"mail": mail})

    async def get_customer(self, customer_id: str) -> Any:
        return await self._get(f"/customers/{customer_id}")

    async def update_customer(self, customer_id: str, data: dict[str, Any]) -> Any:
        return await self._put(f"/customers/{customer_id}", data)

    async def delete_customer(self, customer_id: str) -> Any:
        return await self._delete(f"/customers/{customer_id}")

    async def list_customer_invoices(self, customer_id: str) -> Any:
        return await self._get(f"/customers/{customer_id}/invoices")

    # ------------------------------------------------------------------ #
    # Invoices                                                             #
    # ------------------------------------------------------------------ #

    async def list_invoices(self, page_size: int = 100) -> Any:
        return await self._get("/invoices", params={"page_size": page_size})

    async def create_invoice(self, data: dict[str, Any]) -> Any:
        return await self._post("/invoices", data)

    async def lookup_invoice(self, invoice_external_id: str) -> Any:
        return await self._get("/invoices/lookup", params={"invoice_external_id": invoice_external_id})

    async def list_chargeable_invoices(self, page_size: int = 100) -> Any:
        return await self._get("/invoices/chargeable", params={"page_size": page_size})

    async def list_invoices_by_customer(self, customer_id: str) -> Any:
        return await self._get(f"/invoices/customer/{customer_id}")

    async def get_invoice(self, invoice_id: str) -> Any:
        return await self._get(f"/invoices/{invoice_id}")

    async def update_invoice(self, invoice_id: str, data: dict[str, Any]) -> Any:
        return await self._put(f"/invoices/{invoice_id}", data)

    async def void_invoice(self, invoice_id: str, data: dict[str, Any]) -> Any:
        return await self._post(f"/invoices/{invoice_id}/void", data)

    async def delete_invoice(self, invoice_id: str) -> Any:
        return await self._delete(f"/invoices/{invoice_id}")

    # ------------------------------------------------------------------ #
    # Payment Methods                                                      #
    # ------------------------------------------------------------------ #

    async def list_payment_methods(self, page: int = 1, page_size: int = 100) -> Any:
        return await self._get("/payment-methods", params={"page": page, "page_size": page_size})

    async def create_payment_method(self, data: dict[str, Any]) -> Any:
        return await self._post("/payment-methods", data)

    async def get_payment_method(self, pm_id: str) -> Any:
        return await self._get(f"/payment-methods/{pm_id}")

    async def update_payment_method(self, pm_id: str, data: dict[str, Any]) -> Any:
        return await self._put(f"/payment-methods/{pm_id}", data)

    async def delete_payment_method(self, pm_id: str) -> Any:
        return await self._delete(f"/payment-methods/{pm_id}")

    async def batch_clabe_inscription(self, data: dict[str, Any]) -> Any:
        return await self._post("/payment-methods/batch", data)

    async def list_payment_methods_by_customer(self, customer_id: str) -> Any:
        return await self._get(f"/payment-methods/customer/{customer_id}")

    async def associate_to_subscription(self, pm_id: str, data: dict[str, Any]) -> Any:
        return await self._post(f"/payment-methods/{pm_id}/subscriptions", data)

    async def bulk_associate_subscriptions(self, data: dict[str, Any]) -> Any:
        return await self._post("/payment-methods/subscriptions/bulk", data)

    # ------------------------------------------------------------------ #
    # Subscriptions                                                        #
    # ------------------------------------------------------------------ #

    async def list_subscriptions(self, page: int = 1, page_size: int = 100) -> Any:
        return await self._get("/subscriptions", params={"page": page, "page_size": page_size})

    async def create_subscription(self, data: dict[str, Any]) -> Any:
        return await self._post("/subscriptions", data)

    async def lookup_subscription(self, product_id: str) -> Any:
        return await self._get("/subscriptions/lookup", params={"product_id": product_id})

    async def list_subscriptions_by_customer(self, customer_id: str) -> Any:
        return await self._get(f"/subscriptions/customer/{customer_id}")

    async def get_subscription(self, subscription_id: str) -> Any:
        return await self._get(f"/subscriptions/{subscription_id}")

    async def update_subscription(self, subscription_id: str, data: dict[str, Any]) -> Any:
        return await self._put(f"/subscriptions/{subscription_id}", data)

    async def change_subscription_status(self, subscription_id: str, data: dict[str, Any]) -> Any:
        return await self._post(f"/subscriptions/{subscription_id}/status", data)

    async def delete_subscription(self, subscription_id: str) -> Any:
        return await self._delete(f"/subscriptions/{subscription_id}")

    # ------------------------------------------------------------------ #
    # Transactions                                                         #
    # ------------------------------------------------------------------ #

    async def list_transactions(self, page: int = 1, page_size: int = 100) -> Any:
        return await self._get("/transactions", params={"page": page, "page_size": page_size})

    # ------------------------------------------------------------------ #
    # Payments                                                             #
    # ------------------------------------------------------------------ #

    async def list_payments(self, page: int = 1, page_size: int = 100) -> Any:
        return await self._get("/organization/payments", params={"page": page, "page_size": page_size})

    # ------------------------------------------------------------------ #
    # HTTP primitives                                                      #
    # ------------------------------------------------------------------ #

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def _post(self, path: str, data: dict[str, Any]) -> Any:
        response = await self._client.post(path, json=data)
        response.raise_for_status()
        return response.json()

    async def _put(self, path: str, data: dict[str, Any]) -> Any:
        response = await self._client.put(path, json=data)
        response.raise_for_status()
        return response.json()

    async def _delete(self, path: str) -> Any:
        response = await self._client.delete(path)
        response.raise_for_status()
        return response.json()
