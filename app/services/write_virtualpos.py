from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.virtualpos.client import VirtualPOSClient
from app.models.crm import Client, Plan
from app.models.source_record import SourceRecord
from app.models.write_run import WriteRun
from app.services.read_only_provider_sync import safe_error_message, sanitize_record


class WriteDisabledError(Exception):
    pass


class ClientNotFoundError(Exception):
    pass


class DuplicateClientError(Exception):
    pass


class ReconciliationRequiredError(Exception):
    pass


class LocalStateUnavailableError(Exception):
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


def _update_local_client(client_id: str, payload: dict[str, Any], local_plat: str) -> None:
    if not settings.virtualpos_db_url:
        raise RuntimeError("VirtualPOS local database is not configured")

    dsn = settings.virtualpos_db_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE cliente SET raw_payload = %s, synced_at = NOW() "
            "WHERE platform = %s AND remote_id = %s",
            (Jsonb(payload), local_plat, client_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("VirtualPOS client was not found in the local database")


def _create_local_client(client_id: str, payload: dict[str, Any], local_plat: str) -> None:
    if not settings.virtualpos_db_url:
        raise RuntimeError("VirtualPOS local database is not configured")

    dsn = settings.virtualpos_db_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO cliente (platform, remote_id, raw_payload, synced_at) "
            "VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (platform, remote_id) DO UPDATE SET "
            "raw_payload = EXCLUDED.raw_payload, synced_at = EXCLUDED.synced_at",
            (local_plat, client_id, Jsonb(payload)),
        )


def _ensure_local_client_exists(client_id: str, local_plat: str) -> None:
    if not settings.virtualpos_db_url:
        raise RuntimeError("VirtualPOS local database is not configured")

    dsn = settings.virtualpos_db_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM cliente WHERE platform = %s AND remote_id = %s",
            (local_plat, client_id),
        )
        if cursor.fetchone() is None:
            raise RuntimeError("VirtualPOS client was not found in the local database")


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


def _as_text(value: Any) -> str | None:
    return str(value) if value is not None else None


def _local_platform(source: str) -> str:
    return "virtualPOS2" if source == "virtualpos2" else "virtualPOS1"


def _check_duplicate_client(db: Session, social_id: str) -> None:
    existing = db.scalar(
        select(Client).where(
            Client.social_id == social_id,
            Client.source.like("virtualpos%"),
        )
    )
    if existing is not None:
        raise DuplicateClientError


def _create_local_plan(plan_id: str, payload: dict[str, Any], local_plat: str) -> None:
    if not settings.virtualpos_db_url:
        raise RuntimeError("VirtualPOS local database is not configured")

    dsn = settings.virtualpos_db_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO plan (platform, remote_id, raw_payload, synced_at) "
            "VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (platform, remote_id) DO UPDATE SET "
            "raw_payload = EXCLUDED.raw_payload, synced_at = EXCLUDED.synced_at",
            (local_plat, plan_id, Jsonb(payload)),
        )


async def update_client(db: Session, client_id: str, changes: dict[str, Any]) -> Client:
    """Update a VirtualPOS client, then keep its local and canonical copies aligned."""
    client = db.scalar(
        select(Client).where(Client.external_id == client_id, Client.source.like("virtualpos%"))
    )
    if client is None:
        raise ClientNotFoundError

    local_plat = _local_platform(client.source)
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

    try:
        _ensure_local_client_exists(client_id, local_plat)
    except Exception as exc:
        raise LocalStateUnavailableError from exc

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
        _update_local_client(client_id, sanitized_payload, local_plat)
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
    local_plat = _local_platform(platform)
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
        _create_local_client(client_id, sanitized_payload, local_plat)
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
    local_plat = _local_platform(platform)
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
        _create_local_plan(plan_id, sanitized_payload, local_plat)
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
