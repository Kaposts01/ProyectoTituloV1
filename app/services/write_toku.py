from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.toku.client import TokuClient
from app.models.crm import Client, Subscription
from app.models.source_record import SourceRecord
from app.models.write_run import WriteRun
from app.services.read_only_provider_sync import safe_error_message, sanitize_record


class WriteDisabledError(Exception):
    pass


class CustomerNotFoundError(Exception):
    pass


class SubscriptionNotFoundError(Exception):
    pass


class InvoiceNotFoundError(Exception):
    pass


class ReconciliationRequiredError(Exception):
    pass


def _as_text(value: Any) -> str | None:
    return str(value) if value is not None else None


def _all_secrets() -> tuple[str, ...]:
    return (settings.toku_api_key,)


def _customer_from_response(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    for key in ("customer", "data"):
        value = response.get(key)
        if isinstance(value, dict):
            return value
    return response


def _subscription_from_response(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    for key in ("subscription", "data"):
        value = response.get(key)
        if isinstance(value, dict):
            return value
    return response


def _materialize_client(client: Client, payload: dict[str, Any]) -> None:
    client.raw_payload = payload
    client.first_name = _as_text(payload.get("name"))
    client.email = _as_text(payload.get("mail"))
    client.phone_number = _as_text(payload.get("phone_number"))
    client.social_id = _as_text(payload.get("government_id"))


def _materialize_subscription(sub: Subscription, payload: dict[str, Any]) -> None:
    sub.raw_payload = payload
    customer = payload.get("customer")
    recurring = payload.get("recurring") if isinstance(payload.get("recurring"), dict) else {}
    sub.client_external_id = _as_text(
        (customer.get("id") if isinstance(customer, dict) else None) or payload.get("customer")
    )
    sub.status = _as_text(payload.get("status") or (recurring or {}).get("status"))
    sub.amount = _as_text(payload.get("amount") or (recurring or {}).get("amount"))
    sub.currency = _as_text(payload.get("currency_code") or (recurring or {}).get("currency"))
    sub.suscription_date = _as_text(payload.get("anchor") or (recurring or {}).get("anchor"))
    sub.canceled_at = _as_text(payload.get("end_date") or (recurring or {}).get("end_date"))


async def update_customer(db: Session, customer_id: str, changes: dict[str, Any]) -> Client:
    """Update a Toku customer via PUT /customers/{id}."""
    client = db.scalar(
        select(Client).where(Client.external_id == customer_id, Client.source == "toku")
    )
    if client is None:
        raise CustomerNotFoundError

    if not settings.toku_writes_enabled:
        raise WriteDisabledError

    write_run = WriteRun(
        source="toku",
        resource_type="customer",
        external_id=customer_id,
        operation="update_customer",
        status="pending",
        request_payload=sanitize_record(changes),
    )
    db.add(write_run)
    db.commit()

    try:
        async with TokuClient() as provider:
            await provider.update_customer(customer_id, changes)
            try:
                refreshed = _customer_from_response(await provider.get_customer(customer_id))
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


async def delete_customer(db: Session, customer_id: str) -> Client:
    """Delete a Toku customer via DELETE /customers/{id}."""
    client = db.scalar(
        select(Client).where(Client.external_id == customer_id, Client.source == "toku")
    )
    if client is None:
        raise CustomerNotFoundError

    if not settings.toku_writes_enabled:
        raise WriteDisabledError

    write_run = WriteRun(
        source="toku",
        resource_type="customer",
        external_id=customer_id,
        operation="delete_customer",
        status="pending",
        request_payload={"customer_id": customer_id},
    )
    db.add(write_run)
    db.commit()

    try:
        async with TokuClient() as provider:
            await provider.delete_customer(customer_id)
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


async def change_subscription_status(db: Session, subscription_id: str, status: str) -> Subscription:
    """Change Toku subscription status via POST /subscriptions/{id}/status."""
    sub = db.scalar(
        select(Subscription).where(Subscription.external_id == subscription_id, Subscription.source == "toku")
    )
    if sub is None:
        raise SubscriptionNotFoundError

    if not settings.toku_writes_enabled:
        raise WriteDisabledError

    write_run = WriteRun(
        source="toku",
        resource_type="subscription",
        external_id=subscription_id,
        operation="change_subscription_status",
        status="pending",
        request_payload={"subscription_id": subscription_id, "status": status},
    )
    db.add(write_run)
    db.commit()

    try:
        async with TokuClient() as provider:
            await provider.change_subscription_status(subscription_id, {"status": status})
            try:
                refreshed = _subscription_from_response(await provider.get_subscription(subscription_id))
            except Exception:
                refreshed = None
    except Exception as exc:
        write_run.status = "failed"
        write_run.error_message = safe_error_message(exc, _all_secrets())
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    payload = refreshed or {**dict(sub.raw_payload or {}), "status": status}
    sanitized = sanitize_record(payload)
    write_run.status = "remote_succeeded"
    write_run.response_payload = sanitized
    db.commit()

    try:
        _materialize_subscription(sub, sanitized)
        if not refreshed:
            sub.status = status
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


async def delete_subscription(db: Session, subscription_id: str) -> Subscription:
    """Delete a Toku subscription via DELETE /subscriptions/{id}."""
    sub = db.scalar(
        select(Subscription).where(Subscription.external_id == subscription_id, Subscription.source == "toku")
    )
    if sub is None:
        raise SubscriptionNotFoundError

    if not settings.toku_writes_enabled:
        raise WriteDisabledError

    write_run = WriteRun(
        source="toku",
        resource_type="subscription",
        external_id=subscription_id,
        operation="delete_subscription",
        status="pending",
        request_payload={"subscription_id": subscription_id},
    )
    db.add(write_run)
    db.commit()

    try:
        async with TokuClient() as provider:
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
        deleted_payload = {**dict(sub.raw_payload or {}), "status": "deleted"}
        sub.raw_payload = deleted_payload
        sub.status = "deleted"
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


async def update_invoice(db: Session, invoice_id: str, changes: dict[str, Any]) -> SourceRecord:
    """Update a Toku invoice via PUT /invoices/{id}. Invoices have no canonical model; reconciles SourceRecord only."""
    record = db.scalar(
        select(SourceRecord).where(
            SourceRecord.source == "toku",
            SourceRecord.resource_type == "invoice",
            SourceRecord.external_id == invoice_id,
        )
    )
    if record is None:
        raise InvoiceNotFoundError

    if not settings.toku_writes_enabled:
        raise WriteDisabledError

    write_run = WriteRun(
        source="toku",
        resource_type="invoice",
        external_id=invoice_id,
        operation="update_invoice",
        status="pending",
        request_payload=sanitize_record(changes),
    )
    db.add(write_run)
    db.commit()

    try:
        async with TokuClient() as provider:
            await provider.update_invoice(invoice_id, changes)
            try:
                refreshed = await provider.get_invoice(invoice_id)
            except Exception:
                refreshed = None
    except Exception as exc:
        write_run.status = "failed"
        write_run.error_message = safe_error_message(exc, _all_secrets())
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    payload = refreshed or {**dict(record.payload or {}), **changes}
    sanitized = sanitize_record(payload)
    write_run.status = "remote_succeeded"
    write_run.response_payload = sanitized
    db.commit()

    try:
        record.payload = sanitized
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

    return record


async def delete_invoice(db: Session, invoice_id: str) -> SourceRecord:
    """Delete a Toku invoice via DELETE /invoices/{id}. Marks the SourceRecord payload as deleted."""
    record = db.scalar(
        select(SourceRecord).where(
            SourceRecord.source == "toku",
            SourceRecord.resource_type == "invoice",
            SourceRecord.external_id == invoice_id,
        )
    )
    if record is None:
        raise InvoiceNotFoundError

    if not settings.toku_writes_enabled:
        raise WriteDisabledError

    write_run = WriteRun(
        source="toku",
        resource_type="invoice",
        external_id=invoice_id,
        operation="delete_invoice",
        status="pending",
        request_payload={"invoice_id": invoice_id},
    )
    db.add(write_run)
    db.commit()

    try:
        async with TokuClient() as provider:
            await provider.delete_invoice(invoice_id)
    except Exception as exc:
        write_run.status = "failed"
        write_run.error_message = safe_error_message(exc, _all_secrets())
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    write_run.status = "remote_succeeded"
    db.commit()

    try:
        record.payload = {**dict(record.payload or {}), "status": "deleted"}
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

    return record
