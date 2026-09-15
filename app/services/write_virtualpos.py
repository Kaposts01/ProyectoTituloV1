from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.virtualpos.client import VirtualPOSClient
from app.models.crm import Charge, Client, Plan, Subscription
from app.models.source_record import SourceRecord
from app.models.write_run import WriteRun
from app.services.read_only_provider_sync import safe_error_message, sanitize_record


class WriteDisabledError(Exception):
    pass


class ClientNotFoundError(Exception):
    pass


class DuplicateClientError(Exception):
    pass


class ChargeNotFoundError(Exception):
    pass


class SubscriptionNotFoundError(Exception):
    pass


class ReconciliationRequiredError(Exception):
    pass


class InvalidClientDataError(Exception):
    pass


def normalize_rut(value: str) -> str:
    compact = "".join(character for character in value.upper() if character not in ".- ")
    if len(compact) < 2 or not compact[:-1].isdigit() or compact[-1] not in "0123456789K":
        raise InvalidClientDataError
    body, check_digit = compact[:-1].lstrip("0") or "0", compact[-1]
    total = sum(int(digit) * (2 + index % 6) for index, digit in enumerate(reversed(body)))
    remainder = total % 11
    expected = "0" if remainder == 0 else "K" if remainder == 1 else str(11 - remainder)
    if check_digit != expected:
        raise InvalidClientDataError
    return f"{body}-{check_digit}"


def _client_payload(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    for key in ("client", "data"):
        value = response.get(key)
        if isinstance(value, dict):
            return value
    return response


def _plan_payload(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    for key in ("plan", "data"):
        value = response.get(key)
        if isinstance(value, dict):
            return value
    return response


def _charge_payload(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    for key in ("charge", "data"):
        value = response.get(key)
        if isinstance(value, dict):
            return value
    return response


def _materialize_client(client: Client, payload: dict[str, Any]) -> None:
    client.raw_payload = payload
    client.first_name = _as_text(payload.get("first_name"))
    client.last_name = _as_text(payload.get("last_name"))
    client.email = _as_text(payload.get("email"))
    client.phone_number = _as_text(payload.get("phone_number", payload.get("phone")))
    client.status = _as_text(payload.get("status"))
    client.social_id = _as_text(payload.get("social_id"))
    client.gender_id = _as_text(payload.get("gender_id"))
    client.birth_date = _as_text(payload.get("birth_date"))


def _materialize_plan(plan: Plan, payload: dict[str, Any]) -> None:
    plan.raw_payload = payload
    plan.name = _as_text(payload.get("name"))
    plan.description = _as_text(payload.get("description"))
    plan.amount = _as_text(payload.get("amount"))
    plan.currency = _as_text(payload.get("currency"))
    plan.plan_type = _as_text(payload.get("type"))
    plan.is_active = _as_text(payload.get("is_active"))
    plan.status = _as_text(payload.get("status"))


def _materialize_charge(charge: "Charge", payload: dict[str, Any]) -> None:
    charge.raw_payload = payload
    charge.subscription_external_id = _as_text(payload.get("suscription_id"))
    charge.client_external_id = _as_text(payload.get("client_id") or payload.get("client_uuid"))
    charge.amount = _as_text(payload.get("amount"))
    charge.currency = _as_text(payload.get("currency"))
    charge.status = _as_text(payload.get("status"))
    charge.charge_date = _as_text(payload.get("charge_date"))


def _subscription_payload(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    for key in ("suscription", "subscription", "data"):
        value = response.get(key)
        if isinstance(value, dict):
            return value
    return response


def _materialize_subscription(sub: "Subscription", payload: dict[str, Any]) -> None:
    sub.raw_payload = payload
    client_obj = payload.get("client")
    sub.client_external_id = _as_text(
        payload.get("client_uuid") or (client_obj.get("uuid") if isinstance(client_obj, dict) else None)
    )
    sub.client_social_id = _as_text(
        client_obj.get("social_id") if isinstance(client_obj, dict) else None
    )
    sub.plan_external_id = _as_text(payload.get("plan_id"))
    sub.service_id = _as_text(payload.get("service_id"))
    sub.status = _as_text(payload.get("status"))
    sub.automatic_renewal = _as_text(payload.get("automatic_renewal") or payload.get("renewal"))
    sub.suscription_date = _as_text(payload.get("suscription_date"))
    sub.canceled_at = _as_text(payload.get("canceled_at"))
    sub.amount = _as_text(payload.get("amount"))
    sub.currency = _as_text(payload.get("currency"))


def _as_text(value: Any) -> str | None:
    return str(value) if value is not None else None


def _check_duplicate_client(db: Session, social_id: str) -> None:
    existing = db.scalar(
        select(Client).where(
            Client.social_id == social_id,
            Client.source.like("virtualpos%"),
        )
    )
    if existing is not None:
        raise DuplicateClientError


async def update_client(db: Session, client_id: str, changes: dict[str, Any]) -> Client:
    """Update a VirtualPOS client, then keep its local and canonical copies aligned."""
    client = db.scalar(
        select(Client).where(Client.external_id == client_id, Client.source.like("virtualpos%"))
    )
    if client is None:
        raise ClientNotFoundError

    all_secrets = (
        settings.virtualpos_api_key, settings.virtualpos_secret_key,
        settings.virtualpos2_api_key, settings.virtualpos2_secret_key,
    )

    private_note = changes.pop("private_note", None)
    if private_note is not None:
        client.private_note = private_note or None
    if not changes:
        db.commit()
        return client

    document_type = changes.get("social_id_type") or str((client.raw_payload or {}).get("social_id_type", ""))
    if "social_id" in changes and document_type in {"1", "RUT"}:
        changes["social_id"] = normalize_rut(str(changes["social_id"]))

    if not settings.virtualpos_writes_enabled:
        raise WriteDisabledError

    write_run = WriteRun(
        source=client.source,
        resource_type="client",
        external_id=client_id,
        operation="update_client",
        status="pending",
        request_payload=sanitize_record(changes),
    )
    db.add(write_run)
    db.commit()

    try:
        async with VirtualPOSClient(platform=client.source) as provider:
            response = await provider.update_client(client_id, changes)
            payload = _client_payload(response)
            if payload is None or not payload:
                payload = _client_payload(await provider.get_client(client_id))
            if payload is None:
                raise RuntimeError("VirtualPOS returned no client payload")
    except Exception as exc:
        write_run.status = "failed"
        write_run.error_message = safe_error_message(exc, all_secrets)
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    sanitized_payload = sanitize_record(payload)
    write_run.status = "remote_succeeded"
    write_run.response_payload = sanitized_payload
    db.commit()

    try:
        source_record = db.scalar(
            select(SourceRecord).where(
                SourceRecord.source == client.source,
                SourceRecord.resource_type == "client",
                SourceRecord.external_id == client_id,
            )
        )
        if source_record is None:
            source_record = SourceRecord(
                source=client.source, resource_type="client", external_id=client_id, payload=sanitized_payload
            )
            db.add(source_record)
        else:
            source_record.payload = sanitized_payload
        _materialize_client(client, sanitized_payload)
        write_run.status = "completed"
        write_run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        write_run = db.get(WriteRun, write_run.id)
        if write_run is not None:
            write_run.status = "reconciliation_required"
            write_run.error_message = safe_error_message(exc, all_secrets)
            write_run.finished_at = datetime.now(UTC)
            db.commit()
        raise ReconciliationRequiredError from exc

    return client


async def create_client(db: Session, data: dict[str, Any]) -> Client:
    """Create a VirtualPOS client and persist its provider response locally."""
    platform = data.pop("platform", "virtualpos1")
    all_secrets = (
        settings.virtualpos_api_key, settings.virtualpos_secret_key,
        settings.virtualpos2_api_key, settings.virtualpos2_secret_key,
    )

    private_note = data.pop("private_note", None)
    if data.get("social_id_type") in {"1", "RUT"}:
        data["social_id"] = normalize_rut(str(data.get("social_id", "")))
    if social_id := data.get("social_id"):
        _check_duplicate_client(db, social_id)
    if not settings.virtualpos_writes_enabled:
        raise WriteDisabledError

    write_run = WriteRun(
        source=platform,
        resource_type="client",
        external_id="pending",
        operation="create_client",
        status="pending",
        request_payload=sanitize_record(data),
    )
    db.add(write_run)
    db.commit()

    try:
        async with VirtualPOSClient(platform=platform) as provider:
            response = await provider.create_client(data)
            payload = _client_payload(response)
            client_id = _as_text((payload or {}).get("uuid"))
            if not client_id:
                raise RuntimeError("VirtualPOS returned no client identifier")
            if payload is None or len(payload) == 1:
                payload = _client_payload(await provider.get_client(client_id))
            if payload is None:
                raise RuntimeError("VirtualPOS returned no client payload")
    except Exception as exc:
        write_run.status = "failed"
        write_run.error_message = safe_error_message(exc, all_secrets)
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    sanitized_payload = sanitize_record(payload)
    write_run.external_id = client_id
    write_run.status = "remote_succeeded"
    write_run.response_payload = sanitized_payload
    db.commit()

    try:
        source_record = db.scalar(
            select(SourceRecord).where(
                SourceRecord.source == "virtualpos",
                SourceRecord.resource_type == "client",
                SourceRecord.external_id == client_id,
            )
        )
        if source_record is None:
            source_record = SourceRecord(
                source="virtualpos", resource_type="client", external_id=client_id, payload=sanitized_payload
            )
            db.add(source_record)
            db.flush()
        else:
            source_record.payload = sanitized_payload
        client = Client(source=platform, external_id=client_id, source_record_id=source_record.id)
        _materialize_client(client, sanitized_payload)
        client.private_note = private_note or None
        db.add(client)
        write_run.status = "completed"
        write_run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        write_run = db.get(WriteRun, write_run.id)
        if write_run is not None:
            write_run.status = "reconciliation_required"
            write_run.error_message = safe_error_message(exc, all_secrets)
            write_run.finished_at = datetime.now(UTC)
            db.commit()
        raise ReconciliationRequiredError from exc

    return client


async def create_plan(db: Session, data: dict[str, Any]) -> Plan:
    """Create a VirtualPOS plan and persist its provider response locally."""
    platform = data.pop("platform", "virtualpos1")
    all_secrets = (
        settings.virtualpos_api_key, settings.virtualpos_secret_key,
        settings.virtualpos2_api_key, settings.virtualpos2_secret_key,
    )

    if not settings.virtualpos_writes_enabled:
        raise WriteDisabledError

    write_run = WriteRun(
        source=platform,
        resource_type="plan",
        external_id="pending",
        operation="create_plan",
        status="pending",
        request_payload=sanitize_record(data),
    )
    db.add(write_run)
    db.commit()

    try:
        async with VirtualPOSClient(platform=platform) as provider:
            response = await provider.create_plan(data)
            payload = _plan_payload(response)
            plan_id = _as_text((payload or {}).get("id") or (payload or {}).get("plan_id"))
            if not plan_id:
                raise RuntimeError("VirtualPOS returned no plan identifier")
            if payload is None or len(payload) <= 1:
                payload = _plan_payload(await provider.get_plan(plan_id))
            if payload is None:
                raise RuntimeError("VirtualPOS returned no plan payload")
    except Exception as exc:
        write_run.status = "failed"
        write_run.error_message = safe_error_message(exc, all_secrets)
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    sanitized_payload = sanitize_record(payload)
    write_run.external_id = plan_id
    write_run.status = "remote_succeeded"
    write_run.response_payload = sanitized_payload
    db.commit()

    try:
        source_record = db.scalar(
            select(SourceRecord).where(
                SourceRecord.source == "virtualpos",
                SourceRecord.resource_type == "plan",
                SourceRecord.external_id == plan_id,
            )
        )
        if source_record is None:
            source_record = SourceRecord(
                source="virtualpos", resource_type="plan", external_id=plan_id, payload=sanitized_payload
            )
            db.add(source_record)
            db.flush()
        else:
            source_record.payload = sanitized_payload
        plan = Plan(source=platform, external_id=plan_id, source_record_id=source_record.id)
        _materialize_plan(plan, sanitized_payload)
        db.add(plan)
        write_run.status = "completed"
        write_run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        write_run = db.get(WriteRun, write_run.id)
        if write_run is not None:
            write_run.status = "reconciliation_required"
            write_run.error_message = safe_error_message(exc, all_secrets)
            write_run.finished_at = datetime.now(UTC)
            db.commit()
        raise ReconciliationRequiredError from exc

    return plan


async def create_charge(db: Session, subscription_id: str, data: dict[str, Any], platform: str = "virtualpos1") -> Charge:
    """Create a VirtualPOS charge on an active subscription and persist the response locally."""
    all_secrets = (
        settings.virtualpos_api_key, settings.virtualpos_secret_key,
        settings.virtualpos2_api_key, settings.virtualpos2_secret_key,
    )

    if not settings.virtualpos_writes_enabled:
        raise WriteDisabledError

    request_data = {"suscription_id": subscription_id, **data}

    write_run = WriteRun(
        source=platform,
        resource_type="charge",
        external_id="pending",
        operation="create_charge",
        status="pending",
        request_payload=sanitize_record(request_data),
    )
    db.add(write_run)
    db.commit()

    try:
        async with VirtualPOSClient(platform=platform) as provider:
            response = await provider.create_charge(request_data)
            payload = _charge_payload(response)
            charge_id = _as_text((payload or {}).get("id") or (payload or {}).get("charge_id"))
            if not charge_id:
                raise RuntimeError("VirtualPOS returned no charge identifier")
            if payload is None or len(payload) <= 1:
                payload = _charge_payload(await provider.get_charge(charge_id))
            if payload is None:
                raise RuntimeError("VirtualPOS returned no charge payload")
    except Exception as exc:
        write_run.status = "failed"
        write_run.error_message = safe_error_message(exc, all_secrets)
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    sanitized_payload = sanitize_record(payload)
    write_run.external_id = charge_id
    write_run.status = "remote_succeeded"
    write_run.response_payload = sanitized_payload
    db.commit()

    try:
        source_record = db.scalar(
            select(SourceRecord).where(
                SourceRecord.source == "virtualpos",
                SourceRecord.resource_type == "charge",
                SourceRecord.external_id == charge_id,
            )
        )
        if source_record is None:
            source_record = SourceRecord(
                source="virtualpos", resource_type="charge", external_id=charge_id, payload=sanitized_payload
            )
            db.add(source_record)
            db.flush()
        else:
            source_record.payload = sanitized_payload
        charge = Charge(source=platform, external_id=charge_id, source_record_id=source_record.id)
        _materialize_charge(charge, sanitized_payload)
        db.add(charge)
        write_run.status = "completed"
        write_run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        write_run = db.get(WriteRun, write_run.id)
        if write_run is not None:
            write_run.status = "reconciliation_required"
            write_run.error_message = safe_error_message(exc, all_secrets)
            write_run.finished_at = datetime.now(UTC)
            db.commit()
        raise ReconciliationRequiredError from exc

    return charge


async def cancel_charge(db: Session, charge_id: str) -> Charge:
    """Cancel a pending VirtualPOS charge via DELETE /v3/charge/{id}."""
    charge = db.scalar(
        select(Charge).where(Charge.external_id == charge_id, Charge.source.like("virtualpos%"))
    )
    if charge is None:
        raise ChargeNotFoundError

    if not settings.virtualpos_writes_enabled:
        raise WriteDisabledError

    all_secrets = (
        settings.virtualpos_api_key, settings.virtualpos_secret_key,
        settings.virtualpos2_api_key, settings.virtualpos2_secret_key,
    )

    write_run = WriteRun(
        source=charge.source,
        resource_type="charge",
        external_id=charge_id,
        operation="cancel_charge",
        status="pending",
        request_payload={"charge_id": charge_id},
    )
    db.add(write_run)
    db.commit()

    try:
        async with VirtualPOSClient(platform=charge.source) as provider:
            await provider.delete_charge(charge_id)
            try:
                refreshed_payload = _charge_payload(await provider.get_charge(charge_id))
            except Exception:
                refreshed_payload = None
    except Exception as exc:
        write_run.status = "failed"
        write_run.error_message = safe_error_message(exc, all_secrets)
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    cancelled_payload = refreshed_payload or dict(charge.raw_payload or {})
    if not refreshed_payload or not refreshed_payload.get("status"):
        cancelled_payload = {**cancelled_payload, "status": "cancelado"}

    sanitized_payload = sanitize_record(cancelled_payload)
    write_run.status = "remote_succeeded"
    write_run.response_payload = sanitized_payload
    db.commit()

    try:
        # BDlocales ya no forma parte del flujo en vivo (ver docs/PLAN_CONSOLIDACION_BDLOCAL.md);
        # basta con reconciliar SourceRecord (staging) y la entidad canónica.
        source_record = db.scalar(
            select(SourceRecord).where(
                SourceRecord.source == charge.source,
                SourceRecord.resource_type == "charge",
                SourceRecord.external_id == charge_id,
            )
        )
        if source_record is None:
            source_record = SourceRecord(
                source=charge.source, resource_type="charge", external_id=charge_id, payload=sanitized_payload
            )
            db.add(source_record)
        else:
            source_record.payload = sanitized_payload
        charge.status = _as_text(sanitized_payload.get("status")) or "cancelado"
        charge.raw_payload = sanitized_payload
        write_run.status = "completed"
        write_run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        write_run = db.get(WriteRun, write_run.id)
        if write_run is not None:
            write_run.status = "reconciliation_required"
            write_run.error_message = safe_error_message(exc, all_secrets)
            write_run.finished_at = datetime.now(UTC)
            db.commit()
        raise ReconciliationRequiredError from exc

    return charge


async def create_subscription(db: Session, data: dict[str, Any]) -> Subscription:
    """Create a VirtualPOS subscription and persist the response locally."""
    platform = data.pop("platform", "virtualpos1")
    all_secrets = (
        settings.virtualpos_api_key, settings.virtualpos_secret_key,
        settings.virtualpos2_api_key, settings.virtualpos2_secret_key,
    )

    # Encode URLs to base64 if provided as plain text
    for url_field in ("return_url", "callback_url"):
        if url_field in data and data[url_field]:
            raw = str(data[url_field])
            if not _is_base64(raw):
                data[url_field] = base64.b64encode(raw.encode()).decode()

    if not settings.virtualpos_writes_enabled:
        raise WriteDisabledError

    write_run = WriteRun(
        source=platform,
        resource_type="subscription",
        external_id="pending",
        operation="create_subscription",
        status="pending",
        request_payload=sanitize_record(data),
    )
    db.add(write_run)
    db.commit()

    try:
        async with VirtualPOSClient(platform=platform) as provider:
            response = await provider.create_subscription(data)
            payload = _subscription_payload(response)
            sub_id = _as_text(
                (payload or {}).get("suscription_id")
                or (payload or {}).get("subscription_id")
                or (payload or {}).get("id")
            )
            if not sub_id:
                raise RuntimeError("VirtualPOS returned no subscription identifier")
            if payload is None or len(payload) <= 1:
                payload = _subscription_payload(await provider.get_subscription(sub_id))
            if payload is None:
                raise RuntimeError("VirtualPOS returned no subscription payload")
    except Exception as exc:
        write_run.status = "failed"
        write_run.error_message = safe_error_message(exc, all_secrets)
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    sanitized_payload = sanitize_record(payload)
    write_run.external_id = sub_id
    write_run.status = "remote_succeeded"
    write_run.response_payload = sanitized_payload
    db.commit()

    try:
        source_record = db.scalar(
            select(SourceRecord).where(
                SourceRecord.source == "virtualpos",
                SourceRecord.resource_type == "subscription",
                SourceRecord.external_id == sub_id,
            )
        )
        if source_record is None:
            source_record = SourceRecord(
                source="virtualpos", resource_type="subscription", external_id=sub_id, payload=sanitized_payload
            )
            db.add(source_record)
            db.flush()
        else:
            source_record.payload = sanitized_payload
        sub = Subscription(source=platform, external_id=sub_id, source_record_id=source_record.id)
        _materialize_subscription(sub, sanitized_payload)
        db.add(sub)
        write_run.status = "completed"
        write_run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        write_run = db.get(WriteRun, write_run.id)
        if write_run is not None:
            write_run.status = "reconciliation_required"
            write_run.error_message = safe_error_message(exc, all_secrets)
            write_run.finished_at = datetime.now(UTC)
            db.commit()
        raise ReconciliationRequiredError from exc

    return sub


def _is_base64(value: str) -> bool:
    try:
        return base64.b64encode(base64.b64decode(value)).decode() == value
    except Exception:
        return False


async def cancel_subscription(db: Session, subscription_id: str) -> Subscription:
    """Cancel an active VirtualPOS subscription via DELETE /v3/suscription/{id}."""
    sub = db.scalar(
        select(Subscription).where(Subscription.external_id == subscription_id, Subscription.source.like("virtualpos%"))
    )
    if sub is None:
        raise SubscriptionNotFoundError

    if not settings.virtualpos_writes_enabled:
        raise WriteDisabledError

    all_secrets = (
        settings.virtualpos_api_key, settings.virtualpos_secret_key,
        settings.virtualpos2_api_key, settings.virtualpos2_secret_key,
    )

    write_run = WriteRun(
        source=sub.source,
        resource_type="subscription",
        external_id=subscription_id,
        operation="cancel_subscription",
        status="pending",
        request_payload={"subscription_id": subscription_id},
    )
    db.add(write_run)
    db.commit()

    try:
        async with VirtualPOSClient(platform=sub.source) as provider:
            await provider.cancel_subscription(subscription_id)
            try:
                refreshed_payload = _subscription_payload(await provider.get_subscription(subscription_id))
            except Exception:
                refreshed_payload = None
    except Exception as exc:
        write_run.status = "failed"
        write_run.error_message = safe_error_message(exc, all_secrets)
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    cancelled_payload = dict(refreshed_payload or sub.raw_payload or {})
    if not refreshed_payload or not refreshed_payload.get("status"):
        cancelled_payload = {**cancelled_payload, "status": "CANCELADA"}

    sanitized_payload = sanitize_record(cancelled_payload)
    write_run.status = "remote_succeeded"
    write_run.response_payload = sanitized_payload
    db.commit()

    try:
        # No se escribe en BDlocales: esa base quedó fuera del flujo en vivo tras la
        # consolidación (ver docs/PLAN_CONSOLIDACION_BDLOCAL.md) y su esquema real ya
        # no tiene las columnas platform/remote_id/raw_payload que este write asumía.
        # Basta con reconciliar el registro tocado en SourceRecord (staging) y en la
        # entidad canónica; no hace falta resincronizar todo el canal.
        source_record = db.scalar(
            select(SourceRecord).where(
                SourceRecord.source == sub.source,
                SourceRecord.resource_type == "subscription",
                SourceRecord.external_id == subscription_id,
            )
        )
        if source_record is None:
            source_record = SourceRecord(
                source=sub.source, resource_type="subscription", external_id=subscription_id, payload=sanitized_payload
            )
            db.add(source_record)
        else:
            source_record.payload = sanitized_payload
        sub.status = _as_text(sanitized_payload.get("status")) or "CANCELADA"
        sub.raw_payload = sanitized_payload
        write_run.status = "completed"
        write_run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        write_run = db.get(WriteRun, write_run.id)
        if write_run is not None:
            write_run.status = "reconciliation_required"
            write_run.error_message = safe_error_message(exc, all_secrets)
            write_run.finished_at = datetime.now(UTC)
            db.commit()
        raise ReconciliationRequiredError from exc

    return sub


async def retry_charge(db: Session, charge_id: str) -> Charge:
    """Retry a rejected VirtualPOS charge via GET /v3/charge/{id}/retry."""
    charge = db.scalar(
        select(Charge).where(Charge.external_id == charge_id, Charge.source.like("virtualpos%"))
    )
    if charge is None:
        raise ChargeNotFoundError

    if not settings.virtualpos_writes_enabled:
        raise WriteDisabledError

    all_secrets = (
        settings.virtualpos_api_key, settings.virtualpos_secret_key,
        settings.virtualpos2_api_key, settings.virtualpos2_secret_key,
    )

    write_run = WriteRun(
        source=charge.source,
        resource_type="charge",
        external_id=charge_id,
        operation="retry_charge",
        status="pending",
        request_payload={"charge_id": charge_id},
    )
    db.add(write_run)
    db.commit()

    try:
        async with VirtualPOSClient(platform=charge.source) as provider:
            await provider.retry_charge(charge_id)
            try:
                refreshed_payload = _charge_payload(await provider.get_charge(charge_id))
            except Exception:
                refreshed_payload = None
    except Exception as exc:
        write_run.status = "failed"
        write_run.error_message = safe_error_message(exc, all_secrets)
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    retried_payload = dict(refreshed_payload or charge.raw_payload or {})
    # If the provider still reports "rechazado" after the retry call, force "procesando"
    # so the retry button is disabled and double-retries are prevented.
    if (retried_payload.get("status") or "").lower() == "rechazado":
        retried_payload = {**retried_payload, "status": "procesando"}
    sanitized_payload = sanitize_record(retried_payload)
    write_run.status = "remote_succeeded"
    write_run.response_payload = sanitized_payload
    db.commit()

    try:
        # BDlocales ya no forma parte del flujo en vivo (ver docs/PLAN_CONSOLIDACION_BDLOCAL.md);
        # basta con reconciliar SourceRecord (staging) y la entidad canónica.
        source_record = db.scalar(
            select(SourceRecord).where(
                SourceRecord.source == charge.source,
                SourceRecord.resource_type == "charge",
                SourceRecord.external_id == charge_id,
            )
        )
        if source_record is None:
            source_record = SourceRecord(
                source=charge.source, resource_type="charge", external_id=charge_id, payload=sanitized_payload
            )
            db.add(source_record)
        else:
            source_record.payload = sanitized_payload
        charge.status = _as_text(sanitized_payload.get("status")) or "procesando"
        charge.raw_payload = sanitized_payload
        write_run.status = "completed"
        write_run.finished_at = datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        write_run = db.get(WriteRun, write_run.id)
        if write_run is not None:
            write_run.status = "reconciliation_required"
            write_run.error_message = safe_error_message(exc, all_secrets)
            write_run.finished_at = datetime.now(UTC)
            db.commit()
        raise ReconciliationRequiredError from exc

    return charge
