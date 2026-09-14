from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.payku.client import PaykuClient
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


async def update_client(db: Session, client_id: str, changes: dict[str, Any]) -> Client:
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


async def delete_client(db: Session, client_id: str) -> Client:
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
        request_payload={"client_id": client_id},
    )
    db.add(write_run)
    db.commit()

    try:
        async with PaykuClient() as provider:
            await provider.delete_client(client_id)
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


async def delete_subscription(db: Session, subscription_id: str) -> Subscription:
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
        request_payload={"subscription_id": subscription_id},
    )
    db.add(write_run)
    db.commit()

    try:
        async with PaykuClient() as provider:
            await provider.delete_subscription(subscription_id)
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
