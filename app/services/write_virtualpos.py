from __future__ import annotations

import base64
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.virtualpos.client import VirtualPOSClient
from app.models.charge_recovery import ChargeRecovery
from app.models.crm import Charge, Client, Payment, Plan, Subscription
from app.models.source_record import SourceRecord
from app.models.vp import VpPlan, VpSubscription
from app.models.write_run import WriteRun
from app.services.read_only_provider_sync import safe_error_message, sanitize_record

log = logging.getLogger(__name__)


class WriteDisabledError(Exception):
    pass


class ClientNotFoundError(Exception):
    pass


class DuplicateClientError(Exception):
    pass


class ChargeNotFoundError(Exception):
    pass


class PaymentNotFoundError(Exception):
    pass


class SubscriptionNotFoundError(Exception):
    pass


class ReconciliationRequiredError(Exception):
    pass


class DuplicateSubscriptionError(Exception):
    pass


class RetryBlockedError(Exception):
    pass


# Códigos de rechazo VirtualPOS → decisión (ver docs/integrations/virtualpos/workflows/reintento-cobro-rechazado.md)
_CARD_CODES = {"-1", "-4", "-5", "-7", "-8", "-9", "-11", "-1013", "-1016"}
_RETRY_CODES = {"-2", "-10"}
_RETRY_ONCE_CODES = {"-6", "-3"}
_MERCHANT_CODES = {"-1003", "-1009", "-1010", "-1014", "-1015"}
_KW_CARD = "vencid|expirad|bloquead|inválid|invalid|robad|perdid|cancelad|no soportad|seguridad|restringid"
_KW_RETRY = "fondo|saldo|cupo|conexi|timeout|temporal|intente|no disponible"


def _classify_rejection(attempts_payload: dict, prior_retries: int = 0) -> str:
    """Clasifica el motivo de rechazo: CAMBIO_TARJETA, REINTENTAR, DIFERIR, MANUAL, DESCONOCIDO."""
    ro = attempts_payload.get("rejected_object") or {}
    code = str(ro.get("code") or ro.get("error_code") or "")
    order = (attempts_payload.get("payment") or {}).get("order") or {}
    cards = order.get("authorization_attempts_cards") or []
    if len(cards) >= 3:
        return "CAMBIO_TARJETA"
    last = max(cards, key=lambda c: c.get("created_at", ""), default={}) if cards else {}
    text = " ".join(filter(None, [
        ro.get("message"),
        last.get("response_description"),
        last.get("response_message"),
    ]))
    if code in _CARD_CODES:
        return "CAMBIO_TARJETA"
    if code in _MERCHANT_CODES:
        return "DIFERIR"
    if code in _RETRY_CODES:
        return "MANUAL" if prior_retries > 0 else "REINTENTAR"
    if code in _RETRY_ONCE_CODES:
        return "CAMBIO_TARJETA" if prior_retries > 0 else "REINTENTAR"
    if re.search(_KW_CARD, text, re.IGNORECASE):
        return "CAMBIO_TARJETA"
    if re.search(_KW_RETRY, text, re.IGNORECASE):
        return "CAMBIO_TARJETA" if prior_retries > 0 else "REINTENTAR"
    return "DESCONOCIDO"


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


def _materialize_charge(charge: Charge, payload: dict[str, Any]) -> None:
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


def _materialize_subscription(sub: Subscription, payload: dict[str, Any]) -> None:
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
    """Update a VirtualPOS client, then keep its local and centralized copies aligned."""
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


async def _find_charge_by_internal_code(provider: Any, subscription_id: str, internal_code: str) -> dict | None:
    """Cargo de la suscripción con ese `internal_code` y estado distinto de `cancelado` (todas las páginas).

    Un fallo del listado se propaga: sin listado no se puede garantizar idempotencia y no se crea el cargo.
    """
    page = 1
    while True:
        response = await provider.list_charges(subscription_id, page=page, limit=100)
        for item in _items(response, "charges"):
            if (
                item.get("id")
                and _as_text(item.get("internal_code")) == internal_code
                and str(item.get("status") or "").strip().lower() != "cancelado"
            ):
                return item
        pages = (response.get("pagination") or {}).get("pages") if isinstance(response, dict) else None
        if not isinstance(pages, int) or page >= pages:
            return None
        page += 1


async def create_charge(db: Session, subscription_id: str, data: dict[str, Any], platform: str = "virtualpos1") -> Charge:
    """Create a VirtualPOS charge on an active subscription and persist the response locally."""
    all_secrets = (
        settings.virtualpos_api_key, settings.virtualpos_secret_key,
        settings.virtualpos2_api_key, settings.virtualpos2_secret_key,
    )

    if not settings.virtualpos_writes_enabled:
        raise WriteDisabledError

    ensure_charge_allowed_on_plan(db, subscription_id, platform)

    request_data = {"suscription_id": subscription_id, **data}
    internal_code = _as_text(data.get("internal_code"))

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

    adopted = False
    try:
        async with VirtualPOSClient(platform=platform) as provider:
            existing = None
            if internal_code:
                # VP no impone idempotencia por internal_code (2 POST = 2 cargos): si un POST previo se cortó por
                # timeout pero el cargo se creó, el reintento lo adopta aquí en vez de duplicarlo.
                existing = await _find_charge_by_internal_code(provider, subscription_id, internal_code)
            if existing is not None:
                adopted = True
                payload = {"suscription_id": subscription_id, **existing}
                charge_id = _as_text(payload.get("id"))
            else:
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
    write_run.response_payload = {"adopted": True, "charge_id": charge_id} if adopted else sanitized_payload
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
        charge = db.scalar(select(Charge).where(Charge.external_id == charge_id, Charge.source == platform))
        if charge is None:
            charge = Charge(source=platform, external_id=charge_id, source_record_id=source_record.id)
            db.add(charge)
        else:
            charge.source_record_id = source_record.id
        _materialize_charge(charge, sanitized_payload)
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
        # BDlocales ya no forma parte del flujo en vivo (ver docs/history/migrations/bdlocales-consolidation-closed.md);
        # basta con reconciliar SourceRecord (staging) y la entidad centralizada.
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


class FixedPlanChargeBlockedError(Exception):
    """POST /v3/charge sobre un plan MONTO_FIJO (o de tipo desconocido) con la bandera apagada."""


FIXED_PLAN_BLOCKED_MESSAGE = (
    "La suscripción pertenece a un plan de monto fijo (o de tipo desconocido); VirtualPOS rechaza cargos "
    "manuales en esos planes (E-113). Active VIRTUALPOS_ALLOW_CHARGE_ON_FIXED_PLAN solo tras validarlo en sandbox."
)


def _provider_error_code(exc: Exception) -> str | None:
    """Extrae el código E-nnn de un error de VirtualPOS (sin exponer el cuerpo completo).

    Prefiere `VirtualPOSAPIError.error_code` (NOK con HTTP 200); respaldo por regex sobre `exc.response.text`
    (HTTPStatusError con HTTP 4xx/5xx).
    """
    code = getattr(exc, "error_code", None)
    if isinstance(code, str) and code:
        return code
    response = getattr(exc, "response", None)
    text = getattr(response, "text", "") or ""
    match = re.search(r"E-\d{3}", text)
    return match.group(0) if match else None


def _plan_type_for_subscription(db: Session, subscription_id: str, platform: str) -> str | None:
    """Tipo de plan según datos locales (core `plans`, luego `vp_plans`); None si se desconoce."""
    plan_external_id = db.scalar(
        select(Subscription.plan_external_id).where(
            Subscription.external_id == subscription_id, Subscription.source == platform
        )
    )
    if plan_external_id is None:
        plan_external_id = db.scalar(
            select(VpSubscription.plan_external_id).where(
                VpSubscription.external_id == subscription_id, VpSubscription.platform == platform
            )
        )
    if not plan_external_id:
        return None
    return db.scalar(
        select(Plan.plan_type).where(Plan.external_id == plan_external_id, Plan.source == platform)
    ) or db.scalar(
        select(VpPlan.plan_type).where(VpPlan.external_id == plan_external_id, VpPlan.platform == platform)
    )


def ensure_charge_allowed_on_plan(db: Session, subscription_id: str, platform: str) -> None:
    """Conservador: solo MONTO_VARIABLE conocido pasa; fijo o desconocido se bloquea salvo bandera explícita."""
    if settings.virtualpos_allow_charge_on_fixed_plan:
        return
    plan_type = (_plan_type_for_subscription(db, subscription_id, platform) or "").strip().upper()
    if plan_type != "MONTO_VARIABLE":
        raise FixedPlanChargeBlockedError(FIXED_PLAN_BLOCKED_MESSAGE)


def _items(response: Any, key: str) -> list[dict[str, Any]]:
    value = response.get(key) if isinstance(response, dict) else None
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


async def _list_pending_charges(provider: Any, subscription_id: str) -> list[dict[str, Any]]:
    """Cargos en estado exactamente `pendiente` (nunca procesando/pagado/rechazado), todas las páginas."""
    pending: list[dict[str, Any]] = []
    page = 1
    while True:
        response = await provider.list_charges(subscription_id, page=page, limit=100, status="pendiente")
        pending.extend(c for c in _items(response, "charges") if c.get("status") == "pendiente" and c.get("id"))
        pages = (response.get("pagination") or {}).get("pages") if isinstance(response, dict) else None
        if not isinstance(pages, int) or page >= pages:
            return pending
        page += 1


def _reconcile_cancelled_charges(db: Session, platform: str, cancelled: list[dict[str, Any]]) -> None:
    for item in cancelled:
        charge_id = _as_text(item.get("id"))
        if not charge_id:
            continue
        charge = db.scalar(select(Charge).where(Charge.external_id == charge_id, Charge.source == platform))
        base = dict(charge.raw_payload or {}) if charge is not None else {}
        payload = sanitize_record({**base, **item, "status": "cancelado"})
        source_record = db.scalar(
            select(SourceRecord).where(
                SourceRecord.source == platform,
                SourceRecord.resource_type == "charge",
                SourceRecord.external_id == charge_id,
            )
        )
        if source_record is None:
            db.add(SourceRecord(source=platform, resource_type="charge", external_id=charge_id, payload=payload))
        else:
            source_record.payload = payload
        if charge is not None:
            charge.status = "cancelado"
            charge.raw_payload = payload


def _resolve_platform(db: Session, subscription_id: str, platform: str | None) -> str:
    if platform:
        return platform
    source = db.scalar(
        select(Subscription.source).where(
            Subscription.external_id == subscription_id, Subscription.source.like("virtualpos%")
        )
    )
    return source or "virtualpos1"


async def cancel_future_charges(
    db: Session,
    subscription_id: str,
    *,
    platform: str | None = None,
    charge_ids: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Cancela cargos FUTUROS `pendiente` de una suscripción sin cancelar la suscripción.

    Sin `charge_ids` usa DELETE /v3/charges/{suscription_id} (plural, solo toca pendientes); con `charge_ids`
    usa DELETE /v3/charge/{id} individual, re-consultando el estado de cada uno justo antes de borrar.
    E-079/E-059 (nada pendiente) son un resultado no-op, no un error. VirtualPOS los devuelve como
    HTTP 200 + cuerpo NOK (VirtualPOSAPIError) o, de forma defensiva, como HTTPStatusError 400.
    """
    platform = _resolve_platform(db, subscription_id, platform)
    all_secrets = (
        settings.virtualpos_api_key, settings.virtualpos_secret_key,
        settings.virtualpos2_api_key, settings.virtualpos2_secret_key,
    )
    result: dict[str, Any] = {
        "subscription_id": subscription_id, "dry_run": dry_run, "cancelled": [], "would_cancel": [],
        "skipped": [], "noop": False, "write_run_id": None,
    }

    if dry_run:  # solo lecturas al proveedor; no hay write_run ni escritura
        async with VirtualPOSClient(platform=platform) as provider:
            pending = await _list_pending_charges(provider, subscription_id)
        wanted = set(charge_ids) if charge_ids is not None else None
        result["would_cancel"] = [c for c in pending if wanted is None or c["id"] in wanted]
        result["noop"] = not result["would_cancel"]
        return result

    if not settings.virtualpos_writes_enabled:
        raise WriteDisabledError

    write_run = WriteRun(
        source=platform,
        resource_type="subscription_charges",
        external_id=subscription_id,
        operation="cancel_future_charges",
        status="pending",
        request_payload={"subscription_id": subscription_id, "charge_ids": charge_ids},
    )
    db.add(write_run)
    db.commit()
    result["write_run_id"] = str(write_run.id)

    cancelled: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    try:
        async with VirtualPOSClient(platform=platform) as provider:
            # Re-consulta justo antes de borrar: el estado local/previo puede estar obsoleto.
            pending = await _list_pending_charges(provider, subscription_id)
            if charge_ids is None:
                if pending:
                    try:
                        response = await provider.delete_subscription_charges(subscription_id)
                        cancelled = _items(response, "cancel_charges")
                    except Exception as exc:
                        if _provider_error_code(exc) != "E-079":
                            raise
            else:
                pending_by_id = {c["id"]: c for c in pending}
                for charge_id in charge_ids:
                    if charge_id not in pending_by_id:
                        skipped.append({"id": charge_id, "reason": "no_pendiente"})
                        continue
                    try:
                        await provider.delete_charge(charge_id)
                    except Exception as exc:
                        if _provider_error_code(exc) != "E-059":
                            raise
                        skipped.append({"id": charge_id, "reason": "E-059"})
                        continue
                    cancelled.append({**pending_by_id[charge_id], "status": "cancelado"})
    except Exception as exc:
        # Si el lote falla a medias, los ya cancelados quedan trazados en el write_run.
        _reconcile_cancelled_charges(db, platform, cancelled)
        write_run.status = "failed"
        write_run.error_message = safe_error_message(exc, all_secrets)
        write_run.response_payload = {"cancelled_charge_ids": [c.get("id") for c in cancelled], "skipped": skipped}
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    result["cancelled"] = cancelled
    result["skipped"] = skipped
    result["noop"] = not cancelled
    write_run.status = "remote_succeeded"
    write_run.response_payload = {
        "cancelled_charge_ids": [c.get("id") for c in cancelled], "skipped": skipped, "noop": result["noop"],
    }
    db.commit()

    try:
        _reconcile_cancelled_charges(db, platform, cancelled)
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

    return result


async def reassign_subscription_amount(
    db: Session,
    subscription_id: str,
    new_amount: int,
    effective_date: str,
    *,
    platform: str | None = None,
    description: str | None = None,
    internal_code: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Reemplaza el cargo pendiente del periodo (mes de `effective_date`) por uno nuevo con `new_amount`.

    Orden seguro: primero CREAR el cargo nuevo y solo si tuvo éxito cancelar los pendientes del periodo,
    para no dejar nunca al socio sin cobros si el POST falla (p. ej. E-113).
    """
    platform = _resolve_platform(db, subscription_id, platform)
    period = effective_date[:7]
    all_secrets = (
        settings.virtualpos_api_key, settings.virtualpos_secret_key,
        settings.virtualpos2_api_key, settings.virtualpos2_secret_key,
    )
    if not dry_run and not settings.virtualpos_writes_enabled:
        raise WriteDisabledError
    ensure_charge_allowed_on_plan(db, subscription_id, platform)  # bloqueado: no se llama al proveedor

    code = internal_code or f"{subscription_id}-{period.replace('-', '')}-{new_amount}"
    new_charge_request: dict[str, Any] = {"charge_date": effective_date, "amount": new_amount, "internal_code": code}
    if description:
        new_charge_request["description"] = description

    async with VirtualPOSClient(platform=platform) as provider:
        pending = await _list_pending_charges(provider, subscription_id)
    to_cancel = [c for c in pending if str(c.get("charge_date") or "")[:7] == period]

    result: dict[str, Any] = {
        "subscription_id": subscription_id, "dry_run": dry_run, "would_create": new_charge_request,
        "would_cancel": to_cancel, "created_charge_id": None, "cancelled": [], "write_run_id": None,
    }
    if dry_run:
        return result

    write_run = WriteRun(
        source=platform,
        resource_type="subscription_charges",
        external_id=subscription_id,
        operation="reassign_subscription_amount",
        status="pending",
        request_payload={
            "subscription_id": subscription_id, "new_amount": new_amount, "effective_date": effective_date,
            "create": sanitize_record(new_charge_request), "cancel_charge_ids": [c["id"] for c in to_cancel],
        },
    )
    db.add(write_run)
    db.commit()
    result["write_run_id"] = str(write_run.id)

    # Orden seguro: crear primero y cancelar después, para no dejar al socio sin cobros si el POST falla.
    try:
        new_charge = await create_charge(db, subscription_id, new_charge_request, platform=platform)
    except Exception as exc:
        code_hint = _provider_error_code(exc)
        suffix = f" ({code_hint})" if code_hint else ""
        write_run.status = "failed"
        write_run.error_message = (
            f"No se creó el cargo nuevo{suffix}; no se canceló ningún cargo. {safe_error_message(exc, all_secrets)}"
        )[:2000]
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    result["created_charge_id"] = new_charge.external_id
    write_run.response_payload = {"created_charge_id": new_charge.external_id}
    db.commit()

    ids = [c["id"] for c in to_cancel if c["id"] != new_charge.external_id]
    try:
        if ids:
            cancel_result = await cancel_future_charges(db, subscription_id, platform=platform, charge_ids=ids)
            result["cancelled"] = cancel_result["cancelled"]
    except Exception as exc:
        write_run.status = "reconciliation_required"
        write_run.error_message = (
            "El cargo nuevo se creó pero falló la cancelación de los anteriores; revisar duplicados. "
            + safe_error_message(exc, all_secrets)
        )[:2000]
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    write_run.status = "completed"
    write_run.response_payload = {
        "created_charge_id": new_charge.external_id,
        "cancelled_charge_ids": [c.get("id") for c in result["cancelled"]],
    }
    write_run.finished_at = datetime.now(UTC)
    db.commit()
    return result


async def create_subscription(db: Session, data: dict[str, Any]) -> Subscription:
    """Create a VirtualPOS subscription and persist the response locally."""
    platform = data.pop("platform", "virtualpos1")
    all_secrets = (
        settings.virtualpos_api_key, settings.virtualpos_secret_key,
        settings.virtualpos2_api_key, settings.virtualpos2_secret_key,
    )

    # Encode URLs to base64 if provided as plain text
    for url_field in ("return_url", "callback_url"):
        if data.get(url_field):
            raw = str(data[url_field])
            if not _is_base64(raw):
                data[url_field] = base64.b64encode(raw.encode()).decode()

    # Antiduplicado: evitar crear una segunda suscripción activa para el mismo socio y plan.
    plan_id = data.get("plan_id")
    social_id = data.get("social_id")
    if plan_id and social_id:
        existing = db.scalar(
            select(VpSubscription).where(
                VpSubscription.platform == platform,
                VpSubscription.plan_external_id == str(plan_id),
                VpSubscription.client_social_id == str(social_id),
                VpSubscription.status.in_(("ACTIVA", "SUSCRIBIENDO")),
            )
        )
        if existing is not None:
            raise DuplicateSubscriptionError(
                f"Ya existe una suscripción {existing.status} ({existing.external_id}) "
                f"para el socio {social_id} en el plan {plan_id} ({platform})."
            )

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
    except IntegrityError as exc:
        db.rollback()
        # The partial unique index uq_vp_sub_active_plan_client caught a concurrent duplicate.
        if "uq_vp_sub_active_plan_client" in str(exc.orig):
            write_run = db.get(WriteRun, write_run.id)
            if write_run is not None:
                write_run.status = "failed"
                write_run.error_message = "Duplicate active subscription detected by DB constraint (concurrent request)"
                write_run.finished_at = datetime.now(UTC)
                db.commit()
            raise DuplicateSubscriptionError(
                f"Duplicate subscription for social_id={social_id} plan={plan_id} ({platform}) — concurrent create"
            ) from exc
        write_run = db.get(WriteRun, write_run.id)
        if write_run is not None:
            write_run.status = "reconciliation_required"
            write_run.error_message = safe_error_message(exc, all_secrets)
            write_run.finished_at = datetime.now(UTC)
            db.commit()
        raise ReconciliationRequiredError from exc
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
        # consolidación (ver docs/history/migrations/bdlocales-consolidation-closed.md) y su esquema real ya
        # no tiene las columnas platform/remote_id/raw_payload que este write asumía.
        # Basta con reconciliar el registro tocado en SourceRecord (staging) y en la
        # entidad centralizada; no hace falta resincronizar todo el canal.
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


async def cancel_payment(db: Session, payment_id: str) -> Payment:
    """Cancel a VirtualPOS payment via DELETE /v3/payment/{uuid}."""
    payment = db.scalar(
        select(Payment).where(Payment.external_id == payment_id, Payment.source.like("virtualpos%"))
    )
    if payment is None:
        raise PaymentNotFoundError

    if not settings.virtualpos_writes_enabled:
        raise WriteDisabledError

    all_secrets = (
        settings.virtualpos_api_key, settings.virtualpos_secret_key,
        settings.virtualpos2_api_key, settings.virtualpos2_secret_key,
    )

    write_run = WriteRun(
        source=payment.source,
        resource_type="payment",
        external_id=payment_id,
        operation="cancel_payment",
        status="pending",
        request_payload={"payment_id": payment_id},
    )
    db.add(write_run)
    db.commit()

    try:
        async with VirtualPOSClient(platform=payment.source) as provider:
            await provider.delete_payment(payment_id)
            try:
                refreshed_payload = await provider.get_payment(payment_id)
            except Exception:
                refreshed_payload = None
    except Exception as exc:
        write_run.status = "failed"
        write_run.error_message = safe_error_message(exc, all_secrets)
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    cancelled_payload = dict(refreshed_payload or payment.raw_payload or {})
    if not refreshed_payload or not (refreshed_payload.get("status") or refreshed_payload.get("payment", {}).get("status")):
        cancelled_payload = {**cancelled_payload, "status": "cancelado"}

    sanitized_payload = sanitize_record(cancelled_payload)
    write_run.status = "remote_succeeded"
    write_run.response_payload = sanitized_payload
    db.commit()

    try:
        source_record = db.scalar(
            select(SourceRecord).where(
                SourceRecord.source == payment.source,
                SourceRecord.resource_type == "payment",
                SourceRecord.external_id == payment_id,
            )
        )
        if source_record is None:
            source_record = SourceRecord(
                source=payment.source, resource_type="payment", external_id=payment_id, payload=sanitized_payload
            )
            db.add(source_record)
        else:
            source_record.payload = sanitized_payload
        payment.status = _as_text(sanitized_payload.get("status")) or "cancelado"
        payment.raw_payload = sanitized_payload
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

    return payment


async def retry_charge(db: Session, charge_id: str, source: str | None = None) -> Charge:
    """Retry a rejected VirtualPOS charge via GET /v3/charge/{id}/retry."""
    query = select(Charge).where(Charge.external_id == charge_id, Charge.source.like("virtualpos%"))
    if source is not None:
        query = query.where(Charge.source == source)
    charge = db.scalar(query)
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
            # Clasificar el motivo de rechazo antes de reintentar (RISK-VP-01).
            # Requiere payment.order.uuid del cargo para consultar /attempts.
            decision = "DESCONOCIDO"
            raw_charge = charge.raw_payload or {}
            payment_uuid = (raw_charge.get("charge") or raw_charge).get("payment", {}).get("order", {}).get("uuid")
            if payment_uuid:
                try:
                    attempts = await provider.get_payment_attempts(payment_uuid)
                    prior_retries = db.scalar(
                        select(func.count()).select_from(WriteRun).where(
                            WriteRun.source == charge.source,
                            WriteRun.external_id == charge_id,
                            WriteRun.operation == "retry_charge",
                            WriteRun.status == "completed",
                        )
                    ) or 0
                    decision = _classify_rejection(attempts, prior_retries)
                except Exception as exc_class:
                    log.warning("VP retry_charge: no se pudo clasificar motivo para %s: %s", charge_id, exc_class)

            log.info("VP retry_charge %s: decisión=%s payment_uuid=%s", charge_id, decision, payment_uuid)

            if decision == "CAMBIO_TARJETA":
                write_run.status = "blocked"
                write_run.error_message = f"retry bloqueado: decision={decision}"
                write_run.finished_at = datetime.now(UTC)
                db.commit()
                raise RetryBlockedError(
                    f"Cargo {charge_id}: el motivo de rechazo requiere cambio de tarjeta, no reintento."
                )
            if decision == "DIFERIR":
                write_run.status = "blocked"
                write_run.error_message = f"retry bloqueado: decision={decision} (límite de comercio)"
                write_run.finished_at = datetime.now(UTC)
                db.commit()
                raise RetryBlockedError(
                    f"Cargo {charge_id}: límite del comercio — diferir reintento y alertar a finanzas."
                )

            await provider.retry_charge(charge_id)
            try:
                refreshed_payload = _charge_payload(await provider.get_charge(charge_id))
            except Exception:
                refreshed_payload = None
    except RetryBlockedError:
        raise
    except Exception as exc:
        write_run.status = "failed"
        write_run.error_message = safe_error_message(exc, all_secrets)
        write_run.finished_at = datetime.now(UTC)
        db.commit()
        raise

    retried_payload = dict(refreshed_payload or charge.raw_payload or {})
    sanitized_payload = sanitize_record(retried_payload)
    write_run.status = "remote_succeeded"
    write_run.response_payload = sanitized_payload
    db.commit()

    try:
        # BDlocales ya no forma parte del flujo en vivo (ver docs/history/migrations/bdlocales-consolidation-closed.md);
        # basta con reconciliar SourceRecord (staging) y la entidad centralizada.
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
        db.add(
            ChargeRecovery(
                source=charge.source,
                charge_external_id=charge.external_id,
                subscription_external_id=charge.subscription_external_id,
                write_run_id=write_run.id,
                closes_at=datetime.now(UTC) + timedelta(days=4),
            )
        )
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
