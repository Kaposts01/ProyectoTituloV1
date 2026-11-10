import json
from typing import Any, Self

import httpx

from app.core.channel_errors import ChannelConfigError
from app.core.config import settings
from app.integrations.http_retry import send_with_retries
from app.integrations.payku.auth import build_sign
from app.integrations.payku.write_guard import (
    PROCESS_STATE,
    assert_sandbox_write_allowed,
)

_ERROR_DETAIL_MAX = 200


class PaykuApiError(Exception):
    """Error de negocio de Payku: HTTP 2xx con cuerpo `{"status": "failed", ...}` (d188).

    La doc oficial indica que muchos errores llegan con HTTP 200, asi que el codigo HTTP no basta. `http_status` es el
    HTTP real; `error_type` y `detail` salen de los campos `type`/`message` del cuerpo (recortados). El cuerpo completo
    no se guarda en el mensaje.
    """

    def __init__(self, method: str, error_type: str | None, detail: str | None, http_status: int) -> None:
        self.method = method
        self.error_type = error_type
        self.detail = detail
        self.http_status = http_status
        label = error_type or "sin tipo"
        suffix = f": {detail}" if detail and detail != error_type else ""
        super().__init__(f"Payku rechazo la operacion {method} ({label}, HTTP {http_status}){suffix}")


def _short(value: Any) -> str | None:
    text = " ".join(str(value).split()) if value is not None else ""
    return text[:_ERROR_DETAIL_MAX] or None


def is_failed_response(body: Any) -> bool:
    """True si el cuerpo es un error de negocio de Payku (`status: "failed"`, sin importar mayusculas)."""
    return isinstance(body, dict) and str(body.get("status") or "").strip().lower() == "failed"


def is_no_records_response(body: Any) -> bool:
    """Pagina vacia de un listado: `{"status": "failed", "type": "there are no records"}`.

    Payku la devuelve al pedir una pagina posterior a la ultima (siempre que el total es multiplo de `per_page`) o
    cuando no hay registros. Se identifica por `status == "failed"` y el texto "no records" en el campo `type`. Solo
    los listados la tratan como coleccion vacia; en cualquier otro endpoint es un error.
    """
    return is_failed_response(body) and "no records" in str(body.get("type") or "").lower()


def _raise_for_failed_body(method: str, response: httpx.Response, body: Any, *, allow_no_records: bool) -> None:
    if not is_failed_response(body):
        return
    if allow_no_records and is_no_records_response(body):
        return
    error_type = _short(body.get("type"))
    detail = _short(body.get("message") or body.get("message_error") or body.get("error"))
    raise PaykuApiError(method, error_type, detail, response.status_code)


def normalize_base_url(url: str) -> str:
    """Base URL sin `/` final ni sufijo `/api` (d183).

    La doc oficial publica la base como `https://des.payku.cl/api` / `https://app.payku.cl/api`, pero las rutas
    del cliente ya incluyen `/api/...` (y la firma `Sign` se calcula sobre esa ruta). Si la variable trae `/api`,
    se quita para no pedir `/api/api/...`.
    """
    base = url.strip().rstrip("/")
    if base.lower().endswith("/api"):
        base = base[: -len("/api")].rstrip("/")
    return base


class PaykuClient:
    """Client for the Payku API (/api/* endpoints)."""

    def __init__(self) -> None:
        if not settings.is_production and not settings.channel_enabled("payku"):
            raise RuntimeError(f"Payku esta deshabilitado en {settings.env_mode} (faltan variables PAYKU_SANDBOX_*)")
        api_key = settings.payku_api_key.strip()
        if api_key.lower().startswith("bearer "):
            api_key = api_key[7:].strip()
        if not api_key or not settings.payku_secret_key.strip():
            missing = tuple(
                name
                for name, value in (("PAYKU_API_KEY", api_key), ("PAYKU_SECRET_KEY", settings.payku_secret_key.strip()))
                if not value
            )
            raise ChannelConfigError("Payku sin credenciales", missing)
        self._client = httpx.AsyncClient(
            base_url=normalize_base_url(settings.payku_base_url),
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
        return await self._get(
            "/api/suclient/customers", params={"page": page, "per_page": per_page}, allow_no_records=True
        )

    # ------------------------------------------------------------------ #
    # Planes de Suscripción (/api/suplan)                                  #
    # ------------------------------------------------------------------ #

    async def create_plan(self, data: dict[str, Any]) -> Any:
        return await self._post("/api/suplan", data)

    async def get_plan(self, identifier: str) -> Any:
        return await self._get(f"/api/suplan/{identifier}")

    async def list_plans(self) -> Any:
        return await self._get("/api/suplan/plans", allow_no_records=True)

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
        return await self._get("/api/sususcription", params=params, allow_no_records=True)

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
        return await self._get("/api/sususcriptionv3", params=params, allow_no_records=True)

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
        return await self._get("/api/transaction", params=params, allow_no_records=True)

    # ------------------------------------------------------------------ #
    # Wallet (/api/wallet)                                                 #
    # ------------------------------------------------------------------ #

    async def get_wallet_balance(self) -> Any:
        return await self._get("/api/wallet")

    async def list_wallet_movements(self, page: int = 1, per_page: int = 50) -> Any:
        return await self._get(
            "/api/wallet/list", params={"page": page, "per_page": per_page}, allow_no_records=True
        )

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

    @staticmethod
    def _decode(method: str, response: httpx.Response, *, allow_no_records: bool = False) -> Any:
        """HTTP no-2xx -> HTTPStatusError; 2xx con `status: "failed"` -> PaykuApiError (d188).

        Excepcion: con `allow_no_records` (solo listados) la pagina vacia "there are no records" se devuelve tal cual
        y el llamador la trata como coleccion vacia.
        """
        response.raise_for_status()
        body = response.json()
        _raise_for_failed_body(method, response, body, allow_no_records=allow_no_records)
        return body

    async def _get(
        self, path: str, params: dict[str, Any] | None = None, *, allow_no_records: bool = False
    ) -> Any:
        # SYNC-D-10: solo las lecturas se reintentan (red, 429 y 5xx, con Retry-After y tope). POST/PUT/DELETE: un intento.
        headers = {"Sign": build_sign(path, params or {}, settings.payku_secret_key)}
        response = await send_with_retries(
            lambda: self._client.get(path, params=params, headers=headers), retries=settings.payku_read_retries
        )
        return self._decode("GET", response, allow_no_records=allow_no_records)

    def _guard_write(self, method: str, path: str, data: Any) -> None:
        """Fuera de produccion toda escritura pasa por las guardas duras (antes de tocar la red). d165."""
        if not settings.is_production:
            assert_sandbox_write_allowed(method, path, data, settings, PROCESS_STATE)

    async def _post(self, path: str, data: dict[str, Any]) -> Any:
        self._guard_write("POST", path, data)
        body = json.dumps(data, separators=(",", ":"))
        sign = build_sign(path, data, settings.payku_secret_key)
        response = await self._client.post(
            path,
            content=body,
            headers={"Content-Type": "application/json", "Sign": sign},
        )
        return self._decode("POST", response)

    async def _put(self, path: str, data: dict[str, Any]) -> Any:
        self._guard_write("PUT", path, data)
        body = json.dumps(data, separators=(",", ":"))
        sign = build_sign(path, data, settings.payku_secret_key)
        response = await self._client.put(
            path,
            content=body,
            headers={"Content-Type": "application/json", "Sign": sign},
        )
        return self._decode("PUT", response)

    async def _delete(self, path: str) -> Any:
        self._guard_write("DELETE", path, None)
        response = await self._client.delete(
            path,
            headers={"Sign": build_sign(path, {}, settings.payku_secret_key)},
        )
        return self._decode("DELETE", response)
