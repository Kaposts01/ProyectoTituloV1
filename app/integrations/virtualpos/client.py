import asyncio
import json
import re
from typing import Any, Self

import httpx

from app.core.config import settings
from app.integrations.virtualpos.auth import build_signature

_ERROR_CODE_RE = re.compile(r"^E-\d{3}$")
_LONG_DIGITS_RE = re.compile(r"\b\d{12,19}\b")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")


def _clean_message(value: Any) -> str:
    """Mensaje del proveedor apto para logs/write_runs: sin control chars, sin secuencias tipo PAN, acotado."""
    text = _CONTROL_RE.sub(" ", str(value or "")).strip()
    return _LONG_DIGITS_RE.sub("[redacted]", text)[:300]


class _ErrorResponse:
    """Respuesta ligera y saneada de un error de negocio de VirtualPOS (compatible con httpx.Response en lo usado)."""

    def __init__(self, status_code: int, body: dict[str, Any]) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self._body = body
        self.text = json.dumps(body, ensure_ascii=False)
        self.content = self.text.encode()

    def json(self) -> dict[str, Any]:
        return dict(self._body)


class VirtualPOSAPIError(Exception):
    """Error de negocio de VirtualPOS: el proveedor responde HTTP 200 con cuerpo `{"status": "NOK", ...}`.

    `http_status` es el HTTP real (normalmente 200); `provider_code` el `code` del cuerpo (p. ej. 400);
    `response.status_code` replica `provider_code` para que los llamadores que mapean HTTPStatusError sigan sirviendo.
    """

    def __init__(
        self, error_code: str | None, message: str, provider_code: int | None, http_status: int | None
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.provider_code = provider_code
        self.http_status = http_status
        status = provider_code if isinstance(provider_code, int) and 400 <= provider_code <= 599 else 400
        error: dict[str, Any] = {"message": message}
        if error_code:
            error["error_code"] = error_code
        self.response = _ErrorResponse(status, {"status": "NOK", "code": provider_code, "error": error})
        label = error_code or "sin código"
        super().__init__(f"VirtualPOS rechazó la operación ({label}, code={provider_code}): {message}")


def _api_error_from_body(body: Any, http_status: int | None) -> VirtualPOSAPIError | None:
    """Devuelve el error si el cuerpo JSON es un NOK de negocio; None si es una respuesta normal."""
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    nok = str(body.get("status") or "").upper() == "NOK"
    if not nok and not (isinstance(error, dict) and error.get("error_code")):
        return None
    detail = error if isinstance(error, dict) else {}
    raw_code = str(detail.get("error_code") or "").strip()
    error_code = raw_code if _ERROR_CODE_RE.match(raw_code) else None
    message = _clean_message(detail.get("message") or (error if isinstance(error, str) else "") or body.get("message"))
    provider_code = body.get("code")
    return VirtualPOSAPIError(
        error_code, message, provider_code if isinstance(provider_code, int) else None, http_status
    )


def _decode(response: httpx.Response, *, lenient: bool = False, empty_ok: bool = False) -> Any:
    """Valida la respuesta: HTTP no-2xx -> HTTPStatusError; NOK/E-nnn con HTTP 200 -> VirtualPOSAPIError."""
    response.raise_for_status()
    if empty_ok and not response.content:
        return {}
    try:
        body = response.json()
    except Exception:
        if lenient:
            return {}
        raise
    api_error = _api_error_from_body(body, response.status_code)
    if api_error is not None:
        raise api_error
    return body


class VirtualPOSClient:
    """Client for the VirtualPOS API (v3). Supports both account 1 and account 2."""

    def __init__(self, platform: str = "virtualpos1") -> None:
        # En sandbox/qa Settings deja la cuenta 2 vacia y la cuenta 1 solo con variables VIRTUALPOS_SANDBOX_*.
        if platform == "virtualpos2":
            base_url = settings.virtualpos2_base_url
            api_key = settings.virtualpos2_api_key
            secret_key = settings.virtualpos2_secret_key
        else:
            base_url = settings.virtualpos_base_url
            api_key = settings.virtualpos_api_key
            secret_key = settings.virtualpos_secret_key

        if not base_url or not api_key or not secret_key:  # sandbox/qa: canal sin variables propias = deshabilitado
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
        return _decode(response)

    async def create_client(self, data: dict[str, Any]) -> Any:
        response = await self._client.post("/v3/client", json=data)
        return _decode(response)

    async def list_plans(self) -> Any:
        return await self._get("/v3/plans")

    async def get_plan(self, plan_id: str) -> Any:
        return await self._get(f"/v3/plan/{plan_id}")

    async def create_plan(self, data: dict[str, Any]) -> Any:
        response = await self._client.post("/v3/plan", json=data)
        return _decode(response)

    async def list_subscriptions(self, page: int = 1, limit: int = 100) -> Any:
        return await self._get("/v3/suscriptions", params={"page": page, "limit": limit})

    async def get_subscription(self, subscription_id: str) -> Any:
        return await self._get(f"/v3/suscription/{subscription_id}")

    async def cancel_subscription(self, subscription_id: str) -> Any:
        response = await self._client.delete(f"/v3/suscription/{subscription_id}")
        return _decode(response)

    async def create_card_change_link(self, subscription_id: str) -> Any:
        response = await self._client.put(f"/v3/suscription/{subscription_id}/changecard")
        return _decode(response, empty_ok=True)

    async def create_subscription(self, data: dict[str, Any]) -> Any:
        response = await self._client.post("/v3/suscription", json=data)
        return _decode(response)

    async def list_payments(self, page: int = 1, limit: int = 100) -> Any:
        return await self._get("/v3/payments", params={"page": page, "limit": limit})

    async def get_payment(self, payment_uuid: str) -> Any:
        return await self._get(f"/v3/payment/{payment_uuid}")

    async def get_payment_attempts(self, payment_uuid: str) -> Any:
        return await self._get(f"/v3/payment/{payment_uuid}/attempts")

    async def delete_payment(self, payment_uuid: str) -> Any:
        response = await self._client.delete(f"/v3/payment/{payment_uuid}")
        return _decode(response)

    async def list_charges(
        self, subscription_id: str, page: int = 1, limit: int = 100, status: str | None = None
    ) -> Any:
        params: dict[str, Any] = {"page": page, "limit": limit}
        if status:
            params["status"] = status
        return await self._get(f"/v3/suscription/{subscription_id}/charges", params=params)

    async def get_charge(self, charge_id: str) -> Any:
        return await self._get(f"/v3/charge/{charge_id}")

    async def create_charge(self, data: dict[str, Any]) -> Any:
        response = await self._client.post("/v3/charge", json=data)
        return _decode(response)

    async def delete_charge(self, charge_id: str) -> Any:
        response = await self._client.delete(f"/v3/charge/{charge_id}")
        return _decode(response, lenient=True, empty_ok=True)

    async def delete_subscription_charges(self, subscription_id: str) -> Any:
        """DELETE /v3/charges/{suscription_id}: cancela TODOS los cargos pendientes sin cancelar la suscripción.

        Devuelve `cancel_charges[]`; E-079 (HTTP 400) si no hay cargos pendientes.
        """
        response = await self._client.delete(f"/v3/charges/{subscription_id}")
        return _decode(response, lenient=True, empty_ok=True)

    async def retry_charge(self, charge_id: str) -> Any:
        # GET que cambia estado (relanza el cobro): tras un timeout el primer intento pudo ejecutarse, no se reintenta.
        return await self._get(f"/v3/charge/{charge_id}/retry", retry=False)

    async def _get(self, path: str, params: dict[str, Any] | None = None, *, retry: bool = True) -> Any:
        attempts = settings.virtualpos_read_retries + 1 if retry else 1
        for attempt in range(attempts):
            try:
                response = await self._client.get(path, params=params)
                break
            except (httpx.ReadTimeout, httpx.ReadError, httpx.ConnectError):
                if attempt == attempts - 1:
                    raise
                await asyncio.sleep(2**attempt)
        return _decode(response, lenient=True)
