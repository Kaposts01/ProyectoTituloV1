from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.payku.client import PaykuClient
from app.integrations.payku.write_guard import PaykuWriteBlockedError
from app.models.crm import Client, Subscription
from app.models.write_run import WriteRun
from app.services.read_only_provider_sync import safe_error_message, sanitize_record


class WriteDisabledError(Exception):
    pass


class ClientNotFoundError(Exception):
    pass


class SubscriptionNotFoundError(Exception):
    pass


class ReconciliationRequiredError(Exception):
    pass


def _as_text(value: Any) -> str | None:
    return str(value) if value is not None else None


def _all_secrets() -> tuple[str, ...]:
    return (settings.payku_api_key, settings.payku_secret_key)


def _mark_blocked(db: Session, write_run: WriteRun, exc: PaykuWriteBlockedError) -> None:
    """Registra en write_runs una escritura frenada por las guardas duras (nunca llego a la red)."""
    write_run.status = "blocked"
    write_run.error_message = f"{exc.code}: {exc.message}"[:500]
    write_run.finished_at = datetime.now(UTC)
    db.commit()


def _client_from_response(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    for key in ("data", "customer", "client"):
        value = response.get(key)
        if isinstance(value, dict):
            return value
    return response


def _subscription_from_response(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    for key in ("data", "subscription"):
        value = response.get(key)
        if isinstance(value, dict):
            return value
    return response


def _materialize_client(client: Client, payload: dict[str, Any]) -> None:
    client.raw_payload = payload
    client.first_name = _as_text(payload.get("name"))
    client.email = _as_text(payload.get("email"))
    client.phone_number = _as_text(payload.get("phone"))
    client.social_id = _as_text(payload.get("rut"))
    client.status = _as_text(payload.get("status"))


async def update_client(db: Session, client_id: str, changes: dict[str, Any], *, requested_by_user_id: uuid.UUID | None = None) -> Client:
    """Update a Payku subscription client via PUT /api/suclient/{id}."""
    client = db.scalar(
        select(Client).where(Client.external_id == client_id, Client.source == "payku")
    )
    if client is None:
        raise ClientNotFoundError

    if not settings.payku_writes_enabled:
        raise WriteDisabledError

    write_run = WriteRun(
        source="payku",
        resource_type="client",
        external_id=client_id,
        operation="update_client",
        status="pending",
        requested_by_user_id=requested_by_user_id,
        request_payload=sanitize_record(changes),
    )
    db.add(write_run)
    db.commit()

    try:
        async with PaykuClient() as provider:
            await provider.update_client(client_id, changes)
            try:
                refreshed = _client_from_response(await provider.get_client(client_id))
            except Exception:
                refreshed = None
    except PaykuWriteBlockedError as exc:
        _mark_blocked(db, write_run, exc)
        raise
    except Exception as exc:
        write_run.status = "failed"
        write_run.error_message = safe_error_message(exc, _all_secrets())
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    payload = refreshed or {**dict(client.raw_payload or {}), **changes}
    sanitized = sanitize_record(payload)
    write_run.status = "remote_succeeded"
    write_run.response_payload = sanitized
    db.commit()

    try:
        _materialize_client(client, sanitized)
        write_run.status = "completed"
        write_run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        write_run = db.get(WriteRun, write_run.id)
        if write_run is not None:
            write_run.status = "reconciliation_required"
            write_run.error_message = safe_error_message(exc, _all_secrets())
            write_run.finished_at = datetime.now(UTC)
            db.commit()
        raise ReconciliationRequiredError from exc

    return client


async def delete_client(db: Session, client_id: str, *, requested_by_user_id: uuid.UUID | None = None) -> Client:
    """Delete a Payku subscription client via DELETE /api/suclient/{id}."""
    client = db.scalar(
        select(Client).where(Client.external_id == client_id, Client.source == "payku")
    )
    if client is None:
        raise ClientNotFoundError

    if not settings.payku_writes_enabled:
        raise WriteDisabledError

    write_run = WriteRun(
        source="payku",
        resource_type="client",
        external_id=client_id,
        operation="delete_client",
        status="pending",
        requested_by_user_id=requested_by_user_id,
        request_payload={"client_id": client_id},
    )
    db.add(write_run)
    db.commit()

    try:
        async with PaykuClient() as provider:
            await provider.delete_client(client_id)
    except PaykuWriteBlockedError as exc:
        _mark_blocked(db, write_run, exc)
        raise
    except Exception as exc:
        write_run.status = "failed"
        write_run.error_message = safe_error_message(exc, _all_secrets())
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    write_run.status = "remote_succeeded"
    db.commit()

    try:
        deleted_payload = {**dict(client.raw_payload or {}), "status": "deleted"}
        client.raw_payload = deleted_payload
        client.status = "deleted"
        write_run.status = "completed"
        write_run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        write_run = db.get(WriteRun, write_run.id)
        if write_run is not None:
            write_run.status = "reconciliation_required"
            write_run.error_message = safe_error_message(exc, _all_secrets())
            write_run.finished_at = datetime.now(UTC)
            db.commit()
        raise ReconciliationRequiredError from exc

    return client


async def delete_subscription(db: Session, subscription_id: str, *, requested_by_user_id: uuid.UUID | None = None) -> Subscription:
    """Cancel a Payku subscription via DELETE /api/sususcription/{id}."""
    sub = db.scalar(
        select(Subscription).where(Subscription.external_id == subscription_id, Subscription.source == "payku")
    )
    if sub is None:
        raise SubscriptionNotFoundError

    if not settings.payku_writes_enabled:
        raise WriteDisabledError

    write_run = WriteRun(
        source="payku",
        resource_type="subscription",
        external_id=subscription_id,
        operation="delete_subscription",
        status="pending",
        requested_by_user_id=requested_by_user_id,
        request_payload={"subscription_id": subscription_id},
    )
    db.add(write_run)
    db.commit()

    try:
        async with PaykuClient() as provider:
            await provider.delete_subscription(subscription_id)
    except PaykuWriteBlockedError as exc:
        _mark_blocked(db, write_run, exc)
        raise
    except Exception as exc:
        write_run.status = "failed"
        write_run.error_message = safe_error_message(exc, _all_secrets())
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    write_run.status = "remote_succeeded"
    db.commit()

    try:
        cancelled_payload = {**dict(sub.raw_payload or {}), "status": "cancelled"}
        sub.raw_payload = cancelled_payload
        sub.status = "cancelled"
        write_run.status = "completed"
        write_run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        write_run = db.get(WriteRun, write_run.id)
        if write_run is not None:
            write_run.status = "reconciliation_required"
            write_run.error_message = safe_error_message(exc, _all_secrets())
            write_run.finished_at = datetime.now(UTC)
            db.commit()
        raise ReconciliationRequiredError from exc

    return sub


# ---------------------------------------------------------------------------------------------------------------------
# CRM-14F: retiro de fondos de la billetera Payku
# ---------------------------------------------------------------------------------------------------------------------
# Doc oficial (docs.payku.com/cl, seccion Wallet; copia en payku-docs-es.md):
#   GET  /api/wallet           "permite obtener el saldo de tu billetera virtual payku" -> amount_available, currency.
#   POST /api/wallet/withdraw  "permite crear una liquidacion a la cuenta bancaria del comercio utilizando los fondos de
#                              tu billetera virtual payku". Body: subject (<=200), currency (<=6, ISO), order (<=80),
#                              amount (entero, <=14 digitos). 200 -> {"status": "success", "identifier_wallet": "wa..."}.
# La cuenta destino NO es un parametro: es la cuenta bancaria registrada del comercio. La doc no publica monto minimo,
# comision, limite diario ni si `order` es idempotente (preguntas para la ficha). Se retira SIEMPRE todo el disponible,
# y solo si coincide con el monto que la persona confirmo en pantalla (`expected_amount`).

WALLET_CURRENCY = "CLP"
WALLET_ORDER_PREFIX = "crm-wd-"


class WalletWithdrawDisabledError(Exception):
    """PAYKU_WALLET_WITHDRAW_ENABLED apagado (por defecto)."""


class WalletUnavailableError(Exception):
    """No se pudo leer el saldo de la billetera (red, credenciales, respuesta sin `amount_available` o moneda != CLP)."""


class WalletEmptyError(Exception):
    """El saldo disponible es 0: no hay nada que retirar."""


class WalletBalanceChangedError(Exception):
    """El saldo cambio entre la confirmacion y el retiro: se vuelve a pedir confirmacion con el monto nuevo."""

    def __init__(self, current: int) -> None:
        super().__init__("el saldo disponible cambio")
        self.current = current


def wallet_withdraw_enabled() -> bool:
    """El retiro exige su flag propio Y el interruptor general de escrituras de Payku."""
    return bool(settings.payku_wallet_withdraw_enabled and settings.payku_writes_enabled)


def _wallet_available(body: Any) -> tuple[int, str, str | None]:
    if not isinstance(body, dict):
        raise WalletUnavailableError
    try:
        amount = int(str(body.get("amount_available")).strip())
    except (TypeError, ValueError):
        raise WalletUnavailableError from None
    currency = str(body.get("currency") or WALLET_CURRENCY).strip().upper()
    if currency != WALLET_CURRENCY:  # la doc solo muestra CLP; otra moneda no se retira a ciegas
        raise WalletUnavailableError
    wallet_id = body.get("current_id")
    return amount, currency, str(wallet_id) if wallet_id else None


async def _read_wallet(provider: PaykuClient) -> tuple[int, str, str | None]:
    try:
        body = await provider.get_wallet_balance()
    except Exception as exc:  # red, HTTP, PaykuApiError: todo es "no se pudo leer el saldo"
        raise WalletUnavailableError from exc
    return _wallet_available(body)


async def get_wallet_balance() -> dict[str, Any]:
    """Saldo para el boton. Con el flag apagado NO llama a Payku y responde `enabled: false`."""
    if not wallet_withdraw_enabled():
        return {"enabled": False, "amount_available": None, "currency": None}
    try:
        async with PaykuClient() as provider:
            amount, currency, _ = await _read_wallet(provider)
    except WalletUnavailableError:
        raise
    except Exception as exc:  # ChannelConfigError / canal deshabilitado al construir el cliente
        raise WalletUnavailableError from exc
    return {"enabled": True, "amount_available": amount, "currency": currency}


async def withdraw_wallet_balance(
    db: Session, *, expected_amount: int, requested_by_user_id: uuid.UUID | None = None
) -> WriteRun:
    """Consulta el saldo y retira TODO el disponible (POST /api/wallet/withdraw). Registra la escritura en write_runs."""
    if not settings.payku_wallet_withdraw_enabled:
        raise WalletWithdrawDisabledError
    if not settings.payku_writes_enabled:
        raise WriteDisabledError

    try:
        provider = PaykuClient()
    except Exception as exc:
        raise WalletUnavailableError from exc
    async with provider:
        amount, currency, wallet_id = await _read_wallet(provider)
        if amount <= 0:
            raise WalletEmptyError
        if amount != expected_amount:
            raise WalletBalanceChangedError(amount)

        order = f"{WALLET_ORDER_PREFIX}{uuid.uuid4().hex[:20]}"
        data = {"subject": f"Retiro de saldo desde el CRM ({order})", "currency": currency, "order": order, "amount": amount}
        write_run = WriteRun(
            source="payku",
            resource_type="wallet",
            external_id=order,
            operation="wallet_withdraw",
            status="pending",
            requested_by_user_id=requested_by_user_id,
            request_payload={**data, "wallet_current_id": wallet_id},
        )
        db.add(write_run)
        db.commit()

        try:
            response = await provider.wallet_withdraw(data)
        except PaykuWriteBlockedError as exc:
            _mark_blocked(db, write_run, exc)
            raise
        except Exception as exc:
            write_run.status = "failed"
            write_run.error_message = safe_error_message(exc, _all_secrets())
            write_run.finished_at = datetime.now(UTC)
            db.commit()
            raise

    write_run.status = "completed"
    write_run.response_payload = sanitize_record(response if isinstance(response, dict) else {"raw": str(response)[:200]})
    write_run.finished_at = datetime.now(UTC)
    db.commit()
    return write_run
